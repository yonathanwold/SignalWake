from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.nws import NWSAdapter
from app.adapters.usgs import USGSAdapter
from app.config import Settings, get_settings
from app.database import create_engine, init_db, session_factory
from app.ingest import ensure_source, ingest_once, persist_normalized
from app.logging import configure_logging
from app.models import Event, Source
from app.repository import (
    get_event,
    get_infrastructure,
    list_events,
    list_infrastructure,
    source_response,
)
from app.schemas import (
    EventListResponse,
    EventResponse,
    HealthResponse,
    InfrastructureListResponse,
    InfrastructureResponse,
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
    allow_methods=["GET"],
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
