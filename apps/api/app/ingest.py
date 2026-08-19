from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, payload_hash
from app.history import record_event_version, record_source_state
from app.models import Event, ProcessingState, RawObservation, Source, TransformationRun
from app.observability import bounded_text, error_category

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AdapterIngestResult:
    source_key: str
    attempted_at: datetime
    fetch_succeeded: bool
    fetched_count: int = 0
    normalized_count: int = 0
    skipped_count: int = 0
    http_status: int | None = None
    error: str | None = None

    @property
    def has_usable_events(self) -> bool:
        return self.normalized_count > 0


@dataclass(frozen=True)
class IngestReport:
    results: tuple[AdapterIngestResult, ...]

    @property
    def usable_source_keys(self) -> set[str]:
        return {result.source_key for result in self.results if result.has_usable_events}

    @property
    def fallback_source_keys(self) -> set[str]:
        return {result.source_key for result in self.results if not result.has_usable_events}


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
    else:
        # Keep the current source projection aligned with deploy-time adapter
        # configuration. Append-only source history is written separately by
        # record_source_state and is intentionally not rewritten here.
        source.name = adapter.name
        source.kind = adapter.key.upper()
        source.endpoint = adapter.endpoint
        source.adapter_version = adapter.adapter_version
    return source


async def ingest_once(session: AsyncSession, source_adapters: Iterable[SourceAdapter]) -> IngestReport:
    """Fetch, normalize, and persist one bounded pass over every configured source."""

    results: list[AdapterIngestResult] = []
    for adapter in source_adapters:
        attempted_at = datetime.now(timezone.utc)
        source = await ensure_source(session, adapter)
        run = TransformationRun(
            id=str(uuid.uuid4()),
            run_kind="source_ingest",
            version=adapter.adapter_version,
            source_id=source.id,
            started_at=attempted_at,
            created_at=attempted_at,
            status="running",
        )
        session.add(run)
        await session.flush()
        source.last_run_id = run.id
        source.last_attempt_at = attempted_at
        source.last_http_status = None
        try:
            features = await adapter.fetch()
        except Exception as exc:  # noqa: BLE001 - one source must not block the other
            error = bounded_text(exc) or "source fetch failed"
            category = error_category(exc)
            source.last_error = error
            source.last_failure_at = attempted_at
            source.last_error_category = category
            source.last_http_status = adapter.last_http_status
            source.freshness_seconds = None
            source.last_records_retrieved = 0
            source.last_records_accepted = 0
            source.last_records_rejected = 0
            run.completed_at = datetime.now(timezone.utc)
            run.status = "failed"
            run.error = error
            run.error_category = category
            run.records_retrieved = 0
            run.records_accepted = 0
            run.records_rejected = 0
            await record_source_state(session, source, attempted_at)
            log.error(
                "source_ingest_failed",
                source=adapter.key,
                attempted_at=attempted_at.isoformat(),
                http_status=adapter.last_http_status,
                error=error,
            )
            results.append(
                AdapterIngestResult(
                    source_key=adapter.key,
                    attempted_at=attempted_at,
                    fetch_succeeded=False,
                    http_status=adapter.last_http_status,
                    error=error,
                )
            )
            continue

        normalized_count = 0
        skipped_count = 0
        latest_observed: datetime | None = None
        for index, feature in enumerate(features):
            if not isinstance(feature, dict):
                skipped_count += 1
                log.warning("source_feature_skipped", source=adapter.key, index=index, error="feature is not an object")
                continue
            try:
                normalized = adapter.normalize(feature, attempted_at)
                await persist_normalized(
                    session,
                    source,
                    adapter,
                    normalized,
                    fetched_at=attempted_at,
                    classification="LIVE",
                )
            except (AdapterError, AttributeError, KeyError, TypeError, ValueError) as exc:
                skipped_count += 1
                log.warning(
                    "source_feature_skipped",
                    source=adapter.key,
                    index=index,
                    error=bounded_text(exc),
                )
                continue
            normalized_count += 1
            latest_observed = max(latest_observed, normalized.observed_at) if latest_observed else normalized.observed_at

        source.last_http_status = adapter.last_http_status
        source.freshness_seconds = (
            max(0, int((attempted_at - latest_observed).total_seconds())) if latest_observed else 0
        )
        source.last_records_retrieved = len(features)
        source.last_records_accepted = normalized_count
        source.last_records_rejected = skipped_count
        run.completed_at = datetime.now(timezone.utc)
        run.status = "completed"
        run.records_retrieved = len(features)
        run.records_accepted = normalized_count
        run.records_rejected = skipped_count
        error = None
        if skipped_count:
            error = f"{skipped_count} malformed feature(s) skipped"
            source.last_error = error
            source.last_failure_at = attempted_at
            source.last_error_category = "normalization_error"
            run.error = error
            run.error_category = "normalization_error"
            if normalized_count == 0:
                run.status = "failed"
                source.freshness_seconds = None
            log.warning(
                "source_ingest_partial",
                source=adapter.key,
                fetched_count=len(features),
                normalized_count=normalized_count,
                skipped_count=skipped_count,
            )
        elif normalized_count == 0 and adapter.last_http_status == 204:
            # AviationWeather.gov uses 204 to signal a valid empty PIREP
            # result. Treat it as a successful poll rather than malformed
            # data or a provider failure.
            source.last_success_at = attempted_at
            source.last_error = None
            source.freshness_seconds = 0
            run.error_category = None
            log.info(
                "source_ingest_empty_success",
                source=adapter.key,
                http_status=adapter.last_http_status,
            )
        elif normalized_count == 0:
            error = "no usable records returned"
            source.last_error = error
            source.last_failure_at = attempted_at
            source.last_error_category = "no_usable_records"
            source.freshness_seconds = None
            run.status = "failed"
            run.error = error
            run.error_category = "no_usable_records"
            log.warning(
                "source_ingest_empty",
                source=adapter.key,
                fetched_count=len(features),
                error_category="no_usable_records",
            )
        else:
            source.last_success_at = attempted_at
            source.last_error = None
            run.error_category = None
            log.info(
                "source_ingest_succeeded",
                source=adapter.key,
                fetched_count=len(features),
                normalized_count=normalized_count,
            )
        await record_source_state(session, source, attempted_at)
        results.append(
            AdapterIngestResult(
                source_key=adapter.key,
                attempted_at=attempted_at,
                fetch_succeeded=True,
                fetched_count=len(features),
                normalized_count=normalized_count,
                skipped_count=skipped_count,
                http_status=adapter.last_http_status,
                error=error,
            )
        )
    return IngestReport(tuple(results))


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
        existing.raw_observation_id = raw.id
        existing.event_type = normalized.event_type
        existing.title = normalized.title
        existing.summary = normalized.summary
        existing.severity = normalized.severity
        existing.status = normalized.status
        existing.observed_at = normalized.observed_at
        existing.effective_at = normalized.effective_at
        existing.expires_at = normalized.expires_at
        existing.received_at = fetched_at
        existing.latitude = normalized.latitude
        existing.longitude = normalized.longitude
        existing.geometry_geojson = json.dumps(normalized.geometry, sort_keys=True) if normalized.geometry else None
        existing.provenance_json = json.dumps(
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
        )
        existing.payload_hash = digest
        existing.normalized_version = adapter.adapter_version
        if classification == "LIVE" or existing.classification != "LIVE":
            existing.classification = classification
        raw.processing_state = ProcessingState.NORMALIZED.value
        await record_event_version(session, existing, source)
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
    await record_event_version(session, event, source)
    return event
