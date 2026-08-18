"""Append-only knowledge-time snapshots used by Historical Replay.

The live tables remain the current projections used by existing endpoints.
These small snapshot tables make it possible to answer what was known at a
past UTC boundary without introducing a full event-sourcing runtime.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Event,
    EventVersion,
    InfrastructureAssessment,
    InfrastructureAssessmentVersion,
    InfrastructureAsset,
    InfrastructureAssetVersion,
    InfrastructureSource,
    InfrastructureSourceVersion,
    Source,
    SourceStateVersion,
)


def utc(value: datetime) -> datetime:
    """Normalize internal timestamps to aware UTC values."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_dict(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def event_snapshot(event: Event, source: Source | None = None) -> dict[str, Any]:
    geometry = None
    if event.geometry_geojson:
        try:
            geometry = json.loads(event.geometry_geojson)
        except (TypeError, json.JSONDecodeError):
            geometry = None
    provenance = []
    try:
        parsed = json.loads(event.provenance_json or "[]")
        provenance = parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        pass
    return {
        "id": event.id,
        "source_id": event.source_id,
        "source_key": source.key if source else None,
        "source_name": source.name if source else None,
        "source_event_id": event.source_event_id,
        "type": event.event_type,
        "title": event.title,
        "summary": event.summary,
        "severity": event.severity,
        "status": event.status,
        "observed_at": utc(event.observed_at).isoformat(),
        "effective_at": utc(event.effective_at).isoformat() if event.effective_at else None,
        "expires_at": utc(event.expires_at).isoformat() if event.expires_at else None,
        "received_at": utc(event.received_at).isoformat(),
        "latitude": event.latitude,
        "longitude": event.longitude,
        "geometry": geometry,
        "classification": event.classification,
        "provenance": provenance,
        "payload_hash": event.payload_hash,
        "normalized_version": event.normalized_version,
    }


def source_snapshot(source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "key": source.key,
        "name": source.name,
        "kind": source.kind,
        "endpoint": source.endpoint,
        "active": source.active,
        "adapter_version": source.adapter_version,
        "last_success_at": utc(source.last_success_at).isoformat() if source.last_success_at else None,
        "last_attempt_at": utc(source.last_attempt_at).isoformat() if source.last_attempt_at else None,
        "last_error": source.last_error,
        "last_http_status": source.last_http_status,
        "freshness_seconds": source.freshness_seconds,
        "expected_update_interval_seconds": source.expected_update_interval_seconds,
        "last_run_id": source.last_run_id,
        "last_records_retrieved": source.last_records_retrieved,
        "last_records_accepted": source.last_records_accepted,
        "last_records_rejected": source.last_records_rejected,
    }


def infrastructure_source_snapshot(source: InfrastructureSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "key": source.key,
        "name": source.name,
        "endpoint": source.endpoint,
        "attribution": source.attribution,
        "license": source.license,
        "adapter_version": source.adapter_version,
        "active": source.active,
        "last_import_at": utc(source.last_import_at).isoformat() if source.last_import_at else None,
        "last_import_count": source.last_import_count,
        "last_import_error": source.last_import_error,
    }


def asset_snapshot(asset: InfrastructureAsset, source: InfrastructureSource | None = None) -> dict[str, Any]:
    return {
        "id": asset.id,
        "source_id": asset.source_id,
        "source_key": source.key if source else None,
        "source_name": source.name if source else None,
        "source_url": source.endpoint if source else None,
        "source_attribution": source.attribution if source else None,
        "source_license": source.license if source else None,
        "source_asset_id": asset.source_asset_id,
        "name": asset.name,
        "type": asset.asset_type,
        "subtype": asset.asset_subtype,
        "operator": asset.operator,
        "owner": asset.owner,
        "status": asset.status,
        "region": asset.region,
        "latitude": asset.latitude,
        "longitude": asset.longitude,
        "geometry_type": asset.geometry_type,
        "geometry": _json_dict(asset.geometry_geojson),
        "metadata": _json_dict(asset.metadata_json),
        "classification": asset.classification,
        "source_updated_at": utc(asset.source_updated_at).isoformat() if asset.source_updated_at else None,
        "imported_at": utc(asset.imported_at).isoformat(),
        "updated_at": utc(asset.updated_at).isoformat(),
        "provenance": _json_dict(asset.provenance_json) if isinstance(asset.provenance_json, dict) else json.loads(asset.provenance_json or "[]"),
    }


def assessment_snapshot(assessment: InfrastructureAssessment) -> dict[str, Any]:
    return {
        "classification": "SIGNALWAKE DERIVED ASSESSMENT",
        "id": assessment.id,
        "assessment_key": assessment.assessment_key,
        "assessment_type": assessment.assessment_type,
        "event_id": assessment.event_id,
        "affected_asset_id": assessment.affected_asset_id,
        "affected_region": assessment.affected_region,
        "severity": assessment.severity,
        "status": assessment.status,
        "score": assessment.score,
        "confidence": assessment.confidence,
        "methodology_version": assessment.methodology_version,
        "evidence": _json_dict(assessment.evidence_json),
        "score_components": _json_dict(assessment.score_components_json),
        "metadata": _json_dict(assessment.metadata_json),
        "created_at": utc(assessment.created_at).isoformat(),
        "updated_at": utc(assessment.updated_at).isoformat(),
    }


async def _event_validity(session: AsyncSession, event_id: str) -> None:
    rows = list(
        (
            await session.execute(
                select(EventVersion).where(EventVersion.event_id == event_id).order_by(EventVersion.recorded_at, EventVersion.id)
            )
        ).scalars()
    )
    for index, row in enumerate(rows):
        row.valid_to = rows[index + 1].recorded_at if index + 1 < len(rows) else None


async def record_event_version(
    session: AsyncSession, event: Event, source: Source | None = None
) -> EventVersion | None:
    """Record a changed payload once; repeated polls of identical data are idempotent."""

    await session.flush()
    existing = await session.scalar(
        select(EventVersion).where(EventVersion.event_id == event.id, EventVersion.payload_hash == event.payload_hash)
    )
    if existing is not None:
        return None
    version = EventVersion(
        event_id=event.id,
        source_id=event.source_id,
        source_event_id=event.source_event_id,
        raw_observation_id=event.raw_observation_id,
        recorded_at=utc(event.received_at),
        payload_hash=event.payload_hash,
        snapshot_json=_json(event_snapshot(event, source)),
    )
    session.add(version)
    await session.flush()
    await _event_validity(session, event.id)
    return version


async def record_source_state(session: AsyncSession, source: Source, recorded_at: datetime) -> SourceStateVersion:
    version = SourceStateVersion(
        source_id=source.id, recorded_at=utc(recorded_at), snapshot_json=_json(source_snapshot(source))
    )
    session.add(version)
    return version


async def record_infrastructure_source_state(
    session: AsyncSession, source: InfrastructureSource, recorded_at: datetime
) -> InfrastructureSourceVersion:
    version = InfrastructureSourceVersion(
        source_id=source.id,
        recorded_at=utc(recorded_at),
        snapshot_json=_json(infrastructure_source_snapshot(source)),
    )
    session.add(version)
    return version


async def _asset_validity(session: AsyncSession, asset_id: str) -> None:
    rows = list(
        (
            await session.execute(
                select(InfrastructureAssetVersion)
                .where(InfrastructureAssetVersion.asset_id == asset_id)
                .order_by(InfrastructureAssetVersion.recorded_at, InfrastructureAssetVersion.id)
            )
        ).scalars()
    )
    for index, row in enumerate(rows):
        row.valid_to = rows[index + 1].recorded_at if index + 1 < len(rows) else None


async def record_asset_version(
    session: AsyncSession,
    asset: InfrastructureAsset,
    source: InfrastructureSource | None = None,
    *,
    recorded_at: datetime | None = None,
) -> InfrastructureAssetVersion | None:
    await session.flush()
    existing = await session.scalar(
        select(InfrastructureAssetVersion).where(
            InfrastructureAssetVersion.asset_id == asset.id,
            InfrastructureAssetVersion.payload_hash == asset.payload_hash,
        )
    )
    if existing is not None:
        return None
    version = InfrastructureAssetVersion(
        asset_id=asset.id,
        source_id=asset.source_id,
        source_asset_id=asset.source_asset_id,
        recorded_at=utc(recorded_at or asset.imported_at),
        payload_hash=asset.payload_hash,
        snapshot_json=_json(asset_snapshot(asset, source)),
    )
    session.add(version)
    await session.flush()
    await _asset_validity(session, asset.id)
    return version


async def _assessment_validity(session: AsyncSession, assessment_key: str) -> None:
    rows = list(
        (
            await session.execute(
                select(InfrastructureAssessmentVersion)
                .where(InfrastructureAssessmentVersion.assessment_key == assessment_key)
                .order_by(InfrastructureAssessmentVersion.generated_at, InfrastructureAssessmentVersion.id)
            )
        ).scalars()
    )
    for index, row in enumerate(rows):
        row.valid_to = rows[index + 1].generated_at if index + 1 < len(rows) else None


async def record_assessment_version(
    session: AsyncSession,
    assessment: InfrastructureAssessment | None,
    *,
    assessment_key: str,
    event_id: str,
    methodology_version: str,
    generated_at: datetime,
    is_deleted: bool = False,
) -> InfrastructureAssessmentVersion:
    version = InfrastructureAssessmentVersion(
        assessment_id=assessment.id if assessment else None,
        assessment_key=assessment_key,
        event_id=event_id,
        methodology_version=methodology_version,
        generated_at=utc(generated_at),
        is_deleted=is_deleted,
        snapshot_json=_json(assessment_snapshot(assessment)) if assessment else _json({}),
    )
    session.add(version)
    await session.flush()
    await _assessment_validity(session, assessment_key)
    return version
