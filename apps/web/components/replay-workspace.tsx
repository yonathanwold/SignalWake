"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertIcon, ChevronIcon, HistoryIcon, LinkIcon, PauseIcon, PlayIcon, RefreshIcon } from "./icons";
import { MapSurface } from "./map-surface";
import type { CanonicalEvent, InfrastructureAsset } from "../lib/types";

type ReplayEvent = CanonicalEvent & {
  knowledge_at: string;
  event_time: string | null;
  happened_by_at: boolean;
  temporal_status: "historical" | "active" | "expired" | string;
  version_id: string;
  replay_classification?: string;
};
type ReplayState = {
  timestamp: string;
  events: ReplayEvent[];
  infrastructure: InfrastructureAsset[];
  counts: Record<string, number>;
  truncated: boolean;
};
type TimelineMarker = { timestamp: string; kind: string; id: string; label: string; identity: string; change: string };
type CompareResult = {
  summary: Record<string, number>;
  changes: Record<string, Array<Record<string, unknown>>>;
  truncated: boolean;
};

const MAX_LIMIT = 100;
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
}
function iso(ms: number) {
  return new Date(ms).toISOString();
}
function inputUtc(ms: number) {
  return iso(ms).slice(0, 16);
}
function parseInputUtc(value: string) {
  return Date.parse(`${value}:00Z`);
}
function formatUtc(value: string | number) {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", hour12: false, timeZone: "UTC" }).format(new Date(value));
}
function formatTime(value: string | number) {
  return `${formatUtc(value)}Z`;
}

function stateEvents(value: ReplayState | null) {
  return (value?.events ?? []) as CanonicalEvent[];
}

export function ReplayWorkspace() {
  const now = Date.now();
  const [rangeStart] = useState(now - 7 * DAY);
  const [rangeEnd] = useState(now);
  const [at, setAt] = useState(now);
  const [timeline, setTimeline] = useState<TimelineMarker[]>([]);
  const [state, setState] = useState<ReplayState | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [compareFrom, setCompareFrom] = useState(now - DAY);
  const [compareTo, setCompareTo] = useState(now);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [compareStatus, setCompareStatus] = useState<"idle" | "loading" | "ready" | "empty">("idle");
  const [refreshNonce, setRefreshNonce] = useState(0);

  const loadState = useCallback(async (timestamp: number, signal?: AbortSignal) => {
    const response = await fetch(`${apiBase()}/replay/state?at=${encodeURIComponent(iso(timestamp))}&limit=${MAX_LIMIT}`, { cache: "no-store", signal });
    if (!response.ok) throw new Error("Historical state is unavailable");
    return (await response.json()) as ReplayState;
  }, []);

  const loadTimeline = useCallback(async (start: number, end: number, signal?: AbortSignal) => {
    const response = await fetch(`${apiBase()}/replay/timeline?start_time=${encodeURIComponent(iso(start))}&end_time=${encodeURIComponent(iso(end))}&limit=${MAX_LIMIT}`, { cache: "no-store", signal });
    if (!response.ok) throw new Error("Historical timeline is unavailable");
    return (await response.json()) as { items: TimelineMarker[] };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadTimeline(rangeStart, rangeEnd, controller.signal)
      .then((timelineBody) => { if (!controller.signal.aborted) setTimeline(timelineBody.items); })
      .catch(() => { if (!controller.signal.aborted) setTimeline([]); });
    return () => controller.abort();
  }, [rangeEnd, rangeStart, loadTimeline]);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);
    void loadState(at, controller.signal)
      .then((stateBody) => {
        if (controller.signal.aborted) return;
        setState(stateBody);
        setStatus(stateBody.events.length || stateBody.infrastructure.length ? "ready" : "empty");
        setSelectedEventId((current) => stateBody.events.some((event) => event.id === current) ? current : stateBody.events[0]?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setStatus("error");
        setError(reason instanceof Error ? reason.message : "Historical replay is unavailable");
      });
    return () => controller.abort();
  }, [at, loadState, refreshNonce]);

  useEffect(() => {
    if (!playing) return;
    const interval = window.setInterval(() => {
      setAt((current) => {
        const next = Math.min(rangeEnd, current + 15 * 60 * 1000 * speed);
        if (next >= rangeEnd) setPlaying(false);
        return next;
      });
    }, 650);
    return () => window.clearInterval(interval);
  }, [playing, rangeEnd, speed]);

  const selectedEvent = useMemo(() => state?.events.find((event) => event.id === selectedEventId) ?? null, [selectedEventId, state]);
  const markersAt = useMemo(() => timeline.filter((marker) => Date.parse(marker.timestamp) <= at), [at, timeline]);
  const setScrubber = (value: number) => setAt(Math.min(rangeEnd, Math.max(rangeStart, value)));

  const runCompare = async () => {
    setCompareStatus("loading");
    try {
      const response = await fetch(`${apiBase()}/replay/compare?from_time=${encodeURIComponent(iso(compareFrom))}&to_time=${encodeURIComponent(iso(compareTo))}&limit=30`, { cache: "no-store" });
      if (!response.ok) throw new Error("Comparison is unavailable");
      const body = (await response.json()) as CompareResult;
      setCompare(body);
      setCompareStatus(Object.keys(body.changes).length ? "ready" : "empty");
    } catch {
      setCompare(null);
      setCompareStatus("empty");
    }
  };

  const changeRows = compare ? [
    ["NEWLY KNOWN EVENTS", compare.changes.newly_known_events ?? [], "newly_known_events"],
    ["UPDATED EVENTS", compare.changes.updated_events ?? [], "updated_events"],
    ["EXPIRED EVENTS", compare.changes.expired_events ?? [], "expired_events"],
    ["NEW ASSESSMENTS", compare.changes.new_assessments ?? [], "new_assessments"],
    ["NEWLY EXPOSED INFRASTRUCTURE", compare.changes.newly_exposed_infrastructure ?? [], "newly_exposed_infrastructure"],
  ] as const : [];

  return <div className="replay-page">
    <div className="replay-intro">
      <div>
        <div className="section-eyebrow"><HistoryIcon size={13} /> TEMPORAL CONTEXT / KNOWLEDGE-TIME RECONSTRUCTION</div>
        <h1>Historical Replay</h1>
        <p>Scrub what SIGNALWAKE knew at an exact UTC boundary. Event time stays visible beside ingestion time; later observations never appear early.</p>
      </div>
      <div className="replay-state-badge"><span className={`replay-state-dot replay-state-${status}`} />{status === "ready" ? "HISTORICAL STATE" : status === "empty" ? "NO HISTORY" : status === "error" ? "API UNAVAILABLE" : "LOADING STATE"}<strong>{formatTime(at)}</strong></div>
    </div>

    <section className="replay-controls" aria-label="Replay controls">
      <div className="replay-control-line"><button type="button" className="replay-play" onClick={() => setPlaying((value) => !value)} aria-label={playing ? "Pause replay" : "Play replay"}>{playing ? <PauseIcon size={14} /> : <PlayIcon size={14} />}</button><button type="button" onClick={() => setScrubber(rangeStart)} className="replay-jump">START</button><button type="button" onClick={() => setScrubber(at - HOUR)} className="replay-jump">−1 H</button><button type="button" onClick={() => setScrubber(at + HOUR)} className="replay-jump">+1 H</button><button type="button" onClick={() => setScrubber(rangeEnd)} className="replay-jump">END</button><label className="replay-speed">SPEED <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label><button type="button" className="replay-refresh" onClick={() => setRefreshNonce((value) => value + 1)} aria-label="Refresh replay state"><RefreshIcon size={14} /></button></div>
      <div className="replay-scrubber-wrap"><input aria-label="Historical replay time" className="replay-scrubber" type="range" min={rangeStart} max={rangeEnd} step={60 * 1000} value={Math.min(rangeEnd, Math.max(rangeStart, at))} onChange={(event) => { setPlaying(false); setScrubber(Number(event.target.value)); }} />{timeline.map((marker) => { const position = ((Date.parse(marker.timestamp) - rangeStart) / Math.max(1, rangeEnd - rangeStart)) * 100; return position >= 0 && position <= 100 ? <span key={marker.id} className={`replay-tick replay-tick-${marker.kind}`} style={{ left: `${position}%` }} title={`${marker.kind} · ${formatTime(marker.timestamp)}`} /> : null; })}</div>
      <div className="replay-time-row"><span>{formatTime(rangeStart)}</span><strong>{formatTime(at)}</strong><span>{formatTime(rangeEnd)}</span></div>
    </section>

    <div className="replay-workspace-grid">
      <section className="replay-map-wrap"><div className="replay-panel-head"><span>MAP / AS-OF PROJECTION</span><span>{state?.counts.events ?? 0} EVENTS · {state?.counts.infrastructure ?? 0} ASSETS</span></div>{status === "ready" ? <MapSurface events={stateEvents(state)} infrastructure={state?.infrastructure ?? []} selectedEvent={selectedEvent} selectedInfrastructure={null} onSelectEvent={(event) => setSelectedEventId(event.id)} onSelectInfrastructure={() => undefined} /> : <div className="replay-empty"><AlertIcon size={18} /><strong>{status === "error" ? "HISTORICAL REPLAY UNAVAILABLE" : "NO HISTORICAL REPLAY DATA AVAILABLE"}</strong><span>{error ?? "No versioned event, assessment, infrastructure, or source history exists in this time range."}</span></div>}</section>
      <aside className="replay-event-panel"><div className="replay-panel-head"><span>EVENT MARKERS</span><span>{markersAt.length} KNOWN</span></div>{status === "ready" && state?.events.length ? <div className="replay-event-list">{state.events.map((event) => <button type="button" key={event.id} className={`replay-event-row ${event.id === selectedEventId ? "replay-event-row-selected" : ""}`} onClick={() => setSelectedEventId(event.id)}><span className={`replay-event-dot replay-event-dot-${event.severity}`} /><span><strong>{event.title}</strong><small>{event.source_key.toUpperCase()} · {event.temporal_status.toUpperCase()} · KNOWN {formatTime(event.knowledge_at)}</small></span><ChevronIcon size={13} /></button>)}</div> : <p className="replay-panel-note">Markers appear only when a recorded version is known at the selected boundary.</p>}{selectedEvent && <div className="replay-selected-event"><div className="replay-selected-label">SELECTED EVENT / {selectedEvent.temporal_status.toUpperCase()}</div><h2>{selectedEvent.title}</h2><p>{selectedEvent.summary ?? "No source summary supplied."}</p><dl><div><dt>EVENT TIME</dt><dd>{selectedEvent.event_time ? formatTime(selectedEvent.event_time) : "—"}</dd></div><div><dt>KNOWLEDGE TIME</dt><dd>{formatTime(selectedEvent.knowledge_at)}</dd></div><div><dt>HAPPENED BY T</dt><dd>{selectedEvent.happened_by_at ? "YES" : "NO — FUTURE EVENT TIME"}</dd></div><div><dt>SOURCE STATUS</dt><dd>{selectedEvent.status.toUpperCase()}</dd></div></dl><Link className="lineage-link" href={`/provenance?object_type=event&object_id=${encodeURIComponent(selectedEvent.id)}`}><LinkIcon size={13} /> VIEW EVENT LINEAGE <ChevronIcon size={13} /></Link></div>}</aside>
    </div>

    <section className="replay-compare"><div className="replay-compare-head"><div><span className="section-eyebrow">A / B COMPARISON</span><h2>What changed between two knowledge boundaries?</h2></div><span className="replay-live-label">REPLAY DATA ONLY · NO INVENTED METRICS</span></div><div className="replay-compare-controls"><label><span>FROM / UTC</span><input type="datetime-local" value={inputUtc(compareFrom)} onChange={(event) => setCompareFrom(parseInputUtc(event.target.value))} /></label><label><span>TO / UTC</span><input type="datetime-local" value={inputUtc(compareTo)} onChange={(event) => setCompareTo(parseInputUtc(event.target.value))} /></label><button type="button" onClick={() => void runCompare()} disabled={compareStatus === "loading"}>{compareStatus === "loading" ? "COMPARING…" : "COMPARE A / B"}</button></div>{compareStatus === "ready" && compare && <div className="replay-change-grid">{changeRows.map(([label, rows, key]) => <article key={key}><div><span>{label}</span><strong>{compare.summary[key] ?? rows.length}</strong></div>{rows.length ? <ul>{rows.slice(0, 5).map((row, index) => <li key={`${key}-${index}`}>{String(((row.after ?? row) as Record<string, unknown>).title ?? ((row.after ?? row) as Record<string, unknown>).name ?? ((row.after ?? row) as Record<string, unknown>).assessment_type ?? "Changed record")}</li>)}</ul> : <p>No changes recorded.</p>}</article>)}</div>}{compareStatus === "empty" && <p className="replay-panel-note">No comparison data is available for those boundaries. Use an interval containing recorded history.</p>}</section>
  </div>;
}
