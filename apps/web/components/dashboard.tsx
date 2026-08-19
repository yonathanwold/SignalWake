"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchEvents, demoEvents, demoInfrastructure, demoLayerCatalog, demoSources } from "../lib/data";
import type { CanonicalEvent, InfrastructureAsset, InfrastructureAssessment, LayerCatalogItem, MapLayerData, RainViewerMetadata, Source } from "../lib/types";
import { EventFeed, EventInspector, InfrastructureInspector } from "./event-feed";
import { MapSurface } from "./map-surface";
import { RefreshIcon } from "./icons";

export function Dashboard({ view = "map" }: { view?: "map" | "feed" }) {
  const [events, setEvents] = useState<CanonicalEvent[]>(demoEvents);
  const [sources, setSources] = useState<Source[]>(demoSources);
  const [infrastructure, setInfrastructure] = useState<InfrastructureAsset[]>(demoInfrastructure);
  const [layers, setLayers] = useState<LayerCatalogItem[]>(demoLayerCatalog);
  const [overlays, setOverlays] = useState<Record<string, MapLayerData>>({});
  const [radar, setRadar] = useState<RainViewerMetadata | null>(null);
  const [assessments, setAssessments] = useState<InfrastructureAssessment[]>([]);
  const [mode, setMode] = useState<"LIVE" | "DEMO">("DEMO");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedInfrastructureId, setSelectedInfrastructureId] = useState<string | null>(null);
  const [refreshState, setRefreshState] = useState<"ready" | "loading">("loading");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [windowStart, setWindowStart] = useState<string | null>(null);
  const [windowEnd, setWindowEnd] = useState<string | null>(null);
  const selectedEvent = useMemo(() => events.find((event) => event.id === selectedId) ?? null, [events, selectedId]);
  const selectedInfrastructure = useMemo(() => infrastructure.find((asset) => asset.id === selectedInfrastructureId) ?? null, [infrastructure, selectedInfrastructureId]);
  const load = useCallback(async () => { setRefreshState("loading"); const data = await fetchEvents(); setEvents(data.events); setSources(data.sources); setInfrastructure(data.infrastructure); setAssessments(data.assessments); setLayers(data.layers); setOverlays(data.overlays); setRadar(data.radar); setWindowStart(data.windowStart); setWindowEnd(data.windowEnd); setMode(data.mode); setLastUpdated(new Date(data.fetchedAt)); setSelectedId((current) => current && data.events.some((event) => event.id === current) ? current : null); setSelectedInfrastructureId((current) => current && data.infrastructure.some((asset) => asset.id === current) ? current : null); setRefreshState("ready"); }, []);
  useEffect(() => { void load(); }, [load]);
  const selectEvent = (event: CanonicalEvent) => { setSelectedId(event.id); setSelectedInfrastructureId(null); };
  const selectInfrastructure = (asset: InfrastructureAsset) => { setSelectedInfrastructureId(asset.id); setSelectedId(null); };
  const windowLabel = windowStart && windowEnd ? `${windowStart.slice(0, 10)} → ${windowEnd.slice(0, 10)} UTC / 48H` : "PAST 48H / UTC";
  return <div className={`dashboard-page ${view === "map" ? "map-dashboard" : "feed-dashboard"}`}><div className="page-utility"><div><span className="route-label">{view === "map" ? "OPERATIONAL MAP" : "EVENT FEED"}</span><span className="route-separator">/</span><span className="route-description">EVENT AWARENESS + REFERENCE INFRASTRUCTURE</span></div><div className="utility-right"><span className="utility-freshness"><span className="freshness-dot" /> LAST SYNC {lastUpdated ? `${lastUpdated.toISOString().slice(11, 16)}Z` : "—"}</span><button className="icon-button" type="button" onClick={() => void load()} aria-label="Refresh data"><RefreshIcon size={15} /></button></div></div>{view === "map" ? <div className="map-layout"><MapSurface events={events} infrastructure={infrastructure} layers={layers} overlays={overlays} radar={radar} windowLabel={windowLabel} selectedEvent={selectedEvent} selectedInfrastructure={selectedInfrastructure} onSelectEvent={selectEvent} onSelectInfrastructure={selectInfrastructure} />{selectedInfrastructure ? <InfrastructureInspector asset={selectedInfrastructure} assessments={assessments} infrastructure={infrastructure} onClose={() => setSelectedInfrastructureId(null)} /> : selectedEvent ? <EventInspector event={selectedEvent} assessments={assessments} infrastructure={infrastructure} onClose={() => setSelectedId(null)} /> : null}</div> : <EventFeed events={events} mode={mode} selectedEvent={selectedEvent} onSelect={selectEvent} onClose={() => setSelectedId(null)} onRefresh={() => void load()} refreshState={refreshState} assessments={assessments} infrastructure={infrastructure} />}<div className="source-strip"><span className="source-strip-title">SOURCE HEALTH</span>{sources.map((source) => <span className="source-health" key={source.key}><span className={`source-health-dot health-${source.health.toLowerCase()}`} />{source.key.toUpperCase()} <strong>{source.health}</strong></span>)}<span className="source-health"><span className="source-health-dot health-unknown" />REFERENCE ASSETS <strong>{infrastructure.length.toString().padStart(2, "0")}</strong></span><span className="source-strip-note">Reference infrastructure is not a disruption or impact assessment.</span></div></div>;
}
