from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.adapters.nws import NWSAdapter
from app.adapters.usgs import USGSAdapter
from app.assessments import (
    assessment_response,
    get_assessment,
    list_assessments,
    recompute_event_assessments,
)
from app.config import Settings, get_settings
from app.database import create_engine, init_db, session_factory
from app.derivation import DerivationSettings, rebuild_derived_relationships
from app.graph import GraphEdge, GraphEngine
from app.graph_repository import (
    edge_between,
    edge_response,
    load_graph_context,
    node_response,
)
from app.ingest import ensure_source, ingest_once, persist_normalized
from app.logging import configure_logging
from app.models import Event, InfrastructureRelationshipType, Scenario, Source
from app.provenance import lineage as build_lineage
from app.replay import replay_compare as build_replay_compare
from app.replay import replay_state as build_replay_state
from app.replay import replay_timeline as build_replay_timeline
from app.repository import (
    get_event,
    get_infrastructure,
    list_events,
    list_infrastructure,
    source_response,
)
from app.scenarios import (
    create_scenario,
    execute_scenario,
    get_run,
    get_scenario,
    result_payload,
    run_payload,
    scenario_payload,
)
from app.schemas import (
    AssessmentListResponse,
    AssessmentRecomputeRequest,
    AssessmentRecomputeResponse,
    AssessmentResponse,
    EventListResponse,
    EventResponse,
    GraphEdgeListResponse,
    GraphMetricsResponse,
    GraphNeighborsResponse,
    GraphNodeListResponse,
    GraphNodeResponse,
    GraphPathResponse,
    GraphRebuildResponse,
    GraphSubgraphResponse,
    HealthResponse,
    InfrastructureListResponse,
    InfrastructureResponse,
    LineageResponse,
    ReplayCompareResponse,
    ReplayStateResponse,
    ReplayTimelineResponse,
    ScenarioCreateRequest,
    ScenarioGraphResponse,
    ScenarioListResponse,
    ScenarioResponse,
    ScenarioResultResponse,
    ScenarioRunResponse,
    SourceResponse,
)

log = structlog.get_logger(__name__)
BASE_DIR = Path(__file__).resolve().parent


def adapters(settings: Settings):
    return [
        NWSAdapter(
            settings.nws_alerts_url,
            settings.source_user_agent,
            settings.request_timeout_seconds,
            settings.adapter_version,
        ),
        USGSAdapter(
            settings.usgs_earthquake_url,
            settings.source_user_agent,
            settings.request_timeout_seconds,
            settings.adapter_version,
        ),
    ]


async def seed_demo_data(
    session: AsyncSession,
    settings: Settings,
    *,
    fallback_source_keys: set[str] | None = None,
) -> None:
    seeded_keys: set[str] = set()
    for adapter, filename in zip(adapters(settings), ("nws_alerts.json", "usgs_earthquakes.json"), strict=True):
        if fallback_source_keys is not None and adapter.key not in fallback_source_keys:
            continue
        source = await ensure_source(session, adapter)
        live_event = await session.execute(
            select(Event.id)
            .where(Event.source_id == source.id, Event.classification == "LIVE")
            .limit(1)
        )
        if live_event.scalar_one_or_none() is not None:
            continue
        fixture = json.loads((BASE_DIR / "fixtures" / filename).read_text(encoding="utf-8"))
        for feature in fixture.get("features", []):
            normalized = adapter.normalize(feature, datetime.now(timezone.utc))
            await persist_normalized(
                session,
                source,
                adapter,
                normalized,
                fetched_at=datetime.now(timezone.utc),
                classification="DEMO",
            )
        seeded_keys.add(adapter.key)
    await session.commit()
    if seeded_keys:
        log.info("demo_data_seeded", classification="DEMO", fallback_sources=sorted(seeded_keys))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory
    await init_db(engine)
    async with factory() as session:
        configured_adapters = adapters(settings)
        for adapter in configured_adapters:
            await ensure_source(session, adapter)
        await session.commit()
        fallback_source_keys = {adapter.key for adapter in configured_adapters}
        if settings.ingest_on_startup:
            report = await ingest_once(session, configured_adapters)
            await session.commit()
            fallback_source_keys = report.fallback_source_keys
            log.info(
                "startup_ingest_complete",
                usable_sources=sorted(report.usable_source_keys),
                fallback_sources=sorted(fallback_source_keys),
            )
        if settings.use_demo_data and fallback_source_keys:
            await seed_demo_data(session, settings, fallback_source_keys=fallback_source_keys)
    yield
    await engine.dispose()


app = FastAPI(
    title="SIGNALWAKE API",
    version="0.1.0",
    description="Authoritative NWS and USGS observations normalized into canonical operational events.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


async def session_dependency(
    factory: async_sessionmaker[AsyncSession] = Depends(lambda: app.state.session_factory),
):
    async with factory() as session:
        yield session


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health(session: AsyncSession = Depends(session_dependency)) -> HealthResponse:
    sources = [source_response(item) for item in (await session.execute(select(Source))).scalars().all()]
    return HealthResponse(
        status="ok",
        service="signalwake-api",
        environment=get_settings().app_env,
        database="connected",
        sources=sources,
        generated_at=datetime.now(timezone.utc),
    )


@app.get("/sources", response_model=list[SourceResponse], tags=["sources"])
async def sources(session: AsyncSession = Depends(session_dependency)) -> list[SourceResponse]:
    result = await session.execute(select(Source).order_by(Source.key))
    return [source_response(item) for item in result.scalars().all()]


@app.get("/provenance/lineage", response_model=LineageResponse, tags=["provenance"])
async def provenance_lineage(
    object_type: str = Query(..., description="event, raw_observation, asset, raw_infrastructure_record, relationship, assessment, scenario, scenario_run, or source"),
    object_id: str = Query(...),
    direction: str = Query("both"),
    limit: int = Query(50, ge=1, le=200),
    at: datetime | None = Query(None, description="Optional UTC knowledge-time boundary"),
    session: AsyncSession = Depends(session_dependency),
) -> LineageResponse:
    try:
        result = await build_lineage(
            session,
            object_type=object_type,
            object_id=object_id,
            direction=direction,
            limit=limit,
            at=at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LineageResponse.model_validate(result)


@app.get("/provenance/{object_type}/{object_id}", response_model=LineageResponse, tags=["provenance"])
async def provenance_alias(
    object_type: str,
    object_id: str,
    direction: str = Query("both"),
    limit: int = Query(50, ge=1, le=200),
    at: datetime | None = Query(None),
    session: AsyncSession = Depends(session_dependency),
) -> LineageResponse:
    try:
        result = await build_lineage(
            session,
            object_type=object_type,
            object_id=object_id,
            direction=direction,
            limit=limit,
            at=at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LineageResponse.model_validate(result)


@app.get("/replay/timeline", response_model=ReplayTimelineResponse, tags=["replay"])
async def replay_timeline(
    start_time: datetime = Query(..., description="Inclusive aware UTC range start"),
    end_time: datetime = Query(..., description="Inclusive aware UTC range end"),
    limit: int = Query(100, ge=1, le=100),
    session: AsyncSession = Depends(session_dependency),
) -> ReplayTimelineResponse:
    try:
        result = await build_replay_timeline(session, start_time, end_time, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ReplayTimelineResponse.model_validate(result)


@app.get("/replay/state", response_model=ReplayStateResponse, tags=["replay"])
async def replay_state(
    at: datetime = Query(..., description="Inclusive aware UTC knowledge-time boundary"),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(session_dependency),
) -> ReplayStateResponse:
    try:
        result = await build_replay_state(session, at, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ReplayStateResponse.model_validate(result)


@app.get("/replay/compare", response_model=ReplayCompareResponse, tags=["replay"])
async def replay_compare(
    from_time: datetime = Query(..., description="Earlier inclusive aware UTC boundary"),
    to_time: datetime = Query(..., description="Later inclusive aware UTC boundary"),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(session_dependency),
) -> ReplayCompareResponse:
    try:
        result = await build_replay_compare(session, from_time, to_time, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ReplayCompareResponse.model_validate(result)


@app.get("/events", response_model=EventListResponse, tags=["events"])
async def events(
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
    source: str | None = Query(None, description="Source key, e.g. nws or usgs"),
    type: str | None = Query(None, description="weather_alert or earthquake"),
    severity: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: int = Query(0, ge=0),
    page: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(session_dependency),
) -> EventListResponse:
    offset = (page - 1) * limit if page else cursor
    items, total, next_offset = await list_events(
        session,
        bbox=bbox,
        source=source,
        event_type=type,
        severity=severity,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        cursor=offset,
    )
    return EventListResponse(
        items=items,
        total=total,
        limit=limit,
        next_cursor=str(next_offset) if next_offset is not None else None,
    )


@app.get("/events/{event_id}", response_model=EventResponse, tags=["events"])
async def event_detail(
    event_id: str, session: AsyncSession = Depends(session_dependency)
) -> EventResponse:
    event = await get_event(session, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.get("/infrastructure", response_model=InfrastructureListResponse, tags=["infrastructure"])
async def infrastructure(
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
    type: str | None = Query(None, description="Canonical asset type, e.g. port or rail_corridor"),
    source: str | None = Query(None, description="Infrastructure source key"),
    region: str | None = Query(None, description="Source-provided region, usually state/territory"),
    limit: int = Query(100, ge=1, le=500),
    cursor: int = Query(0, ge=0),
    page: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(session_dependency),
) -> InfrastructureListResponse:
    offset = (page - 1) * limit if page else cursor
    try:
        items, total, next_offset = await list_infrastructure(
            session,
            bbox=bbox,
            asset_type=type,
            source=source,
            region=region,
            limit=limit,
            cursor=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return InfrastructureListResponse(
        items=items,
        total=total,
        limit=limit,
        next_cursor=str(next_offset) if next_offset is not None else None,
    )


@app.get("/infrastructure/{asset_id}", response_model=InfrastructureResponse, tags=["infrastructure"])
async def infrastructure_detail(
    asset_id: str, session: AsyncSession = Depends(session_dependency)
) -> InfrastructureResponse:
    asset = await get_infrastructure(session, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Infrastructure asset not found")
    return asset


@app.get("/assessments", response_model=AssessmentListResponse, tags=["assessments"])
async def assessments(
    event_id: str | None = Query(None),
    asset_id: str | None = Query(None),
    assessment_type: str | None = Query(None),
    type_filter: str | None = Query(None, alias="type"),
    status: str | None = Query(None),
    min_score: float | None = Query(None, ge=0, le=100),
    max_score: float | None = Query(None, ge=0, le=100),
    limit: int = Query(100, ge=1, le=500),
    cursor: int = Query(0, ge=0),
    page: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(session_dependency),
) -> AssessmentListResponse:
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=422, detail="min_score must not exceed max_score")
    offset = (page - 1) * limit if page else cursor
    items, total, next_offset = await list_assessments(
        session,
        event_id=event_id,
        asset_id=asset_id,
        assessment_type=assessment_type or type_filter,
        status=status,
        min_score=min_score,
        max_score=max_score,
        limit=limit,
        cursor=offset,
    )
    return AssessmentListResponse(
        items=items,
        total=total,
        limit=limit,
        next_cursor=str(next_offset) if next_offset is not None else None,
    )


@app.get("/assessments/{assessment_id}", response_model=AssessmentResponse, tags=["assessments"])
async def assessment_detail(
    assessment_id: str, session: AsyncSession = Depends(session_dependency)
) -> AssessmentResponse:
    item = await get_assessment(session, assessment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return item


@app.get(
    "/events/{event_id}/assessments",
    response_model=AssessmentListResponse,
    tags=["assessments"],
)
async def event_assessments(
    event_id: str,
    limit: int = Query(100, ge=1, le=500),
    cursor: int = Query(0, ge=0),
    session: AsyncSession = Depends(session_dependency),
) -> AssessmentListResponse:
    if await get_event(session, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found")
    items, total, next_offset = await list_assessments(
        session, event_id=event_id, limit=limit, cursor=cursor
    )
    return AssessmentListResponse(
        items=items,
        total=total,
        limit=limit,
        next_cursor=str(next_offset) if next_offset is not None else None,
    )


@app.get(
    "/infrastructure/{asset_id}/assessments",
    response_model=AssessmentListResponse,
    tags=["assessments"],
)
async def infrastructure_assessments(
    asset_id: str,
    limit: int = Query(100, ge=1, le=500),
    cursor: int = Query(0, ge=0),
    session: AsyncSession = Depends(session_dependency),
) -> AssessmentListResponse:
    if await get_infrastructure(session, asset_id) is None:
        raise HTTPException(status_code=404, detail="Infrastructure asset not found")
    items, total, next_offset = await list_assessments(
        session, asset_id=asset_id, limit=limit, cursor=cursor
    )
    return AssessmentListResponse(
        items=items,
        total=total,
        limit=limit,
        next_cursor=str(next_offset) if next_offset is not None else None,
    )


@app.post(
    "/assessments/recompute",
    response_model=AssessmentRecomputeResponse,
    tags=["assessments"],
)
async def assessments_recompute(
    request: AssessmentRecomputeRequest,
    session: AsyncSession = Depends(session_dependency),
) -> AssessmentRecomputeResponse:
    try:
        result = await recompute_event_assessments(
            session,
            request.event_id,
            radius_km=request.radius_km,
            depth=request.depth,
            asset_limit=request.asset_limit,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssessmentRecomputeResponse(
        event_id=result.event_id,
        methodology_version=result.methodology_version,
        inserted_count=result.inserted_count,
        updated_count=result.updated_count,
        deleted_count=result.deleted_count,
        total=len(result.items),
        settings=result.settings,
        items=[assessment_response(item) for item in result.items],
    )


GRAPH_RELATIONSHIP_TYPES = {item.value for item in InfrastructureRelationshipType}
GRAPH_MAX_LIMIT = 200


def _relationship_filter(value: str | None) -> set[str] | None:
    if not value:
        return None
    values = {item.strip().upper() for item in value.split(",") if item.strip()}
    invalid = values - GRAPH_RELATIONSHIP_TYPES
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unsupported relationship type(s): {', '.join(sorted(invalid))}")
    return values


def _nodes_by_id(assets):
    return {asset.id: asset for asset in assets}


def _path_edges(engine: GraphEngine, path: list[str], relationship_types: set[str] | None) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for from_id, to_id in zip(path, path[1:]):
        candidates = [
            edge
            for edge in engine.edges.values()
            if engine._allowed(edge, relationship_types)
            and ((edge.from_id == from_id and edge.to_id == to_id) or (edge.directionality != "DIRECTED" and edge.from_id == to_id and edge.to_id == from_id))
        ]
        if candidates:
            edges.append(sorted(candidates, key=lambda edge: (edge.relationship_type, edge.id))[0])
    return edges


@app.get("/graph/nodes", response_model=GraphNodeListResponse, tags=["graph"])
async def graph_nodes(
    type: str | None = Query(None, description="Canonical asset type"),
    region: str | None = Query(None),
    source: str | None = Query(None, description="Infrastructure source key"),
    limit: int = Query(50, ge=1, le=GRAPH_MAX_LIMIT),
    cursor: int = Query(0, ge=0),
    page: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(session_dependency),
) -> GraphNodeListResponse:
    assets, engine = await load_graph_context(session)
    filtered = [
        asset
        for asset in assets
        if (not type or asset.asset_type == type)
        and (not region or asset.region == region)
        and (not source or (asset.source and asset.source.key == source.lower()))
    ]
    offset = (page - 1) * limit if page else cursor
    visible = filtered[offset : offset + limit + 1]
    next_cursor = str(offset + limit) if len(visible) > limit else None
    return GraphNodeListResponse(
        items=[node_response(asset, engine) for asset in visible[:limit]],
        total=len(filtered),
        limit=limit,
        next_cursor=next_cursor,
    )


@app.get("/graph/nodes/{node_id}", response_model=GraphNodeResponse, tags=["graph"])
async def graph_node_detail(
    node_id: str, session: AsyncSession = Depends(session_dependency)
) -> GraphNodeResponse:
    assets, engine = await load_graph_context(session)
    asset = _nodes_by_id(assets).get(node_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return node_response(asset, engine)


@app.get("/graph/edges", response_model=GraphEdgeListResponse, tags=["graph"])
async def graph_edges(
    relationship_type: str | None = Query(None, description="One or comma-separated relationship types"),
    limit: int = Query(100, ge=1, le=GRAPH_MAX_LIMIT),
    cursor: int = Query(0, ge=0),
    session: AsyncSession = Depends(session_dependency),
) -> GraphEdgeListResponse:
    selected_types = _relationship_filter(relationship_type)
    _assets, engine = await load_graph_context(session, relationship_types=selected_types)
    edges = [
        edge
        for edge in engine.edges.values()
        if not selected_types or edge.relationship_type in selected_types
    ]
    edges = sorted(edges, key=lambda edge: (edge.relationship_type, edge.from_id, edge.to_id, edge.id))
    visible = edges[cursor : cursor + limit]
    return GraphEdgeListResponse(
        items=[edge_response(edge) for edge in visible],
        total=len(edges),
        limit=limit,
        next_cursor=str(cursor + limit) if cursor + limit < len(edges) else None,
    )


@app.get("/graph/nodes/{node_id}/neighbors", response_model=GraphNeighborsResponse, tags=["graph"])
async def graph_node_neighbors(
    node_id: str,
    relationship_type: str | None = Query(None, description="One or comma-separated relationship types"),
    direction: str = Query("both", pattern="^(both|in|out)$"),
    depth: int = Query(1, ge=1, le=4),
    limit: int = Query(50, ge=1, le=GRAPH_MAX_LIMIT),
    session: AsyncSession = Depends(session_dependency),
) -> GraphNeighborsResponse:
    relationship_types = _relationship_filter(relationship_type)
    assets, engine = await load_graph_context(session, relationship_types=relationship_types)
    asset_map = _nodes_by_id(assets)
    root = asset_map.get(node_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    selected_edges = [
        edge for edge in engine.edges.values() if not relationship_types or edge.relationship_type in relationship_types
    ]
    if direction != "both" and any(edge.directionality != "DIRECTED" for edge in selected_edges):
        raise HTTPException(status_code=400, detail="Current relationships are undirected; use direction=both")
    neighbor_ids = engine.neighbor_ids(
        node_id,
        depth=depth,
        limit=limit,
        direction=direction,
        relationship_types=relationship_types,
    )
    visible_ids = {node_id, *neighbor_ids}
    return GraphNeighborsResponse(
        root=node_response(root, engine, relationship_types=relationship_types),
        nodes=[node_response(asset_map[item], engine, relationship_types=relationship_types) for item in neighbor_ids],
        edges=edge_between(engine, visible_ids),
        depth=depth,
        limit=limit,
    )


@app.get("/graph/paths", response_model=GraphPathResponse, tags=["graph"])
async def graph_paths(
    from_node: str = Query(..., alias="from"),
    to_node: str = Query(..., alias="to"),
    max_hops: int = Query(8, ge=0, le=20),
    relationship_types: str | None = Query(None, description="One or comma-separated relationship types"),
    session: AsyncSession = Depends(session_dependency),
) -> GraphPathResponse:
    selected_types = _relationship_filter(relationship_types)
    assets, engine = await load_graph_context(session, relationship_types=selected_types)
    asset_map = _nodes_by_id(assets)
    if from_node not in asset_map or to_node not in asset_map:
        raise HTTPException(status_code=404, detail="One or both graph nodes not found")
    path = engine.shortest_path(from_node, to_node, max_hops=max_hops, relationship_types=selected_types)
    if path is None:
        raise HTTPException(status_code=404, detail="No path exists within max_hops")
    edge_path = _path_edges(engine, path, selected_types)
    return GraphPathResponse(
        from_node_id=from_node,
        to_node_id=to_node,
        max_hops=max_hops,
        hops=len(path) - 1,
        nodes=[node_response(asset_map[item], engine, relationship_types=selected_types) for item in path],
        edges=[edge_response(edge) for edge in edge_path],
    )


@app.get("/graph/subgraph", response_model=GraphSubgraphResponse, tags=["graph"])
async def graph_subgraph(
    root: str = Query(...),
    depth: int = Query(2, ge=0, le=4),
    relationship_type: str | None = Query(None),
    type: str | None = Query(None, description="Optional node type filter"),
    region: str | None = Query(None),
    max_nodes: int = Query(50, ge=1, le=GRAPH_MAX_LIMIT),
    session: AsyncSession = Depends(session_dependency),
) -> GraphSubgraphResponse:
    selected_types = _relationship_filter(relationship_type)
    assets, full_engine = await load_graph_context(session, relationship_types=selected_types)
    asset_map = _nodes_by_id(assets)
    if root not in asset_map:
        raise HTTPException(status_code=404, detail="Graph root node not found")
    allowed_ids = {
        asset.id
        for asset in assets
        if asset.id == root or ((not type or asset.asset_type == type) and (not region or asset.region == region))
    }
    filtered_engine = GraphEngine(
        [node for node in full_engine.nodes.values() if node.id in allowed_ids],
        [edge for edge in full_engine.edges.values() if edge.from_id in allowed_ids and edge.to_id in allowed_ids],
    )
    selected_nodes, selected_edges, truncated = filtered_engine.subgraph(
        root, depth=depth, max_nodes=max_nodes, relationship_types=selected_types
    )
    selected_ids = {node.id for node in selected_nodes}
    return GraphSubgraphResponse(
        root_node_id=root,
        depth=depth,
        max_nodes=max_nodes,
        truncated=truncated,
        nodes=[node_response(asset_map[node.id], filtered_engine, relationship_types=selected_types) for node in selected_nodes],
        edges=[edge_response(edge) for edge in selected_edges if edge.from_id in selected_ids and edge.to_id in selected_ids],
    )


@app.get("/graph/metrics", response_model=GraphMetricsResponse, tags=["graph"])
async def graph_metrics(
    node_id: str | None = Query(None),
    type: str | None = Query(None),
    region: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(50, ge=1, le=GRAPH_MAX_LIMIT),
    session: AsyncSession = Depends(session_dependency),
) -> GraphMetricsResponse:
    assets, engine = await load_graph_context(session)
    if node_id:
        assets = [asset for asset in assets if asset.id == node_id]
        if not assets:
            raise HTTPException(status_code=404, detail="Graph node not found")
    else:
        assets = [
            asset for asset in assets
            if (not type or asset.asset_type == type)
            and (not region or asset.region == region)
            and (not source or (asset.source and asset.source.key == source.lower()))
        ][:limit]
    return GraphMetricsResponse(
        items=[node_response(asset, engine) for asset in assets],
        total=len(assets),
        limit=limit,
    )


@app.post("/graph/rebuild", response_model=GraphRebuildResponse, tags=["graph"])
async def graph_rebuild(
    endpoint_tolerance_m: float = Query(100.0, gt=0, le=1000),
    adjacency_distance_km: float = Query(25.0, gt=0, le=200),
    session: AsyncSession = Depends(session_dependency),
) -> GraphRebuildResponse:
    stats = await rebuild_derived_relationships(
        session,
        DerivationSettings(
            endpoint_tolerance_m=endpoint_tolerance_m,
            adjacency_distance_km=adjacency_distance_km,
        ),
    )
    return GraphRebuildResponse.model_validate(stats.as_dict())


@app.post("/scenarios", response_model=ScenarioResponse, status_code=201, tags=["scenarios"])
async def scenarios_create(
    request: ScenarioCreateRequest,
    session: AsyncSession = Depends(session_dependency),
) -> ScenarioResponse:
    try:
        scenario = await create_scenario(
            session,
            name=request.name,
            scenario_type=request.scenario_type,
            target_node_ids=request.target_node_ids,
            target_edge_ids=request.target_edge_ids,
            assumption=request.assumption,
            duration_seconds=request.duration_seconds,
            created_by=request.created_by,
        )
        await session.commit()
        await session.refresh(scenario, ["targets"])
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Scenario definition conflicts with an existing persisted definition") from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScenarioResponse.model_validate(scenario_payload(scenario))


@app.get("/scenarios", response_model=ScenarioListResponse, tags=["scenarios"])
async def scenarios_list(
    limit: int = Query(50, ge=1, le=100),
    cursor: int = Query(0, ge=0),
    session: AsyncSession = Depends(session_dependency),
) -> ScenarioListResponse:
    statement = select(Scenario).options(selectinload(Scenario.targets)).order_by(Scenario.created_at.desc(), Scenario.id)
    scenarios = list((await session.execute(statement)).scalars().all())
    visible = scenarios[cursor : cursor + limit]
    return ScenarioListResponse(
        items=[ScenarioResponse.model_validate(scenario_payload(item, include_baseline=False)) for item in visible],
        total=len(scenarios),
        limit=limit,
        next_cursor=str(cursor + limit) if cursor + limit < len(scenarios) else None,
    )


@app.get("/scenarios/{scenario_id}", response_model=ScenarioResponse, tags=["scenarios"])
async def scenarios_detail(
    scenario_id: str,
    session: AsyncSession = Depends(session_dependency),
) -> ScenarioResponse:
    scenario = await get_scenario(session, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return ScenarioResponse.model_validate(scenario_payload(scenario))


@app.post("/scenarios/{scenario_id}/runs", response_model=ScenarioRunResponse, status_code=201, tags=["scenarios"])
async def scenarios_run(
    scenario_id: str,
    session: AsyncSession = Depends(session_dependency),
) -> ScenarioRunResponse:
    try:
        run = await execute_scenario(session, scenario_id)
        await session.commit()
        await session.refresh(run, ["result"])
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Scenario run conflicts with an existing persisted run") from exc
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ScenarioRunResponse.model_validate(run_payload(run))


@app.get("/scenario-runs/{run_id}", response_model=ScenarioRunResponse, tags=["scenarios"])
async def scenario_run_detail(
    run_id: str,
    session: AsyncSession = Depends(session_dependency),
) -> ScenarioRunResponse:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Scenario run not found")
    return ScenarioRunResponse.model_validate(run_payload(run))


@app.get("/scenario-runs/{run_id}/result", response_model=ScenarioResultResponse, tags=["scenarios"])
async def scenario_run_result(
    run_id: str,
    session: AsyncSession = Depends(session_dependency),
) -> ScenarioResultResponse:
    run = await get_run(session, run_id)
    if run is None or run.result is None:
        raise HTTPException(status_code=404, detail="Scenario run result not found")
    return ScenarioResultResponse.model_validate(result_payload(run.result))


@app.get("/scenario-runs/{run_id}/graph", response_model=ScenarioGraphResponse, tags=["scenarios"])
async def scenario_run_graph(
    run_id: str,
    state: str = Query("modified", pattern="^(baseline|modified)$"),
    limit: int = Query(100, ge=1, le=GRAPH_MAX_LIMIT),
    session: AsyncSession = Depends(session_dependency),
) -> ScenarioGraphResponse:
    run = await get_run(session, run_id)
    if run is None or run.result is None:
        raise HTTPException(status_code=404, detail="Scenario run result not found")
    result = result_payload(run.result)
    snapshot = result[state]
    all_nodes = snapshot.get("nodes", [])
    selected_nodes = all_nodes[:limit]
    selected_ids = {item.get("id") for item in selected_nodes}
    all_edges = [
        edge
        for edge in snapshot.get("edges", [])
        if edge.get("from_id") in selected_ids and edge.get("to_id") in selected_ids
    ]
    edge_limit = min(len(all_edges), limit * 4)
    return ScenarioGraphResponse(
        run_id=run.id,
        state=state,
        graph_hash=snapshot.get("hash", ""),
        nodes=selected_nodes,
        edges=all_edges[:edge_limit],
        truncated=len(all_nodes) > limit or len(all_edges) > edge_limit,
        max_nodes=limit,
    )
