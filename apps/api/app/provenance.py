"""Bounded provenance graph construction for the Phase 7 workspace.

The current projections already contain stable foreign keys and evidence JSON.
This module turns those facts into a small, deterministic one-hop graph.  An
explicit ``LineageRecord`` is honored when present, while legacy rows are
covered by the same deterministic relationships without a backfill job.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models import (
    Event,
    EventVersion,
    InfrastructureAssessment,
    InfrastructureAssessmentVersion,
    InfrastructureAsset,
    InfrastructureAssetVersion,
    InfrastructureRelationship,
    InfrastructureSource,
    LineageRecord,
    RawInfrastructureRecord,
    RawObservation,
    Scenario,
    ScenarioResult,
    ScenarioRun,
    Source,
    TransformationRun,
)

OBJECT_TYPES = {
    "event",
    "raw_observation",
    "asset",
    "raw_infrastructure_record",
    "relationship",
    "assessment",
    "scenario",
    "scenario_run",
    "scenario_result",
    "source",
    "transformation_run",
    "event_version",
    "assessment_version",
}
DIRECTIONS = {"upstream", "downstream", "both"}


def _json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _list_json(value: str | list[Any] | None) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _source_info(source: Source | InfrastructureSource | None) -> dict[str, Any] | None:
    if source is None:
        return None
    last_error = getattr(source, "last_error", None) or getattr(source, "last_import_error", None)
    if last_error:
        health = "ERROR"
    else:
        last_success = getattr(source, "last_success_at", None) or getattr(source, "last_import_at", None)
        if last_success is None:
            health = "UNKNOWN"
        else:
            if last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=timezone.utc)
            interval = getattr(source, "expected_update_interval_seconds", None) or 3600
            health = "HEALTHY" if (datetime.now(timezone.utc) - last_success).total_seconds() < interval else "STALE"
    return {
        "id": source.id,
        "key": source.key,
        "name": source.name,
        "url": source.endpoint,
        "health": health,
    }


def _kind(type_name: str) -> str:
    return "direct" if type_name in {"source", "raw_observation", "raw_infrastructure_record"} else "derived"


def _node(
    type_name: str,
    object_id: str,
    *,
    label: str | None = None,
    direct_or_derived: str | None = None,
    source: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
    ingested_at: datetime | None = None,
    generated_at: datetime | None = None,
    transformation: dict[str, Any] | None = None,
    freshness_seconds: int | None = None,
    confidence: float | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": type_name,
        "id": str(object_id),
        "label": label or f"{type_name.replace('_', ' ').title()} {str(object_id)[:12]}",
        "direct_or_derived": direct_or_derived or _kind(type_name),
        "source": source,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "generated_at": generated_at,
        "transformation": transformation,
        "freshness_seconds": freshness_seconds,
        "confidence": confidence,
        "evidence": evidence or {},
    }


def _edge(
    upstream_type: str,
    upstream_id: str,
    downstream_type: str,
    downstream_id: str,
    relation_kind: str,
    *,
    evidence: dict[str, Any] | None = None,
    transformation_run_id: str | None = None,
    observed_at: datetime | None = None,
    ingested_at: datetime | None = None,
    generated_at: datetime | None = None,
    edge_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": edge_id or f"{upstream_type}:{upstream_id}|{relation_kind}|{downstream_type}:{downstream_id}",
        "upstream": {"type": upstream_type, "id": str(upstream_id)},
        "downstream": {"type": downstream_type, "id": str(downstream_id)},
        "relation_kind": relation_kind,
        "transformation_run_id": transformation_run_id,
        "evidence": evidence or {},
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "generated_at": generated_at,
    }


def _edge_matches(edge: dict[str, Any], object_type: str, object_id: str, direction: str) -> bool:
    upstream = edge["upstream"] == {"type": object_type, "id": str(object_id)}
    downstream = edge["downstream"] == {"type": object_type, "id": str(object_id)}
    return direction == "both" or (direction == "upstream" and downstream) or (direction == "downstream" and upstream)


async def _load_objects(session: AsyncSession) -> dict[str, dict[str, Any]]:
    """Load the bounded object catalog used to materialize lineage nodes."""

    objects: dict[str, dict[str, Any]] = {}
    sources = list((await session.execute(select(Source))).scalars().all())
    infra_sources = list((await session.execute(select(InfrastructureSource))).scalars().all())
    for item in sources + infra_sources:
        objects[f"source:{item.id}"] = _node(
            "source",
            item.id,
            label=item.name,
            direct_or_derived="direct",
            source=_source_info(item),
            generated_at=getattr(item, "last_success_at", None) or getattr(item, "last_import_at", None),
            freshness_seconds=getattr(item, "freshness_seconds", None),
            transformation={
                "version": item.adapter_version,
                "run_id": getattr(item, "last_run_id", None),
            },
            evidence={
                "last_error": getattr(item, "last_error", None) or getattr(item, "last_import_error", None),
                "records_retrieved": getattr(item, "last_records_retrieved", None),
                "records_accepted": getattr(item, "last_records_accepted", None),
                "records_rejected": getattr(item, "last_records_rejected", None),
            },
        )

    raw_rows = list((await session.execute(select(RawObservation).options(joinedload(RawObservation.source)))).scalars().all())
    for item in raw_rows:
        objects[f"raw_observation:{item.id}"] = _node(
            "raw_observation",
            item.id,
            label=f"Raw observation {item.source_record_id}",
            direct_or_derived="direct",
            source=_source_info(item.source),
            observed_at=item.observed_at,
            ingested_at=item.fetched_at,
            transformation={"version": item.adapter_version, "run_kind": "source_ingest"},
            evidence={"source_record_id": item.source_record_id, "payload_hash": item.payload_hash, "processing_state": item.processing_state},
        )

    events = list((await session.execute(select(Event).options(joinedload(Event.source)))).scalars().all())
    events_by_id = {item.id: item for item in events}
    for item in events:
        objects[f"event:{item.id}"] = _node(
            "event",
            item.id,
            label=item.title,
            direct_or_derived="derived",
            source=_source_info(item.source),
            observed_at=item.observed_at,
            ingested_at=item.received_at,
            transformation={"version": item.normalized_version, "run_kind": "normalization"},
            freshness_seconds=item.source.freshness_seconds if item.source else None,
            evidence={"source_event_id": item.source_event_id, "payload_hash": item.payload_hash, "classification": item.classification},
        )

    raw_infra = list((await session.execute(select(RawInfrastructureRecord).options(joinedload(RawInfrastructureRecord.source)))).scalars().all())
    for item in raw_infra:
        objects[f"raw_infrastructure_record:{item.id}"] = _node(
            "raw_infrastructure_record",
            item.id,
            label=f"Raw infrastructure record {item.source_record_id}",
            direct_or_derived="direct",
            source=_source_info(item.source),
            observed_at=item.source_updated_at,
            ingested_at=item.fetched_at,
            transformation={"version": item.adapter_version, "run_kind": "infrastructure_import"},
            evidence={"source_record_id": item.source_record_id, "payload_hash": item.payload_hash, "processing_state": item.processing_state},
        )

    assets = list((await session.execute(select(InfrastructureAsset).options(joinedload(InfrastructureAsset.source)))).scalars().all())
    infra_sources_by_id = {item.id: item for item in infra_sources}
    sources_by_id = {item.id: item for item in sources}
    for item in assets:
        objects[f"asset:{item.id}"] = _node(
            "asset",
            item.id,
            label=item.name,
            direct_or_derived="derived",
            source=_source_info(item.source),
            observed_at=item.source_updated_at,
            ingested_at=item.imported_at,
            generated_at=item.updated_at,
            transformation={"version": item.normalized_version, "run_kind": "infrastructure_import"},
            evidence={"source_asset_id": item.source_asset_id, "payload_hash": item.payload_hash, "classification": item.classification},
        )

    event_versions = list((await session.execute(select(EventVersion))).scalars().all())
    for item in event_versions:
        snapshot = _json(item.snapshot_json)
        objects[f"event_version:{item.id}"] = _node(
            "event_version",
            item.id,
            label=f"Event version {item.recorded_at.isoformat()}",
            direct_or_derived="derived",
            source=_source_info(sources_by_id.get(item.source_id)),
            generated_at=item.recorded_at,
            transformation={"version": snapshot.get("normalized_version"), "run_kind": "historical_snapshot"},
            evidence={"event_id": item.event_id, "payload_hash": item.payload_hash, "valid_to": item.valid_to, "raw_observation_id": item.raw_observation_id},
        )

    asset_versions = list((await session.execute(select(InfrastructureAssetVersion))).scalars().all())
    for item in asset_versions:
        snapshot = _json(item.snapshot_json)
        objects[f"asset_version:{item.id}"] = _node(
            "asset_version",
            item.id,
            label=f"Asset version {item.recorded_at.isoformat()}",
            direct_or_derived="derived",
            source=_source_info(infra_sources_by_id.get(item.source_id)),
            generated_at=item.recorded_at,
            transformation={"version": snapshot.get("normalized_version"), "run_kind": "historical_snapshot"},
            evidence={"asset_id": item.asset_id, "payload_hash": item.payload_hash, "valid_to": item.valid_to},
        )

    relationships = list((await session.execute(select(InfrastructureRelationship))).scalars().all())
    for item in relationships:
        evidence = _json(item.evidence_json)
        objects[f"relationship:{item.id}"] = _node(
            "relationship",
            item.id,
            label=item.relationship_type.replace("_", " "),
            direct_or_derived="derived" if item.relationship_source == "DERIVED" else "direct",
            generated_at=item.updated_at,
            transformation={"version": item.derivation_version, "run_kind": "relationship_derivation" if item.relationship_source == "DERIVED" else "source_observation"},
            confidence=item.confidence,
            evidence=evidence,
        )

    assessments = list((await session.execute(select(InfrastructureAssessment))).scalars().all())
    for item in assessments:
        objects[f"assessment:{item.id}"] = _node(
            "assessment",
            item.id,
            label=f"{item.assessment_type.replace('_', ' ')} ({item.score:g})",
            direct_or_derived="derived",
            generated_at=item.updated_at,
            transformation={"version": item.methodology_version, "run_kind": "assessment"},
            confidence=item.confidence,
            evidence=_json(item.evidence_json),
        )

    assessment_versions = list((await session.execute(select(InfrastructureAssessmentVersion))).scalars().all())
    assessment_ids = {item.id for item in assessments}
    for item in assessment_versions:
        target_id = item.assessment_id or item.assessment_key
        if target_id not in assessment_ids:
            event = events_by_id.get(item.event_id)
            objects[f"assessment:{target_id}"] = _node(
                "assessment",
                target_id,
                label=f"Assessment history {item.assessment_key[:18]}",
                direct_or_derived="derived",
                source=_source_info(event.source) if event else None,
                generated_at=item.generated_at,
                transformation={"version": item.methodology_version, "run_kind": "historical_snapshot"},
                evidence={"historical_only": True, "is_deleted": item.is_deleted},
            )
        objects[f"assessment_version:{item.id}"] = _node(
            "assessment_version",
            item.id,
            label=f"Assessment version {item.generated_at.isoformat()}",
            direct_or_derived="derived",
            source=_source_info(events_by_id.get(item.event_id).source) if events_by_id.get(item.event_id) else None,
            generated_at=item.generated_at,
            transformation={"version": item.methodology_version, "run_kind": "historical_snapshot"},
            evidence={"assessment_id": item.assessment_id, "assessment_key": item.assessment_key, "is_deleted": item.is_deleted, "valid_to": item.valid_to},
        )

    scenarios = list((await session.execute(select(Scenario))).scalars().all())
    for item in scenarios:
        objects[f"scenario:{item.id}"] = _node(
            "scenario", item.id, label=item.name, direct_or_derived="derived", generated_at=item.created_at,
            transformation={"version": item.methodology_version, "run_kind": "scenario"},
            evidence={"scenario_type": item.scenario_type, "input_hash": item.input_hash},
        )
    runs = list((await session.execute(select(ScenarioRun))).scalars().all())
    for item in runs:
        objects[f"scenario_run:{item.id}"] = _node(
            "scenario_run", item.id, label=f"Scenario run {item.id[:12]}", direct_or_derived="derived",
            generated_at=item.completed_at, transformation={"version": item.methodology_version, "run_kind": "scenario"},
            evidence={"status": item.status, "run_key": item.run_key},
        )
    results = list((await session.execute(select(ScenarioResult))).scalars().all())
    for item in results:
        objects[f"scenario_result:{item.id}"] = _node(
            "scenario_result", item.id, label=f"Scenario result {item.id[:12]}", direct_or_derived="derived",
            generated_at=item.created_at, evidence=_json(item.evidence_json),
        )

    runs_metadata = list((await session.execute(select(TransformationRun))).scalars().all())
    for item in runs_metadata:
        objects[f"transformation_run:{item.id}"] = _node(
            "transformation_run", item.id, label=f"{item.run_kind} {item.version}", direct_or_derived="derived",
            ingested_at=item.completed_at, generated_at=item.completed_at,
            transformation={"version": item.version, "run_kind": item.run_kind, "status": item.status},
            evidence={"source_id": item.source_id, "records_retrieved": item.records_retrieved, "records_accepted": item.records_accepted, "records_rejected": item.records_rejected, "error": item.error, "metadata": _json(item.metadata_json)},
        )
    return objects


def _relationship_evidence_ids(evidence: dict[str, Any]) -> set[str]:
    ids = {str(item) for item in evidence.get("relationship_ids", []) if item is not None}
    relationship = evidence.get("relationship_evidence", [])
    if isinstance(relationship, list):
        ids.update(str(item.get("relationship_id")) for item in relationship if isinstance(item, dict) and item.get("relationship_id"))
    return ids


def _scenario_target_ids(scenario: Scenario) -> Iterable[tuple[str, str]]:
    targets = getattr(scenario, "targets", [])
    for target in targets:
        yield ("asset" if target.target_kind == "NODE" else "relationship", target.target_id)


async def _build_edges(session: AsyncSession) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    sources = list((await session.execute(select(Source))).scalars().all())
    infra_sources = list((await session.execute(select(InfrastructureSource))).scalars().all())
    for source in sources:
        for raw in (await session.execute(select(RawObservation).where(RawObservation.source_id == source.id))).scalars().all():
            edges.append(_edge("source", source.id, "raw_observation", raw.id, "observed_from", ingested_at=raw.fetched_at))
        for event in (await session.execute(select(Event).where(Event.source_id == source.id))).scalars().all():
            edges.append(_edge("source", source.id, "event", event.id, "published", observed_at=event.observed_at, ingested_at=event.received_at))
    for source in infra_sources:
        for raw in (await session.execute(select(RawInfrastructureRecord).where(RawInfrastructureRecord.source_id == source.id))).scalars().all():
            edges.append(_edge("source", source.id, "raw_infrastructure_record", raw.id, "observed_from", ingested_at=raw.fetched_at))
        for asset in (await session.execute(select(InfrastructureAsset).where(InfrastructureAsset.source_id == source.id))).scalars().all():
            edges.append(_edge("source", source.id, "asset", asset.id, "published", observed_at=asset.source_updated_at, ingested_at=asset.imported_at))

    events = list((await session.execute(select(Event))).scalars().all())
    for event in events:
        if event.raw_observation_id:
            edges.append(_edge("raw_observation", event.raw_observation_id, "event", event.id, "normalized_to", evidence={"version": event.normalized_version}, observed_at=event.observed_at, ingested_at=event.received_at))
        for assessment in (await session.execute(select(InfrastructureAssessment).where(InfrastructureAssessment.event_id == event.id))).scalars().all():
            edges.append(_edge("event", event.id, "assessment", assessment.id, "assessed_into", evidence={"methodology_version": assessment.methodology_version}, generated_at=assessment.updated_at))
    assets = list((await session.execute(select(InfrastructureAsset))).scalars().all())
    for asset in assets:
        if asset.raw_infrastructure_record_id:
            edges.append(_edge("raw_infrastructure_record", asset.raw_infrastructure_record_id, "asset", asset.id, "normalized_to", evidence={"version": asset.normalized_version}, observed_at=asset.source_updated_at, ingested_at=asset.imported_at))
    for version in (await session.execute(select(EventVersion))).scalars().all():
        if version.raw_observation_id:
            edges.append(_edge("raw_observation", version.raw_observation_id, "event_version", version.id, "normalized_to", evidence={"payload_hash": version.payload_hash}, generated_at=version.recorded_at))
        edges.append(_edge("event_version", version.id, "event", version.event_id, "historical_version_of", evidence={"payload_hash": version.payload_hash, "valid_to": version.valid_to}, generated_at=version.recorded_at))
    for version in (await session.execute(select(InfrastructureAssetVersion))).scalars().all():
        edges.append(_edge("asset_version", version.id, "asset", version.asset_id, "historical_version_of", evidence={"payload_hash": version.payload_hash, "valid_to": version.valid_to}, generated_at=version.recorded_at))
    relationships = list((await session.execute(select(InfrastructureRelationship))).scalars().all())
    for relationship in relationships:
        evidence = _json(relationship.evidence_json)
        transform = "derived_from_geometry" if relationship.relationship_source == "DERIVED" else "observed_relationship"
        for asset_id in (relationship.from_asset_id, relationship.to_asset_id):
            edges.append(_edge("asset", asset_id, "relationship", relationship.id, transform, evidence={"predicate": relationship.derivation_method, "derivation_version": relationship.derivation_version, **evidence}, generated_at=relationship.updated_at))
    assessments = list((await session.execute(select(InfrastructureAssessment))).scalars().all())
    for assessment in assessments:
        evidence = _json(assessment.evidence_json)
        if assessment.affected_asset_id:
            edges.append(_edge("asset", assessment.affected_asset_id, "assessment", assessment.id, "assessed_into", evidence={"methodology_version": assessment.methodology_version, **evidence}, generated_at=assessment.updated_at))
        for relationship_id in sorted(_relationship_evidence_ids(evidence)):
            edges.append(_edge("relationship", relationship_id, "assessment", assessment.id, "evidence_for", evidence={"methodology_version": assessment.methodology_version}, generated_at=assessment.updated_at))
    for version in (await session.execute(select(InfrastructureAssessmentVersion))).scalars().all():
        target_id = version.assessment_id or version.assessment_key
        edges.append(_edge("assessment_version", version.id, "assessment", target_id, "historical_version_of", evidence={"is_deleted": version.is_deleted, "valid_to": version.valid_to}, generated_at=version.generated_at))
    scenarios = list((await session.execute(select(Scenario).options(selectinload(Scenario.targets)))).scalars().all())
    for scenario in scenarios:
        for target_type, target_id in _scenario_target_ids(scenario):
            edges.append(_edge(target_type, target_id, "scenario", scenario.id, "scenario_target", evidence={"methodology_version": scenario.methodology_version}, generated_at=scenario.created_at))
        for run in (await session.execute(select(ScenarioRun).where(ScenarioRun.scenario_id == scenario.id))).scalars().all():
            edges.append(_edge("scenario", scenario.id, "scenario_run", run.id, "executed_as", evidence={"methodology_version": run.methodology_version}, generated_at=run.completed_at))
    runs = list((await session.execute(select(ScenarioRun))).scalars().all())
    for run in runs:
        result = await session.scalar(select(ScenarioResult).where(ScenarioResult.run_id == run.id))
        if result:
            edges.append(_edge("scenario_run", run.id, "scenario_result", result.id, "generated", evidence=_json(result.evidence_json), generated_at=result.created_at))

    explicit = list((await session.execute(select(LineageRecord).options(joinedload(LineageRecord.transformation_run)))).scalars().all())
    for item in explicit:
        evidence = _json(item.evidence_json)
        edges.append(_edge(item.upstream_type, item.upstream_id, item.downstream_type, item.downstream_id, item.relation_kind, evidence=evidence, transformation_run_id=item.transformation_run_id, observed_at=item.observed_at, ingested_at=item.ingested_at, generated_at=item.generated_at, edge_id=item.id))
    return edges


async def lineage(
    session: AsyncSession,
    *,
    object_type: str,
    object_id: str,
    direction: str = "both",
    limit: int = 50,
    at: datetime | None = None,
) -> dict[str, Any]:
    object_type = {"infrastructure_asset": "asset", "raw_infrastructure": "raw_infrastructure_record", "scenario_run_result": "scenario_result"}.get(object_type, object_type)
    if object_type not in OBJECT_TYPES:
        raise ValueError(f"object_type must be one of: {', '.join(sorted(OBJECT_TYPES))}")
    if direction not in DIRECTIONS:
        raise ValueError("direction must be upstream, downstream, or both")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    objects = await _load_objects(session)
    key = f"{object_type}:{object_id}"
    if key not in objects and object_type == "assessment":
        # Tombstoned assessment versions intentionally have no current row or
        # assessment_id FK.  Their stable assessment key remains queryable.
        historical = list((await session.execute(select(InfrastructureAssessmentVersion).where(InfrastructureAssessmentVersion.assessment_key == object_id).limit(1))).scalars().all())
        if historical:
            objects[key] = _node("assessment", object_id, label=f"Assessment history {object_id[:18]}", direct_or_derived="derived", generated_at=historical[0].generated_at, transformation={"version": historical[0].methodology_version, "run_kind": "historical_snapshot"}, evidence={"historical_only": True})
    if key not in objects:
        # Source IDs can belong to an infrastructure source; all catalogues use
        # the same public ``source`` object type.
        raise LookupError("Provenance object not found")
    all_edges = await _build_edges(session)
    deduplicated = {item["id"]: item for item in all_edges}
    edges = [item for item in deduplicated.values() if _edge_matches(item, object_type, object_id, direction)]
    if at is not None:
        version_types = {"event": "event_version", "asset": "asset_version", "assessment": "assessment_version"}
        version_type = version_types.get(object_type)
        if version_type:
            boundary = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
            edges = [
                item
                for item in edges
                if not any(
                    endpoint["type"] == version_type
                    and item.get("generated_at") is not None
                    and (
                        item["generated_at"].replace(tzinfo=timezone.utc)
                        if item["generated_at"].tzinfo is None
                        else item["generated_at"]
                    )
                    > boundary
                    for endpoint in (item["upstream"], item["downstream"])
                )
            ]
    edges.sort(key=lambda item: (item["relation_kind"], item["upstream"]["id"], item["downstream"]["id"], item["id"]))
    truncated = len(edges) > limit
    selected = edges[:limit]
    node_keys = {key}
    for item in selected:
        node_keys.add(f"{item['upstream']['type']}:{item['upstream']['id']}")
        node_keys.add(f"{item['downstream']['type']}:{item['downstream']['id']}")

    # Historical knowledge-time context is additive and bounded.  It avoids
    # rewriting the current object while showing which source version was
    # known at the requested boundary.
    if at is not None and object_type == "event":
        versions = list((await session.execute(select(EventVersion).where(EventVersion.event_id == object_id, EventVersion.recorded_at <= at).order_by(EventVersion.recorded_at.desc()).limit(10))).scalars().all())
        for version in versions:
            version_key = f"event_version:{version.id}"
            objects[version_key] = _node("event_version", version.id, label=f"Event version {version.recorded_at.isoformat()}", direct_or_derived="derived", generated_at=version.recorded_at, transformation={"version": _json(version.snapshot_json).get("normalized_version"), "run_kind": "historical_snapshot"}, evidence={"payload_hash": version.payload_hash, "valid_to": version.valid_to})
            node_keys.add(version_key)
            if not any(item["id"] == f"event_version:{version.id}|historical_version_of|event:{object_id}" for item in selected):
                selected.append(_edge("event_version", version.id, "event", object_id, "historical_version_of", generated_at=version.recorded_at, evidence={"known_as_of": at.isoformat()}))
            if version.raw_observation_id:
                raw_key = f"raw_observation:{version.raw_observation_id}"
                node_keys.add(raw_key)
                if not any(item["id"] == f"raw_observation:{version.raw_observation_id}|normalized_to|event_version:{version.id}" for item in selected):
                    selected.append(_edge("raw_observation", version.raw_observation_id, "event_version", version.id, "normalized_to", generated_at=version.recorded_at, evidence={"payload_hash": version.payload_hash}))
    if at is not None and object_type == "assessment":
        versions = list((await session.execute(select(InfrastructureAssessmentVersion).where((InfrastructureAssessmentVersion.assessment_id == object_id) | (InfrastructureAssessmentVersion.assessment_key == object_id), InfrastructureAssessmentVersion.generated_at <= at).order_by(InfrastructureAssessmentVersion.generated_at.desc()).limit(10))).scalars().all())
        for version in versions:
            version_key = f"assessment_version:{version.id}"
            objects[version_key] = _node("assessment_version", version.id, label=f"Assessment version {version.generated_at.isoformat()}", direct_or_derived="derived", generated_at=version.generated_at, transformation={"version": version.methodology_version, "run_kind": "historical_snapshot"}, evidence={"is_deleted": version.is_deleted, "valid_to": version.valid_to})
            node_keys.add(version_key)
            if not any(item["id"] == f"assessment_version:{version.id}|historical_version_of|assessment:{object_id}" for item in selected):
                selected.append(_edge("assessment_version", version.id, "assessment", object_id, "historical_version_of", generated_at=version.generated_at, evidence={"known_as_of": at.isoformat()}))
    if at is not None and object_type == "asset":
        versions = list((await session.execute(select(InfrastructureAssetVersion).where(InfrastructureAssetVersion.asset_id == object_id, InfrastructureAssetVersion.recorded_at <= at).order_by(InfrastructureAssetVersion.recorded_at.desc()).limit(10))).scalars().all())
        for version in versions:
            version_key = f"asset_version:{version.id}"
            snapshot = _json(version.snapshot_json)
            objects[version_key] = _node("asset_version", version.id, label=f"Asset version {version.recorded_at.isoformat()}", direct_or_derived="derived", generated_at=version.recorded_at, transformation={"version": snapshot.get("normalized_version"), "run_kind": "historical_snapshot"}, evidence={"payload_hash": version.payload_hash, "valid_to": version.valid_to})
            node_keys.add(version_key)
            if not any(item["id"] == f"asset_version:{version.id}|historical_version_of|asset:{object_id}" for item in selected):
                selected.append(_edge("asset_version", version.id, "asset", object_id, "historical_version_of", generated_at=version.recorded_at, evidence={"known_as_of": at.isoformat()}))
    selected = selected[:limit]
    node_list = [objects[item] for item in sorted(node_keys) if item in objects]
    return {"object_type": object_type, "object_id": str(object_id), "direction": direction, "limit": limit, "truncated": truncated, "nodes": node_list, "edges": selected}
