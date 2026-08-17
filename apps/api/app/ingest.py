from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import NormalizedEvent, SourceAdapter, payload_hash
from app.models import Event, ProcessingState, RawObservation, Source

log = structlog.get_logger(__name__)


async def ensure_source(session: AsyncSession, adapter: SourceAdapter) -> Source:
    source = (await session.execute(select(Source).where(Source.key == adapter.key))).scalar_one_or_none()
    if source is None:
        source = Source(
            key=adapter.key,
            name=adapter.name,
            kind=adapter.key.upper(),
            endpoint=adapter.endpoint,
            adapter_version=adapter.adapter_version,
        )
        session.add(source)
        await session.flush()
    return source


async def persist_normalized(
    session: AsyncSession,
    source: Source,
    adapter: SourceAdapter,
    normalized: NormalizedEvent,
    *,
    fetched_at: datetime | None = None,
    classification: str = "LIVE",
) -> Event:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    payload = normalized.payload
    digest = payload_hash(payload)
    raw = (
        await session.execute(
            select(RawObservation).where(
                RawObservation.source_id == source.id, RawObservation.payload_hash == digest
            )
        )
    ).scalar_one_or_none()
    if raw is None:
        raw = RawObservation(
            source_id=source.id,
            source_record_id=normalized.source_event_id,
            observed_at=normalized.observed_at,
            fetched_at=fetched_at,
            payload=json.dumps(payload, sort_keys=True),
            payload_hash=digest,
            processing_state=ProcessingState.RECEIVED.value,
            adapter_version=adapter.adapter_version,
        )
        session.add(raw)
        await session.flush()
    existing = (
        await session.execute(
            select(Event).where(
                Event.source_id == source.id, Event.source_event_id == normalized.source_event_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    event = Event(
        source_id=source.id,
        raw_observation_id=raw.id,
        source_event_id=normalized.source_event_id,
        event_type=normalized.event_type,
        title=normalized.title,
        summary=normalized.summary,
        severity=normalized.severity,
        status=normalized.status,
        observed_at=normalized.observed_at,
        effective_at=normalized.effective_at,
        expires_at=normalized.expires_at,
        received_at=fetched_at,
        latitude=normalized.latitude,
        longitude=normalized.longitude,
        geometry_geojson=json.dumps(normalized.geometry, sort_keys=True) if normalized.geometry else None,
        provenance_json=json.dumps(
            [
                {
                    "source_record_id": normalized.source_event_id,
                    "source_url": adapter.endpoint,
                    "fetched_at": fetched_at.isoformat(),
                    "raw_observation_id": raw.id,
                    "adapter_version": adapter.adapter_version,
                    "payload_hash": digest,
                }
            ]
        ),
        payload_hash=digest,
        normalized_version=adapter.adapter_version,
        classification=classification,
    )
    raw.processing_state = ProcessingState.NORMALIZED.value
    session.add(event)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return (
            await session.execute(
                select(Event).where(
                    Event.source_id == source.id, Event.source_event_id == normalized.source_event_id
                )
            )
        ).scalar_one()
    return event

