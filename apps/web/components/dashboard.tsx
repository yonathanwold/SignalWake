"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { fetchEvents, demoEvents, demoInfrastructure, demoSources } from "../lib/data";
import type { CanonicalEvent, InfrastructureAsset, InfrastructureAssessment, Source } from "../lib/types";
import { EventFeed, EventInspector, InfrastructureInspector } from "./event-feed";
import { MapSurface } from "./map-surface";
import { ClassificationPill, SeverityDot } from "./status-pill";
import { RefreshIcon } from "./icons";

export function Dashboard({ view = "map" }: { view?: "map" | "feed" }) {
  const [events, setEvents] = useState<CanonicalEvent[]>(demoEvents);
  const [sources, setSources] = useState<Source[]>(demoSources);
  const [infrastructure, setInfrastructure] = useState<InfrastructureAsset[]>(demoInfrastructure);
  const [assessments, setAssessments] = useState<InfrastructureAssessment[]>([]);
  const [mode, setMode] = useState<"LIVE" | "DEMO">("DEMO");
  const [selectedId, setSelectedId] = useState<string | null>(demoEvents[0]?.id ?? null);
  const [selectedInfrastructureId, setSelectedInfrastructureId] = useState<string | null>(null);
  const [refreshState, setRefreshState] = useState<"ready" | "loading">("loading");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const selectedEvent = useMemo(() => events.find((event) => event.id === selectedId) ?? events[0] ?? null, [events, selectedId]);
  const selectedInfrastructure = useMemo(() => infrastructure.find((asset) => asset.id === selectedInfrastructureId) ?? null, [infrastructure, selectedInfrastructureId]);
  const load = useCallback(async () => { setRefreshState("loading"); const data = await fetchEvents(); setEvents(data.events); setSources(data.sources); setInfrastructure(data.infrastructure); setAssessments(data.assessments); setMode(data.mode); setLastUpdated(new Date(data.fetchedAt)); setSelectedId((current) => data.events.some((event) => event.id === current) ? current : data.events[0]?.id ?? null); setSelectedInfrastructureId((current) => data.infrastructure.some((asset) => asset.id === current) ? current : null); setRefreshState("ready"); }, []);
  useEffect(() => { void load(); }, [load]);
  const selectEvent = (event: CanonicalEvent) => { setSelectedId(event.id); setSelectedInfrastructureId(null); };
  const selectInfrastructure = (asset: InfrastructureAsset) => { setSelectedInfrastructureId(asset.id); setSelectedId(null); };
  return <div className="dashboard-page"><div className="page-utility"><div><span className="route-label">{view === "map" ? "OPERATIONAL MAP" : "EVENT FEED"}</span><span className="route-separator">/</span><span className="route-description">EVENT AWARENESS + REFERENCE INFRASTRUCTURE</span></div><div className="utility-right"><span className="utility-freshness"><span className="freshness-dot" /> LAST SYNC {lastUpdated ? `${lastUpdated.toISOString().slice(11, 16)}Z` : "—"}</span><button className="icon-button" type="button" onClick={() => void load()} aria-label="Refresh data"><RefreshIcon size={15} /></button></div></div>{view === "map" ? <><div className="map-layout"><MapSurface events={events} infrastructure={infrastructure} selectedEvent={selectedEvent} selectedInfrastructure={selectedInfrastructure} onSelectEvent={selectEvent} onSelectInfrastructure={selectInfrastructure} />{selectedInfrastructure ? <InfrastructureInspector asset={selectedInfrastructure} assessments={assessments} infrastructure={infrastructure} /> : <EventInspector event={selectedEvent} assessments={assessments} infrastructure={infrastructure} />}</div><div className="map-summary"><div className="summary-label">EVENT FEED <span>{events.length.toString().padStart(2, "0")}</span></div><div className="summary-events">{events.slice(0, 3).map((event) => <button key={event.id} className={`summary-event ${selectedEvent?.id === event.id ? "summary-event-selected" : ""}`} type="button" onClick={() => selectEvent(event)}><SeverityDot severity={event.severity} /><span className="summary-event-title">{event.title}</span><ClassificationPill value={event.classification} /><span className={`summary-source summary-source-${event.source_key}`}>{event.source_key.toUpperCase()}</span></button>)}</div><Link className="summary-view-all" href="/feed">VIEW ALL <span>→</span></Link></div></> : <EventFeed events={events} mode={mode} selectedEvent={selectedEvent} onSelect={selectEvent} onRefresh={() => void load()} refreshState={refreshState} assessments={assessments} infrastructure={infrastructure} />}<div className="source-strip"><span className="source-strip-title">SOURCE HEALTH</span>{sources.map((source) => <span className="source-health" key={source.key}><span className={`source-health-dot health-${source.health.toLowerCase()}`} />{source.key.toUpperCase()} <strong>{source.health}</strong></span>)}<span className="source-health"><span className="source-health-dot health-unknown" />REFERENCE ASSETS <strong>{infrastructure.length.toString().padStart(2, "0")}</strong></span><span className="source-strip-note">Reference infrastructure is not a disruption or impact assessment.</span></div></div>;
}
