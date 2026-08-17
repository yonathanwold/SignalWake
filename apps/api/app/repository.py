from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Event, InfrastructureAsset, InfrastructureSource, Source
from app.schemas import (
    EventResponse,
    InfrastructureProvenance,
    InfrastructureResponse,
    Provenance,
    SourceResponse,
)
from app.spatial import geometry_intersects_bbox, parse_bbox


def _health(source: Source, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if source.last_error:
        return "ERROR"
    if source.last_success_at is None:
        return "UNKNOWN"
    success_at = source.last_success_at
    if success_at.tzinfo is None:
        success_at = success_at.replace(tzinfo=timezone.utc)
    age = (now - success_at).total_seconds()
    return "HEALTHY" if age < 3600 else "STALE"


def source_response(source: Source) -> SourceResponse:
    return SourceResponse.model_validate({**source.__dict__, "health": _health(source)})


def event_response(event: Event) -> EventResponse:
    try:
        geometry = json.loads(event.geometry_geojson) if event.geometry_geojson else None
    except json.JSONDecodeError:
        geometry = None
    try:
        provenance_data = json.loads(event.provenance_json or "[]")
    except json.JSONDecodeError:
        provenance_data = []
    return EventResponse(
        id=event.id,
        source_id=event.source_id,
        source_key=event.source.key if event.source else "unknown",
        source_name=event.source.name if event.source else "Unknown source",
        source_event_id=event.source_event_id,
        type=event.event_type,
        title=event.title,
        summary=event.summary,
        severity=event.severity,
        status=event.status,
        observed_at=event.observed_at,
        effective_at=event.effective_at,
        expires_at=event.expires_at,
        received_at=event.received_at,
        latitude=event.latitude,
        longitude=event.longitude,
        geometry=geometry,
        classification=event.classification,
        provenance=[Provenance.model_validate(item) for item in provenance_data],
    )


def apply_bbox(statement: Select, bbox: str | None) -> Select:
    if not bbox:
        return statement
    try:
        min_lon, min_lat, max_lon, max_lat = [float(value.strip()) for value in bbox.split(",")]
    except (ValueError, TypeError):
        return statement
    return statement.where(
        Event.longitude.is_not(None),
        Event.latitude.is_not(None),
        Event.longitude >= min_lon,
        Event.longitude <= max_lon,
        Event.latitude >= min_lat,
        Event.latitude <= max_lat,
    )


async def list_events(
    session: AsyncSession,
    *,
    bbox: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 50,
    cursor: int = 0,
) -> tuple[list[EventResponse], int, int | None]:
    statement = select(Event).options(joinedload(Event.source)).order_by(Event.observed_at.desc())
    count_statement = select(func.count(Event.id))
    if source:
        statement = statement.join(Event.source).where(Source.key == source.lower())
        count_statement = count_statement.join(Event.source).where(Source.key == source.lower())
    if event_type:
        statement = statement.where(Event.event_type == event_type)
        count_statement = count_statement.where(Event.event_type == event_type)
    if severity:
        statement = statement.where(Event.severity == severity)
        count_statement = count_statement.where(Event.severity == severity)
    if start_time:
        statement = statement.where(Event.observed_at >= start_time)
        count_statement = count_statement.where(Event.observed_at >= start_time)
    if end_time:
        statement = statement.where(Event.observed_at <= end_time)
        count_statement = count_statement.where(Event.observed_at <= end_time)
    statement = apply_bbox(statement, bbox)
    count_statement = apply_bbox(count_statement, bbox)
    total = int((await session.execute(count_statement)).scalar_one())
    result = await session.execute(statement.offset(cursor).limit(limit + 1))
    events = list(result.unique().scalars())
    next_cursor = cursor + limit if len(events) > limit else None
    return [event_response(item) for item in events[:limit]], total, next_cursor


async def get_event(session: AsyncSession, event_id: str) -> EventResponse | None:
    result = await session.execute(
        select(Event).options(joinedload(Event.source)).where(Event.id == event_id)
    )
    event = result.unique().scalar_one_or_none()
    return event_response(event) if event else None


def infrastructure_response(asset: InfrastructureAsset) -> InfrastructureResponse:
    try:
        geometry = json.loads(asset.geometry_geojson)
    except json.JSONDecodeError:
        geometry = {"type": asset.geometry_type, "coordinates": []}
    try:
        metadata = json.loads(asset.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    try:
        provenance_data = json.loads(asset.provenance_json or "[]")
    except json.JSONDecodeError:
        provenance_data = []
    source = asset.source
    return InfrastructureResponse(
        id=asset.id,
        source_id=asset.source_id,
        source_key=source.key if source else "unknown",
        source_name=source.name if source else "Unknown source",
        source_url=source.endpoint if source else "",
        source_attribution=source.attribution if source else "",
        source_license=source.license if source else "",
        source_asset_id=asset.source_asset_id,
        name=asset.name,
        type=asset.asset_type,
        subtype=asset.asset_subtype,
        operator=asset.operator,
        owner=asset.owner,
        status=asset.status,
        region=asset.region,
        latitude=asset.latitude,
        longitude=asset.longitude,
        geometry_type=asset.geometry_type,
        geometry=geometry,
        metadata=metadata if isinstance(metadata, dict) else {},
        classification=asset.classification,
        source_updated_at=asset.source_updated_at,
        imported_at=asset.imported_at,
        updated_at=asset.updated_at,
        provenance=[InfrastructureProvenance.model_validate(item) for item in provenance_data],
    )


def _postgres(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bool(bind is not None and bind.dialect.name == "postgresql")


def _infrastructure_bbox(statement: Select, bbox: tuple[float, float, float, float], *, postgres: bool) -> Select:
    min_lon, min_lat, max_lon, max_lat = bbox
    if postgres:
        return statement.where(
            text(
                "ST_Intersects(infrastructure_assets.geometry, "
                "ST_MakeEnvelope(:infra_min_lon, :infra_min_lat, :infra_max_lon, :infra_max_lat, 4326))"
            )
        ).params(
            infra_min_lon=min_lon,
            infra_min_lat=min_lat,
            infra_max_lon=max_lon,
            infra_max_lat=max_lat,
        )
    return statement


async def list_infrastructure(
    session: AsyncSession,
    *,
    bbox: str | None = None,
    asset_type: str | None = None,
    source: str | None = None,
    region: str | None = None,
    limit: int = 100,
    cursor: int = 0,
) -> tuple[list[InfrastructureResponse], int, int | None]:
    parsed_bbox = parse_bbox(bbox) if bbox else None
    postgres = _postgres(session)
    statement = select(InfrastructureAsset).options(joinedload(InfrastructureAsset.source)).order_by(
        InfrastructureAsset.name.asc(), InfrastructureAsset.id.asc()
    )
    count_statement = select(func.count(InfrastructureAsset.id))
    if source:
        statement = statement.join(InfrastructureAsset.source).where(InfrastructureSource.key == source.lower())
        count_statement = count_statement.join(InfrastructureAsset.source).where(InfrastructureSource.key == source.lower())
    if asset_type:
        statement = statement.where(InfrastructureAsset.asset_type == asset_type)
        count_statement = count_statement.where(InfrastructureAsset.asset_type == asset_type)
    if region:
        statement = statement.where(InfrastructureAsset.region == region)
        count_statement = count_statement.where(InfrastructureAsset.region == region)
    if parsed_bbox and postgres:
        statement = _infrastructure_bbox(statement, parsed_bbox, postgres=True)
        count_statement = _infrastructure_bbox(count_statement, parsed_bbox, postgres=True)
        total = int((await session.execute(count_statement)).scalar_one())
        result = await session.execute(statement.offset(cursor).limit(limit + 1))
        assets = list(result.unique().scalars())
    else:
        result = await session.execute(statement)
        assets = list(result.unique().scalars())
        if parsed_bbox:
            assets = [
                asset
                for asset in assets
                if geometry_intersects_bbox(json.loads(asset.geometry_geojson), parsed_bbox)
            ]
        total = len(assets)
        assets = assets[cursor : cursor + limit + 1]
    next_cursor = cursor + limit if len(assets) > limit else None
    return [infrastructure_response(item) for item in assets[:limit]], total, next_cursor


async def get_infrastructure(session: AsyncSession, asset_id: str) -> InfrastructureResponse | None:
    result = await session.execute(
        select(InfrastructureAsset)
        .options(joinedload(InfrastructureAsset.source))
        .where(InfrastructureAsset.id == asset_id)
    )
    asset = result.unique().scalar_one_or_none()
    return infrastructure_response(asset) if asset else None
