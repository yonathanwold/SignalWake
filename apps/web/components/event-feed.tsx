"use client";

import { useMemo, useState } from "react";
import type { CanonicalEvent, InfrastructureAsset, InfrastructureAssessment } from "../lib/types";
import { AlertIcon, ChevronIcon, LinkIcon, MapIcon, QuakeIcon, RefreshIcon } from "./icons";
import { ClassificationPill, SeverityDot } from "./status-pill";

function timeLabel(value: string) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC", month: "short", day: "2-digit" }).format(date).replace(",", "");
}
function relativeLabel(value: string) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}
function sourceLabel(event: CanonicalEvent) { return event.source_key === "nws" ? "NWS" : "USGS"; }
function assessmentLabel(value: string) { return value.replaceAll("_", " "); }
function assessmentTarget(assessment: InfrastructureAssessment, infrastructure: InfrastructureAsset[]) {
  const asset = assessment.affected_asset_id ? infrastructure.find((item) => item.id === assessment.affected_asset_id) : null;
  return asset?.name ?? assessment.affected_asset_id ?? assessment.affected_region ?? "REGION NOT SUPPLIED";
}

function AssessmentPanel({ assessments, infrastructure }: { assessments: InfrastructureAssessment[]; infrastructure: InfrastructureAsset[] }) {
  return <div className="assessment-panel">
    <div className="provenance-heading"><span className="assessment-derived-mark">DERIVED</span><span>SIGNALWAKE ASSESSMENTS</span></div>
    {assessments.length === 0 ? <p className="assessment-empty">No derived assessments are available from the API for this selection.</p> : <div className="assessment-list">
      {assessments.map((assessment) => <article className="assessment-row" key={assessment.id}>
        <div className="assessment-row-head"><strong>{assessmentLabel(assessment.assessment_type)}</strong><b>{assessment.score.toFixed(1)} / 100</b></div>
        <div className="assessment-row-meta"><span className={`text-${assessment.severity}`}>{assessment.severity.toUpperCase()}</span><span>{assessment.status.toUpperCase()}</span><span>TARGET {assessmentTarget(assessment, infrastructure)}</span></div>
        <div className="assessment-row-meta"><span>CONFIDENCE {assessment.confidence === null ? "NOT COMPUTED" : `${Math.round(assessment.confidence * 100)}%`}</span><span>{assessment.methodology_version}</span></div>
        <details><summary>COMPONENTS + EVIDENCE</summary><code>{JSON.stringify({ score_components: assessment.score_components, evidence: assessment.evidence }, null, 2)}</code></details>
      </article>)}
    </div>}
  </div>;
}

export function EventFeed({ events, mode, selectedEvent, onSelect, onRefresh, refreshState = "ready", assessments, infrastructure }: { events: CanonicalEvent[]; mode: "LIVE" | "DEMO"; selectedEvent: CanonicalEvent | null; onSelect: (event: CanonicalEvent) => void; onRefresh: () => void; refreshState?: "ready" | "loading"; assessments: InfrastructureAssessment[]; infrastructure: InfrastructureAsset[]; }) {
  const [sourceFilter, setSourceFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => events.filter((event) => (sourceFilter === "all" || event.source_key === sourceFilter) && (typeFilter === "all" || event.type === typeFilter) && (severityFilter === "all" || event.severity === severityFilter) && (!query || `${event.title} ${event.summary ?? ""}`.toLowerCase().includes(query.toLowerCase()))), [events, sourceFilter, typeFilter, severityFilter, query]);
  return <section className="feed-section" aria-label="Event feed">
    <div className="section-heading"><div><div className="section-eyebrow">CANONICAL EVENT STREAM</div><h1>Event Feed</h1><p>Latest observations, normalized to one source-aware event model.</p></div><div className="heading-actions"><span className={`stream-state stream-${mode.toLowerCase()}`}><span className="stream-dot" /> {mode}</span><button className="button button-quiet" type="button" onClick={onRefresh} disabled={refreshState === "loading"}><RefreshIcon size={14} /> {refreshState === "loading" ? "REFRESHING" : "REFRESH"}</button></div></div>
    <div className="feed-toolbar"><label className="search-box"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search event title or place" aria-label="Search events" /></label><label className="select-label"><span>SOURCE</span><select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="all">ALL SOURCES</option><option value="nws">NWS</option><option value="usgs">USGS</option></select></label><label className="select-label"><span>TYPE</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">ALL TYPES</option><option value="weather_alert">WEATHER</option><option value="earthquake">EARTHQUAKE</option></select></label><label className="select-label"><span>SEVERITY</span><select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}><option value="all">ALL LEVELS</option><option value="warning">WARNING</option><option value="advisory">ADVISORY</option><option value="info">INFO</option></select></label><span className="result-count">{filtered.length.toString().padStart(2, "0")} RESULTS</span></div>
    <div className="feed-layout"><div className="feed-list" role="list">{filtered.length === 0 ? <div className="empty-feed"><span>NO MATCHING OBSERVATIONS</span><p>Change the filters to inspect another part of the stream.</p></div> : filtered.map((event) => <button className={`feed-row ${selectedEvent?.id === event.id ? "feed-row-selected" : ""}`} key={event.id} onClick={() => onSelect(event)} type="button"><span className="feed-row-severity"><SeverityDot severity={event.severity} /></span><span className="feed-row-main"><span className="feed-row-title">{event.title}</span><span className="feed-row-sub"><span className={`source-mark source-${event.source_key}`}>{sourceLabel(event)}</span><span>{event.type === "earthquake" ? "SEISMIC" : "WEATHER"}</span><span>{relativeLabel(event.observed_at)}</span></span></span><span className="feed-row-time">{timeLabel(event.observed_at)}</span><ChevronIcon size={14} /></button>)}</div><EventInspector event={selectedEvent ?? filtered[0] ?? null} assessments={assessments} infrastructure={infrastructure} /></div>
  </section>;
}

export function EventInspector({ event, assessments = [], infrastructure = [] }: { event: CanonicalEvent | null; assessments?: InfrastructureAssessment[]; infrastructure?: InfrastructureAsset[] }) {
  if (!event) return <aside className="inspector inspector-empty"><div className="inspector-empty-mark">+</div><div>SELECT AN OBSERVATION</div><p>Choose an event to inspect its canonical fields and source provenance.</p></aside>;
  const isQuake = event.type === "earthquake";
  const eventAssessments = assessments.filter((assessment) => assessment.event_id === event.id);
  return <aside className="inspector"><div className="inspector-topline"><span>EVENT INSPECTOR</span><ClassificationPill value={event.classification} /></div><div className="inspector-event-kind"><span className={`inspector-icon inspector-icon-${event.source_key}`}>{isQuake ? <QuakeIcon size={16} /> : <AlertIcon size={16} />}</span><span>{isQuake ? "SEISMIC OBSERVATION" : "WEATHER ALERT"}</span><span className="inspector-active">{event.status.toUpperCase()}</span></div><h2>{event.title}</h2>{event.summary && <p className="inspector-summary">{event.summary}</p>}<div className="inspector-field-grid"><div><span>SEVERITY</span><strong className={`text-${event.severity}`}>{event.severity.toUpperCase()}</strong></div><div><span>OBSERVED UTC</span><strong>{timeLabel(event.observed_at)}</strong></div><div><span>COORDINATES</span><strong>{event.latitude !== null && event.longitude !== null ? `${event.latitude.toFixed(3)}°, ${event.longitude.toFixed(3)}°` : "POLYGON"}</strong></div><div><span>EVENT ID</span><strong className="mono">{event.source_event_id.slice(-16)}</strong></div></div><div className="inspector-divider" /><AssessmentPanel assessments={eventAssessments} infrastructure={infrastructure} /><div className="inspector-divider" /><div className="provenance-heading"><LinkIcon size={14} /><span>SOURCE PROVENANCE</span></div><div className="provenance-source"><span className={`source-mark source-${event.source_key}`}>{sourceLabel(event)}</span><span>{event.source_name}</span><span className="provenance-record">{event.provenance[0]?.adapter_version ?? "—"} / ADAPTER</span></div><div className="provenance-row"><span>RAW RECORD</span><span className="mono">{event.provenance[0]?.raw_observation_id?.slice(-18) ?? "UNAVAILABLE"}</span></div><div className="provenance-row"><span>PAYLOAD HASH</span><span className="mono">{event.provenance[0]?.payload_hash?.slice(0, 14) ?? "UNAVAILABLE"}…</span></div><a className="source-link" href={event.provenance[0]?.source_url} target="_blank" rel="noreferrer"><LinkIcon size={13} /> OPEN AUTHORITATIVE SOURCE <ChevronIcon size={13} /></a></aside>;
}

function infrastructureTypeLabel(asset: InfrastructureAsset) {
  return asset.type === "rail_corridor" ? "RAIL CORRIDOR" : asset.type.replaceAll("_", " ").toUpperCase();
}

function infrastructureLocation(asset: InfrastructureAsset) {
  if (asset.latitude !== null && asset.longitude !== null) return `${asset.latitude.toFixed(3)}°, ${asset.longitude.toFixed(3)}°`;
  return asset.geometry_type.toUpperCase();
}

export function InfrastructureInspector({ asset, assessments = [], infrastructure = [] }: { asset: InfrastructureAsset | null; assessments?: InfrastructureAssessment[]; infrastructure?: InfrastructureAsset[] }) {
  if (!asset) return <aside className="inspector inspector-empty"><div className="inspector-empty-mark">+</div><div>SELECT REFERENCE DATA</div><p>Choose a port facility or rail corridor to inspect its source and geometry.</p></aside>;
  const provenance = asset.provenance[0];
  const assetAssessments = assessments.filter((assessment) => assessment.affected_asset_id === asset.id);
  return <aside className="inspector infrastructure-inspector"><div className="inspector-topline"><span>INFRASTRUCTURE INSPECTOR</span><ClassificationPill value={asset.classification} /></div><div className="inspector-event-kind"><span className="inspector-icon inspector-icon-infrastructure"><MapIcon size={16} /></span><span>{infrastructureTypeLabel(asset)}</span><span className="inspector-active inspector-reference">REFERENCE</span></div><h2>{asset.name}</h2><p className="inspector-summary">Reference geometry from a public transportation dataset. It is not an inferred dependency or disruption score.</p><div className="inspector-field-grid"><div><span>SUBTYPE</span><strong>{asset.subtype ?? "—"}</strong></div><div><span>REGION</span><strong>{asset.region ?? "—"}</strong></div><div><span>LOCATION</span><strong>{infrastructureLocation(asset)}</strong></div><div><span>STATUS</span><strong>{asset.status?.toUpperCase() ?? "NOT SUPPLIED"}</strong></div></div><div className="inspector-divider" /><AssessmentPanel assessments={assetAssessments} infrastructure={infrastructure} /><div className="inspector-divider" /><div className="provenance-heading"><LinkIcon size={14} /><span>SOURCE PROVENANCE</span></div><div className="provenance-source"><span className="source-mark source-infrastructure">{asset.source_key === "fra_rail" ? "FRA" : "BTS"}</span><span>{asset.source_name}</span><span className="provenance-record">{provenance?.adapter_version ?? "—"} / IMPORTER</span></div><div className="provenance-row"><span>SOURCE RECORD</span><span className="mono">{asset.source_asset_id}</span></div><div className="provenance-row"><span>IMPORTED UTC</span><span className="mono">{timeLabel(asset.imported_at)}</span></div><div className="provenance-row"><span>UPDATED UTC</span><span className="mono">{asset.source_updated_at ? timeLabel(asset.source_updated_at) : "NOT SUPPLIED"}</span></div><a className="source-link" href={asset.source_url} target="_blank" rel="noreferrer"><LinkIcon size={13} /> OPEN DATASET SOURCE <ChevronIcon size={13} /></a></aside>;
}
