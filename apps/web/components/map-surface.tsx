"use client";

import { useMemo } from "react";
import type { CanonicalEvent } from "../lib/types";
import { AlertIcon, MapIcon, QuakeIcon } from "./icons";
import { SeverityDot } from "./status-pill";

type MapSurfaceProps = {
  events: CanonicalEvent[];
  selectedEvent: CanonicalEvent | null;
  onSelect: (event: CanonicalEvent) => void;
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

export function MapSurface({ events, selectedEvent, onSelect }: MapSurfaceProps) {
  const points = useMemo(() => events.map((event) => ({ event, center: geometryCenter(event) })).filter((item): item is { event: CanonicalEvent; center: { longitude: number; latitude: number } } => item.center !== null), [events]);
  return <section className="map-section" aria-label="Operational event map">
    <div className="map-toolbar"><div className="map-title"><MapIcon size={16} /><span>NORTH AMERICA / LIVE SITUATIONAL VIEW</span></div><div className="map-toolbar-right"><span className="map-coordinate">W 130° — W 60°</span><span className="map-zoom">+ <span>1.0×</span> −</span></div></div>
    <div className="map-canvas">
      <svg className="map-svg" viewBox="0 0 1000 600" role="img" aria-label="Dark geographic map with event overlays">
        <defs><pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse"><path d="M50 0H0V50" fill="none" stroke="#1f2b3a" strokeWidth="0.7" /></pattern><radialGradient id="map-glow" cx="50%" cy="40%"><stop offset="0" stopColor="#172b40" stopOpacity="0.5" /><stop offset="1" stopColor="#09101b" stopOpacity="0" /></radialGradient></defs>
        <rect width="1000" height="600" fill="#0a111b" /><rect width="1000" height="600" fill="url(#grid)" opacity="0.55" /><ellipse cx="500" cy="280" rx="470" ry="310" fill="url(#map-glow)" />
        <path d="M102 202 124 157 176 127 212 98 279 78 329 88 378 61 422 76 472 71 509 95 556 92 592 112 631 107 670 126 701 120 737 149 775 156 791 179 847 190 871 218 848 248 819 249 801 277 766 275 743 306 720 303 705 329 663 325 644 347 599 337 565 353 537 342 508 354 470 344 439 368 398 358 365 374 330 355 298 358 270 337 236 334 216 309 181 307 166 276 127 267Z" fill="#101e2a" stroke="#33495d" strokeWidth="1.2" opacity="0.95" />
        <path d="M679 388 706 377 749 391 778 412 801 447 838 462 861 494 888 500 913 538 898 568 861 565 836 545 811 537 790 516 754 514 728 488 697 484 675 454 651 441Z" fill="#101e2a" stroke="#33495d" strokeWidth="1.2" opacity="0.95" />
        <path d="M477 355 499 375 514 410 544 422 565 455 594 466 610 500 629 525 613 555 580 547 561 519 524 503 499 480 471 466 448 438 426 405Z" fill="#101e2a" stroke="#33495d" strokeWidth="1.2" opacity="0.95" />
        <path d="M0 420h1000M0 300h1000M0 180h1000M140 0v600M350 0v600M560 0v600M770 0v600" stroke="#294052" strokeWidth="0.7" strokeDasharray="3 8" opacity="0.45" />
        <text x="85" y="184" className="map-label">PACIFIC NORTHWEST</text><text x="450" y="150" className="map-label">GREAT LAKES</text><text x="695" y="283" className="map-label">NORTHEAST</text><text x="418" y="527" className="map-label">GULF OF MEXICO</text>
        {events.filter((event) => event.geometry?.type === "Polygon").map((event) => <polygon key={`poly-${event.id}`} points={polygonPoints(event)} className={`event-polygon severity-fill-${event.severity} ${selectedEvent?.id === event.id ? "event-polygon-selected" : ""}`} onClick={() => onSelect(event)} />)}
        {points.map(({ event, center }) => { const point = project(center.longitude, center.latitude); const selected = selectedEvent?.id === event.id; return <g key={event.id} className={`event-marker marker-${event.severity} ${selected ? "event-marker-selected" : ""}`} transform={`translate(${point.x} ${point.y})`} onClick={() => onSelect(event)} role="button" aria-label={`Select ${event.title}`} tabIndex={0} onKeyDown={(keyboardEvent) => { if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") onSelect(event); }}><circle r={selected ? 14 : 10} className="marker-halo" /><circle r={selected ? 6 : 4.5} className="marker-core" /><circle r="2" className="marker-glint" /></g>; })}
      </svg>
      <div className="map-fallback-note"><span className="fallback-dot" /><span>MAP RUNTIME / SVG FALLBACK</span><span className="fallback-detail">MapLibre style URL not configured</span></div>
      <div className="map-layer-rail"><div className="rail-label">LAYERS</div><button className="layer-control layer-active" type="button"><span className="layer-swatch layer-swatch-alert" /><span>NWS ALERTS</span><strong>{events.filter((event) => event.source_key === "nws").length.toString().padStart(2, "0")}</strong></button><button className="layer-control layer-active" type="button"><span className="layer-swatch layer-swatch-quake" /><span>USGS QUAKES</span><strong>{events.filter((event) => event.source_key === "usgs").length.toString().padStart(2, "0")}</strong></button><button className="layer-control" type="button" disabled><span className="layer-swatch layer-swatch-future" /><span>POWER GRID</span><strong>—</strong></button><button className="layer-control" type="button" disabled><span className="layer-swatch layer-swatch-future" /><span>TRANSPORT</span><strong>—</strong></button></div>
      <div className="map-legend"><span><span className="legend-dot legend-warning" /> WARNING</span><span><span className="legend-dot legend-advisory" /> ADVISORY</span><span><span className="legend-dot legend-info" /> INFO</span></div>
      <div className="map-scale"><span>0</span><span className="scale-line" /><span>500 km</span></div>
    </div>
    <div className="map-foot"><span><span className="foot-icon"><AlertIcon size={14} /></span> WEATHER OVERLAYS</span><span><span className="foot-icon"><QuakeIcon size={14} /></span> SEISMIC OBSERVATIONS</span><span className="map-foot-note"><SeverityDot severity="info" /> Geometry is source-provided · positions are not impact assessments</span></div>
  </section>;
}
