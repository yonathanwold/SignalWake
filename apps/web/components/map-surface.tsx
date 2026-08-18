"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { CanonicalEvent, InfrastructureAsset, LayerCatalogItem } from "../lib/types";
import { AlertIcon, MapIcon, QuakeIcon } from "./icons";
import { SeverityDot } from "./status-pill";

type MapSurfaceProps = {
  events: CanonicalEvent[];
  infrastructure: InfrastructureAsset[];
  layers?: LayerCatalogItem[];
  windowLabel?: string;
  selectedEvent: CanonicalEvent | null;
  selectedInfrastructure: InfrastructureAsset | null;
  onSelectEvent: (event: CanonicalEvent) => void;
  onSelectInfrastructure: (asset: InfrastructureAsset) => void;
};

const INITIAL_CENTER: [number, number] = [-98.5795, 39.8283];
const INITIAL_ZOOM = 4;
const BASEMAP_SOURCE_ID = "carto-dark-osm";
const CARTO_DARK_TILES = [
  "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
];

type MapGeometry = { type: string; coordinates: unknown };
type MapFeature = {
  type: "Feature";
  id?: string;
  properties: Record<string, string>;
  geometry: MapGeometry;
};
type MapCollection = { type: "FeatureCollection"; features: MapFeature[] };
type MapFeatureLike = {
  properties?: Record<string, unknown>;
  geometry?: MapGeometry;
};
type MapTooltip = {
  title: string;
  source: string;
  classification: string;
  coordinates: string;
  x: number;
  y: number;
};
type MapViewState = { longitude: number; latitude: number; zoom: number };

function isMapGeometry(value: { type: string; coordinates: unknown } | null | undefined): value is MapGeometry {
  return Boolean(value && typeof value.type === "string" && value.coordinates !== null && value.coordinates !== undefined);
}

function eventCollection(events: CanonicalEvent[]): MapCollection {
  const features: MapFeature[] = [];
  for (const event of events) {
    // Keep source geometry untouched. Coordinates are only synthesized when the
    // API did not provide geometry at all.
    const geometry: MapGeometry | null = isMapGeometry(event.geometry)
      ? event.geometry
      : event.latitude !== null && event.longitude !== null
        ? { type: "Point", coordinates: [event.longitude, event.latitude] }
        : null;
    if (!geometry) continue;
    features.push({
      type: "Feature",
      id: event.id,
      properties: {
        eventId: event.id,
        severity: event.severity,
        source: event.source_key,
        title: event.title,
        classification: event.classification,
      },
      geometry,
    });
  }
  return { type: "FeatureCollection", features };
}

function eventPointCollection(events: CanonicalEvent[]): MapCollection {
  return {
    type: "FeatureCollection",
    features: eventCollection(events).features.filter((feature) => feature.geometry.type === "Point"),
  };
}

function infrastructureCollection(infrastructure: InfrastructureAsset[]): MapCollection {
  const features: MapFeature[] = [];
  for (const asset of infrastructure) {
    // Imported assets normally always have geometry. Retain it verbatim and use
    // the canonical point only for the rare record where geometry is absent.
    const geometry: MapGeometry | null = isMapGeometry(asset.geometry)
      ? asset.geometry
      : asset.latitude !== null && asset.longitude !== null
        ? { type: "Point", coordinates: [asset.longitude, asset.latitude] }
        : null;
    if (!geometry) continue;
    features.push({
      type: "Feature",
      id: asset.id,
      properties: {
        infrastructureId: asset.id,
        assetType: asset.type,
        source: asset.source_key,
        title: asset.name,
        classification: asset.classification,
      },
      geometry,
    });
  }
  return { type: "FeatureCollection", features };
}

function mapStyle(events: CanonicalEvent[], infrastructure: InfrastructureAsset[], catalog: LayerCatalogItem[] = []) {
  const severityColor = ["match", ["get", "severity"], "critical", "#ef4444", "warning", "#ed6868", "advisory", "#f1ad38", "watch", "#f1ad38", "#22c7a8"];
  const polygonGeometry = ["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false];
  const sourceKeys = Array.from(new Set([
    ...events.map((event) => event.source_key),
    ...catalog.filter((item) => item.source_key && ["LIVE", "NEAR_REAL_TIME", "DEGRADED"].includes(item.status)).map((item) => item.source_key as string),
  ])).filter((source) => source !== "nws" && source !== "usgs");
  const dynamicEventLayers = sourceKeys.flatMap((source) => {
    const safeSource = source.replace(/[^a-z0-9_-]/gi, "-");
    const filter = ["all", ["==", ["get", "source"], source]];
    return [
      { id: `event-${safeSource}-polygons`, type: "fill", source: "events", filter: [...filter, polygonGeometry], paint: { "fill-color": severityColor, "fill-opacity": 0.18 } },
      { id: `event-${safeSource}-polygon-outline`, type: "line", source: "events", filter: [...filter, polygonGeometry], paint: { "line-color": severityColor, "line-width": 2, "line-opacity": 0.9 } },
      { id: `event-${safeSource}-points`, type: "circle", source: "event-points", filter: [...filter, ["==", ["geometry-type"], "Point"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 5, "circle-color": severityColor, "circle-stroke-color": "#080808", "circle-stroke-width": 1.5 } },
    ];
  });
  return {
    version: 8,
    sources: {
      [BASEMAP_SOURCE_ID]: {
        type: "raster",
        tiles: CARTO_DARK_TILES,
        tileSize: 256,
        attribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a> <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">© CARTO</a>',
      },
      events: { type: "geojson", data: eventCollection(events) },
      "event-points": { type: "geojson", data: eventPointCollection(events), cluster: true, clusterRadius: 42, clusterMaxZoom: 5 },
      infrastructure: { type: "geojson", data: infrastructureCollection(infrastructure) },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#09111b" } },
      { id: "basemap", type: "raster", source: BASEMAP_SOURCE_ID, paint: { "raster-opacity": 1 } },
      { id: "event-polygons", type: "fill", source: "events", filter: ["all", ["==", ["get", "source"], "nws"], polygonGeometry], paint: { "fill-color": severityColor, "fill-opacity": 0.2 } },
      { id: "event-polygon-outline", type: "line", source: "events", filter: ["all", ["==", ["get", "source"], "nws"], polygonGeometry], paint: { "line-color": severityColor, "line-width": 2, "line-opacity": 0.95 } },
      { id: "event-clusters", type: "circle", source: "event-points", filter: ["has", "point_count"], paint: { "circle-radius": ["step", ["get", "point_count"], 14, 25, 18, 100, 23], "circle-color": "#22c7a8", "circle-stroke-color": "#071312", "circle-stroke-width": 2, "circle-opacity": 0.9 } },
      { id: "event-nws-point-halo", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "nws"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 10, "circle-color": "transparent", "circle-stroke-color": severityColor, "circle-stroke-width": 1.2, "circle-stroke-opacity": 0.5 } },
      { id: "event-nws-points", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "nws"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 5, "circle-color": severityColor, "circle-stroke-color": "#09111b", "circle-stroke-width": 1.5 } },
      { id: "event-usgs-point-halo", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "usgs"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 10, "circle-color": "transparent", "circle-stroke-color": severityColor, "circle-stroke-width": 1.2, "circle-stroke-opacity": 0.5 } },
      { id: "event-usgs-points", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "usgs"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 5, "circle-color": severityColor, "circle-stroke-color": "#09111b", "circle-stroke-width": 1.5 } },
      { id: "infrastructure-polygons", type: "fill", source: "infrastructure", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#a986f5", "fill-opacity": 0.15 } },
      { id: "infrastructure-rail-lines", type: "line", source: "infrastructure", filter: ["all", ["==", ["geometry-type"], "LineString"], ["==", ["get", "assetType"], "rail_corridor"]], paint: { "line-color": "#6ab6ff", "line-width": 2.6, "line-opacity": 0.88, "line-dasharray": [1, 1.5] } },
      { id: "infrastructure-port-points", type: "circle", source: "infrastructure", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "assetType"], "port"]], paint: { "circle-radius": 6, "circle-color": "#f1ad38", "circle-stroke-color": "#15100a", "circle-stroke-width": 1.5 } },
      { id: "infrastructure-other-points", type: "circle", source: "infrastructure", filter: ["all", ["==", ["geometry-type"], "Point"], ["!=", ["get", "assetType"], "port"]], paint: { "circle-radius": 5, "circle-color": "#a986f5", "circle-stroke-color": "#15101f", "circle-stroke-width": 1.5 } },
      ...dynamicEventLayers,
    ],
  };
}

function selectableEvent(event: CanonicalEvent) {
  return isMapGeometry(event.geometry) || (event.latitude !== null && event.longitude !== null);
}

function selectableInfrastructure(asset: InfrastructureAsset) {
  return isMapGeometry(asset.geometry) || (asset.latitude !== null && asset.longitude !== null);
}

function pointCoordinatesLabel(geometry: MapGeometry | undefined) {
  if (geometry?.type !== "Point" || !Array.isArray(geometry.coordinates) || geometry.coordinates.length < 2) {
    return geometry ? `${geometry.type.toUpperCase()} GEOMETRY · source coordinates preserved` : "COORDINATES NOT SUPPLIED";
  }
  const longitude = geometry.coordinates[0];
  const latitude = geometry.coordinates[1];
  if (typeof longitude !== "number" || typeof latitude !== "number") return "COORDINATES NOT SUPPLIED";
  return `${latitude.toFixed(5)}° ${latitude >= 0 ? "N" : "S"} · ${Math.abs(longitude).toFixed(5)}° ${longitude >= 0 ? "E" : "W"}`;
}

function centerLabel(view: MapViewState) {
  const latitudeHemisphere = view.latitude >= 0 ? "N" : "S";
  const longitudeHemisphere = view.longitude >= 0 ? "E" : "W";
  return `${Math.abs(view.latitude).toFixed(5)}°${latitudeHemisphere} / ${Math.abs(view.longitude).toFixed(5)}°${longitudeHemisphere}`;
}

export function MapSurface({ events, infrastructure, layers = [], windowLabel = "PAST 48H / UTC", selectedEvent, selectedInfrastructure, onSelectEvent, onSelectInfrastructure }: MapSurfaceProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const eventsRef = useRef(events);
  const infrastructureRef = useRef(infrastructure);
  const layersRef = useRef(layers);
  const onSelectEventRef = useRef(onSelectEvent);
  const onSelectInfrastructureRef = useRef(onSelectInfrastructure);
  const [mapRuntime, setMapRuntime] = useState<"loading" | "ready" | "error">("loading");
  const [mapTooltip, setMapTooltip] = useState<MapTooltip | null>(null);
  const [viewState, setViewState] = useState<MapViewState>({ longitude: INITIAL_CENTER[0], latitude: INITIAL_CENTER[1], zoom: INITIAL_ZOOM });
  const [keyboardIndex, setKeyboardIndex] = useState(0);
  const [showNws, setShowNws] = useState(true);
  const [showUsgs, setShowUsgs] = useState(true);
  const [showPorts, setShowPorts] = useState(true);
  const [showRail, setShowRail] = useState(true);
  const [hiddenLayers, setHiddenLayers] = useState<Record<string, boolean>>({});
  const selectedLabel = selectedEvent?.title ?? selectedInfrastructure?.name ?? "none";
  eventsRef.current = events;
  infrastructureRef.current = infrastructure;
  layersRef.current = layers;
  onSelectEventRef.current = onSelectEvent;
  onSelectInfrastructureRef.current = onSelectInfrastructure;

  useEffect(() => {
    let disposed = false;
    let basemapFailed = false;
    void import("maplibre-gl").then((maplibre) => {
      if (disposed || !mapContainerRef.current) return;
      try {
        maplibre.setWorkerUrl("/maplibre-gl-worker.mjs");
        const map = new maplibre.Map({
          container: mapContainerRef.current,
          style: mapStyle(eventsRef.current, infrastructureRef.current, layersRef.current) as never,
          center: INITIAL_CENTER,
          zoom: INITIAL_ZOOM,
          minZoom: 2,
          maxZoom: 12,
          attributionControl: { compact: false },
          renderWorldCopies: false,
        });
        mapRef.current = map;
        const selectFromFeature = (feature: MapFeatureLike | undefined) => {
          const eventId = feature?.properties?.eventId;
          const event = typeof eventId === "string" ? eventsRef.current.find((item) => item.id === eventId) : undefined;
          if (event) {
            onSelectEventRef.current(event);
            return;
          }
          const infrastructureId = feature?.properties?.infrastructureId;
          const asset = typeof infrastructureId === "string" ? infrastructureRef.current.find((item) => item.id === infrastructureId) : undefined;
          if (asset) onSelectInfrastructureRef.current(asset);
        };
        const showFeatureTooltip = (feature: MapFeatureLike | undefined, point: { x: number; y: number }) => {
          if (!feature?.properties) return;
          const title = typeof feature.properties.title === "string" ? feature.properties.title : "SELECTED MAP FEATURE";
          const sourceKey = typeof feature.properties.source === "string" ? feature.properties.source : "source";
          const source = sourceKey === "nws" ? "NWS" : sourceKey === "usgs" ? "USGS" : sourceKey.toUpperCase();
          const classification = typeof feature.properties.classification === "string" ? feature.properties.classification : "REFERENCE";
          setMapTooltip({ title, source, classification, coordinates: pointCoordinatesLabel(feature.geometry), x: point.x, y: point.y });
        };
        const featureLayerIds = [
          "event-polygons",
          "event-polygon-outline",
          "event-nws-points",
          "event-nws-point-halo",
          "event-usgs-points",
          "event-usgs-point-halo",
          "infrastructure-polygons",
          "infrastructure-port-points",
          "infrastructure-rail-lines",
          "infrastructure-other-points",
          ...layersRef.current.flatMap((item) => item.source_key && item.source_key !== "nws" && item.source_key !== "usgs" ? [`event-${item.source_key.replace(/[^a-z0-9_-]/gi, "-")}-polygons`, `event-${item.source_key.replace(/[^a-z0-9_-]/gi, "-")}-polygon-outline`, `event-${item.source_key.replace(/[^a-z0-9_-]/gi, "-")}-points`] : []),
        ];
        map.on("load", () => {
          if (!disposed && !basemapFailed) setMapRuntime("ready");
        });
        map.on("error", (event) => {
          const sourceId = (event as unknown as { sourceId?: string }).sourceId;
          if (sourceId === BASEMAP_SOURCE_ID || sourceId === undefined) {
            basemapFailed = true;
            if (!disposed) setMapRuntime("error");
          }
        });
        featureLayerIds.forEach((layerId) => {
          map.on("click", layerId, (event) => {
            const feature = event.features?.[0] as MapFeatureLike | undefined;
            selectFromFeature(feature);
            showFeatureTooltip(feature, event.point);
          });
          map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
        });
        map.on("click", "event-clusters", (event) => {
          const feature = event.features?.[0] as { properties?: Record<string, unknown> } | undefined;
          const clusterId = feature?.properties?.cluster_id;
          if (typeof clusterId !== "number") return;
          const source = map.getSource("event-points") as unknown as { getClusterExpansionZoom?: (id: number, callback: (error: Error | null, zoom: number) => void) => void };
          source.getClusterExpansionZoom?.(clusterId, (error, zoom) => {
            if (!error) map.easeTo({ center: event.lngLat, zoom });
          });
        });
        map.on("mouseenter", "event-clusters", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "event-clusters", () => { map.getCanvas().style.cursor = ""; });
        map.on("movestart", () => setMapTooltip(null));
        map.on("moveend", () => {
          const center = map.getCenter();
          setViewState({ longitude: center.lng, latitude: center.lat, zoom: map.getZoom() });
        });
      } catch {
        if (!disposed) setMapRuntime("error");
      }
    }).catch(() => {
      if (!disposed) setMapRuntime("error");
    });
    return () => {
      disposed = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const source = mapRef.current?.getSource("events") as import("maplibre-gl").GeoJSONSource | undefined;
    source?.setData(eventCollection(events) as never);
    const pointSource = mapRef.current?.getSource("event-points") as import("maplibre-gl").GeoJSONSource | undefined;
    pointSource?.setData(eventPointCollection(events) as never);
  }, [events]);

  useEffect(() => {
    const source = mapRef.current?.getSource("infrastructure") as import("maplibre-gl").GeoJSONSource | undefined;
    source?.setData(infrastructureCollection(infrastructure) as never);
  }, [infrastructure]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || mapRuntime !== "ready") return;
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    ["event-polygons", "event-polygon-outline", "event-nws-points", "event-nws-point-halo"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showNws)));
    ["event-usgs-points", "event-usgs-point-halo"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showUsgs)));
    map.setLayoutProperty("event-clusters", "visibility", visibility(showNws && showUsgs && !Object.values(hiddenLayers).some(Boolean)));
    map.setLayoutProperty("infrastructure-polygons", "visibility", visibility(showPorts));
    map.setLayoutProperty("infrastructure-port-points", "visibility", visibility(showPorts));
    ["infrastructure-rail-lines", "infrastructure-other-points"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showRail)));
  }, [hiddenLayers, mapRuntime, showNws, showUsgs, showPorts, showRail]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || mapRuntime !== "ready") return;
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    layers.forEach((item) => {
      if (!item.source_key || item.source_key === "nws" || item.source_key === "usgs") return;
      const source = item.source_key.replace(/[^a-z0-9_-]/gi, "-");
      const visible = !hiddenLayers[item.key];
      [`event-${source}-polygons`, `event-${source}-polygon-outline`, `event-${source}-points`].forEach((layer) => {
        if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", visibility(visible));
      });
    });
  }, [hiddenLayers, layers, mapRuntime]);

  const handleMapKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    const selectable = [
      ...events.filter(selectableEvent).map((item) => ({ kind: "event" as const, item })),
      ...infrastructure.filter(selectableInfrastructure).map((item) => ({ kind: "infrastructure" as const, item })),
    ];
    if (!selectable.length) return;
    if (event.key !== "ArrowRight" && event.key !== "ArrowDown" && event.key !== "ArrowLeft" && event.key !== "ArrowUp" && event.key !== "Enter") return;
    event.preventDefault();
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown" ? (keyboardIndex + 1) % selectable.length : event.key === "ArrowLeft" || event.key === "ArrowUp" ? (keyboardIndex - 1 + selectable.length) % selectable.length : keyboardIndex % selectable.length;
    setKeyboardIndex(nextIndex);
    const selected = selectable[nextIndex];
    if (selected.kind === "event") onSelectEvent(selected.item);
    else onSelectInfrastructure(selected.item);
  }, [events, infrastructure, keyboardIndex, onSelectEvent, onSelectInfrastructure]);

  return <section className="map-section" aria-label="Operational event and infrastructure map">
    <div className="map-toolbar"><div className="map-title"><MapIcon size={16} /><span>NORTH AMERICA / LIVE SITUATIONAL VIEW</span><small>{windowLabel}</small></div><div className="map-toolbar-right"><span className="map-coordinate">CENTER {centerLabel(viewState)}</span><span className="map-zoom">Z <span>{viewState.zoom.toFixed(1)}</span></span></div></div>
    <div className="map-canvas">
      <div ref={mapContainerRef} className="maplibre-canvas" role="application" aria-label={`MapLibre operational event map. Selected ${selectedLabel}. Drag to pan, scroll to zoom, and focus this map to use arrow keys to select events.`} tabIndex={0} onKeyDown={handleMapKeyDown} />
      {mapTooltip && <div className="map-feature-tooltip" style={{ left: mapTooltip.x, top: mapTooltip.y }} aria-live="polite"><strong>{mapTooltip.title}</strong><span>{mapTooltip.source} · {mapTooltip.classification}</span><small>{mapTooltip.coordinates}</small></div>}
      {mapRuntime === "ready" && <div className="maplibre-zoom-controls" aria-label="Map controls"><button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label="Zoom in">+</button><button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label="Zoom out">−</button><button type="button" onClick={() => mapRef.current?.flyTo({ center: INITIAL_CENTER, zoom: INITIAL_ZOOM })} aria-label="Reset map view">⌾</button></div>}
      <div className={`map-runtime-note map-runtime-note-${mapRuntime}`} role={mapRuntime === "error" ? "status" : undefined}><span className={`fallback-dot fallback-dot-${mapRuntime}`} /><span>{mapRuntime === "ready" ? "MAP RUNTIME / CARTO DARK OSM" : mapRuntime === "error" ? "BASEMAP UNAVAILABLE" : "MAP RUNTIME / LOADING CARTO"}</span><span className="fallback-detail">{mapRuntime === "ready" ? "OpenStreetMap tiles · source geometry preserved" : mapRuntime === "error" ? "The public tile service did not load; no geographic fallback is shown" : "Fetching public OpenStreetMap tiles"}</span></div>
      <div className="map-layer-rail"><div className="rail-label">LIVE EVENT DATA</div><button className={`layer-control ${showNws ? "layer-active" : ""}`} type="button" onClick={() => setShowNws((value) => !value)} aria-pressed={showNws}><span className="layer-swatch layer-swatch-alert" /><span>NWS ALERTS</span><strong>{events.filter((event) => event.source_key === "nws").length.toString().padStart(2, "0")}</strong></button><button className={`layer-control ${showUsgs ? "layer-active" : ""}`} type="button" onClick={() => setShowUsgs((value) => !value)} aria-pressed={showUsgs}><span className="layer-swatch layer-swatch-quake" /><span>USGS QUAKES</span><strong>{events.filter((event) => event.source_key === "usgs").length.toString().padStart(2, "0")}</strong></button>{layers.filter((item) => item.source_key && item.source_key !== "nws" && item.source_key !== "usgs").map((item) => { const source = item.source_key as string; const hasData = events.some((event) => event.source_key === source); const canToggle = hasData && ["LIVE", "NEAR_REAL_TIME", "DEGRADED"].includes(item.status); const count = item.counts.accepted ?? events.filter((event) => event.source_key === source).length; return <button key={item.key} className={`layer-control ${!hiddenLayers[item.key] ? "layer-active" : ""}`} type="button" disabled={!canToggle} onClick={() => setHiddenLayers((current) => ({ ...current, [item.key]: !current[item.key] }))} aria-pressed={!hiddenLayers[item.key]}><span className="layer-swatch layer-swatch-future" /><span>{item.name.toUpperCase()}</span><strong>{canToggle ? count.toString().padStart(2, "0") : item.status}</strong></button>; })}<div className="rail-label rail-label-reference">INFRASTRUCTURE REFERENCE DATA</div><button className={`layer-control ${showPorts ? "layer-active" : ""}`} type="button" onClick={() => setShowPorts((value) => !value)} aria-pressed={showPorts}><span className="layer-swatch layer-swatch-port" /><span>PORT FACILITIES</span><strong>{infrastructure.filter((asset) => asset.type === "port").length.toString().padStart(2, "0")}</strong></button><button className={`layer-control ${showRail ? "layer-active" : ""}`} type="button" onClick={() => setShowRail((value) => !value)} aria-pressed={showRail}><span className="layer-swatch layer-swatch-rail" /><span>RAIL CORRIDORS</span><strong>{infrastructure.filter((asset) => asset.type === "rail_corridor").length.toString().padStart(2, "0")}</strong></button><button className="layer-control" type="button" disabled><span className="layer-swatch layer-swatch-future" /><span>POWER GRID / FUTURE</span><strong>—</strong></button></div>
      <div className="map-legend"><span><span className="legend-dot legend-warning" /> WARNING</span><span><span className="legend-dot legend-advisory" /> ADVISORY</span><span><span className="legend-dot legend-info" /> INFO</span></div>
      <div className="map-scale"><span>0</span><span className="scale-line" /><span>500 km</span></div>
    </div>
    <div className="map-foot"><span><span className="foot-icon"><AlertIcon size={14} /></span> WEATHER OVERLAYS</span><span><span className="foot-icon"><QuakeIcon size={14} /></span> SEISMIC OBSERVATIONS</span><span className="map-foot-note"><SeverityDot severity="info" /> Reference assets are source-provided · no impact assessment is implied</span></div>
  </section>;
}
