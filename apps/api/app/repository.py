from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Event, Source
from app.schemas import EventResponse, Provenance, SourceResponse


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
