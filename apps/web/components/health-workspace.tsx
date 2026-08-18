"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertIcon, HeartbeatIcon, RefreshIcon } from "./icons";
import type { HealthMetrics, HealthSource } from "../lib/types";

const apiBase = () => process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const formatTime = (value: string | null | undefined) => value ? new Date(value).toISOString().replace("T", " ").slice(0, 19) + "Z" : "—";
const formatDuration = (seconds: number | null | undefined) => {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
};
const stateClass = (state: string) => `health-state health-state-${state.toLowerCase()}`;

function MetricCard({ label, value, note }: { label: string; value: string; note: string }) {
  return <article className="health-metric-card"><span>{label}</span><strong>{value}</strong><small>{note}</small></article>;
}

function SourceRow({ source }: { source: HealthSource }) {
  return <article className="health-source-row">
    <div className="health-source-heading"><span className={stateClass(source.operational_state)} /> <strong>{source.key}</strong><em>{source.source_type}</em><b className={stateClass(source.operational_state)}>{source.operational_state}</b></div>
    <p>{source.name}</p>
    <div className="health-source-fields">
      <span><label>LAST SUCCESS</label>{formatTime(source.last_success_at)}</span>
      <span><label>LAST ATTEMPT</label>{formatTime(source.last_attempt_at)}</span>
      <span><label>LAST FAILURE</label>{formatTime(source.last_failure_at)}</span>
      <span><label>FRESHNESS</label>{source.freshness_seconds === null ? "—" : `${source.freshness_seconds}s / ${source.freshness_threshold_seconds}s`}</span>
      <span><label>RECEIVED / ACCEPTED</label>{source.records_received ?? "—"} / {source.records_accepted ?? "—"}</span>
      <span><label>REJECTED</label>{source.records_rejected ?? "—"}</span>
      <span><label>ADAPTER</label>{source.adapter_version}</span>
      <span><label>RUN</label>{source.last_run_id ? source.last_run_id.slice(0, 12) : "—"}</span>
    </div>
    {source.last_error && <div className="health-source-error"><AlertIcon size={13} /> {source.last_error_category || "failure"}: {source.last_error}</div>}
  </article>;
}

export function HealthWorkspace() {
  const [metrics, setMetrics] = useState<HealthMetrics | null>(null);
  const [ready, setReady] = useState<string>("checking");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [metricsResponse, readyResponse] = await Promise.all([
        fetch(`${apiBase()}/metrics`, { cache: "no-store" }),
        fetch(`${apiBase()}/health/ready`, { cache: "no-store" }),
      ]);
      if (!metricsResponse.ok) throw new Error(`Telemetry endpoint returned ${metricsResponse.status}`);
      const body = await metricsResponse.json() as HealthMetrics;
      setMetrics(body);
      setReady(readyResponse.ok ? "ready" : "not ready");
    } catch (cause) {
      setMetrics(null);
      setReady("unavailable");
      setError(cause instanceof Error ? cause.message : "Telemetry API unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (error || !metrics) {
    return <div className="health-page"><div className="health-intro"><div><div className="section-eyebrow"><HeartbeatIcon size={14} /> SYSTEM HEALTH</div><h1>Runtime signal, plainly shown.</h1><p>Health telemetry comes from the running API. No demo counters are used here.</p></div><button className="button" type="button" onClick={() => void load()} disabled={loading}><RefreshIcon size={13} /> {loading ? "CHECKING" : "RETRY"}</button></div><div className="health-state-panel health-state-error"><AlertIcon size={20} /><strong>TELEMETRY UNAVAILABLE</strong><span>{error || "Waiting for the API telemetry response."}</span><small>Readiness: {ready}. Start the API and refresh this workspace.</small></div></div>;
  }

  const process = metrics.process_local;
  const stateCounts = metrics.sources.counts;
  return <div className="health-page">
    <div className="health-intro"><div><div className="section-eyebrow"><HeartbeatIcon size={14} /> SYSTEM HEALTH / OBSERVABILITY</div><h1>Runtime signal, plainly shown.</h1><p>Operational source freshness, API behavior, and persisted processing runs in one bounded view.</p></div><div className="health-intro-actions"><span className="health-updated">UPDATED {formatTime(metrics.generated_at)}</span><button className="button" type="button" onClick={() => void load()} disabled={loading}><RefreshIcon size={13} /> {loading ? "REFRESHING" : "REFRESH"}</button></div></div>
    <div className="health-overview"><div className="health-overall"><span className={stateClass(stateCounts.DOWN ? "DOWN" : stateCounts.DEGRADED ? "DEGRADED" : stateCounts.ACTIVE ? "ACTIVE" : "UNKNOWN")} /><div><small>PLATFORM STATE</small><strong>{stateCounts.DOWN ? "DOWN" : stateCounts.DEGRADED ? "DEGRADED" : stateCounts.ACTIVE ? "ACTIVE" : "UNKNOWN"}</strong><p>Readiness <b>{ready.toUpperCase()}</b> · process-local snapshot</p></div></div><div className="health-state-counts"><span>ACTIVE <b>{stateCounts.ACTIVE || 0}</b></span><span>DEGRADED <b>{stateCounts.DEGRADED || 0}</b></span><span>DOWN <b>{stateCounts.DOWN || 0}</b></span><span>UNKNOWN <b>{stateCounts.UNKNOWN || 0}</b></span></div></div>
    <section className="health-section"><div className="health-section-heading"><div><span className="section-eyebrow">SOURCE MATRIX</span><h2>Event and infrastructure inputs</h2></div><span className="health-scope-label">POINT-IN-TIME / PERSISTED SOURCE STATE</span></div><div className="health-source-list">{metrics.sources.items.length ? metrics.sources.items.map((source) => <SourceRow key={`${source.source_type}-${source.id}`} source={source} />) : <div className="health-empty">No source telemetry has been persisted yet.</div>}</div></section>
    <section className="health-section"><div className="health-section-heading"><div><span className="section-eyebrow">API PROCESS</span><h2>Requests and endpoint performance</h2></div><span className="health-scope-label">PROCESS-LOCAL / SINCE STARTUP</span></div><div className="health-metric-grid"><MetricCard label="REQUESTS" value={process.requests.toLocaleString()} note={`${process.errors.toLocaleString()} errors · ${(process.error_rate * 100).toFixed(1)}% rate`} /><MetricCard label="AVERAGE LATENCY" value={`${process.average_latency_ms.toFixed(1)} ms`} note={`max ${process.max_latency_ms.toFixed(1)} ms`} /><MetricCard label="UPTIME" value={formatDuration(process.uptime_seconds)} note="current API process" /></div><div className="health-endpoint-list">{process.endpoints.length ? process.endpoints.map((endpoint) => <div className="health-endpoint-row" key={`${endpoint.method}-${endpoint.route}`}><code>{endpoint.method}</code><strong>{endpoint.route}</strong><span>{endpoint.requests} req · {endpoint.average_latency_ms.toFixed(1)} ms avg · {(endpoint.error_rate * 100).toFixed(1)}% errors</span></div>) : <div className="health-empty">No API requests have been recorded in this process.</div>}</div></section>
    <section className="health-section"><div className="health-section-heading"><div><span className="section-eyebrow">PROCESSING RUNS</span><h2>Persisted transformation latency</h2></div><span className="health-scope-label">HISTORICAL / TRANSFORMATION_RUN</span></div><div className="health-run-list">{metrics.persisted_runs.by_kind.length ? metrics.persisted_runs.by_kind.map((run) => <div className="health-run-row" key={run.run_kind}><strong>{run.run_kind}</strong><span>{run.run_count} runs · {run.completed} completed · {run.failed} failed · {run.partial} partial</span><b>{run.average_latency_ms.toFixed(1)} ms avg</b><small>{run.records_accepted} accepted / {run.records_rejected} rejected</small></div>) : <div className="health-empty">No persisted transformation runs yet.</div>}</div></section>
    <section className="health-section"><div className="health-section-heading"><div><span className="section-eyebrow">RECENT INCIDENTS</span><h2>Actual failures in the bounded window</h2></div><span className="health-scope-label">PROCESS-LOCAL + PERSISTED / MAX 100</span></div><div className="health-incident-list">{metrics.recent_failures.length ? metrics.recent_failures.map((incident, index) => <div className="health-incident-row" key={`${String(incident.request_id || incident.run_id || "incident")}-${index}`}><AlertIcon size={13} /><span><strong>{String(incident.error_category || incident.status || "failure")}</strong><small>{formatTime(String(incident.occurred_at || ""))} · {String(incident.source || "telemetry")}</small></span><code>{String(incident.message || incident.route || incident.run_kind || "No additional detail")}</code></div>) : <div className="health-empty">No failures recorded in the bounded window.</div>}</div></section>
    <p className="health-footnote">Metrics are UTC. Request and endpoint counters reset when the API process restarts. Startup ingestion is bounded and there is no permanent scheduler or worker in this deployment.</p>
  </div>;
}
