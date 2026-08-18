"""Second-order, deterministic scenario execution over the persisted graph.

Scenario execution is intentionally an in-memory mutation.  Reference assets
and persisted relationships are never updated or marked unavailable.  The
stored snapshots and hashes make each result explainable and repeatable even
when the source graph changes after the scenario was authored.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.graph import GraphEdge, GraphEngine, GraphNode
from app.graph_repository import _graph_edge
from app.models import (
    InfrastructureAsset,
    InfrastructureRelationship,
    Scenario,
    ScenarioResult,
    ScenarioRun,
    ScenarioTarget,
    ScenarioTargetKind,
    ScenarioType,
)

METHODOLOGY_VERSION = "second-order-v1"
MAX_TARGETS = 50
MAX_PATH_PAIRS = 2_000
MAX_CHANGED_PATHS = 200
MAX_GRAPH_NODES = 200


def _json_value(value: str | dict | list | None, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _node_snapshot(node: GraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "asset_type": node.asset_type,
        "region": node.region,
        "source_key": node.source_key,
    }


def _edge_snapshot(edge: GraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "from_id": edge.from_id,
        "to_id": edge.to_id,
        "relationship_type": edge.relationship_type,
        "directionality": edge.directionality,
        "relationship_source": edge.relationship_source,
        "relationship_key": edge.relationship_key,
    }


def graph_snapshot(engine: GraphEngine) -> dict[str, Any]:
    """Return a compact, sorted representation suitable for hashing/storage."""

    nodes = [_node_snapshot(engine.nodes[node_id]) for node_id in sorted(engine.nodes)]
    edges = [_edge_snapshot(engine.edges[edge_id]) for edge_id in sorted(engine.edges)]
    snapshot = {"nodes": nodes, "edges": edges}
    snapshot["node_count"] = len(nodes)
    snapshot["edge_count"] = len(edges)
    snapshot["hash"] = _hash({"nodes": nodes, "edges": edges})
    return snapshot


def _engine_from_snapshot(snapshot: dict[str, Any]) -> GraphEngine:
    return GraphEngine(
        [
            GraphNode(
                item["id"],
                item.get("name", ""),
                item.get("asset_type", ""),
                item.get("region"),
                item.get("source_key"),
            )
            for item in snapshot.get("nodes", [])
        ],
        [
            GraphEdge(
                item["id"],
                item["from_id"],
                item["to_id"],
                item.get("relationship_type", ""),
                item.get("directionality", "UNDIRECTED"),
                item.get("relationship_source", "DERIVED"),
                item.get("relationship_key", ""),
            )
            for item in snapshot.get("edges", [])
        ],
    )


@dataclass(frozen=True)
class ScenarioExecution:
    baseline: dict[str, Any]
    modified: dict[str, Any]
    metrics: dict[str, Any]
    evidence: dict[str, Any]


def _edge_is_alternate(engine: GraphEngine, edge: GraphEdge) -> bool:
    """Whether endpoints remain connected when this edge alone is ignored."""

    if edge.from_id not in engine.nodes or edge.to_id not in engine.nodes:
        return False
    visited = {edge.from_id}
    queue = [edge.from_id]
    while queue:
        current = queue.pop(0)
        for neighbor_id, candidate in engine._neighbors_for(current):
            if candidate.id == edge.id or neighbor_id in visited:
                continue
            if neighbor_id == edge.to_id:
                return True
            visited.add(neighbor_id)
            queue.append(neighbor_id)
    return False


def _path_metrics(baseline: GraphEngine, modified: GraphEngine) -> dict[str, Any]:
    surviving = sorted(set(baseline.nodes) & set(modified.nodes))
    pairs = list(combinations(surviving, 2))[:MAX_PATH_PAIRS]
    reachable_baseline = 0
    reachable_modified = 0
    preserved_reachable = 0
    path_increases: list[float] = []
    changed: list[dict[str, Any]] = []
    for from_id, to_id in pairs:
        baseline_path = baseline.shortest_path(from_id, to_id, max_hops=max(0, len(surviving) - 1))
        modified_path = modified.shortest_path(from_id, to_id, max_hops=max(0, len(surviving) - 1))
        baseline_hops = len(baseline_path) - 1 if baseline_path else None
        modified_hops = len(modified_path) - 1 if modified_path else None
        if baseline_path:
            reachable_baseline += 1
        if modified_path:
            reachable_modified += 1
        if baseline_path and modified_path:
            preserved_reachable += 1
            if modified_hops is not None and baseline_hops is not None and modified_hops > baseline_hops:
                path_increases.append(modified_hops - baseline_hops)
        if baseline_hops != modified_hops:
            changed.append(
                {
                    "from_node_id": from_id,
                    "to_node_id": to_id,
                    "baseline_hops": baseline_hops,
                    "scenario_hops": modified_hops,
                    "delta_hops": (modified_hops - baseline_hops) if baseline_hops is not None and modified_hops is not None else None,
                    "baseline_path": baseline_path,
                    "scenario_path": modified_path,
                    "change": "UNREACHABLE" if baseline_path and not modified_path else "PATH_LENGTH_CHANGED",
                }
            )
    return {
        "pair_limit": MAX_PATH_PAIRS,
        "pairs_evaluated": len(pairs),
        "baseline_reachable_pairs": reachable_baseline,
        "scenario_reachable_pairs": reachable_modified,
        "preserved_reachable_pairs": preserved_reachable,
        "changed_paths": changed[:MAX_CHANGED_PATHS],
        "changed_path_count": len(changed),
        "average_positive_path_increase": round(sum(path_increases) / len(path_increases), 6) if path_increases else 0.0,
    }


def _alternate_metrics(baseline: GraphEngine, modified: GraphEngine) -> dict[str, Any]:
    baseline_candidates = [edge for edge in baseline.edges.values() if _edge_is_alternate(baseline, edge)]
    preserved = [edge.id for edge in baseline_candidates if edge.id in modified.edges and _edge_is_alternate(modified, modified.edges[edge.id])]
    return {
        "baseline_alternate_route_edges": len(baseline_candidates),
        "scenario_alternate_route_edges": len(preserved),
        "preserved_alternate_route_edges": len(preserved),
        "lost_alternate_route_edge_ids": sorted(edge.id for edge in baseline_candidates if edge.id not in preserved),
    }


def execute_graph_scenario(
    baseline: GraphEngine,
    *,
    scenario_type: str,
    target_node_ids: list[str],
    target_edge_ids: list[str],
    assumption: str,
) -> ScenarioExecution:
    """Run the scenario entirely against copied in-memory graph structures."""

    baseline_snapshot = graph_snapshot(baseline)
    target_nodes = sorted(set(target_node_ids))
    target_edges = sorted(set(target_edge_ids))
    if scenario_type == ScenarioType.EDGE_UNAVAILABLE.value:
        removed_nodes: set[str] = set()
        explicit_removed_edges = set(target_edges)
    else:
        removed_nodes = set(target_nodes)
        explicit_removed_edges = set(target_edges)
    removed_edges = {
        edge.id
        for edge in baseline.edges.values()
        if edge.id in explicit_removed_edges or edge.from_id in removed_nodes or edge.to_id in removed_nodes
    }
    modified = GraphEngine(
        [node for node in baseline.nodes.values() if node.id not in removed_nodes],
        [edge for edge in baseline.edges.values() if edge.id not in removed_edges],
    )
    modified_snapshot = graph_snapshot(modified)
    baseline_components = baseline.connected_components()
    scenario_components = modified.connected_components()
    baseline_largest = max((len(item) for item in baseline_components), default=0)
    scenario_largest = max((len(item) for item in scenario_components), default=0)
    paths = _path_metrics(baseline, modified)
    alternates = _alternate_metrics(baseline, modified)
    base_reachable = paths["baseline_reachable_pairs"]
    scenario_reachable = paths["scenario_reachable_pairs"]
    reachability_ratio = scenario_reachable / base_reachable if base_reachable else 1.0
    largest_ratio = scenario_largest / baseline_largest if baseline_largest else 1.0
    alternate_base = alternates["baseline_alternate_route_edges"]
    alternate_ratio = alternates["scenario_alternate_route_edges"] / alternate_base if alternate_base else 1.0
    baseline_hops = [
        item["baseline_hops"]
        for item in paths["changed_paths"]
        if item["baseline_hops"] is not None and item["scenario_hops"] is not None
    ]
    path_inflation = min(
        1.0,
        paths["average_positive_path_increase"] / max(1.0, sum(baseline_hops) / len(baseline_hops))
        if baseline_hops
        else 0.0,
    )
    resilience_score = round(
        max(0.0, min(100.0, 100.0 * (0.45 * reachability_ratio + 0.35 * largest_ratio + 0.20 * alternate_ratio - 0.10 * path_inflation))),
        4,
    )
    baseline_ids = set(baseline.nodes)
    disconnected = sorted(
        node_id
        for node_id in modified.nodes
        if baseline.shortest_path(node_id, node_id) and any(
            baseline.shortest_path(node_id, other, max_hops=max(0, len(baseline.nodes) - 1))
            and modified.shortest_path(node_id, other, max_hops=max(0, len(modified.nodes) - 1)) is None
            for other in baseline_ids - {node_id}
        )
    )
    baseline_articulation = sorted(baseline.articulation_points())
    scenario_articulation = sorted(modified.articulation_points())
    metrics = {
        "baseline": {
            "node_count": baseline_snapshot["node_count"],
            "edge_count": baseline_snapshot["edge_count"],
            "component_count": len(baseline_components),
            "largest_component_size": baseline_largest,
            "articulation_point_ids": baseline_articulation,
        },
        "scenario": {
            "node_count": modified_snapshot["node_count"],
            "edge_count": modified_snapshot["edge_count"],
            "component_count": len(scenario_components),
            "largest_component_size": scenario_largest,
            "articulation_point_ids": scenario_articulation,
        },
        "removed_node_ids": target_nodes,
        "removed_edge_ids": sorted(removed_edges),
        "disconnected_node_ids": disconnected,
        "newly_articulation_point_ids": sorted(set(scenario_articulation) - set(baseline_articulation)),
        "no_longer_articulation_point_ids": sorted(set(baseline_articulation) - set(scenario_articulation)),
        "path_analysis": paths,
        "alternate_routes": alternates,
        "resilience": {
            "score": resilience_score,
            "delta_from_intact": round(resilience_score - 100.0, 4),
            "components": {
                "surviving_reachability_ratio": round(reachability_ratio, 6),
                "largest_component_ratio": round(largest_ratio, 6),
                "alternate_route_preservation_ratio": round(alternate_ratio, 6),
                "path_inflation_penalty": round(path_inflation, 6),
            },
            "weights": {
                "surviving_reachability_ratio": 0.45,
                "largest_component_ratio": 0.35,
                "alternate_route_preservation_ratio": 0.20,
                "path_inflation_penalty": -0.10,
            },
        },
    }
    evidence = {
        "what_changed": "Selected graph nodes and/or edges were removed in memory for structural comparison.",
        "why": "The scenario assumption marks selected targets unavailable for this modeled graph only.",
        "assumption": assumption,
        "target_node_ids": target_nodes,
        "target_edge_ids": target_edges,
        "algorithm": "Sorted adjacency, connected components, bounded BFS shortest paths, Tarjan articulation points, and direct-edge alternate-route checks.",
        "methodology_version": METHODOLOGY_VERSION,
        "graph_semantics": "Undirected persisted infrastructure relationships; no upstream/downstream semantics.",
        "baseline_graph_hash": baseline_snapshot["hash"],
        "modified_graph_hash": modified_snapshot["hash"],
        "baseline_counts": {"nodes": baseline_snapshot["node_count"], "edges": baseline_snapshot["edge_count"]},
        "modified_counts": {"nodes": modified_snapshot["node_count"], "edges": modified_snapshot["edge_count"]},
        "limits": {"max_path_pairs": MAX_PATH_PAIRS, "max_changed_paths": MAX_CHANGED_PATHS},
        "non_claims": ["No outage, service, economic, logistical, or real-world causal claim is made."],
    }
    return ScenarioExecution(baseline_snapshot, modified_snapshot, metrics, evidence)


async def _load_baseline(session: AsyncSession) -> tuple[list[InfrastructureAsset], GraphEngine]:
    assets = list(
        (
            await session.execute(
                select(InfrastructureAsset)
                .options(joinedload(InfrastructureAsset.source))
                .order_by(InfrastructureAsset.id)
            )
        )
        .unique()
        .scalars()
    )
    asset_ids = {asset.id for asset in assets}
    relationships = [
        relationship
        for relationship in (
            await session.execute(
                select(InfrastructureRelationship).order_by(
                    InfrastructureRelationship.relationship_type,
                    InfrastructureRelationship.from_asset_id,
                    InfrastructureRelationship.to_asset_id,
                    InfrastructureRelationship.id,
                )
            )
        ).scalars()
        if relationship.from_asset_id in asset_ids and relationship.to_asset_id in asset_ids
    ]
    return assets, GraphEngine(
        [
            GraphNode(asset.id, asset.name, asset.asset_type, asset.region, asset.source.key if asset.source else None)
            for asset in assets
        ],
        [_graph_edge(relationship) for relationship in relationships],
    )


def _target_payload(target: ScenarioTarget) -> dict[str, Any]:
    return {
        "id": target.id,
        "target_kind": target.target_kind,
        "target_id": target.target_id,
        "position": target.position,
        "snapshot": _json_value(target.target_snapshot_json, {}),
    }


def scenario_payload(scenario: Scenario, *, include_baseline: bool = True) -> dict[str, Any]:
    baseline = _json_value(scenario.baseline_snapshot_json, {})
    return {
        "id": scenario.id,
        "name": scenario.name,
        "scenario_type": scenario.scenario_type,
        "created_by": scenario.created_by,
        "assumption": scenario.assumption,
        "duration_seconds": scenario.duration_seconds,
        "methodology_version": scenario.methodology_version,
        "input_hash": scenario.input_hash,
        "baseline_graph_hash": scenario.baseline_graph_hash,
        "baseline_node_count": scenario.baseline_node_count,
        "baseline_edge_count": scenario.baseline_edge_count,
        "baseline": baseline if include_baseline else {"hash": scenario.baseline_graph_hash, "node_count": scenario.baseline_node_count, "edge_count": scenario.baseline_edge_count},
        "assumptions": _json_value(scenario.assumptions_json, {}),
        "targets": [_target_payload(target) for target in scenario.targets],
        "created_at": scenario.created_at,
        "updated_at": scenario.updated_at,
    }


def run_payload(run: ScenarioRun, *, include_result: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": run.id,
        "scenario_id": run.scenario_id,
        "run_key": run.run_key,
        "status": run.status,
        "methodology_version": run.methodology_version,
        "baseline_graph_hash": run.baseline_graph_hash,
        "modified_graph_hash": run.modified_graph_hash,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
        "reproducibility": _json_value(run.reproducibility_json, {}),
    }
    if include_result and run.result:
        payload["result"] = result_payload(run.result)
    return payload


def result_payload(result: ScenarioResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "run_id": result.run_id,
        "baseline": _json_value(result.baseline_snapshot_json, {}),
        "modified": _json_value(result.modified_snapshot_json, {}),
        "metrics": _json_value(result.metrics_json, {}),
        "evidence": _json_value(result.evidence_json, {}),
        "created_at": result.created_at,
    }


async def create_scenario(
    session: AsyncSession,
    *,
    name: str,
    scenario_type: str,
    target_node_ids: list[str],
    target_edge_ids: list[str],
    assumption: str,
    duration_seconds: int | None,
    created_by: str,
) -> Scenario:
    try:
        scenario_kind = ScenarioType(scenario_type)
    except ValueError as exc:
        raise ValueError(f"Unsupported scenario_type: {scenario_type}") from exc
    nodes = list(dict.fromkeys(target_node_ids))
    edges = list(dict.fromkeys(target_edge_ids))
    if len(nodes) != len(target_node_ids) or len(edges) != len(target_edge_ids):
        raise ValueError("Target selections must not contain duplicates")
    if len(nodes) + len(edges) < 1:
        raise ValueError("At least one target is required")
    if len(nodes) + len(edges) > MAX_TARGETS:
        raise ValueError(f"At most {MAX_TARGETS} targets may be selected")
    if scenario_kind == ScenarioType.EDGE_UNAVAILABLE and (len(edges) != 1 or nodes):
        raise ValueError("EDGE_UNAVAILABLE requires exactly one edge target")
    if scenario_kind == ScenarioType.ASSET_UNAVAILABLE and (len(nodes) != 1 or edges):
        raise ValueError("ASSET_UNAVAILABLE requires exactly one asset target")
    if scenario_kind == ScenarioType.MULTIPLE_ASSETS_UNAVAILABLE and (len(nodes) < 2 or edges):
        raise ValueError("MULTIPLE_ASSETS_UNAVAILABLE requires at least two asset targets")
    _assets, engine = await _load_baseline(session)
    missing_nodes = sorted(set(nodes) - set(engine.nodes))
    missing_edges = sorted(set(edges) - set(engine.edges))
    if missing_nodes:
        raise LookupError(f"Graph node target not found: {', '.join(missing_nodes)}")
    if missing_edges:
        raise LookupError(f"Graph edge target not found: {', '.join(missing_edges)}")
    baseline = graph_snapshot(engine)
    targets = [{"kind": ScenarioTargetKind.NODE.value, "id": target} for target in nodes]
    targets.extend({"kind": ScenarioTargetKind.EDGE.value, "id": target} for target in edges)
    input_hash = _hash(
        {
            "scenario_type": scenario_kind.value,
            "targets": targets,
            "assumption": assumption,
            "duration_seconds": duration_seconds,
            "methodology_version": METHODOLOGY_VERSION,
            "baseline_graph_hash": baseline["hash"],
        }
    )
    now = datetime.now(timezone.utc)
    scenario = Scenario(
        id=str(uuid.uuid4()),
        name=name,
        scenario_type=scenario_kind.value,
        created_by=created_by,
        assumption=assumption,
        duration_seconds=duration_seconds,
        methodology_version=METHODOLOGY_VERSION,
        input_hash=input_hash,
        baseline_graph_hash=baseline["hash"],
        baseline_node_count=baseline["node_count"],
        baseline_edge_count=baseline["edge_count"],
        baseline_snapshot_json=baseline,
        assumptions_json={"selected_targets_are_removed_in_memory": True, "duration_seconds": duration_seconds},
        created_at=now,
        updated_at=now,
    )
    session.add(scenario)
    for position, target in enumerate(targets):
        target_id = target["id"]
        target_snapshot = baseline["nodes"] if target["kind"] == ScenarioTargetKind.NODE.value else baseline["edges"]
        selected = next(item for item in target_snapshot if item["id"] == target_id)
        session.add(
            ScenarioTarget(
                id=str(uuid.uuid4()),
                scenario_id=scenario.id,
                target_kind=target["kind"],
                target_id=target_id,
                position=position,
                target_snapshot_json=selected,
            )
        )
    await session.flush()
    await session.refresh(scenario, ["targets"])
    return scenario


async def execute_scenario(session: AsyncSession, scenario_id: str) -> ScenarioRun:
    scenario = await session.scalar(
        select(Scenario).options(selectinload(Scenario.targets)).where(Scenario.id == scenario_id)
    )
    if scenario is None:
        raise LookupError("Scenario not found")
    run_key = _hash(
        {
            "scenario_id": scenario.id,
            "input_hash": scenario.input_hash,
            "baseline_graph_hash": scenario.baseline_graph_hash,
            "methodology_version": scenario.methodology_version,
        }
    )
    existing = await session.scalar(
        select(ScenarioRun).options(selectinload(ScenarioRun.result)).where(ScenarioRun.run_key == run_key)
    )
    if existing is not None:
        return existing
    baseline_snapshot = _json_value(scenario.baseline_snapshot_json, {})
    baseline = _engine_from_snapshot(baseline_snapshot)
    nodes = [target.target_id for target in scenario.targets if target.target_kind == ScenarioTargetKind.NODE.value]
    edges = [target.target_id for target in scenario.targets if target.target_kind == ScenarioTargetKind.EDGE.value]
    execution = execute_graph_scenario(
        baseline,
        scenario_type=scenario.scenario_type,
        target_node_ids=nodes,
        target_edge_ids=edges,
        assumption=scenario.assumption,
    )
    now = datetime.now(timezone.utc)
    run = ScenarioRun(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"signalwake:scenario-run:{run_key}")),
        scenario_id=scenario.id,
        run_key=run_key,
        status="completed",
        methodology_version=METHODOLOGY_VERSION,
        baseline_graph_hash=execution.baseline["hash"],
        modified_graph_hash=execution.modified["hash"],
        started_at=now,
        completed_at=now,
        created_at=now,
        reproducibility_json={
            "input_hash": scenario.input_hash,
            "baseline_graph_hash": execution.baseline["hash"],
            "modified_graph_hash": execution.modified["hash"],
            "methodology_version": METHODOLOGY_VERSION,
            "deterministic": True,
        },
    )
    run.result = ScenarioResult(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"signalwake:scenario-result:{run_key}")),
        run_id=run.id,
        baseline_snapshot_json=execution.baseline,
        modified_snapshot_json=execution.modified,
        metrics_json=execution.metrics,
        evidence_json=execution.evidence,
        created_at=now,
    )
    session.add(run)
    await session.flush()
    await session.refresh(run, ["result"])
    return run


async def get_scenario(session: AsyncSession, scenario_id: str) -> Scenario | None:
    return await session.scalar(
        select(Scenario).options(selectinload(Scenario.targets)).where(Scenario.id == scenario_id)
    )


async def get_run(session: AsyncSession, run_id: str) -> ScenarioRun | None:
    return await session.scalar(
        select(ScenarioRun).options(selectinload(ScenarioRun.result)).where(ScenarioRun.id == run_id)
    )
