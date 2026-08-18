"""Bounded, deterministic historical state reconstruction.

Replay is knowledge-time based: a row is visible only when its recorded
ingestion/import/generation time is at or before the requested UTC boundary.
Event validity is then evaluated against that same boundary using the event's
effective and expiry timestamps.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EventVersion,
    InfrastructureAssessmentVersion,
    InfrastructureAssetVersion,
    InfrastructureSourceVersion,
    SourceStateVersion,
)

REPLAY_MAX_LIMIT = 100
REPLAY_SCAN_LIMIT = 10_000


def normalize_utc(value: datetime, field: str = "timestamp") -> datetime:
    """Require an unambiguous aware datetime and return UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset (use UTC, e.g. 2026-08-17T12:00:00Z)")
    return value.astimezone(timezone.utc)


def _stored_utc(value: datetime) -> datetime:
    """Treat timezone-stripped SQLite values as UTC; user input stays strict."""

    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _decode(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return normalize_utc(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return normalize_utc(parsed) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _sort_key(row: Any, field: str) -> tuple[datetime, str]:
    value = getattr(row, field)
    return _stored_utc(value), row.id


async def _as_of_rows(
    session: AsyncSession,
    model: Any,
    field: str,
    at: datetime,
) -> tuple[list[Any], bool]:
    """Load a bounded prefix and retain the latest row for each identity."""

    column = getattr(model, field)
    result = await session.execute(
        select(model).where(column <= at).order_by(column.desc(), model.id.desc()).limit(REPLAY_SCAN_LIMIT + 1)
    )
    rows = list(result.scalars())
    truncated = len(rows) > REPLAY_SCAN_LIMIT
    rows = rows[:REPLAY_SCAN_LIMIT]
    return rows, truncated


def _latest(rows: Iterable[Any], identity: Any, field: str) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for row in sorted(rows, key=lambda item: _sort_key(item, field)):
        result[identity(row)] = row
    return result


def _event_status(snapshot: dict[str, Any], at: datetime) -> tuple[str, bool]:
    effective = _parse(snapshot.get("effective_at")) or _parse(snapshot.get("observed_at"))
    expires = _parse(snapshot.get("expires_at"))
    happened = effective is not None and effective <= at
    if expires is not None and at >= expires:
        return "expired", happened
    if effective is not None and at < effective:
        return "historical", False
    if snapshot.get("status") == "observed" and happened:
        return "historical", True
    return "active", happened


def _event_projection(row: EventVersion, at: datetime) -> dict[str, Any]:
    snapshot = _decode(row.snapshot_json)
    temporal_status, happened = _event_status(snapshot, at)
    recorded_at = _stored_utc(row.recorded_at)
    snapshot.update(
        {
            "knowledge_at": recorded_at,
            "recorded_at": recorded_at,
            "event_time": _parse(snapshot.get("effective_at")) or _parse(snapshot.get("observed_at")),
            "happened_by_at": happened,
            "temporal_status": temporal_status,
            "replay_classification": "HISTORICAL",
            "version_id": row.id,
            "version_payload_hash": row.payload_hash,
        }
    )
    return snapshot


def _assessment_projection(row: InfrastructureAssessmentVersion) -> dict[str, Any]:
    snapshot = _decode(row.snapshot_json)
    generated_at = _stored_utc(row.generated_at)
    snapshot.update({"knowledge_at": generated_at, "generated_at": generated_at, "version_id": row.id})
    return snapshot


def _asset_projection(row: InfrastructureAssetVersion) -> dict[str, Any]:
    snapshot = _decode(row.snapshot_json)
    recorded_at = _stored_utc(row.recorded_at)
    snapshot.update(
        {
            "knowledge_at": recorded_at,
            "recorded_at": recorded_at,
            "version_id": row.id,
            "version_payload_hash": row.payload_hash,
            "replay_classification": "HISTORICAL",
        }
    )
    return snapshot


def _source_health(snapshot: dict[str, Any], at: datetime) -> str:
    if snapshot.get("last_error"):
        return "ERROR"
    success_at = _parse(snapshot.get("last_success_at"))
    if success_at is None:
        return "UNKNOWN"
    return "HEALTHY" if (at - success_at).total_seconds() < 3600 else "STALE"


def _source_projection(row: SourceStateVersion, at: datetime) -> dict[str, Any]:
    snapshot = _decode(row.snapshot_json)
    recorded_at = _stored_utc(row.recorded_at)
    snapshot.update({"knowledge_at": recorded_at, "recorded_at": recorded_at, "health": _source_health(snapshot, at)})
    return snapshot


def _identity_event(row: EventVersion) -> tuple[str, str]:
    return row.source_id, row.source_event_id


def _identity_asset(row: InfrastructureAssetVersion) -> tuple[str, str]:
    return row.source_id, row.source_asset_id


def _identity_assessment(row: InfrastructureAssessmentVersion) -> str:
    return row.assessment_key


async def _collect(session: AsyncSession, at: datetime) -> dict[str, Any]:
    event_rows, event_truncated = await _as_of_rows(session, EventVersion, "recorded_at", at)
    asset_rows, asset_truncated = await _as_of_rows(session, InfrastructureAssetVersion, "recorded_at", at)
    assessment_rows, assessment_truncated = await _as_of_rows(
        session, InfrastructureAssessmentVersion, "generated_at", at
    )
    source_rows, source_truncated = await _as_of_rows(session, SourceStateVersion, "recorded_at", at)
    infra_source_rows, infra_source_truncated = await _as_of_rows(
        session, InfrastructureSourceVersion, "recorded_at", at
    )
    events = [_event_projection(row, at) for row in _latest(event_rows, _identity_event, "recorded_at").values()]
    assets = [_asset_projection(row) for row in _latest(asset_rows, _identity_asset, "recorded_at").values()]
    assessments = [
        _assessment_projection(row)
        for row in _latest(assessment_rows, _identity_assessment, "generated_at").values()
        if not row.is_deleted
    ]
    sources = [_source_projection(row, at) for row in _latest(source_rows, lambda row: row.source_id, "recorded_at").values()]
    infrastructure_sources = [
        _decode(row.snapshot_json) | {"knowledge_at": _stored_utc(row.recorded_at), "recorded_at": _stored_utc(row.recorded_at)}
        for row in _latest(infra_source_rows, lambda row: row.source_id, "recorded_at").values()
    ]
    events.sort(key=lambda item: (item.get("event_time") or item.get("observed_at") or "", item.get("id", "")))
    assets.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    assessments.sort(key=lambda item: (-float(item.get("score", 0)), item.get("assessment_key", "")))
    sources.sort(key=lambda item: item.get("key", ""))
    infrastructure_sources.sort(key=lambda item: item.get("key", ""))
    return {
        "events": events,
        "assessments": assessments,
        "infrastructure": assets,
        "sources": sources,
        "infrastructure_sources": infrastructure_sources,
        "truncated": any((event_truncated, asset_truncated, assessment_truncated, source_truncated, infra_source_truncated)),
    }


async def replay_state(session: AsyncSession, at: datetime, *, limit: int = 50) -> dict[str, Any]:
    at = normalize_utc(at, "at")
    if not 1 <= limit <= REPLAY_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {REPLAY_MAX_LIMIT}")
    state = await _collect(session, at)
    truncated = state["truncated"]
    result: dict[str, Any] = {
        "timestamp": at,
        "as_of": at,
        "events": state["events"][:limit],
        "assessments": state["assessments"][:limit],
        "infrastructure": state["infrastructure"][:limit],
        "sources": state["sources"][:limit],
        "infrastructure_sources": state["infrastructure_sources"][:limit],
        "counts": {
            "events": len(state["events"]),
            "assessments": len(state["assessments"]),
            "infrastructure": len(state["infrastructure"]),
            "sources": len(state["sources"]),
            "infrastructure_sources": len(state["infrastructure_sources"]),
        },
        "limit": limit,
        "truncated": truncated
        or any(
            len(state[key]) > limit
            for key in ("events", "assessments", "infrastructure", "sources", "infrastructure_sources")
        ),
        "semantics": {
            "knowledge_time": "Rows are included only when recorded/generated/imported at or before timestamp.",
            "event_time": "Event effective/observed timestamps are retained separately and do not control visibility.",
            "boundary": "The at boundary is inclusive; expiry at exactly at is expired.",
            "timezone": "All replay timestamps are normalized to UTC.",
        },
    }
    return result


async def replay_timeline(
    session: AsyncSession, start_time: datetime, end_time: datetime, *, limit: int = 100
) -> dict[str, Any]:
    start = normalize_utc(start_time, "start_time")
    end = normalize_utc(end_time, "end_time")
    if start > end:
        raise ValueError("start_time must not be after end_time")
    if not 1 <= limit <= REPLAY_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {REPLAY_MAX_LIMIT}")
    markers: list[dict[str, Any]] = []
    model_fields = (
        (EventVersion, "recorded_at", "event"),
        (InfrastructureAssetVersion, "recorded_at", "infrastructure"),
        (InfrastructureAssessmentVersion, "generated_at", "assessment"),
        (SourceStateVersion, "recorded_at", "source"),
        (InfrastructureSourceVersion, "recorded_at", "infrastructure_source"),
    )
    truncated = False
    for model, field, kind in model_fields:
        column = getattr(model, field)
        rows = list(
            (
                await session.execute(
                    select(model)
                    .where(column >= start, column <= end)
                    .order_by(column.asc(), model.id.asc())
                    .limit(REPLAY_SCAN_LIMIT + 1)
                )
            ).scalars()
        )
        truncated = truncated or len(rows) > REPLAY_SCAN_LIMIT
        for row in rows[:REPLAY_SCAN_LIMIT]:
            timestamp = _stored_utc(getattr(row, field))
            if kind == "event":
                label = f"event:{row.source_event_id}"
                identity = f"{row.source_id}:{row.source_event_id}"
            elif kind == "infrastructure":
                label = f"asset:{row.source_asset_id}"
                identity = f"{row.source_id}:{row.source_asset_id}"
            elif kind == "assessment":
                label = f"assessment:{row.assessment_key}"
                identity = row.assessment_key
            elif kind == "source":
                label = f"source:{row.source_id}"
                identity = row.source_id
            else:
                label = f"infrastructure_source:{row.source_id}"
                identity = row.source_id
            markers.append(
                {
                    "timestamp": timestamp,
                    "recorded_at": timestamp,
                    "kind": kind,
                    "id": row.id,
                    "identity": identity,
                    "label": label,
                    "change": "deleted" if getattr(row, "is_deleted", False) else "versioned",
                }
            )
    markers.sort(key=lambda item: (item["timestamp"], item["kind"], item["identity"], item["id"]))
    return {
        "start_time": start,
        "end_time": end,
        "items": markers[:limit],
        "limit": limit,
        "truncated": truncated or len(markers) > limit,
        "total": len(markers),
    }


def _changed(
    before: list[dict[str, Any]], after: list[dict[str, Any]], identity: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    before_map = {identity(item): item for item in before}
    after_map = {identity(item): item for item in after}
    newly_known = [after_map[key] for key in sorted(after_map.keys(), key=str) if key not in before_map]
    updated = [
        {"before": before_map[key], "after": after_map[key]}
        for key in sorted(after_map.keys(), key=str)
        if key in before_map and json.dumps(before_map[key], sort_keys=True, default=str) != json.dumps(after_map[key], sort_keys=True, default=str)
    ]
    expired = [item for item in after if item.get("temporal_status") == "expired" and before_map.get(identity(item), {}).get("temporal_status") != "expired"]
    return newly_known, updated, expired


async def replay_compare(
    session: AsyncSession,
    from_time: datetime,
    to_time: datetime,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    start = normalize_utc(from_time, "from_time")
    end = normalize_utc(to_time, "to_time")
    if start > end:
        raise ValueError("from_time must not be after to_time")
    if not 1 <= limit <= REPLAY_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {REPLAY_MAX_LIMIT}")
    before = await _collect(session, start)
    after = await _collect(session, end)
    new_events, updated_events, expired_events = _changed(
        before["events"], after["events"], lambda item: (item.get("source_id"), item.get("source_event_id"))
    )
    new_assessments, changed_assessments, _ = _changed(
        before["assessments"], after["assessments"], lambda item: item.get("assessment_key")
    )
    new_assets, changed_assets, _ = _changed(
        before["infrastructure"], after["infrastructure"], lambda item: (item.get("source_id"), item.get("source_asset_id"))
    )
    changes = {
        "newly_known_events": new_events[:limit],
        "updated_events": updated_events[:limit],
        "expired_events": expired_events[:limit],
        "new_assessments": new_assessments[:limit],
        "changed_assessments": changed_assessments[:limit],
        "newly_exposed_infrastructure": new_assets[:limit],
        "changed_infrastructure": changed_assets[:limit],
    }
    return {
        "from_time": start,
        "to_time": end,
        "summary": {
            "newly_known_events": len(new_events),
            "updated_events": len(updated_events),
            "expired_events": len(expired_events),
            "new_assessments": len(new_assessments),
            "changed_assessments": len(changed_assessments),
            "newly_exposed_infrastructure": len(new_assets),
            "changed_infrastructure": len(changed_assets),
        },
        "changes": changes,
        "limit": limit,
        "truncated": before["truncated"] or after["truncated"] or any(
            len(value) > limit for value in (new_events, updated_events, expired_events, new_assessments, changed_assessments, new_assets, changed_assets)
        ),
    }
