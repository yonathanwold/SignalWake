"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { CanonicalEvent, InfrastructureAsset, LayerCatalogItem, MapLayerData, RainViewerMetadata } from "../lib/types";
import { AlertIcon, ChevronIcon, MapIcon, QuakeIcon } from "./icons";
import { SeverityDot } from "./status-pill";

type MapSurfaceProps = {
  events: CanonicalEvent[];
  infrastructure: InfrastructureAsset[];
  layers?: LayerCatalogItem[];
  overlays?: Record<string, MapLayerData>;
  radar?: RainViewerMetadata | null;
  windowLabel?: string;
  selectedEvent: CanonicalEvent | null;
  selectedInfrastructure: InfrastructureAsset | null;
  onSelectEvent: (event: CanonicalEvent) => void;
  onSelectInfrastructure: (asset: InfrastructureAsset) => void;
};

const INITIAL_CENTER: [number, number] = [-98.5795, 39.8283];
const INITIAL_ZOOM = 4;
const BASEMAP_SOURCE_ID = "basemap";
const CARTO_DARK_TILES = [
  "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
];
type BasemapProvider = {
  id: "carto" | "osm";
  label: string;
  tiles: string[];
  attribution: string;
};

const BASEMAP_PROVIDERS: BasemapProvider[] = [
  {
    id: "carto",
    label: "CARTO DARK OSM",
    tiles: CARTO_DARK_TILES,
    attribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a> <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">© CARTO</a>',
  },
  {
    id: "osm",
    label: "OPENSTREETMAP STANDARD",
    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
    attribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>',
  },
];
const BASEMAP_LOAD_TIMEOUT_MS = 8000;

const ACTIVE_EVENT_LAYER_KEYS = new Set(["nws_alerts", "nws_observations", "usgs_earthquakes", "usgs_water", "nhc_systems", "noaa_coops", "nasa_firms", "airnow", "nasa_eonet", "aviation_weather", "fema_declarations", "road511"]);
const ACTIVE_LAYER_STATUSES = new Set(["LIVE", "NEAR_REAL_TIME", "DEGRADED"]);
const SOURCE_POINT_STYLES: Record<string, { color: string; halo: string; radius: number }> = {
  nws_observations: { color: "#6ab6ff", halo: "#6ab6ff", radius: 4 },
  usgs_water: { color: "#4b8fff", halo: "#4b8fff", radius: 4 },
  nhc: { color: "#ed6868", halo: "#ed6868", radius: 6 },
  noaa_coops: { color: "#22c7a8", halo: "#22c7a8", radius: 5 },
  nasa_firms: { color: "#f1ad38", halo: "#f1ad38", radius: 5 },
  airnow: { color: "#a986f5", halo: "#a986f5", radius: 4 },
  nasa_eonet: { color: "#bf84f3", halo: "#bf84f3", radius: 5 },
  aviation_weather: { color: "#f1ad38", halo: "#f1ad38", radius: 4 },
  fema_declarations: { color: "#ed6868", halo: "#ed6868", radius: 5 },
  road511: { color: "#f59e0b", halo: "#f59e0b", radius: 5 },
};

function isActiveEventLayer(item: LayerCatalogItem) {
  return Boolean(item.source_key && ACTIVE_EVENT_LAYER_KEYS.has(item.key) && ACTIVE_LAYER_STATUSES.has(item.status));
}

function activeSourceKeys(catalog: LayerCatalogItem[]) {
  const knownRows = catalog.filter((item) => ACTIVE_EVENT_LAYER_KEYS.has(item.key));
  const catalogRows = knownRows.filter(isActiveEventLayer);
  return knownRows.length > 0
    ? new Set(catalogRows.map((item) => item.source_key as string))
    : new Set(["nws", "usgs"]);
}

function visibleEvents(events: CanonicalEvent[], catalog: LayerCatalogItem[]) {
  const sources = activeSourceKeys(catalog);
  return events.filter((event) => sources.has(event.source_key));
}

type MapGeometry = { type: string; coordinates: unknown };
type MapFeature = {
  type: "Feature";
  id?: string;
  properties: Record<string, unknown>;
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
        type: event.type,
        magnitude: event.magnitude ?? null,
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

function overlayCollection(overlays: Record<string, MapLayerData>, key: string): MapCollection {
  const body = overlays[key];
  if (!body) return { type: "FeatureCollection", features: [] };
  return {
    type: "FeatureCollection",
    features: body.features.flatMap((feature) => {
      if (!feature.geometry || typeof feature.geometry.type !== "string") return [];
      return [{
        type: "Feature" as const,
        id: feature.id,
        properties: { ...feature.properties, source: key, title: String(feature.properties?.name ?? feature.properties?.model ?? feature.properties?.callsign ?? feature.properties?.icao24 ?? key), classification: feature.properties?.classification ?? (key === "open_meteo" ? "MODEL_FIELD" : key === "opensky" ? "OBSERVATION" : "REFERENCE") },
        geometry: feature.geometry,
      }];
    }),
  };
}

function mapStyle(events: CanonicalEvent[], infrastructure: InfrastructureAsset[], catalog: LayerCatalogItem[] = [], overlays: Record<string, MapLayerData> = {}, radar: RainViewerMetadata | null = null, provider: BasemapProvider = BASEMAP_PROVIDERS[0]) {
  const severityColor = ["match", ["get", "severity"], "critical", "#ef4444", "warning", "#ed6868", "advisory", "#f1ad38", "watch", "#f1ad38", "#22c7a8"];
  const polygonGeometry = ["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false];
  const earthquakeRadius = ["interpolate", ["linear"], ["coalesce", ["get", "magnitude"], 0], 0, 4, 4, 6, 5, 9, 6, 13];
  const earthquakeHaloRadius = ["interpolate", ["linear"], ["coalesce", ["get", "magnitude"], 0], 0, 8, 4, 12, 5, 18, 6, 25];
  const activeSources = activeSourceKeys(catalog);
  const mapEvents = events.filter((event) => activeSources.has(event.source_key));
  const sourceKeys = Array.from(new Set(mapEvents.map((event) => event.source_key))).filter((source) => source !== "nws" && source !== "usgs");
  const dynamicEventLayers = sourceKeys.flatMap((source) => {
    const safeSource = source.replace(/[^a-z0-9_-]/gi, "-");
    const filter = ["all", ["==", ["get", "source"], source]];
    const pointStyle = SOURCE_POINT_STYLES[source] ?? { color: "#22c7a8", halo: "#22c7a8", radius: 5 };
    return [
      { id: `event-${safeSource}-polygons`, type: "fill", source: "events", filter: [...filter, polygonGeometry], paint: { "fill-color": severityColor, "fill-opacity": 0.18 } },
      { id: `event-${safeSource}-polygon-outline`, type: "line", source: "events", filter: [...filter, polygonGeometry], paint: { "line-color": severityColor, "line-width": 2, "line-opacity": 0.9 } },
      { id: `event-${safeSource}-point-halo`, type: "circle", source: "event-points", filter: [...filter, ["==", ["geometry-type"], "Point"], ["!", ["has", "point_count"]]], paint: { "circle-radius": pointStyle.radius + 5, "circle-color": "transparent", "circle-stroke-color": pointStyle.halo, "circle-stroke-width": 1.2, "circle-stroke-opacity": 0.38 } },
      { id: `event-${safeSource}-point-ring`, type: "circle", source: "event-points", filter: [...filter, ["==", ["geometry-type"], "Point"], ["!", ["has", "point_count"]]], paint: { "circle-radius": pointStyle.radius + 2.5, "circle-color": "#09111b", "circle-stroke-color": pointStyle.color, "circle-stroke-width": 1.8, "circle-stroke-opacity": 0.95 } },
      { id: `event-${safeSource}-points`, type: "circle", source: "event-points", filter: [...filter, ["==", ["geometry-type"], "Point"], ["!", ["has", "point_count"]]], paint: { "circle-radius": pointStyle.radius, "circle-color": "#09111b", "circle-stroke-color": pointStyle.color, "circle-stroke-width": 1.2 } },
      { id: `event-${safeSource}-point-core`, type: "circle", source: "event-points", filter: [...filter, ["==", ["geometry-type"], "Point"], ["!", ["has", "point_count"]]], paint: { "circle-radius": Math.max(1.6, pointStyle.radius * 0.34), "circle-color": pointStyle.color, "circle-stroke-color": "#09111b", "circle-stroke-width": 0.8 } },
    ];
  });
  const sources: Record<string, unknown> = {
    [BASEMAP_SOURCE_ID]: {
      type: "raster",
      tiles: provider.tiles,
      tileSize: 256,
      attribution: provider.attribution,
    },
    events: { type: "geojson", data: eventCollection(mapEvents) },
    "event-points": { type: "geojson", data: eventPointCollection(mapEvents), cluster: true, clusterRadius: 42, clusterMaxZoom: 5 },
    infrastructure: { type: "geojson", data: infrastructureCollection(infrastructure) },
    "open-meteo": { type: "geojson", data: overlayCollection(overlays, "open_meteo") },
    opensky: { type: "geojson", data: overlayCollection(overlays, "opensky"), cluster: true, clusterRadius: 34, clusterMaxZoom: 7 },
    nppes: { type: "geojson", data: overlayCollection(overlays, "nppes") },
    census: { type: "geojson", data: overlayCollection(overlays, "census") },
  };
  const overlayLayers: unknown[] = [
    { id: "opensky-clusters", type: "circle", source: "opensky", filter: ["has", "point_count"], paint: { "circle-radius": ["step", ["get", "point_count"], 12, 25, 16, 100, 21], "circle-color": "#06131d", "circle-stroke-color": "#17c993", "circle-stroke-width": 1.7, "circle-opacity": 0.92 } },
    { id: "opensky-points", type: "circle", source: "opensky", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 2.5, 5, 3.5, 9, 5], "circle-color": "#17c993", "circle-opacity": 0.78, "circle-stroke-color": "#b8ffe8", "circle-stroke-width": 0.7 } },
    { id: "census-state-fill", type: "fill", source: "census", filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "MultiPolygon"]], paint: { "fill-color": "#8b5cf6", "fill-opacity": 0.035 } },
    { id: "census-state-outline", type: "line", source: "census", filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "MultiPolygon"]], paint: { "line-color": "#8b5cf6", "line-width": 0.8, "line-opacity": 0.38 } },
    { id: "open-meteo-field-halo", type: "circle", source: "open-meteo", paint: { "circle-radius": 18, "circle-color": "#38bdf8", "circle-opacity": 0.12, "circle-stroke-color": "#38bdf8", "circle-stroke-width": 1 } },
    { id: "open-meteo-field-core", type: "circle", source: "open-meteo", paint: { "circle-radius": 6, "circle-color": "#38bdf8", "circle-opacity": 0.42, "circle-stroke-color": "#bae6fd", "circle-stroke-width": 1 } },
    { id: "nppes-provider-ring", type: "circle", source: "nppes", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 5, "circle-color": "#09111b", "circle-stroke-color": "#a986f5", "circle-stroke-width": 1.4, "circle-opacity": 0.94 } },
  ];
  if (radar?.tile_url_template) {
    sources.rainviewer = { type: "raster", tiles: [radar.tile_url_template], tileSize: 256, attribution: radar.attribution ?? "RainViewer" };
    overlayLayers.unshift({ id: "rainviewer-radar", type: "raster", source: "rainviewer", paint: { "raster-opacity": 0.38, "raster-fade-duration": 0 } });
  }
  return {
    version: 8,
    sources,
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#09111b" } },
      { id: "basemap", type: "raster", source: BASEMAP_SOURCE_ID, paint: { "raster-opacity": 1 } },
      ...overlayLayers,
      { id: "event-polygons", type: "fill", source: "events", filter: ["all", ["==", ["get", "source"], "nws"], polygonGeometry], paint: { "fill-color": severityColor, "fill-opacity": 0.2 } },
      { id: "event-polygon-outline", type: "line", source: "events", filter: ["all", ["==", ["get", "source"], "nws"], polygonGeometry], paint: { "line-color": severityColor, "line-width": 2, "line-opacity": 0.95 } },
      { id: "event-clusters", type: "circle", source: "event-points", filter: ["has", "point_count"], paint: { "circle-radius": ["step", ["get", "point_count"], 14, 25, 18, 100, 23], "circle-color": "#09111b", "circle-stroke-color": "#22c7a8", "circle-stroke-width": ["step", ["get", "point_count"], 2, 25, 2.5, 100, 3.2], "circle-stroke-opacity": 0.96, "circle-opacity": 0.98 } },
      { id: "event-nws-point-halo", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "nws"], ["!", ["has", "point_count"]]], paint: { "circle-radius": ["match", ["get", "severity"], "critical", 14, "warning", 12, "advisory", 10, 8], "circle-color": "transparent", "circle-stroke-color": severityColor, "circle-stroke-width": 1.4, "circle-stroke-opacity": 0.65 } },
      { id: "event-nws-points", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "nws"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 5.5, "circle-color": "#09111b", "circle-stroke-color": severityColor, "circle-stroke-width": 1.8 } },
      { id: "event-nws-point-core", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "nws"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 2, "circle-color": severityColor, "circle-stroke-color": "#09111b", "circle-stroke-width": 0.8 } },
      { id: "event-usgs-point-halo", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "usgs"], ["!", ["has", "point_count"]]], paint: { "circle-radius": earthquakeHaloRadius, "circle-color": "transparent", "circle-stroke-color": "#6ab6ff", "circle-stroke-width": 1.4, "circle-stroke-opacity": 0.68 } },
      { id: "event-usgs-points", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "usgs"], ["!", ["has", "point_count"]]], paint: { "circle-radius": earthquakeRadius, "circle-color": "#09111b", "circle-stroke-color": "#6ab6ff", "circle-stroke-width": 1.9 } },
      { id: "event-usgs-point-core", type: "circle", source: "event-points", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "source"], "usgs"], ["!", ["has", "point_count"]]], paint: { "circle-radius": 2.2, "circle-color": "#6ab6ff", "circle-stroke-color": "#09111b", "circle-stroke-width": 0.8 } },
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

export function MapSurface({ events, infrastructure, layers = [], overlays = {}, radar = null, windowLabel = "PAST 48H / UTC", selectedEvent, selectedInfrastructure, onSelectEvent, onSelectInfrastructure }: MapSurfaceProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const eventsRef = useRef(events);
  const infrastructureRef = useRef(infrastructure);
  const layersRef = useRef(layers);
  const overlaysRef = useRef(overlays);
  const radarRef = useRef(radar);
  const onSelectEventRef = useRef(onSelectEvent);
  const onSelectInfrastructureRef = useRef(onSelectInfrastructure);
  const [mapRuntime, setMapRuntime] = useState<"loading" | "ready" | "error">("loading");
  const [activeProviderIndex, setActiveProviderIndex] = useState(0);
  const providerIndexRef = useRef(0);
  const [mapTooltip, setMapTooltip] = useState<MapTooltip | null>(null);
  const [viewState, setViewState] = useState<MapViewState>({ longitude: INITIAL_CENTER[0], latitude: INITIAL_CENTER[1], zoom: INITIAL_ZOOM });
  const [keyboardIndex, setKeyboardIndex] = useState(0);
  const [showNws, setShowNws] = useState(true);
  const [showUsgs, setShowUsgs] = useState(true);
  const [showPorts, setShowPorts] = useState(true);
  const [showRail, setShowRail] = useState(true);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [hiddenLayers, setHiddenLayers] = useState<Record<string, boolean>>({});
  const selectedLabel = selectedEvent?.title ?? selectedInfrastructure?.name ?? "none";
  eventsRef.current = events;
  infrastructureRef.current = infrastructure;
  layersRef.current = layers;
  overlaysRef.current = overlays;
  radarRef.current = radar;
  onSelectEventRef.current = onSelectEvent;
  onSelectInfrastructureRef.current = onSelectInfrastructure;

  useEffect(() => {
    let disposed = false;
    let switchingBasemap = false;
    let basemapWatchdog: ReturnType<typeof setTimeout> | null = null;
    void import("maplibre-gl").then((maplibre) => {
      if (disposed || !mapContainerRef.current) return;
      try {
        maplibre.setWorkerUrl("/maplibre-gl-worker.mjs");
        const map = new maplibre.Map({
          container: mapContainerRef.current,
          style: mapStyle(eventsRef.current, infrastructureRef.current, layersRef.current, overlaysRef.current, radarRef.current, BASEMAP_PROVIDERS[providerIndexRef.current]) as never,
          center: INITIAL_CENTER,
          zoom: INITIAL_ZOOM,
          minZoom: 2,
          maxZoom: 12,
          attributionControl: { compact: false },
          renderWorldCopies: false,
        });
        mapRef.current = map;
        const clearBasemapWatchdog = () => {
          if (basemapWatchdog !== null) {
            clearTimeout(basemapWatchdog);
            basemapWatchdog = null;
          }
        };
        const markBasemapUnavailable = () => {
          clearBasemapWatchdog();
          switchingBasemap = false;
          if (!disposed) setMapRuntime("error");
        };
        const armBasemapWatchdog = () => {
          clearBasemapWatchdog();
          basemapWatchdog = setTimeout(() => {
            basemapWatchdog = null;
            if (disposed) return;
            // A provider that never reaches style.load has failed just as a
            // provider that emits a source error. Continue once, then report
            // the honest all-providers-failed state.
            switchingBasemap = false;
            if (providerIndexRef.current + 1 >= BASEMAP_PROVIDERS.length) {
              markBasemapUnavailable();
            } else {
              failoverBasemap();
            }
          }, BASEMAP_LOAD_TIMEOUT_MS);
        };
        const failoverBasemap = () => {
          if (disposed || switchingBasemap) return;
          const nextIndex = providerIndexRef.current + 1;
          if (nextIndex >= BASEMAP_PROVIDERS.length) {
            markBasemapUnavailable();
            return;
          }
          switchingBasemap = true;
          providerIndexRef.current = nextIndex;
          setActiveProviderIndex(nextIndex);
          setMapRuntime("loading");
          armBasemapWatchdog();
          try {
            map.setStyle(mapStyle(eventsRef.current, infrastructureRef.current, layersRef.current, overlaysRef.current, radarRef.current, BASEMAP_PROVIDERS[nextIndex]) as never);
          } catch {
            markBasemapUnavailable();
          }
        };
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
        const activeSources = activeSourceKeys(layersRef.current);
        const dynamicSources = Array.from(new Set([
          ...eventsRef.current.map((event) => event.source_key).filter((source) => activeSources.has(source)),
          ...activeSources,
        ])).filter((source) => source !== "nws" && source !== "usgs");
        const featureLayerIds = [
          "event-polygons",
          "event-polygon-outline",
          "event-nws-points",
          "event-nws-point-halo",
          "event-nws-point-core",
          "event-usgs-points",
          "event-usgs-point-halo",
          "event-usgs-point-core",
          "infrastructure-polygons",
          "infrastructure-port-points",
          "infrastructure-rail-lines",
          "infrastructure-other-points",
          "open-meteo-field-halo",
          "open-meteo-field-core",
          "nppes-provider-ring",
          "opensky-points",
          "opensky-clusters",
          "census-state-fill",
          "census-state-outline",
          ...dynamicSources.flatMap((source) => { const safeSource = source.replace(/[^a-z0-9_-]/gi, "-"); return [`event-${safeSource}-polygons`, `event-${safeSource}-polygon-outline`, `event-${safeSource}-point-halo`, `event-${safeSource}-point-ring`, `event-${safeSource}-points`, `event-${safeSource}-point-core`]; }),
        ];
        const markBasemapReady = () => {
          clearBasemapWatchdog();
          switchingBasemap = false;
          if (!disposed) setMapRuntime("ready");
        };
        map.on("load", markBasemapReady);
        // `load` is emitted only for the initial map. Provider failover uses
        // setStyle(), whose completion is reported by `style.load` instead.
        map.on("style.load", markBasemapReady);
        map.on("error", (event) => {
          const sourceId = (event as unknown as { sourceId?: string }).sourceId;
          // Undefined source errors before the style is loaded generally mean
          // the initial style/basemap could not start. Once the style is live,
          // only an explicit basemap source failure should trigger failover;
          // overlay errors must not hide an otherwise usable map.
          if (sourceId === BASEMAP_SOURCE_ID || (sourceId === undefined && !map.isStyleLoaded())) {
            failoverBasemap();
          }
        });
        armBasemapWatchdog();
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
        map.on("click", "opensky-clusters", (event) => {
          const feature = event.features?.[0] as { properties?: Record<string, unknown> } | undefined;
          const clusterId = feature?.properties?.cluster_id;
          if (typeof clusterId !== "number") return;
          const source = map.getSource("opensky") as unknown as { getClusterExpansionZoom?: (id: number, callback: (error: Error | null, zoom: number) => void) => void };
          source.getClusterExpansionZoom?.(clusterId, (error, zoom) => { if (!error) map.easeTo({ center: event.lngLat, zoom }); });
        });
        map.on("mouseenter", "opensky-clusters", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "opensky-clusters", () => { map.getCanvas().style.cursor = ""; });
        map.on("mouseenter", "opensky-points", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "opensky-points", () => { map.getCanvas().style.cursor = ""; });
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
      if (basemapWatchdog !== null) clearTimeout(basemapWatchdog);
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const source = mapRef.current?.getSource("events") as import("maplibre-gl").GeoJSONSource | undefined;
    const mapEvents = visibleEvents(events, layers);
    source?.setData(eventCollection(mapEvents) as never);
    const pointSource = mapRef.current?.getSource("event-points") as import("maplibre-gl").GeoJSONSource | undefined;
    pointSource?.setData(eventPointCollection(mapEvents) as never);
  }, [events, layers]);

  useEffect(() => {
    const source = mapRef.current?.getSource("opensky") as import("maplibre-gl").GeoJSONSource | undefined;
    source?.setData(overlayCollection(overlays, "opensky") as never);
  }, [overlays]);

  useEffect(() => {
    const source = mapRef.current?.getSource("infrastructure") as import("maplibre-gl").GeoJSONSource | undefined;
    source?.setData(infrastructureCollection(infrastructure) as never);
  }, [infrastructure]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || mapRuntime !== "ready") return;
    for (const key of ["open_meteo", "nppes", "census"]) {
      const source = map.getSource(key === "open_meteo" ? "open-meteo" : key) as import("maplibre-gl").GeoJSONSource | undefined;
      source?.setData(overlayCollection(overlays, key) as never);
    }
    if (radar?.tile_url_template && !map.getSource("rainviewer")) {
      map.addSource("rainviewer", { type: "raster", tiles: [radar.tile_url_template], tileSize: 256, attribution: radar.attribution ?? "RainViewer" });
      map.addLayer({ id: "rainviewer-radar", type: "raster", source: "rainviewer", paint: { "raster-opacity": 0.38, "raster-fade-duration": 0 } });
    }
  }, [mapRuntime, overlays, radar]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || mapRuntime !== "ready") return;
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    ["event-polygons", "event-polygon-outline", "event-nws-points", "event-nws-point-halo", "event-nws-point-core"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showNws)));
    ["event-usgs-points", "event-usgs-point-halo", "event-usgs-point-core"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showUsgs)));
    map.setLayoutProperty("event-clusters", "visibility", visibility(showNws && showUsgs && !Object.values(hiddenLayers).some(Boolean)));
    map.setLayoutProperty("infrastructure-polygons", "visibility", visibility(showPorts));
    map.setLayoutProperty("infrastructure-port-points", "visibility", visibility(showPorts));
    ["infrastructure-rail-lines", "infrastructure-other-points"].forEach((layer) => map.setLayoutProperty(layer, "visibility", visibility(showRail)));
    const showModel = !hiddenLayers.open_meteo;
    const showProviders = !hiddenLayers.nppes;
    const showCensus = !hiddenLayers.census;
    const showRadar = !hiddenLayers.rainviewer;
    const showOpenSky = !hiddenLayers.opensky;
    ["opensky-points", "opensky-clusters"].forEach((layer) => { if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", visibility(showOpenSky)); });
    ["open-meteo-field-halo", "open-meteo-field-core"].forEach((layer) => { if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", visibility(showModel)); });
    if (map.getLayer("nppes-provider-ring")) map.setLayoutProperty("nppes-provider-ring", "visibility", visibility(showProviders));
    ["census-state-fill", "census-state-outline"].forEach((layer) => { if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", visibility(showCensus)); });
    if (map.getLayer("rainviewer-radar")) map.setLayoutProperty("rainviewer-radar", "visibility", visibility(showRadar));
  }, [hiddenLayers, mapRuntime, showNws, showUsgs, showPorts, showRail, overlays, radar]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || mapRuntime !== "ready") return;
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    layers.filter(isActiveEventLayer).forEach((item) => {
      if (!item.source_key || item.source_key === "nws" || item.source_key === "usgs") return;
      const source = item.source_key.replace(/[^a-z0-9_-]/gi, "-");
      const visible = !hiddenLayers[item.key];
      [`event-${source}-polygons`, `event-${source}-polygon-outline`, `event-${source}-point-halo`, `event-${source}-point-ring`, `event-${source}-points`, `event-${source}-point-core`].forEach((layer) => {
        if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", visibility(visible));
      });
    });
  }, [hiddenLayers, layers, mapRuntime]);

  const activeLayers = layers.filter((item) => {
    if (!isActiveEventLayer(item)) return false;
    return (item.counts.accepted ?? 0) > 0 || events.some((event) => event.source_key === item.source_key);
  });
  const activeSources = activeSourceKeys(layers);
  const overlayCounts = { opensky: overlays.opensky?.map_addressable_count ?? overlays.opensky?.feature_count ?? 0, open_meteo: overlays.open_meteo?.feature_count ?? 0, nppes: overlays.nppes?.feature_count ?? 0, census: overlays.census?.feature_count ?? 0 };

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
      <div className={`map-runtime-note map-runtime-note-${mapRuntime}`} role={mapRuntime === "error" ? "status" : undefined}><span className={`fallback-dot fallback-dot-${mapRuntime}`} /><span>{mapRuntime === "ready" ? `MAP RUNTIME / ${BASEMAP_PROVIDERS[activeProviderIndex].label}` : mapRuntime === "error" ? "BASEMAP UNAVAILABLE" : `MAP RUNTIME / TRYING ${BASEMAP_PROVIDERS[activeProviderIndex].label}`}</span><span className="fallback-detail">{mapRuntime === "ready" ? `${BASEMAP_PROVIDERS[activeProviderIndex].label} · source geometry preserved` : mapRuntime === "error" ? "All real basemap providers failed; no synthetic geographic fallback is shown" : `Fetching ${BASEMAP_PROVIDERS[activeProviderIndex].label} tiles`}</span></div>
      <div className={`map-layer-rail ${railCollapsed ? "map-layer-rail-collapsed" : ""}`}>
        <button className="layer-rail-toggle" type="button" onClick={() => setRailCollapsed((value) => !value)} aria-expanded={!railCollapsed} aria-label={railCollapsed ? "Expand live map layers" : "Collapse live map layers"}><ChevronIcon size={13} /><span>{railCollapsed ? "LAYERS" : "HIDE LAYERS"}</span></button>
        {!railCollapsed && <div className="layer-rail-body"><div className="rail-label">LIVE EVENT DATA</div>{activeSources.has("nws") && <button className={`layer-control ${showNws ? "layer-active" : ""}`} type="button" onClick={() => setShowNws((value) => !value)} aria-pressed={showNws}><span className="layer-swatch layer-swatch-alert" /><span>NWS ALERTS</span><strong>{events.filter((event) => event.source_key === "nws").length.toString().padStart(2, "0")}</strong></button>}{activeSources.has("usgs") && <button className={`layer-control ${showUsgs ? "layer-active" : ""}`} type="button" onClick={() => setShowUsgs((value) => !value)} aria-pressed={showUsgs}><span className="layer-swatch layer-swatch-quake" /><span>USGS QUAKES</span><strong>{events.filter((event) => event.source_key === "usgs").length.toString().padStart(2, "0")}</strong></button>}{activeLayers.filter((item) => item.source_key !== "nws" && item.source_key !== "usgs").map((item) => { const source = item.source_key as string; const hasData = events.some((event) => event.source_key === source); const canToggle = hasData && ["LIVE", "NEAR_REAL_TIME", "DEGRADED"].includes(item.status); const count = item.counts.accepted ?? events.filter((event) => event.source_key === source).length; const pointStyle = SOURCE_POINT_STYLES[source]; return <button key={item.key} className={`layer-control ${!hiddenLayers[item.key] ? "layer-active" : ""}`} type="button" disabled={!canToggle} onClick={() => setHiddenLayers((current) => ({ ...current, [item.key]: !current[item.key] }))} aria-pressed={!hiddenLayers[item.key]}><span className="layer-swatch layer-swatch-source" style={{ background: pointStyle?.color ?? "#22c7a8" }} /><span>{item.name.toUpperCase()}</span><strong>{count.toString().padStart(2, "0")}</strong></button>; })}{overlayCounts.opensky > 0 && <button className={`layer-control ${!hiddenLayers.opensky ? "layer-active" : ""}`} type="button" onClick={() => setHiddenLayers((current) => ({ ...current, opensky: !current.opensky }))} aria-pressed={!hiddenLayers.opensky}><span className="layer-swatch" style={{ background: "#17c993" }} /><span>AIRCRAFT STATES</span><strong>{overlayCounts.opensky.toLocaleString()}</strong></button>}<div className="rail-label">MODEL AND REFERENCE OVERLAYS</div>{overlayCounts.open_meteo > 0 && <button className={`layer-control ${!hiddenLayers.open_meteo ? "layer-active" : ""}`} type="button" onClick={() => setHiddenLayers((current) => ({ ...current, open_meteo: !current.open_meteo }))} aria-pressed={!hiddenLayers.open_meteo}><span className="layer-swatch" style={{ background: "#38bdf8" }} /><span>OPEN-METEO MODEL</span><strong>{overlayCounts.open_meteo.toString().padStart(2, "0")}</strong></button>}{overlayCounts.nppes > 0 && <button className={`layer-control ${!hiddenLayers.nppes ? "layer-active" : ""}`} type="button" onClick={() => setHiddenLayers((current) => ({ ...current, nppes: !current.nppes }))} aria-pressed={!hiddenLayers.nppes}><span className="layer-swatch" style={{ background: "#a986f5" }} /><span>NPPES PROVIDERS</span><strong>{overlayCounts.nppes.toString().padStart(2, "0")}</strong></button>}{overlayCounts.census > 0 && <button className={`layer-control ${!hiddenLayers.census ? "layer-active" : ""}`} type="button" onClick={() => setHiddenLayers((current) => ({ ...current, census: !current.census }))} aria-pressed={!hiddenLayers.census}><span className="layer-swatch" style={{ background: "#8b5cf6" }} /><span>CENSUS STATES</span><strong>{overlayCounts.census.toString().padStart(2, "0")}</strong></button>}{radar?.tile_url_template && <button className={`layer-control ${!hiddenLayers.rainviewer ? "layer-active" : ""}`} type="button" onClick={() => setHiddenLayers((current) => ({ ...current, rainviewer: !current.rainviewer }))} aria-pressed={!hiddenLayers.rainviewer}><span className="layer-swatch" style={{ background: "#22c7a8" }} /><span>RAINVIEWER RADAR</span><strong>RADAR</strong></button>}<div className="rail-label rail-label-reference">INFRASTRUCTURE REFERENCE DATA</div><button className={`layer-control ${showPorts ? "layer-active" : ""}`} type="button" onClick={() => setShowPorts((value) => !value)} aria-pressed={showPorts}><span className="layer-swatch layer-swatch-port" /><span>PORT FACILITIES</span><strong>{infrastructure.filter((asset) => asset.type === "port").length.toString().padStart(2, "0")}</strong></button><button className={`layer-control ${showRail ? "layer-active" : ""}`} type="button" onClick={() => setShowRail((value) => !value)} aria-pressed={showRail}><span className="layer-swatch layer-swatch-rail" /><span>RAIL CORRIDORS</span><strong>{infrastructure.filter((asset) => asset.type === "rail_corridor").length.toString().padStart(2, "0")}</strong></button></div>}
      </div>
      <div className="map-legend"><span><span className="legend-dot legend-warning" /> WARNING</span><span><span className="legend-dot legend-advisory" /> ADVISORY</span><span><span className="legend-dot legend-info" /> INFO</span>{overlayCounts.opensky > 0 && <span><span className="legend-ring" style={{ borderColor: "#17c993" }} /> AIRCRAFT · OBSERVATION</span>}{activeLayers.filter((item) => item.source_key && item.source_key !== "nws" && item.source_key !== "usgs").slice(0, 4).map((item) => { const style = SOURCE_POINT_STYLES[item.source_key as string]; return <span key={item.key}><span className="legend-ring" style={{ borderColor: style?.color ?? "#22c7a8" }} /> {item.name.toUpperCase()}</span>; })}{overlayCounts.open_meteo > 0 && <span><span className="legend-ring" style={{ borderColor: "#38bdf8" }} /> MODEL FIELD</span>}{radar?.tile_url_template && <span><span className="legend-ring" style={{ borderColor: "#22c7a8" }} /> RADAR · {radar.timestamp?.slice(11, 16) ?? "LIVE"}Z</span>}</div>
      <div className="map-scale"><span>0</span><span className="scale-line" /><span>500 km</span></div>
    </div>
    <div className="map-foot"><span><span className="foot-icon"><AlertIcon size={14} /></span> WEATHER OVERLAYS</span><span><span className="foot-icon"><QuakeIcon size={14} /></span> SEISMIC OBSERVATIONS</span>{overlayCounts.opensky > 0 && <span><span className="foot-icon"><span className="severity-dot severity-info" /></span> AIRCRAFT STATES</span>}<span className="map-foot-note"><SeverityDot severity="info" /> Reference assets and aircraft states are source-provided · no impact assessment is implied</span></div>
  </section>;
}
