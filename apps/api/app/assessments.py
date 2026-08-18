"""Deterministic event-to-infrastructure assessments.

This module is intentionally separate from ingestion and graph derivation.
Events and infrastructure remain source facts, graph relationships remain
persisted derived edges, and this table is a replaceable, methodology-versioned
assessment projection over those inputs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.graph import GraphEdge, GraphEngine, GraphNode
from app.history import record_assessment_version
from app.models import (
    AssessmentStatus,
    AssessmentType,
    Event,
    InfrastructureAssessment,
    InfrastructureAsset,
    InfrastructureRelationship,
    TransformationRun,
)
from app.schemas import AssessmentResponse
from app.spatial import distance_geometry_to_point_km, geometry_intersects, validate_geometry

METHODOLOGY_VERSION = "phase4-v1"
DEFAULT_RADIUS_KM = 50.0
MAX_RADIUS_KM = 500.0
MAX_DEPTH = 4
MAX_ASSETS = 5000

SEVERITY_NORMALIZATION = {
    "info": 0.2,
    "advisory": 0.4,
    "watch": 0.6,
    "warning": 0.8,
    "critical": 1.0,
}
SCORE_WEIGHTS = {"event_severity": 0.50, "spatial_match": 0.35, "graph_exposure": 0.15}
FORMULA = (
    "score = event_severity_score * 0.50 + spatial_match_score * 0.35 "
    "+ graph_exposure_score * 0.15"
)


@dataclass(frozen=True, slots=True)
class AssessmentRecomputeResult:
    event_id: str
    methodology_version: str
    inserted_count: int
    updated_count: int
    deleted_count: int
    items: list[InfrastructureAssessment]
    settings: dict[str, Any]


def _json_dict(value: str | dict | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def assessment_response(assessment: InfrastructureAssessment) -> AssessmentResponse:
    return AssessmentResponse(
        classification="SIGNALWAKE DERIVED ASSESSMENT",
        id=assessment.id,
        assessment_key=assessment.assessment_key,
        assessment_type=assessment.assessment_type,
        event_id=assessment.event_id,
        affected_asset_id=assessment.affected_asset_id,
        affected_region=assessment.affected_region,
        severity=assessment.severity,
        status=assessment.status,
        score=assessment.score,
        confidence=assessment.confidence,
        methodology_version=assessment.methodology_version,
        evidence=_json_dict(assessment.evidence_json),
        score_components=_json_dict(assessment.score_components_json),
        metadata=_json_dict(assessment.metadata_json),
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
    )


def _event_geometry(event: Event) -> dict[str, Any] | None:
    if event.geometry_geojson:
        try:
            return validate_geometry(json.loads(event.geometry_geojson))
        except (TypeError, json.JSONDecodeError, ValueError):
            pass
    if event.longitude is not None and event.latitude is not None:
        return {"type": "Point", "coordinates": [event.longitude, event.latitude]}
    return None


def _asset_geometry(asset: InfrastructureAsset) -> dict[str, Any] | None:
    try:
        return validate_geometry(json.loads(asset.geometry_geojson))
    except (TypeError, json.JSONDecodeError, ValueError):
        return None


def _severity_value(event: Event) -> float:
    return SEVERITY_NORMALIZATION.get(event.severity.casefold(), 0.0)


def _scores(
    event: Event,
    *,
    spatial_score: float,
    graph_score: float = 0.0,
    spatial_input: dict[str, Any],
    graph_input: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    severity_normalized = _severity_value(event)
    severity_score = round(severity_normalized * 100, 4)
    spatial_score = round(max(0.0, min(100.0, spatial_score)), 4)
    graph_score = round(max(0.0, min(100.0, graph_score)), 4)
    components: dict[str, Any] = {
        "formula": FORMULA,
        "methodology_version": METHODOLOGY_VERSION,
        "weights": SCORE_WEIGHTS,
        "event_severity": {
            "input": event.severity,
            "normalized": severity_normalized,
            "score": severity_score,
            "weighted_score": round(severity_score * SCORE_WEIGHTS["event_severity"], 4),
        },
        "spatial_match": {
            **spatial_input,
            "score": spatial_score,
            "weighted_score": round(spatial_score * SCORE_WEIGHTS["spatial_match"], 4),
        },
        "graph_exposure": {
            **(graph_input or {"input": "not_applicable"}),
            "score": graph_score,
            "weighted_score": round(graph_score * SCORE_WEIGHTS["graph_exposure"], 4),
        },
    }
    total = round(
        severity_score * SCORE_WEIGHTS["event_severity"]
        + spatial_score * SCORE_WEIGHTS["spatial_match"]
        + graph_score * SCORE_WEIGHTS["graph_exposure"],
        4,
    )
    return total, components


def _assessment_key(event_id: str, assessment_type: str, asset_id: str | None, region: str | None) -> str:
    target = f"asset:{asset_id}" if asset_id else f"region:{region}"
    return f"{METHODOLOGY_VERSION}|{event_id}|{assessment_type}|{target}"


def _base_values(
    event: Event,
    *,
    assessment_type: str,
    asset: InfrastructureAsset | None,
    score: float,
    components: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "assessment_key": _assessment_key(
            event.id, assessment_type, asset.id if asset else None, asset.region if asset else None
        ),
        "assessment_type": assessment_type,
        "event_id": event.id,
        "affected_asset_id": asset.id if asset else None,
        "affected_region": asset.region if asset else None,
        "severity": event.severity,
        "status": event.status,
        "score": score,
        # Confidence is deliberately null: no probabilistic outage or impact
        # evidence is available in the source observations or graph.
        "confidence": None,
        "methodology_version": METHODOLOGY_VERSION,
        "evidence_json": json.dumps(evidence, sort_keys=True),
        "score_components_json": json.dumps(components, sort_keys=True),
        "metadata_json": json.dumps(
            {"classification": "SIGNALWAKE DERIVED ASSESSMENT", "source_fact_ids": [event.id]},
            sort_keys=True,
        ),
    }


def _graph_engine(
    assets: list[InfrastructureAsset], relationships: list[InfrastructureRelationship]
) -> tuple[GraphEngine, dict[str, GraphEdge]]:
    nodes = [
        GraphNode(
            id=asset.id,
            name=asset.name,
            asset_type=asset.asset_type,
            region=asset.region,
            source_key=asset.source.key if asset.source else None,
        )
        for asset in assets
    ]
    edges = [
        GraphEdge(
            id=relationship.id,
            from_id=relationship.from_asset_id,
            to_id=relationship.to_asset_id,
            relationship_type=relationship.relationship_type,
            directionality=relationship.directionality,
            relationship_source=relationship.relationship_source,
            relationship_key=relationship.relationship_key,
            source_relationship_id=relationship.source_relationship_id,
            derivation_method=relationship.derivation_method,
            derivation_version=relationship.derivation_version,
            confidence=relationship.confidence,
            evidence=_json_dict(relationship.evidence_json),
            distance_km=relationship.distance_km,
            tolerance_m=relationship.tolerance_m,
        )
        for relationship in relationships
    ]
    return GraphEngine(nodes, edges), {edge.id: edge for edge in edges}


def _path_edges(engine: GraphEngine, path: list[str], edge_by_id: dict[str, GraphEdge]) -> list[GraphEdge]:
    result: list[GraphEdge] = []
    for left, right in zip(path, path[1:]):
        candidates = [
            edge
            for edge in edge_by_id.values()
            if (edge.from_id == left and edge.to_id == right)
            or (edge.directionality != "DIRECTED" and edge.from_id == right and edge.to_id == left)
        ]
        if candidates:
            result.append(sorted(candidates, key=lambda item: (item.relationship_type, item.id))[0])
    return result


async def recompute_event_assessments(
    session: AsyncSession,
    event_id: str,
    *,
    radius_km: float = DEFAULT_RADIUS_KM,
    depth: int = 2,
    asset_limit: int = 200,
) -> AssessmentRecomputeResult:
    if not 0 < radius_km <= MAX_RADIUS_KM:
        raise ValueError(f"radius_km must be greater than zero and at most {MAX_RADIUS_KM:g}")
    if not 1 <= depth <= MAX_DEPTH:
        raise ValueError(f"depth must be between 1 and {MAX_DEPTH}")
    if not 1 <= asset_limit <= MAX_ASSETS:
        raise ValueError(f"asset_limit must be between 1 and {MAX_ASSETS}")

    event = await session.scalar(select(Event).where(Event.id == event_id))
    if event is None:
        raise LookupError("Event not found")
    assets_result = await session.execute(
        select(InfrastructureAsset)
        .options(joinedload(InfrastructureAsset.source))
        .order_by(InfrastructureAsset.id)
        .limit(asset_limit)
    )
    assets = list(assets_result.unique().scalars())
    asset_by_id = {asset.id: asset for asset in assets}
    relationship_result = await session.execute(
        select(InfrastructureRelationship).order_by(
            InfrastructureRelationship.relationship_type,
            InfrastructureRelationship.from_asset_id,
            InfrastructureRelationship.to_asset_id,
            InfrastructureRelationship.id,
        )
    )
    relationships = [
        relationship
        for relationship in relationship_result.scalars().all()
        if relationship.from_asset_id in asset_by_id and relationship.to_asset_id in asset_by_id
    ]
    engine, edge_by_id = _graph_engine(assets, relationships)
    event_geometry = _event_geometry(event)
    desired: dict[str, dict[str, Any]] = {}
    direct_asset_ids: set[str] = set()

    if event_geometry:
        for asset in assets:
            asset_geometry = _asset_geometry(asset)
            if asset_geometry is None:
                continue
            if geometry_intersects(event_geometry, asset_geometry):
                direct_asset_ids.add(asset.id)
                score, components = _scores(
                    event,
                    spatial_score=100,
                    spatial_input={
                        "predicate": "geometry_intersects",
                        "event_geometry_type": event_geometry["type"],
                        "asset_geometry_type": asset_geometry["type"],
                        "boundary_inclusive": True,
                    },
                )
                evidence = {
                    "event_id": event.id,
                    "asset_id": asset.id,
                    "predicate": "geometry_intersects",
                    "event_geometry_type": event_geometry["type"],
                    "asset_geometry_type": asset_geometry["type"],
                    "event_classification": event.classification,
                    "asset_classification": asset.classification,
                }
                values = _base_values(
                    event,
                    assessment_type=AssessmentType.EVENT_INTERSECTS_INFRASTRUCTURE.value,
                    asset=asset,
                    score=score,
                    components=components,
                    evidence=evidence,
                )
                desired[values["assessment_key"]] = values

    # Radius is restricted to point observations.  Polygon/line event extents
    # use the actual intersection predicate above rather than a guessed center.
    if event_geometry and event_geometry["type"] == "Point":
        longitude, latitude = event_geometry["coordinates"][:2]
        for asset in assets:
            asset_geometry = _asset_geometry(asset)
            if asset_geometry is None:
                continue
            distance_km = distance_geometry_to_point_km(asset_geometry, longitude, latitude)
            if distance_km > radius_km:
                continue
            direct_asset_ids.add(asset.id)
            proximity = max(0.0, min(1.0, 1.0 - distance_km / radius_km))
            score, components = _scores(
                event,
                spatial_score=proximity * 100,
                spatial_input={
                    "predicate": "distance_geometry_to_point_km <= radius_km",
                    "distance_km": round(distance_km, 6),
                    "radius_km": radius_km,
                    "proximity": round(proximity, 6),
                    "boundary_inclusive": True,
                },
            )
            evidence = {
                "event_id": event.id,
                "asset_id": asset.id,
                "predicate": "distance_geometry_to_point_km <= radius_km",
                "event_point": [longitude, latitude],
                "distance_km": round(distance_km, 6),
                "radius_km": radius_km,
                "event_classification": event.classification,
                "asset_classification": asset.classification,
            }
            values = _base_values(
                event,
                assessment_type=AssessmentType.INFRASTRUCTURE_WITHIN_EVENT_RADIUS.value,
                asset=asset,
                score=score,
                components=components,
                evidence=evidence,
            )
            desired[values["assessment_key"]] = values

    # Graph traversal is structural connected-graph exposure.  It does not
    # imply operational upstream/downstream dependency or an outage.
    for seed_id in sorted(direct_asset_ids):
        for target_id in engine.neighbor_ids(seed_id, depth=depth, limit=asset_limit):
            if target_id in direct_asset_ids:
                continue
            paths = [
                path
                for path in (engine.shortest_path(seed_id, target_id, max_hops=depth),)
                if path is not None and len(path) > 1
            ]
            if not paths:
                continue
            path = paths[0]
            hops = len(path) - 1
            path_edges = _path_edges(engine, path, edge_by_id)
            asset = asset_by_id[target_id]
            graph_proximity = max(0.0, min(1.0, (depth - hops + 1) / depth))
            score, components = _scores(
                event,
                spatial_score=0,
                graph_score=graph_proximity * 100,
                spatial_input={"predicate": "not_applicable_for_structural_traversal"},
                graph_input={
                    "input": "bounded_undirected_traversal",
                    "seed_asset_id": seed_id,
                    "hops": hops,
                    "max_depth": depth,
                    "proximity": round(graph_proximity, 6),
                },
            )
            evidence = {
                "event_id": event.id,
                "asset_id": asset.id,
                "seed_asset_id": seed_id,
                "path_node_ids": path,
                "relationship_ids": [edge.id for edge in path_edges],
                "relationship_keys": [edge.relationship_key for edge in path_edges],
                "relationship_evidence": [edge.evidence for edge in path_edges],
                "hops": hops,
                "max_depth": depth,
                "directionality": "UNDIRECTED",
                "interpretation": "structural connected-graph exposure; not operational dependency or outage",
            }
            values = _base_values(
                event,
                assessment_type=AssessmentType.DEPENDENCY_EXPOSURE.value,
                asset=asset,
                score=score,
                components=components,
                evidence=evidence,
            )
            desired.setdefault(values["assessment_key"], values)

    existing_result = await session.execute(
        select(InfrastructureAssessment).where(
            InfrastructureAssessment.event_id == event.id,
            InfrastructureAssessment.methodology_version == METHODOLOGY_VERSION,
        )
    )
    existing = {item.assessment_key: item for item in existing_result.scalars().all()}
    deleted_count = 0
    now = datetime.now(timezone.utc)
    deleted_keys: list[str] = []
    for key, item in existing.items():
        if key not in desired:
            await session.delete(item)
            deleted_count += 1
            deleted_keys.append(key)
    inserted_count = updated_count = 0
    for key in sorted(desired):
        values = desired[key]
        current = existing.get(key)
        if current is None:
            session.add(InfrastructureAssessment(created_at=now, updated_at=now, **values))
            inserted_count += 1
        else:
            for field, value in values.items():
                setattr(current, field, value)
            current.updated_at = now
            updated_count += 1
    await session.flush()
    for key in sorted(desired):
        current = existing.get(key)
        if current is None:
            current = await session.scalar(
                select(InfrastructureAssessment).where(InfrastructureAssessment.assessment_key == key)
            )
        if current is not None:
            await record_assessment_version(
                session,
                current,
                assessment_key=key,
                event_id=event.id,
                methodology_version=METHODOLOGY_VERSION,
                generated_at=now,
            )
    for key in deleted_keys:
        await record_assessment_version(
            session,
            None,
            assessment_key=key,
            event_id=event.id,
            methodology_version=METHODOLOGY_VERSION,
            generated_at=now,
            is_deleted=True,
        )
    result_items = list(
        (
            await session.execute(
                select(InfrastructureAssessment)
                .where(
                    InfrastructureAssessment.event_id == event.id,
                    InfrastructureAssessment.methodology_version == METHODOLOGY_VERSION,
                )
                .order_by(InfrastructureAssessment.score.desc(), InfrastructureAssessment.assessment_key)
            )
        )
        .scalars()
        .all()
    )
    run = TransformationRun(
        id=str(uuid.uuid4()),
        run_kind="assessment",
        version=METHODOLOGY_VERSION,
        source_id=event.source_id,
        started_at=now,
        completed_at=now,
        created_at=now,
        status="completed",
        records_retrieved=len(assets),
        records_accepted=len(desired),
        records_rejected=deleted_count,
        metadata_json=json.dumps({"event_id": event.id, "radius_km": radius_km, "depth": depth, "asset_limit": asset_limit}, sort_keys=True),
    )
    session.add(run)
    return AssessmentRecomputeResult(
        event_id=event.id,
        methodology_version=METHODOLOGY_VERSION,
        inserted_count=inserted_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
        items=result_items,
        settings={"radius_km": radius_km, "depth": depth, "asset_limit": asset_limit},
    )


async def list_assessments(
    session: AsyncSession,
    *,
    event_id: str | None = None,
    asset_id: str | None = None,
    assessment_type: str | None = None,
    status: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    limit: int = 100,
    cursor: int = 0,
) -> tuple[list[AssessmentResponse], int, int | None]:
    statement = select(InfrastructureAssessment).order_by(
        InfrastructureAssessment.score.desc(), InfrastructureAssessment.assessment_key
    )
    count_statement = select(func.count(InfrastructureAssessment.id))
    filters = []
    if event_id:
        filters.append(InfrastructureAssessment.event_id == event_id)
    if asset_id:
        filters.append(InfrastructureAssessment.affected_asset_id == asset_id)
    if assessment_type:
        filters.append(InfrastructureAssessment.assessment_type == assessment_type)
    if status:
        filters.append(InfrastructureAssessment.status == status)
    if min_score is not None:
        filters.append(InfrastructureAssessment.score >= min_score)
    if max_score is not None:
        filters.append(InfrastructureAssessment.score <= max_score)
    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(*filters)
    total = int((await session.execute(count_statement)).scalar_one())
    rows = list((await session.execute(statement.offset(cursor).limit(limit + 1))).scalars())
    next_cursor = cursor + limit if len(rows) > limit else None
    return [assessment_response(item) for item in rows[:limit]], total, next_cursor


async def get_assessment(session: AsyncSession, assessment_id: str) -> AssessmentResponse | None:
    item = await session.scalar(
        select(InfrastructureAssessment).where(InfrastructureAssessment.id == assessment_id)
    )
    return assessment_response(item) if item else None


def recompute_result_response(result: AssessmentRecomputeResult) -> dict[str, Any]:
    return {
        "event_id": result.event_id,
        "methodology_version": result.methodology_version,
        "inserted_count": result.inserted_count,
        "updated_count": result.updated_count,
        "deleted_count": result.deleted_count,
        "total": len(result.items),
        "settings": result.settings,
        "items": [assessment_response(item) for item in result.items],
    }


def assessment_status_for_event(event: Event) -> str:
    return {
        "active": AssessmentStatus.ACTIVE.value,
        "expired": AssessmentStatus.EXPIRED.value,
        "observed": AssessmentStatus.OBSERVED.value,
    }.get(event.status, event.status)


def _cli() -> None:
    import argparse
    import asyncio
    import sys

    parser = argparse.ArgumentParser(description="Recompute deterministic SIGNALWAKE assessments for one event")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--radius-km", type=float, default=DEFAULT_RADIUS_KM)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--asset-limit", type=int, default=200)
    args = parser.parse_args()

    async def run() -> None:
        from app.config import Settings
        from app.database import create_engine, init_db, session_factory

        settings = Settings(database_url=args.database_url) if args.database_url else Settings()
        engine = create_engine(settings)
        await init_db(engine)
        async with session_factory(engine)() as session:
            result = await recompute_event_assessments(
                session,
                args.event_id,
                radius_km=args.radius_km,
                depth=args.depth,
                asset_limit=args.asset_limit,
            )
            await session.commit()
            print(
                json.dumps(
                    {
                        "event_id": result.event_id,
                        "methodology_version": result.methodology_version,
                        "inserted_count": result.inserted_count,
                        "updated_count": result.updated_count,
                        "deleted_count": result.deleted_count,
                        "total": len(result.items),
                        "settings": result.settings,
                    },
                    sort_keys=True,
                )
            )
        await engine.dispose()

    try:
        asyncio.run(run())
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(str(exc), file=sys.stderr)
        raise


if __name__ == "__main__":
    _cli()
