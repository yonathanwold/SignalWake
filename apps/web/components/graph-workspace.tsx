"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import type { GraphEdge, GraphNode, GraphNodeList, GraphSubgraph, InfrastructureAssessment, InfrastructureAssessmentList } from "../lib/types";
import { ChevronIcon, LinkIcon, NetworkIcon, RefreshIcon } from "./icons";

const relationOptions = ["ALL", "CONNECTED_TO", "INTERSECTS", "ADJACENT_TO"] as const;

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
}

function edgeLabel(edge: GraphEdge) {
  return edge.relationship_type.replaceAll("_", " ");
}

function evidenceSummary(edge: GraphEdge) {
  const measured = edge.distance_km == null ? "" : ` · ${edge.distance_km.toFixed(2)} km measured`;
  const threshold = edge.tolerance_m == null ? "" : ` · ${edge.tolerance_m} m tolerance`;
  return `${edgeLabel(edge)}${measured}${threshold}`;
}

export function GraphWorkspace() {
  const [nodeList, setNodeList] = useState<GraphNodeList | null>(null);
  const [subgraph, setSubgraph] = useState<GraphSubgraph | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [regionFilter, setRegionFilter] = useState("ALL");
  const [relationshipFilter, setRelationshipFilter] = useState<(typeof relationOptions)[number]>("ALL");
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [assessments, setAssessments] = useState<InfrastructureAssessment[]>([]);
  const [assessmentState, setAssessmentState] = useState<"loading" | "ready" | "error">("loading");

  const loadNodes = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (typeFilter !== "ALL") params.set("type", typeFilter);
      if (regionFilter !== "ALL") params.set("region", regionFilter);
      const response = await fetch(`${apiBase()}/graph/nodes?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Graph API returned ${response.status}`);
      const body = (await response.json()) as GraphNodeList;
      setNodeList(body);
      setSelectedNodeId((current) => body.items.some((node) => node.id === current) ? current : body.items[0]?.id ?? null);
      setStatus(body.items.length ? "ready" : "empty");
    } catch (cause) {
      setNodeList(null);
      setSubgraph(null);
      setSelectedNodeId(null);
      setStatus("error");
      setError(cause instanceof Error ? cause.message : "Unable to reach the graph API");
    }
  }, [regionFilter, typeFilter]);

  useEffect(() => { void loadNodes(); }, [loadNodes]);

  useEffect(() => {
    const controller = new AbortController();
    setAssessmentState("loading");
    fetch(`${apiBase()}/assessments?limit=500`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Assessment API returned ${response.status}`);
        return response.json() as Promise<InfrastructureAssessmentList>;
      })
      .then((body) => { setAssessments(body.items); setAssessmentState("ready"); })
      .catch((cause: unknown) => { if ((cause as { name?: string }).name !== "AbortError") { setAssessments([]); setAssessmentState("error"); } });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedNodeId) {
      setSubgraph(null);
      return;
    }
    const controller = new AbortController();
    const params = new URLSearchParams({ root: selectedNodeId, depth: "2", max_nodes: "30" });
    if (relationshipFilter !== "ALL") params.set("relationship_type", relationshipFilter);
    fetch(`${apiBase()}/graph/subgraph?${params.toString()}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Subgraph request returned ${response.status}`);
        return response.json() as Promise<GraphSubgraph>;
      })
      .then((body) => { setSubgraph(body); setSelectedEdgeId(null); })
      .catch((cause: unknown) => { if ((cause as { name?: string }).name !== "AbortError") setError("Unable to load the selected subgraph"); });
    return () => controller.abort();
  }, [relationshipFilter, selectedNodeId]);

  const regions = useMemo(() => ["ALL", ...Array.from(new Set((nodeList?.items ?? []).map((node) => node.region).filter(Boolean) as string[])).sort()], [nodeList]);
  const selectedNode = subgraph?.nodes.find((node) => node.id === selectedNodeId) ?? nodeList?.items.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = subgraph?.edges.find((edge) => edge.id === selectedEdgeId) ?? null;
  const selectedAssessments = selectedNode ? assessments.filter((assessment) => assessment.affected_asset_id === selectedNode.id) : [];
  const positions = useMemo(() => {
    const nodes = subgraph?.nodes ?? [];
    const center = { x: 380, y: 195 };
    const radius = Math.min(145, Math.max(80, nodes.length * 18));
    return new Map(nodes.map((node, index) => [node.id, nodes.length === 1 ? center : { x: center.x + Math.cos((index / nodes.length) * Math.PI * 2 - Math.PI / 2) * radius, y: center.y + Math.sin((index / nodes.length) * Math.PI * 2 - Math.PI / 2) * radius }]));
  }, [subgraph]);

  const handleNodeKey = (event: KeyboardEvent<SVGGElement>, node: GraphNode) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedNodeId(node.id); }
  };

  return <div className="graph-page">
    <div className="page-utility"><div><span className="route-label">INFRASTRUCTURE GRAPH</span><span className="route-separator">/</span><span className="route-description">BOUNDED RELATIONSHIP WORKSPACE</span></div><div className="utility-right"><span className="utility-freshness"><span className="freshness-dot" /> {nodeList ? `${nodeList.total} NODES` : "GRAPH DATA"}</span><button className="icon-button" type="button" onClick={() => void loadNodes()} aria-label="Refresh graph data"><RefreshIcon size={15} /></button></div></div>
    <div className="graph-intro"><div><span className="section-eyebrow">DEPENDENCY CONTEXT / PHASE 03</span><h1>Infrastructure Graph</h1><p>Explore only source-backed assets and persisted relationships. Every edge below is labeled with its derivation rule; no disruption or dependency claim is inferred.</p></div><div className="graph-bound"><NetworkIcon size={17} /><span>BOUNDED MODE</span><strong>DEPTH 2 · MAX 30 NODES</strong></div></div>
    <div className="graph-toolbar" aria-label="Graph filters"><label><span>ASSET TYPE</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option>ALL</option><option value="port">PORT</option><option value="rail_corridor">RAIL CORRIDOR</option></select></label><label><span>REGION</span><select value={regionFilter} onChange={(event) => setRegionFilter(event.target.value)}>{regions.map((region) => <option key={region}>{region}</option>)}</select></label><label><span>RELATIONSHIP</span><select value={relationshipFilter} onChange={(event) => setRelationshipFilter(event.target.value as (typeof relationOptions)[number])}>{relationOptions.map((relation) => <option key={relation} value={relation}>{relation.replaceAll("_", " ")}</option>)}</select></label><span className="graph-toolbar-note">DERIVED EDGES ONLY · NO NATIONAL GRAPH DEFAULT</span></div>
    {status === "loading" && <div className="graph-state" role="status"><span className="state-pulse" /> LOADING PERSISTED GRAPH DATA</div>}
    {status === "error" && <div className="graph-state graph-state-error" role="alert"><strong>GRAPH DATA UNAVAILABLE</strong><span>{error ?? "The API did not respond."}</span><button type="button" onClick={() => void loadNodes()}>RETRY</button></div>}
    {status === "empty" && <div className="graph-state graph-state-empty"><strong>NO PERSISTED RELATIONSHIPS YET</strong><span>Import the Phase 2 assets, then run <code>python -m app.derivation</code>. This surface does not fabricate fallback edges.</span></div>}
    {status === "ready" && <div className="graph-layout"><section className="graph-canvas-panel" aria-label="Infrastructure relationship graph"><div className="graph-panel-head"><span>SCOPED SUBGRAPH</span><span>{subgraph ? `${subgraph.nodes.length} NODES / ${subgraph.edges.length} EDGES` : "SELECT A ROOT"}</span></div><div className="graph-canvas-wrap">{subgraph && subgraph.nodes.length && subgraph.edges.length ? <svg className="graph-svg" viewBox="0 0 760 390" role="img" aria-label="Bounded infrastructure relationship graph">{subgraph.edges.map((edge) => { const from = positions.get(edge.from_node_id); const to = positions.get(edge.to_node_id); if (!from || !to) return null; return <g key={edge.id} role="button" tabIndex={0} aria-label={`Inspect ${edgeLabel(edge)} relationship`} className={`graph-edge ${selectedEdgeId === edge.id ? "graph-edge-selected" : ""}`} onClick={() => setSelectedEdgeId(edge.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedEdgeId(edge.id); }}><line x1={from.x} y1={from.y} x2={to.x} y2={to.y} /><text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 6}>{edgeLabel(edge)}</text></g>; })}{subgraph.nodes.map((node) => { const point = positions.get(node.id); if (!point) return null; return <g key={node.id} role="button" tabIndex={0} aria-label={`Select ${node.name}`} className={`graph-node graph-node-${node.type} ${selectedNodeId === node.id ? "graph-node-selected" : ""}`} transform={`translate(${point.x} ${point.y})`} onClick={() => setSelectedNodeId(node.id)} onKeyDown={(event) => handleNodeKey(event, node)}><circle r={selectedNodeId === node.id ? 15 : 11} /><text y="31">{node.name.length > 24 ? `${node.name.slice(0, 22)}…` : node.name}</text><text y="45" className="graph-node-meta">{node.type.replaceAll("_", " ")} · {node.region ?? "REGION —"}</text></g>; })}</svg> : <div className="graph-canvas-empty">{subgraph ? "NO PERSISTED RELATIONSHIPS FOR THIS SCOPE" : "Select a node to inspect its bounded neighborhood."}</div>}</div><div className="graph-canvas-foot"><span><i className="graph-key-port" /> PORT</span><span><i className="graph-key-rail" /> RAIL</span><span><i className="graph-key-edge" /> PERSISTED EDGE</span>{subgraph?.truncated && <strong>MAX NODE BOUND REACHED</strong>}</div></section><aside className="graph-sidebar"><div className="graph-sidebar-head"><span>NODE INDEX</span><strong>{nodeList?.total.toString().padStart(2, "0")}</strong></div><div className="graph-node-list" role="list">{nodeList?.items.map((node) => <button type="button" key={node.id} className={`graph-node-row ${selectedNodeId === node.id ? "graph-node-row-selected" : ""}`} onClick={() => setSelectedNodeId(node.id)}><span className={`graph-row-dot graph-row-${node.type}`} /><span><strong>{node.name}</strong><small>{node.type.replaceAll("_", " ")} · {node.region ?? "—"}</small></span><ChevronIcon size={13} /></button>)}</div></aside></div>}
    {selectedNode && <section className="graph-detail-grid"><article className="graph-detail-card"><div className="inspector-topline"><span>SELECTED NODE</span><span className="graph-badge">{selectedNode.classification}</span></div><h2>{selectedNode.name}</h2><p className="graph-detail-summary">{selectedNode.type.replaceAll("_", " ")} · {selectedNode.region ?? "Region not supplied"} · {selectedNode.source_key}</p><div className="graph-metrics"><div><span>DEGREE</span><strong>{selectedNode.metrics.degree}</strong></div><div><span>COMPONENT</span><strong>{selectedNode.metrics.component_size}</strong></div><div><span>BETWEENNESS</span><strong>{selectedNode.metrics.betweenness_centrality.toFixed(3)}</strong></div><div><span>ARTICULATION</span><strong>{selectedNode.metrics.is_articulation_point ? "YES" : "NO"}</strong></div></div><div className="graph-assessment-summary"><div className="inspector-topline"><span>SIGNALWAKE DERIVED ASSESSMENTS</span><span className="graph-badge">{assessmentState === "error" ? "API UNAVAILABLE" : `${selectedAssessments.length} FOUND`}</span></div>{assessmentState === "loading" ? <p>Loading assessment state…</p> : assessmentState === "error" ? <p>Assessment state is unavailable; no values are inferred.</p> : selectedAssessments.length === 0 ? <p>No derived assessments are stored for this asset.</p> : <div>{selectedAssessments.slice(0, 4).map((assessment) => <div className="graph-assessment-row" key={assessment.id}><strong>{assessment.assessment_type.replaceAll("_", " ")}</strong><span>{assessment.score.toFixed(1)} / 100 · {assessment.status.toUpperCase()}</span><small>{assessment.methodology_version} · confidence {assessment.confidence === null ? "not computed" : `${Math.round(assessment.confidence * 100)}%`}</small></div>)}</div>}</div><Link className="source-link" href="/"><LinkIcon size={13} /> VIEW SOURCE ASSET ON MAP <ChevronIcon size={13} /></Link></article>{selectedEdge ? <article className="graph-detail-card"><div className="inspector-topline"><span>SELECTED EDGE</span><span className="graph-badge">{selectedEdge.relationship_source}</span></div><h2>{edgeLabel(selectedEdge)}</h2><p className="graph-detail-summary">{evidenceSummary(selectedEdge)}</p><div className="graph-edge-rule"><span>DERIVATION RULE</span><strong>{selectedEdge.derivation_method ?? "Source-observed relationship"}</strong><small>{selectedEdge.derivation_version ? `Version ${selectedEdge.derivation_version}` : ""}</small></div><div className="graph-evidence"><span>PROVENANCE EVIDENCE</span><code>{JSON.stringify(selectedEdge.evidence)}</code></div></article> : <article className="graph-detail-card graph-detail-muted"><div className="inspector-topline"><span>EDGE INSPECTOR</span><span>SELECT AN EDGE</span></div><p>Choose a line in the scoped graph to inspect its source records, predicate, tolerance, and measured distance.</p></article>}</section>}
  </div>;
}
