"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { GraphEdge, GraphEdgeList, GraphNode, GraphNodeList, Scenario, ScenarioList, ScenarioRun } from "../lib/types";

const scenarioTypes = [
  { value: "ASSET_UNAVAILABLE", label: "One asset unavailable", hint: "Remove one graph node in memory." },
  { value: "EDGE_UNAVAILABLE", label: "One relationship unavailable", hint: "Remove one persisted relationship in memory." },
  { value: "MULTIPLE_ASSETS_UNAVAILABLE", label: "Multiple assets unavailable", hint: "Remove two or more graph nodes in memory." },
] as const;

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
}

function formatHash(hash: string) {
  return hash ? `${hash.slice(0, 12)}…` : "—";
}

type SnapshotNode = {
  id: string;
  name: string;
  asset_type: string;
  region: string | null;
  source_key: string | null;
};

type SnapshotEdge = {
  id: string;
  from_id: string;
  to_id: string;
  relationship_type: string;
};

type Snapshot = {
  nodes: SnapshotNode[];
  edges: SnapshotEdge[];
  hash: string;
  node_count: number;
  edge_count: number;
};

const SNAPSHOT_NODE_LIMIT = 24;
const SNAPSHOT_EDGE_LIMIT = 48;

function SnapshotGraph({
  state,
  snapshot,
  removedNodeIds,
  removedEdgeIds,
  affectedNodeIds,
}: {
  state: "baseline" | "modified";
  snapshot: Snapshot;
  removedNodeIds: string[];
  removedEdgeIds: string[];
  affectedNodeIds: string[];
}) {
  const visibleNodes = snapshot.nodes.slice(0, SNAPSHOT_NODE_LIMIT);
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const candidateEdges = snapshot.edges.filter((edge) => visibleIds.has(edge.from_id) && visibleIds.has(edge.to_id));
  const visibleEdges = candidateEdges.slice(0, SNAPSHOT_EDGE_LIMIT);
  const omittedNodes = Math.max(0, snapshot.nodes.length - visibleNodes.length);
  const omittedEdges = Math.max(0, snapshot.edges.length - visibleEdges.length);
  const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(Math.max(1, visibleNodes.length)))));
  const rows = Math.max(1, Math.ceil(visibleNodes.length / columns));
  const width = 520;
  const height = Math.max(230, rows * 52 + 54);
  const positions = new Map<string, { x: number; y: number }>();
  visibleNodes.forEach((node, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    positions.set(node.id, { x: 68 + column * ((width - 136) / Math.max(1, columns - 1)), y: 28 + row * 52 });
  });
  const removedNodes = new Set(removedNodeIds);
  const removedEdges = new Set(removedEdgeIds);
  const affectedNodes = new Set(affectedNodeIds);
  const nodeStatus = (id: string) => state === "baseline" && removedNodes.has(id) ? "removed" : affectedNodes.has(id) ? "affected" : "baseline";
  const edgeStatus = (id: string) => state === "baseline" && removedEdges.has(id) ? "removed" : "baseline";

  return <div className={`scenario-snapshot scenario-snapshot-${state}`}>
    <div className="scenario-snapshot-heading"><div><span>{state === "baseline" ? "BASELINE" : "MODIFIED"}</span><strong>{state === "baseline" ? "Persisted graph snapshot" : "In-memory simulated graph"}</strong></div><code>{formatHash(snapshot.hash)}</code></div>
    <div className="scenario-snapshot-canvas"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`snapshot-${state}-title snapshot-${state}-desc`}>
      <title id={`snapshot-${state}-title`}>{state === "baseline" ? "Baseline persisted graph" : "Modified scenario graph"}</title>
      <desc id={`snapshot-${state}-desc`}>{snapshot.node_count} nodes and {snapshot.edge_count} edges in the {state} snapshot. Removed targets are red and affected surviving nodes are amber.</desc>
      {visibleEdges.map((edge) => {
        const from = positions.get(edge.from_id);
        const to = positions.get(edge.to_id);
        if (!from || !to) return null;
        return <line key={edge.id} className={`scenario-snapshot-edge scenario-snapshot-edge-${edgeStatus(edge.id)}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} aria-label={`${edge.relationship_type} ${edge.id}`} />;
      })}
      {visibleNodes.map((node) => {
        const point = positions.get(node.id);
        if (!point) return null;
        const status = nodeStatus(node.id);
        return <g key={node.id} className={`scenario-snapshot-node scenario-snapshot-node-${status}`}><circle cx={point.x} cy={point.y} r="12" /><text x={point.x} y={point.y + 27}>{node.name.length > 16 ? `${node.name.slice(0, 15)}…` : node.name}</text><title>{`${node.name} · ${status.toUpperCase()} · ${node.id}`}</title></g>;
      })}
    </svg></div>
    <div className="scenario-snapshot-list" aria-label={`${state} visible graph nodes`}>
      {visibleNodes.map((node) => <span key={node.id} className={`scenario-snapshot-chip scenario-snapshot-chip-${nodeStatus(node.id)}`} title={node.id}>{node.name}</span>)}
    </div>
    <p className="scenario-snapshot-note">Showing {visibleNodes.length} of {snapshot.node_count} nodes and {visibleEdges.length} of {snapshot.edge_count} edges.{omittedNodes || omittedEdges ? ` Bounded view omits ${omittedNodes} nodes and ${omittedEdges} edges.` : ""}</p>
  </div>;
}

export function ScenarioLab() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioType, setScenarioType] = useState<(typeof scenarioTypes)[number]["value"]>("ASSET_UNAVAILABLE");
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);
  const [selectedEdge, setSelectedEdge] = useState<string>("");
  const [name, setName] = useState("Graph removal check");
  const [assumption, setAssumption] = useState("Selected targets are unavailable in the modeled infrastructure graph.");
  const [duration, setDuration] = useState("");
  const [activeScenario, setActiveScenario] = useState<Scenario | null>(null);
  const [run, setRun] = useState<ScenarioRun | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [actionState, setActionState] = useState<"idle" | "creating" | "running">("idle");
  const [error, setError] = useState<string | null>(null);

  const selectedNodeSet = useMemo(() => new Set(selectedNodes), [selectedNodes]);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const [nodesResponse, edgesResponse, scenariosResponse] = await Promise.all([
        fetch(`${apiBase()}/graph/nodes?limit=200`, { cache: "no-store" }),
        fetch(`${apiBase()}/graph/edges?limit=200`, { cache: "no-store" }),
        fetch(`${apiBase()}/scenarios?limit=50`, { cache: "no-store" }),
      ]);
      if (!nodesResponse.ok || !edgesResponse.ok || !scenariosResponse.ok) throw new Error("Scenario API is unavailable");
      const nodeBody = (await nodesResponse.json()) as GraphNodeList;
      const edgeBody = (await edgesResponse.json()) as GraphEdgeList;
      const scenarioBody = (await scenariosResponse.json()) as ScenarioList;
      setNodes(nodeBody.items);
      setEdges(edgeBody.items);
      setScenarios(scenarioBody.items);
      setState(nodeBody.items.length ? "ready" : "empty");
    } catch (cause) {
      setState("error");
      setError(cause instanceof Error ? cause.message : "Unable to reach the Scenario API");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    setSelectedNodes([]);
    setSelectedEdge("");
    setRun(null);
  }, [scenarioType]);

  function toggleNode(id: string) {
    setSelectedNodes((current) => {
      if (scenarioType === "ASSET_UNAVAILABLE") return current.includes(id) ? [] : [id];
      if (current.includes(id)) return current.filter((item) => item !== id);
      return current.length >= 50 ? current : [...current, id];
    });
  }

  async function createScenario() {
    setActionState("creating");
    setError(null);
    try {
      const response = await fetch(`${apiBase()}/scenarios`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name,
          scenario_type: scenarioType,
          target_node_ids: scenarioType === "EDGE_UNAVAILABLE" ? [] : selectedNodes,
          target_edge_ids: scenarioType === "EDGE_UNAVAILABLE" ? (selectedEdge ? [selectedEdge] : []) : [],
          assumption,
          duration_seconds: duration ? Number(duration) : null,
        }),
      });
      const body = (await response.json()) as { detail?: string } & Partial<Scenario>;
      if (!response.ok) throw new Error(body.detail || `Scenario creation failed (${response.status})`);
      const created = body as Scenario;
      setActiveScenario(created);
      setRun(null);
      setScenarios((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Scenario creation failed");
    } finally {
      setActionState("idle");
    }
  }

  async function runScenario() {
    if (!activeScenario) return;
    setActionState("running");
    setError(null);
    try {
      const response = await fetch(`${apiBase()}/scenarios/${activeScenario.id}/runs`, { method: "POST" });
      const body = (await response.json()) as { detail?: string } & Partial<ScenarioRun>;
      if (!response.ok) throw new Error(body.detail || `Scenario run failed (${response.status})`);
      setRun(body as ScenarioRun);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Scenario run failed");
    } finally {
      setActionState("idle");
    }
  }

  const metrics = run?.result?.metrics;
  const baselineSnapshot = run?.result?.baseline as Snapshot | undefined;
  const modifiedSnapshot = run?.result?.modified as Snapshot | undefined;
  const selectedTargetCount = scenarioType === "EDGE_UNAVAILABLE" ? (selectedEdge ? 1 : 0) : selectedNodes.length;
  const canCreate = scenarioType === "MULTIPLE_ASSETS_UNAVAILABLE" ? selectedTargetCount >= 2 : selectedTargetCount === 1;

  return <div className="scenario-page">
    <div className="scenario-intro">
      <div><div className="section-eyebrow">SECOND-ORDER / SCENARIO ENGINE</div><h1>Scenario Lab</h1><p>Remove selected nodes or relationships from the modeled graph and inspect structural changes. This is a deterministic graph comparison, not an outage or impact forecast.</p></div>
      <div className="scenario-bound"><span>METHOD</span><strong>second-order-v1</strong><span>GRAPH</span><strong>UNDIRECTED / SOURCE-BACKED</strong></div>
    </div>

    {state === "loading" && <div className="scenario-state"><span className="state-pulse" /> LOADING PERSISTED GRAPH AND SCENARIOS</div>}
    {state === "error" && <div className="scenario-state scenario-state-error"><strong>SCENARIO API UNAVAILABLE</strong><span>{error}</span><button type="button" onClick={() => void load()}>RETRY</button></div>}
    {state === "empty" && <div className="scenario-state scenario-state-empty"><strong>NO GRAPH NODES AVAILABLE</strong><span>Import reference infrastructure and run the explicit graph rebuild before creating a scenario. No sample result is substituted here.</span></div>}

    {state === "ready" && <>
      <section className="scenario-builder" aria-labelledby="scenario-builder-heading">
        <div className="scenario-panel-heading"><div><span>01 / DEFINE</span><h2 id="scenario-builder-heading">Choose what becomes unavailable</h2></div><small>{nodes.length} nodes · {edges.length} relationships loaded</small></div>
        <div className="scenario-type-row">{scenarioTypes.map((item) => <button key={item.value} type="button" className={`scenario-type ${scenarioType === item.value ? "scenario-type-selected" : ""}`} onClick={() => setScenarioType(item.value)} aria-pressed={scenarioType === item.value}><strong>{item.label}</strong><span>{item.hint}</span></button>)}</div>
        <div className="scenario-form-grid">
          <label><span>SCENARIO NAME</span><input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} /></label>
          <label><span>DURATION (OPTIONAL)</span><input type="number" min="0" max="31536000" value={duration} onChange={(event) => setDuration(event.target.value)} placeholder="not used in topology" /></label>
          <label className="scenario-form-wide"><span>ASSUMPTION</span><textarea value={assumption} onChange={(event) => setAssumption(event.target.value)} maxLength={1000} /></label>
        </div>
        {scenarioType === "EDGE_UNAVAILABLE" ? <div className="scenario-target-list"><div className="scenario-list-label">RELATIONSHIPS / SELECT ONE</div>{edges.length ? edges.map((edge) => <button type="button" key={edge.id} className={`scenario-target-row ${selectedEdge === edge.id ? "scenario-target-selected" : ""}`} onClick={() => setSelectedEdge((current) => current === edge.id ? "" : edge.id)} aria-pressed={selectedEdge === edge.id}><span className="scenario-target-mark scenario-edge-mark" /><span><strong>{edge.relationship_type.replaceAll("_", " ")}</strong><small>{edge.from_node_id.slice(0, 8)}… ↔ {edge.to_node_id.slice(0, 8)}… · {edge.relationship_source}</small></span><code>{edge.id.slice(0, 10)}…</code></button>) : <p className="scenario-empty-note">No persisted relationships are available in this graph.</p>}</div> : <div className="scenario-target-list"><div className="scenario-list-label">ASSETS / {scenarioType === "MULTIPLE_ASSETS_UNAVAILABLE" ? "SELECT TWO OR MORE" : "SELECT ONE"}</div>{nodes.map((node) => <button type="button" key={node.id} className={`scenario-target-row ${selectedNodeSet.has(node.id) ? "scenario-target-selected" : ""}`} onClick={() => toggleNode(node.id)} aria-pressed={selectedNodeSet.has(node.id)}><span className={`scenario-target-mark scenario-${node.type}`} /><span><strong>{node.name}</strong><small>{node.type.replaceAll("_", " ")} · {node.region || "region not provided"}</small></span><code>{node.id.slice(0, 10)}…</code></button>)}</div>}
        <div className="scenario-builder-footer"><span>{selectedTargetCount} target{selectedTargetCount === 1 ? "" : "s"} selected · only in-memory graph removal</span><button type="button" className="scenario-primary-button" disabled={!canCreate || actionState !== "idle" || !name.trim()} onClick={() => void createScenario()}>{actionState === "creating" ? "CREATING…" : "CREATE SCENARIO"}</button></div>
      </section>

      <section className="scenario-lower-grid">
        <div className="scenario-panel scenario-history"><div className="scenario-panel-heading"><div><span>02 / SAVED INPUTS</span><h2>Scenario definitions</h2></div></div>{scenarios.length ? scenarios.map((item) => <button type="button" key={item.id} className={`scenario-history-row ${activeScenario?.id === item.id ? "scenario-history-selected" : ""}`} onClick={() => { setActiveScenario(item); setRun(null); }}><span><strong>{item.name}</strong><small>{item.scenario_type.replaceAll("_", " ")} · {item.targets.length} target{item.targets.length === 1 ? "" : "s"}</small></span><code>{formatHash(item.baseline_graph_hash)}</code></button>) : <p className="scenario-empty-note">No scenarios created yet.</p>}</div>
        <div className="scenario-panel scenario-run-panel"><div className="scenario-panel-heading"><div><span>03 / EXECUTE</span><h2>{activeScenario ? activeScenario.name : "Run a saved definition"}</h2></div>{activeScenario && <button type="button" className="scenario-secondary-button" disabled={actionState !== "idle"} onClick={() => void runScenario()}>{actionState === "running" ? "RUNNING…" : run ? "RE-RUN (IDEMPOTENT)" : "RUN SCENARIO"}</button>}</div>{activeScenario ? <div className="scenario-run-context"><p>{activeScenario.assumption}</p><div><span>BASELINE HASH</span><code>{formatHash(activeScenario.baseline_graph_hash)}</code></div><div><span>TARGETS</span><code>{activeScenario.targets.map((target) => target.target_id.slice(0, 8)).join(" · ")}</code></div></div> : <p className="scenario-empty-note">Create a definition above, then run it explicitly to persist a result.</p>}{error && actionState === "idle" && <p className="scenario-inline-error">{error}</p>}</div>
      </section>

      {run?.result && metrics && <section className="scenario-result" aria-labelledby="scenario-result-heading"><div className="scenario-panel-heading"><div><span>04 / RESULT</span><h2 id="scenario-result-heading">Baseline → modified graph</h2></div><span className="scenario-derived-label">DERIVED SECOND ORDER · {run.methodology_version}</span></div><div className="scenario-state-legend"><span className="scenario-state-tag scenario-baseline-tag">BASELINE <small>persisted snapshot</small></span><span className="scenario-state-tag scenario-removed-tag">REMOVED <small>selected targets</small></span><span className="scenario-state-tag scenario-affected-tag">AFFECTED <small>reachability changed</small></span><Link href="/infrastructure">OPEN INFRASTRUCTURE GRAPH ↗</Link></div><div className="scenario-metric-grid"><div><span>COMPONENTS</span><strong>{metrics.baseline.component_count} → {metrics.scenario.component_count}</strong></div><div><span>LARGEST COMPONENT</span><strong>{metrics.baseline.largest_component_size} → {metrics.scenario.largest_component_size}</strong></div><div><span>REACHABLE PAIRS</span><strong>{metrics.path_analysis.baseline_reachable_pairs} → {metrics.path_analysis.scenario_reachable_pairs}</strong></div><div><span>RESILIENCE (STRUCTURAL)</span><strong>{metrics.resilience.score.toFixed(1)} <em>{metrics.resilience.delta_from_intact.toFixed(1)}</em></strong></div></div>{baselineSnapshot && modifiedSnapshot && <div className="scenario-snapshot-grid"><SnapshotGraph state="baseline" snapshot={baselineSnapshot} removedNodeIds={metrics.removed_node_ids} removedEdgeIds={metrics.removed_edge_ids} affectedNodeIds={metrics.disconnected_node_ids} /><SnapshotGraph state="modified" snapshot={modifiedSnapshot} removedNodeIds={metrics.removed_node_ids} removedEdgeIds={metrics.removed_edge_ids} affectedNodeIds={metrics.disconnected_node_ids} /></div>}<div className="scenario-result-columns"><div><h3>What changed</h3><p>{run.result.evidence.what_changed as string}</p><dl><dt>REMOVED NODES</dt><dd>{metrics.removed_node_ids.length ? metrics.removed_node_ids.join(", ") : "none"}</dd><dt>REMOVED EDGES</dt><dd>{metrics.removed_edge_ids.length ? metrics.removed_edge_ids.join(", ") : "none"}</dd><dt>AFFECTED / DISCONNECTED</dt><dd>{metrics.disconnected_node_ids.length ? metrics.disconnected_node_ids.join(", ") : "none observed"}</dd><dt>CHANGED PATHS</dt><dd>{metrics.path_analysis.changed_path_count} of {metrics.path_analysis.pairs_evaluated} bounded pairs</dd></dl></div><div><h3>Formula & limits</h3><p>Score = 100 × (0.45 × surviving reachability + 0.35 × largest-component fraction + 0.20 × alternate-route preservation − 0.10 × path-inflation penalty).</p><dl><dt>BASELINE HASH</dt><dd><code>{formatHash(run.baseline_graph_hash)}</code></dd><dt>MODIFIED HASH</dt><dd><code>{formatHash(run.modified_graph_hash)}</code></dd><dt>ALTERNATE ROUTES</dt><dd>{metrics.alternate_routes.baseline_alternate_route_edges} → {metrics.alternate_routes.scenario_alternate_route_edges}</dd><dt>NON-CLAIM</dt><dd>No outage, service, economic, logistical, or causal claim.</dd></dl></div></div></section>}
    </>}
  </div>;
}
