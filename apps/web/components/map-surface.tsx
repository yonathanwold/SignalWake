"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { CanonicalEvent, InfrastructureAsset } from "../lib/types";
import { AlertIcon, MapIcon, QuakeIcon } from "./icons";
import { SeverityDot } from "./status-pill";

type MapSurfaceProps = {
  events: CanonicalEvent[];
  infrastructure: InfrastructureAsset[];
  selectedEvent: CanonicalEvent | null;
  selectedInfrastructure: InfrastructureAsset | null;
  onSelectEvent: (event: CanonicalEvent) => void;
  onSelectInfrastructure: (asset: InfrastructureAsset) => void;
};

const bounds = { minLon: -130, maxLon: -60, minLat: 20, maxLat: 56 };
function project(longitude: number, latitude: number) {
  return { x: ((longitude - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * 1000, y: ((bounds.maxLat - latitude) / (bounds.maxLat - bounds.minLat)) * 600 };
}
function geometryCenter(event: CanonicalEvent) {
  if (event.longitude !== null && event.latitude !== null) return { longitude: event.longitude, latitude: event.latitude };
  const coordinates = event.geometry?.coordinates;
  if (event.geometry?.type === "Polygon" && Array.isArray(coordinates) && Array.isArray(coordinates[0])) {
    const ring = coordinates[0] as number[][];
    const points = ring.filter((point) => Array.isArray(point) && point.length >= 2);
    if (points.length) return { longitude: points.reduce((sum, point) => sum + point[0], 0) / points.length, latitude: points.reduce((sum, point) => sum + point[1], 0) / points.length };
  }
  return null;
}
function polygonPoints(event: CanonicalEvent) {
  if (event.geometry?.type !== "Polygon" || !Array.isArray(event.geometry.coordinates) || !Array.isArray(event.geometry.coordinates[0])) return "";
  return (event.geometry.coordinates[0] as number[][]).map(([longitude, latitude]) => { const p = project(longitude, latitude); return `${p.x},${p.y}`; }).join(" ");
}

function infrastructureCenter(asset: InfrastructureAsset) {
  if (asset.longitude !== null && asset.latitude !== null) return { longitude: asset.longitude, latitude: asset.latitude };
  const coordinates = asset.geometry?.coordinates;
  if (asset.geometry?.type === "LineString" && Array.isArray(coordinates)) {
    const points = (coordinates as number[][]).filter((point) => Array.isArray(point) && point.length >= 2);
    if (points.length) return { longitude: points.reduce((sum, point) => sum + point[0], 0) / points.length, latitude: points.reduce((sum, point) => sum + point[1], 0) / points.length };
  }
  return null;
}

function infrastructureLinePoints(asset: InfrastructureAsset) {
  if (asset.geometry?.type !== "LineString" || !Array.isArray(asset.geometry.coordinates)) return "";
  return (asset.geometry.coordinates as number[][]).map(([longitude, latitude]) => { const point = project(longitude, latitude); return `${point.x},${point.y}`; }).join(" ");
}

type MapFeature = {
  type: "Feature";
  id?: string;
  properties: Record<string, string>;
  geometry: { type: "Point" | "Polygon" | "LineString"; coordinates: unknown };
};
type MapCollection = { type: "FeatureCollection"; features: MapFeature[] };

function eventCollection(events: CanonicalEvent[]): MapCollection {
  const features: MapFeature[] = [];
  for (const event of events) {
    const geometry: MapFeature["geometry"] | null = event.geometry?.type === "Point" || event.geometry?.type === "Polygon"
      ? { type: event.geometry.type, coordinates: event.geometry.coordinates }
      : event.latitude !== null && event.longitude !== null
        ? { type: "Point" as const, coordinates: [event.longitude, event.latitude] }
        : null;
    if (!geometry) continue;
    features.push({
      type: "Feature",
      id: event.id,
      properties: { eventId: event.id, severity: event.severity, source: event.source_key, title: event.title },
      geometry,
    });
  }
  return { type: "FeatureCollection", features };
}

function infrastructureCollection(infrastructure: InfrastructureAsset[]): MapCollection {
  return {
    type: "FeatureCollection",
    features: infrastructure.map((asset) => ({
      type: "Feature",
      id: asset.id,
      properties: { infrastructureId: asset.id, assetType: asset.type, source: asset.source_key, title: asset.name },
      geometry: { type: asset.geometry.type as "Point" | "Polygon" | "LineString", coordinates: asset.geometry.coordinates },
    })),
  };
}

function graticuleCollection(): MapCollection {
  const features: MapFeature[] = [];
  for (let longitude = -180; longitude <= 180; longitude += 10) {
    features.push({
      type: "Feature",
      properties: {},
      geometry: {
      type: "LineString",
      coordinates: [[longitude, -80], [longitude, 80]],
      },
    });
  }
  for (let latitude = -80; latitude <= 80; latitude += 10) {
    features.push({
      type: "Feature",
      properties: {},
      geometry: {
      type: "LineString",
      coordinates: [[-180, latitude], [180, latitude]],
      },
    });
  }
  return { type: "FeatureCollection", features };
}

function mapStyle(events: CanonicalEvent[], infrastructure: InfrastructureAsset[]) {
  const land: MapCollection = {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: { kind: "north-america" }, geometry: { type: "Polygon", coordinates: [[[-168, 72], [-151, 71], [-140, 62], [-131, 55], [-124, 49], [-117, 48], [-110, 49], [-104, 46], [-96, 49], [-87, 47], [-80, 45], [-67, 47], [-60, 54], [-62, 60], [-72, 62], [-80, 69], [-96, 72], [-115, 74], [-135, 75], [-152, 76], [-168, 72]]] } },
      { type: "Feature", properties: { kind: "central-america" }, geometry: { type: "Polygon", coordinates: [[[-117, 32], [-106, 28], [-97, 25], [-91, 18], [-86, 15], [-82, 11], [-86, 8], [-94, 15], [-101, 20], [-109, 24], [-117, 32]]] } },
      { type: "Feature", properties: { kind: "south-america" }, geometry: { type: "Polygon", coordinates: [[[-81, 12], [-70, 10], [-60, 4], [-50, -3], [-45, -15], [-49, -28], [-58, -40], [-69, -53], [-77, -50], [-79, -35], [-73, -19], [-81, 12]]] } },
    ],
  };
  return {
    version: 8,
    sources: { land: { type: "geojson", data: land }, graticule: { type: "geojson", data: graticuleCollection() }, events: { type: "geojson", data: eventCollection(events) }, infrastructure: { type: "geojson", data: infrastructureCollection(infrastructure) } },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#09111b" } },
      { id: "land-fill", type: "fill", source: "land", paint: { "fill-color": "#101e2a", "fill-opacity": 0.96 } },
      { id: "land-outline", type: "line", source: "land", paint: { "line-color": "#344b5f", "line-width": 1.2, "line-opacity": 0.9 } },
      { id: "graticule", type: "line", source: "graticule", paint: { "line-color": "#294052", "line-width": 0.7, "line-opacity": 0.42, "line-dasharray": [2, 5] } },
      { id: "event-polygons", type: "fill", source: "events", filter: ["all", ["==", ["geometry-type"], "Polygon"], ["==", ["get", "source"], "nws"]], paint: { "fill-color": ["match", ["get", "severity"], "critical", "#ef4444", "warning", "#ed6868", "advisory", "#f1ad38", "#22c7a8"], "fill-opacity": 0.16 } },
      { id: "event-polygon-outline", type: "line", source: "events", filter: ["all", ["==", ["geometry-type"], "Polygon"], ["==", ["get", "source"], "nws"]], paint: { "line-color": ["match", ["get", "severity"], "critical", "#ef4444", "warning", "#ed6868", "advisory", "#f1ad38", "#22c7a8"], "line-width": 1.8, "line-opacity": 0.9 } },
      { id: "event-point-halo", type: "circle", source: "events", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "usgs"]], paint: { "circle-radius": 10, "circle-color": "transparent", "circle-stroke-color": ["match", ["get", "severity"], "critical", "#ef4444", "warning", "#ed6868", "advisory", "#f1ad38", "#22c7a8"], "circle-stroke-width": 1.2, "circle-stroke-opacity": 0.48 } },
      { id: "event-points", type: "circle", source: "events", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "usgs"]], paint: { "circle-radius": 5, "circle-color": ["match", ["get", "severity"], "critical", "#ef4444", "warning", "#ed6868", "advisory", "#f1ad38", "#22c7a8"], "circle-stroke-color": "#09111b", "circle-stroke-width": 1.5 } },
      { id: "infrastructure-rail-lines", type: "line", source: "infrastructure", filter: ["==", ["get", "assetType"], "rail_corridor"], paint: { "line-color": "#6ab6ff", "line-width": 2.4, "line-opacity": 0.82, "line-dasharray": [1, 1.5] } },
      { id: "infrastructure-port-points", type: "circle", source: "infrastructure", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "assetType"], "port"]], paint: { "circle-radius": 6, "circle-color": "#f1ad38", "circle-stroke-color": "#15100a", "circle-stroke-width": 1.5 } },
      { id: "infrastructure-other-points", type: "circle", source: "infrastructure", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 5, "circle-color": "#a986f5", "circle-stroke-color": "#15101f", "circle-stroke-width": 1.5 } },
    ],
  };
}

export function MapSurface({ events, infrastructure, selectedEvent, selectedInfrastructure, onSelectEvent, onSelectInfrastructure }: MapSurfaceProps) {
  const points = useMemo(() => events.map((event) => ({ event, center: geometryCenter(event) })).filter((item): item is { event: CanonicalEvent; center: { longitude: number; latitude: number } } => item.center !== null), [events]);
  const infrastructurePoints = useMemo(() => infrastructure.map((asset) => ({ asset, center: infrastructureCenter(asset) })).filter((item): item is { asset: InfrastructureAsset; center: { longitude: number; latitude: number } } => item.center !== null), [infrastructure]);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const eventsRef = useRef(events);
  const infrastructureRef = useRef(infrastructure);
  const onSelectEventRef = useRef(onSelectEvent);
  const onSelectInfrastructureRef = useRef(onSelectInfrastructure);
  const [mapRuntime, setMapRuntime] = useState<"loading" | "ready" | "fallback">("loading");
  const [keyboardIndex, setKeyboardIndex] = useState(0);
  const [showNws, setShowNws] = useState(true);
  const [showUsgs, setShowUsgs] = useState(true);
  const [showPorts, setShowPorts] = useState(true);
  const [showRail, setShowRail] = useState(true);
  eventsRef.current = events;
  infrastructureRef.current = infrastructure;
  onSelectEventRef.current = onSelectEvent;
  onSelectInfrastructureRef.current = onSelectInfrastructure;

  useEffect(() => {
    let disposed = false;
    void import("maplibre-gl").then((maplibre) => {
      if (disposed || !mapContainerRef.current) return;
      try {
        maplibre.setWorkerUrl("/maplibre-gl-worker.mjs");
        const map = new maplibre.Map({
          container: mapContainerRef.current,
          style: mapStyle(eventsRef.current, infrastructureRef.current) as never,
          center: [-96, 38],
          zoom: 3.25,
          minZoom: 2,
          maxZoom: 9,
          attributionControl: false,
          renderWorldCopies: false,
        });
        mapRef.current = map;
        const selectFromFeature = (feature: { properties?: Record<string, unknown> } | undefined) => {
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
        map.on("load", () => {
          if (disposed) return;
          setMapRuntime("ready");
        });
        map.on("error", () => {
          if (!disposed) setMapRuntime("fallback");
        });
        map.on("click", "event-points", (event) => selectFromFeature(event.features?.[0]));
        map.on("click", "event-polygons", (event) => selectFromFeature(event.features?.[0]));
        map.on("click", "event-polygon-outline", (event) => selectFromFeature(event.features?.[0]));
        map.on("click", "infrastructure-port-points", (event) => selectFromFeature(event.features?.[0]));
        map.on("click", "infrastructure-rail-lines", (event) => selectFromFeature(event.features?.[0]));
        map.on("click", "infrastructure-other-points", (event) => selectFromFeature(event.features?.[0]));
        map.on("mouseenter", "event-points", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseenter", "event-polygons", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "event-points", () => { map.getCanvas().style.cursor = ""; });
        map.on("mouseleave", "event-polygons", () => { map.getCanvas().style.cursor = ""; });
        map.on("mouseenter", "infrastructure-port-points", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseenter", "infrastructure-rail-lines", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "infrastructure-port-points", () => { map.getCanvas().style.cursor = ""; });
        map.on("mouseleave", "infrastructure-rail-lines", () => { map.getCanvas().style.cursor = ""; });
      } catch {
        if (!disposed) setMapRuntime("fallback");
      }
    }).catch(() => {
      if (!disposed) setMapRuntime("fallback");
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
  }, [events]);

  useEffect(() => {
    const source = mapRef.current?.getSource("infrastructure") as import("maplibre-gl").GeoJSONSource | undefined;
    source?.setData(infrastructureCollection(infrastructure) as never);
  }, [infrastructure]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || mapRuntime !== "ready") return;
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    ["event-polygons", "event-polygon-outline"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showNws)));
    ["event-points", "event-point-halo"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showUsgs)));
    map.setLayoutProperty("infrastructure-port-points", "visibility", visibility(showPorts));
    map.setLayoutProperty("infrastructure-rail-lines", "visibility", visibility(showRail));
  }, [mapRuntime, showNws, showUsgs, showPorts, showRail]);

  const handleMapKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    const selectable = [
      ...events.filter((item) => geometryCenter(item) !== null).map((item) => ({ kind: "event" as const, item })),
      ...infrastructure.filter((item) => infrastructureCenter(item) !== null).map((item) => ({ kind: "infrastructure" as const, item })),
    ];
    if (!selectable.length) return;
    if (event.key !== "ArrowRight" && event.key !== "ArrowDown" && event.key !== "ArrowLeft" && event.key !== "ArrowUp" && event.key !== "Enter") return;
    event.preventDefault();
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown" ? (keyboardIndex + 1) % selectable.length : event.key === "ArrowLeft" || event.key === "ArrowUp" ? (keyboardIndex - 1 + selectable.length) % selectable.length : keyboardIndex;
    setKeyboardIndex(nextIndex);
    if (event.key === "Enter" || event.key === "ArrowRight" || event.key === "ArrowDown" || event.key === "ArrowLeft" || event.key === "ArrowUp") {
      const selected = selectable[nextIndex];
      if (selected.kind === "event") onSelectEvent(selected.item);
      else onSelectInfrastructure(selected.item);
    }
  }, [events, infrastructure, keyboardIndex, onSelectEvent, onSelectInfrastructure]);

  return <section className="map-section" aria-label="Operational event and infrastructure map">
    <div className="map-toolbar"><div className="map-title"><MapIcon size={16} /><span>NORTH AMERICA / LIVE SITUATIONAL VIEW</span></div><div className="map-toolbar-right"><span className="map-coordinate">W 130° — W 60°</span><span className="map-zoom">+ <span>1.0×</span> −</span></div></div>
    <div className="map-canvas">
      <div ref={mapContainerRef} className={`maplibre-canvas ${mapRuntime === "ready" ? "maplibre-canvas-ready" : "maplibre-canvas-hidden"}`} role="application" aria-label="MapLibre operational event map. Focus this map and use arrow keys to select events." tabIndex={0} onKeyDown={handleMapKeyDown} />
      <svg className={`map-svg ${mapRuntime === "fallback" ? "map-svg-visible" : "map-svg-hidden"}`} viewBox="0 0 1000 600" role="img" aria-label="Dark geographic map with event overlays">
        <defs><pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse"><path d="M50 0H0V50" fill="none" stroke="#1f2b3a" strokeWidth="0.7" /></pattern><radialGradient id="map-glow" cx="50%" cy="40%"><stop offset="0" stopColor="#172b40" stopOpacity="0.5" /><stop offset="1" stopColor="#09101b" stopOpacity="0" /></radialGradient></defs>
        <rect width="1000" height="600" fill="#0a111b" /><rect width="1000" height="600" fill="url(#grid)" opacity="0.55" /><ellipse cx="500" cy="280" rx="470" ry="310" fill="url(#map-glow)" />
        <path d="M102 202 124 157 176 127 212 98 279 78 329 88 378 61 422 76 472 71 509 95 556 92 592 112 631 107 670 126 701 120 737 149 775 156 791 179 847 190 871 218 848 248 819 249 801 277 766 275 743 306 720 303 705 329 663 325 644 347 599 337 565 353 537 342 508 354 470 344 439 368 398 358 365 374 330 355 298 358 270 337 236 334 216 309 181 307 166 276 127 267Z" fill="#101e2a" stroke="#33495d" strokeWidth="1.2" opacity="0.95" />
        <path d="M679 388 706 377 749 391 778 412 801 447 838 462 861 494 888 500 913 538 898 568 861 565 836 545 811 537 790 516 754 514 728 488 697 484 675 454 651 441Z" fill="#101e2a" stroke="#33495d" strokeWidth="1.2" opacity="0.95" />
        <path d="M477 355 499 375 514 410 544 422 565 455 594 466 610 500 629 525 613 555 580 547 561 519 524 503 499 480 471 466 448 438 426 405Z" fill="#101e2a" stroke="#33495d" strokeWidth="1.2" opacity="0.95" />
        <path d="M0 420h1000M0 300h1000M0 180h1000M140 0v600M350 0v600M560 0v600M770 0v600" stroke="#294052" strokeWidth="0.7" strokeDasharray="3 8" opacity="0.45" />
        <text x="85" y="184" className="map-label">PACIFIC NORTHWEST</text><text x="450" y="150" className="map-label">GREAT LAKES</text><text x="695" y="283" className="map-label">NORTHEAST</text><text x="418" y="527" className="map-label">GULF OF MEXICO</text>
        {events.filter((event) => event.geometry?.type === "Polygon" && (event.source_key === "nws" ? showNws : showUsgs)).map((event) => <polygon key={`poly-${event.id}`} points={polygonPoints(event)} className={`event-polygon severity-fill-${event.severity} ${selectedEvent?.id === event.id ? "event-polygon-selected" : ""}`} onClick={() => onSelectEvent(event)} />)}
        {points.filter(({ event }) => event.source_key === "nws" ? showNws : showUsgs).map(({ event, center }) => { const point = project(center.longitude, center.latitude); const selected = selectedEvent?.id === event.id; return <g key={event.id} className={`event-marker marker-${event.severity} ${selected ? "event-marker-selected" : ""}`} transform={`translate(${point.x} ${point.y})`} onClick={() => onSelectEvent(event)} role="button" aria-label={`Select ${event.title}`} tabIndex={0} onKeyDown={(keyboardEvent) => { if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") onSelectEvent(event); }}><circle r={selected ? 14 : 10} className="marker-halo" /><circle r={selected ? 6 : 4.5} className="marker-core" /><circle r="2" className="marker-glint" /></g>; })}
        {infrastructure.filter((asset) => asset.type === "rail_corridor" ? showRail : showPorts).filter((asset) => asset.geometry.type === "LineString").map((asset) => <polyline key={`infra-line-${asset.id}`} points={infrastructureLinePoints(asset)} className={`infrastructure-rail ${selectedInfrastructure?.id === asset.id ? "infrastructure-selected" : ""}`} onClick={() => onSelectInfrastructure(asset)} role="button" aria-label={`Select ${asset.name}`} />)}
        {infrastructurePoints.filter(({ asset }) => asset.geometry.type !== "LineString" && (asset.type === "port" ? showPorts : showRail)).map(({ asset, center }) => { const point = project(center.longitude, center.latitude); const selected = selectedInfrastructure?.id === asset.id; return <g key={`infra-point-${asset.id}`} className={`infrastructure-marker infrastructure-${asset.type} ${selected ? "infrastructure-selected" : ""}`} transform={`translate(${point.x} ${point.y})`} onClick={() => onSelectInfrastructure(asset)} role="button" aria-label={`Select ${asset.name}`} tabIndex={0} onKeyDown={(keyboardEvent) => { if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") onSelectInfrastructure(asset); }}><circle r={selected ? 9 : 6} className="infrastructure-marker-core" /></g>; })}
      </svg>
      {mapRuntime === "ready" && <div className="maplibre-zoom-controls" aria-label="Map controls"><button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label="Zoom in">+</button><button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label="Zoom out">−</button><button type="button" onClick={() => mapRef.current?.flyTo({ center: [-96, 38], zoom: 3.25 })} aria-label="Reset map view">⌾</button></div>}
      <div className="map-fallback-note"><span className={`fallback-dot fallback-dot-${mapRuntime}`} /><span>{mapRuntime === "ready" ? "MAP RUNTIME / MAPLIBRE GL JS" : mapRuntime === "fallback" ? "MAP RUNTIME / SVG FALLBACK" : "MAP RUNTIME / INITIALIZING"}</span><span className="fallback-detail">{mapRuntime === "ready" ? "Self-contained vector style · no token required" : mapRuntime === "fallback" ? "MapLibre initialization unavailable" : "Loading self-contained vector style"}</span></div>
      <div className="map-layer-rail"><div className="rail-label">LIVE EVENT DATA</div><button className={`layer-control ${showNws ? "layer-active" : ""}`} type="button" onClick={() => setShowNws((value) => !value)} aria-pressed={showNws}><span className="layer-swatch layer-swatch-alert" /><span>NWS ALERTS</span><strong>{events.filter((event) => event.source_key === "nws").length.toString().padStart(2, "0")}</strong></button><button className={`layer-control ${showUsgs ? "layer-active" : ""}`} type="button" onClick={() => setShowUsgs((value) => !value)} aria-pressed={showUsgs}><span className="layer-swatch layer-swatch-quake" /><span>USGS QUAKES</span><strong>{events.filter((event) => event.source_key === "usgs").length.toString().padStart(2, "0")}</strong></button><div className="rail-label rail-label-reference">INFRASTRUCTURE REFERENCE DATA</div><button className={`layer-control ${showPorts ? "layer-active" : ""}`} type="button" onClick={() => setShowPorts((value) => !value)} aria-pressed={showPorts}><span className="layer-swatch layer-swatch-port" /><span>PORT FACILITIES</span><strong>{infrastructure.filter((asset) => asset.type === "port").length.toString().padStart(2, "0")}</strong></button><button className={`layer-control ${showRail ? "layer-active" : ""}`} type="button" onClick={() => setShowRail((value) => !value)} aria-pressed={showRail}><span className="layer-swatch layer-swatch-rail" /><span>RAIL CORRIDORS</span><strong>{infrastructure.filter((asset) => asset.type === "rail_corridor").length.toString().padStart(2, "0")}</strong></button><button className="layer-control" type="button" disabled><span className="layer-swatch layer-swatch-future" /><span>POWER GRID / FUTURE</span><strong>—</strong></button></div>
      <div className="map-legend"><span><span className="legend-dot legend-warning" /> WARNING</span><span><span className="legend-dot legend-advisory" /> ADVISORY</span><span><span className="legend-dot legend-info" /> INFO</span></div>
      <div className="map-scale"><span>0</span><span className="scale-line" /><span>500 km</span></div>
    </div>
    <div className="map-foot"><span><span className="foot-icon"><AlertIcon size={14} /></span> WEATHER OVERLAYS</span><span><span className="foot-icon"><QuakeIcon size={14} /></span> SEISMIC OBSERVATIONS</span><span className="map-foot-note"><SeverityDot severity="info" /> Reference assets are source-provided · no impact assessment is implied</span></div>
  </section>;
}
