"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { LineageNode, LineageResponse } from "../lib/types";
import { ChevronIcon, LinkIcon, RefreshIcon } from "./icons";

const stages = [
  { key: "source", label: "SOURCE" },
  { key: "raw", label: "RAW OBSERVATIONS" },
  { key: "canonical", label: "NORMALIZED OBJECTS" },
  { key: "derived", label: "RELATIONSHIPS + ASSESSMENTS" },
  { key: "scenario", label: "SCENARIO DOWNSTREAM" },
] as const;

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
}

function stageFor(node: LineageNode) {
  if (node.type === "source") return "source";
  if (node.type.includes("raw")) return "raw";
  if (["event", "asset", "event_version", "asset_version"].includes(node.type)) return "canonical";
  if (["scenario", "scenario_run", "scenario_result"].includes(node.type)) return "scenario";
  return "derived";
}

function timeLabel(value: string | null) {
  if (!value) return "NOT SUPPLIED";
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)).replace(",", "");
}

function shortId(value: string) {
  return value.length > 20 ? `${value.slice(0, 8)}…${value.slice(-8)}` : value;
}

export function ProvenanceWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryType = searchParams.get("object_type");
  const queryId = searchParams.get("object_id");
  const [lineage, setLineage] = useState<LineageResponse | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "empty" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!queryType || !queryId) {
      setStatus("empty");
      setLineage(null);
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      const params = new URLSearchParams({ object_type: queryType, object_id: queryId, direction: "both", limit: "80" });
      const response = await fetch(`${apiBase()}/provenance/lineage?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Provenance API returned ${response.status}`);
      const body = (await response.json()) as LineageResponse;
      setLineage(body);
      setSelectedKey(`${body.object_type}:${body.object_id}`);
      setStatus(body.nodes.length > 1 ? "ready" : "empty");
    } catch (cause) {
      setLineage(null);
      setStatus("error");
      setError(cause instanceof Error ? cause.message : "Unable to reach the provenance API");
    }
  }, [queryId, queryType]);

  useEffect(() => { void load(); }, [load]);

  const selected = useMemo(() => lineage?.nodes.find((node) => `${node.type}:${node.id}` === selectedKey) ?? null, [lineage, selectedKey]);
  const grouped = useMemo(() => stages.map((stage) => ({ ...stage, nodes: (lineage?.nodes ?? []).filter((node) => stageFor(node) === stage.key) })), [lineage]);

  function selectNode(node: LineageNode) {
    setSelectedKey(`${node.type}:${node.id}`);
    router.replace(`/provenance?object_type=${encodeURIComponent(node.type)}&object_id=${encodeURIComponent(node.id)}`);
  }

  return <div className="provenance-page">
    <div className="page-utility"><div><span className="route-label">SOURCE PROVENANCE</span><span className="route-separator">/</span><span className="route-description">BOUNDED CHAIN OF CUSTODY</span></div><div className="utility-right"><span className="utility-freshness"><span className="freshness-dot" /> {lineage ? `${lineage.nodes.length} NODES · ${lineage.edges.length} LINKS` : "LINEAGE DATA"}</span><button className="icon-button" type="button" onClick={() => void load()} aria-label="Refresh provenance data"><RefreshIcon size={15} /></button></div></div>
    <div className="provenance-intro"><div><span className="section-eyebrow"><LinkIcon size={13} /> CHAIN OF CUSTODY / PHASE 07</span><h1>Where did this claim come from?</h1><p>Trace source observations through normalized objects and deterministic transformations. Direct source facts are separated from derived relationships, assessments, and scenario projections.</p></div><div className="provenance-bound"><span>API BOUND</span><strong>ONE-HOP · MAX 80 LINKS</strong></div></div>
    {!queryType || !queryId ? <div className="provenance-state provenance-state-empty"><strong>SELECT A CLAIM TO TRACE</strong><span>Open provenance from an event, infrastructure asset, graph edge, assessment, or replay selection. This workspace does not fabricate a default lineage graph.</span><Link href="/feed">OPEN EVENT FEED <ChevronIcon size={13} /></Link></div> : null}
    {status === "loading" && <div className="provenance-state" role="status"><span className="state-pulse" /> LOADING PERSISTED LINEAGE</div>}
    {status === "error" && <div className="provenance-state provenance-state-error" role="alert"><strong>LINEAGE UNAVAILABLE</strong><span>{error ?? "The API did not respond."}</span><button type="button" onClick={() => void load()}>RETRY</button></div>}
    {status === "empty" && queryType && queryId && <div className="provenance-state provenance-state-empty"><strong>NO DEPENDENCIES RECORDED</strong><span>This object exists, but no upstream or downstream links are persisted or deterministically available.</span></div>}
    {lineage && (status === "ready" || status === "empty") && <>
      <div className="provenance-toolbar"><span>FOCUSED OBJECT</span><strong>{lineage.object_type.replaceAll("_", " ").toUpperCase()} / {shortId(lineage.object_id)}</strong><span className="provenance-direction">UPSTREAM + DOWNSTREAM</span>{lineage.truncated && <b>BOUNDED RESULT · MORE LINKS AVAILABLE</b>}</div>
      <div className="provenance-flow">{grouped.map((stage) => <section className="provenance-stage" key={stage.key}><div className="provenance-stage-head"><span>{stage.label}</span><strong>{stage.nodes.length.toString().padStart(2, "0")}</strong></div><div className="provenance-node-list">{stage.nodes.length === 0 ? <span className="provenance-stage-empty">NO OBJECTS IN SCOPE</span> : stage.nodes.map((node) => <button type="button" key={`${node.type}:${node.id}`} className={`provenance-node ${selectedKey === `${node.type}:${node.id}` ? "provenance-node-selected" : ""}`} onClick={() => selectNode(node)}><span className={`provenance-node-dot provenance-node-${node.direct_or_derived}`} /><span><strong>{node.label}</strong><small>{node.type.replaceAll("_", " ")} · {shortId(node.id)}</small></span><ChevronIcon size={12} /></button>)}</div></section>)}</div>
      <div className="provenance-detail-grid"><article className="provenance-detail-card"><div className="inspector-topline"><span>SELECTED LINEAGE NODE</span><span className={`provenance-kind provenance-kind-${selected?.direct_or_derived ?? "derived"}`}>{selected?.direct_or_derived?.toUpperCase() ?? "—"}</span></div><h2>{selected?.label ?? "Select a node"}</h2>{selected && <><p className="provenance-detail-id">{selected.type.toUpperCase()} / {selected.id}</p><dl className="provenance-detail-fields"><div><dt>OBSERVED UTC</dt><dd>{timeLabel(selected.observed_at)}</dd></div><div><dt>INGESTED UTC</dt><dd>{timeLabel(selected.ingested_at)}</dd></div><div><dt>GENERATED UTC</dt><dd>{timeLabel(selected.generated_at)}</dd></div><div><dt>CONFIDENCE</dt><dd>{selected.confidence === null ? "NOT COMPUTED" : `${Math.round(selected.confidence * 100)}%`}</dd></div></dl><div className="provenance-detail-block"><span>SOURCE</span><code>{selected.source ? JSON.stringify(selected.source, null, 2) : "NOT SUPPLIED"}</code></div><div className="provenance-detail-block"><span>TRANSFORMATION / VERSION</span><code>{selected.transformation ? JSON.stringify(selected.transformation, null, 2) : "NOT SUPPLIED"}</code></div><div className="provenance-detail-block"><span>EVIDENCE</span><code>{JSON.stringify(selected.evidence, null, 2)}</code></div></>}</article><article className="provenance-detail-card"><div className="inspector-topline"><span>LINEAGE LINKS</span><span>{lineage.edges.length} IN SCOPE</span></div><div className="provenance-edge-list">{lineage.edges.length === 0 ? <p>No links are available for this object.</p> : lineage.edges.map((edge) => <button type="button" className="provenance-edge-row" key={edge.id} onClick={() => { const target = lineage.nodes.find((node) => `${node.type}:${node.id}` === `${edge.upstream.type}:${edge.upstream.id}` || `${node.type}:${node.id}` === `${edge.downstream.type}:${edge.downstream.id}`); if (target) selectNode(target); }}><span>{edge.upstream.type.replaceAll("_", " ")} → {edge.downstream.type.replaceAll("_", " ")}</span><strong>{edge.relation_kind.replaceAll("_", " ")}</strong><small>{shortId(edge.upstream.id)} → {shortId(edge.downstream.id)}</small></button>)}</div></article></div>
    </>}
  </div>;
}
