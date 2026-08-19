import type { CanonicalEvent, InfrastructureAsset, InfrastructureAssessment, LayerCatalogItem, Source } from "./types";

const portSourceUrl = "https://data-usdot.opendata.arcgis.com/datasets/usdot::port-facilities/about";
const railSourceUrl = "https://data-usdot.opendata.arcgis.com/datasets/usdot::rail-lines/about";
const usgsSourceUrl = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson";

function demoInfrastructureProvenance(sourceRecordId: string, sourceUrl: string) {
  return [{ source_record_id: sourceRecordId, source_url: sourceUrl, source_name: "U.S. DOT representative fixture", attribution: "Representative fixture only; not the full live dataset", license: "See authoritative source page", fetched_at: "2026-08-17T14:31:05Z", raw_record_id: `demo-raw-${sourceRecordId.toLowerCase()}`, adapter_version: "1.0.0", payload_hash: `demo-hash-${sourceRecordId.toLowerCase()}` }];
}

export const demoInfrastructure: InfrastructureAsset[] = [
  { id: "demo-infra-port-001", source_id: "demo-source-bts-ports", source_key: "bts_ports", source_name: "BTS Port Facilities (representative fixture)", source_url: portSourceUrl, source_attribution: "U.S. Department of Transportation, Bureau of Transportation Statistics", source_license: "U.S. Government public data; confirm current dataset terms", source_asset_id: "PORT-VA-001", name: "Demo Hampton Roads Terminal", type: "port", subtype: "Marine terminal", operator: "Example Port Authority", owner: null, status: null, region: "VA", latitude: 36.95, longitude: -76.34, geometry_type: "Point", geometry: { type: "Point", coordinates: [-76.34, 36.95] }, metadata: { OBJECTID: "PORT-VA-001" }, classification: "REFERENCE", source_updated_at: "2026-08-16T12:00:00Z", imported_at: "2026-08-17T14:31:05Z", updated_at: "2026-08-17T14:31:05Z", provenance: demoInfrastructureProvenance("PORT-VA-001", portSourceUrl) },
  { id: "demo-infra-rail-001", source_id: "demo-source-fra-rail", source_key: "fra_rail", source_name: "FRA Rail Lines (representative fixture)", source_url: railSourceUrl, source_attribution: "U.S. Department of Transportation, Federal Railroad Administration", source_license: "U.S. Government public data; confirm current dataset terms", source_asset_id: "RAIL-VA-001", name: "Demo Eastern Freight", type: "rail_corridor", subtype: "Tidewater", operator: null, owner: null, status: "Active", region: "VA", latitude: 37.15, longitude: -76.9, geometry_type: "LineString", geometry: { type: "LineString", coordinates: [[-77.1, 37.0], [-76.9, 37.15], [-76.65, 37.3]] }, metadata: { OBJECTID: "RAIL-VA-001" }, classification: "REFERENCE", source_updated_at: "2026-08-14T09:00:00Z", imported_at: "2026-08-17T14:31:05Z", updated_at: "2026-08-17T14:31:05Z", provenance: demoInfrastructureProvenance("RAIL-VA-001", railSourceUrl) },
];

export const demoEvents: CanonicalEvent[] = [
  {
    id: "demo-nws-001",
    source_id: "demo-source-nws",
    source_key: "nws",
    source_name: "National Weather Service",
    source_event_id: "urn:oid:2.49.0.1.840.0.demo-nws-001.001",
    type: "weather_alert",
    title: "Severe Thunderstorm Warning issued for the Mid-Atlantic",
    summary: "Demo fixture representing an NWS alert payload.",
    severity: "warning",
    status: "active",
    observed_at: "2026-08-17T14:12:00Z",
    effective_at: "2026-08-17T14:12:00Z",
    expires_at: "2026-08-17T16:00:00Z",
    received_at: "2026-08-17T14:13:02Z",
    latitude: 39.55,
    longitude: -77.65,
    geometry: { type: "Polygon", coordinates: [[[-79.8, 38.4], [-75.5, 38.4], [-75.5, 40.7], [-79.8, 40.7], [-79.8, 38.4]]] },
    classification: "DEMO",
    provenance: [{ source_record_id: "urn:oid:2.49.0.1.840.0.demo-nws-001.001", source_url: "https://api.weather.gov/alerts/active?status=actual", fetched_at: "2026-08-17T14:13:02Z", raw_observation_id: "demo-raw-nws-001", adapter_version: "1.0.0", payload_hash: "demo-hash-nws-001" }],
  },
  {
    id: "demo-usgs-001",
    source_id: "demo-source-usgs",
    source_key: "usgs",
    source_name: "United States Geological Survey",
    source_event_id: "demo-usgs-001",
    type: "earthquake",
    title: "M 4.6 - 12 km N of Demo Ridge",
    summary: "Magnitude 4.6 · 12 km N of Demo Ridge",
    severity: "advisory",
    status: "observed",
    observed_at: "2026-08-17T14:30:00Z",
    effective_at: "2026-08-17T14:30:00Z",
    expires_at: null,
    received_at: "2026-08-17T14:31:05Z",
    latitude: 34.0522,
    longitude: -118.2437,
    geometry: { type: "Point", coordinates: [-118.2437, 34.0522, 11.2] },
    classification: "DEMO",
    provenance: [{ source_record_id: "demo-usgs-001", source_url: usgsSourceUrl, fetched_at: "2026-08-17T14:31:05Z", raw_observation_id: "demo-raw-usgs-001", adapter_version: "1.0.0", payload_hash: "demo-hash-usgs-001" }],
  },
  {
    id: "demo-usgs-002",
    source_id: "demo-source-usgs",
    source_key: "usgs",
    source_name: "United States Geological Survey",
    source_event_id: "demo-usgs-002",
    title: "M 3.2 - 8 km W of Demo Bay",
    summary: "Magnitude 3.2 · 8 km W of Demo Bay",
    type: "earthquake",
    severity: "info",
    status: "observed",
    observed_at: "2026-08-17T14:00:00Z",
    effective_at: "2026-08-17T14:00:00Z",
    expires_at: null,
    received_at: "2026-08-17T14:01:05Z",
    latitude: 37.7749,
    longitude: -122.4194,
    geometry: { type: "Point", coordinates: [-122.4194, 37.7749, 7.4] },
    classification: "DEMO",
    provenance: [{ source_record_id: "demo-usgs-002", source_url: usgsSourceUrl, fetched_at: "2026-08-17T14:01:05Z", raw_observation_id: "demo-raw-usgs-002", adapter_version: "1.0.0", payload_hash: "demo-hash-usgs-002" }],
  },
];

export const demoSources: Source[] = [
  { id: "demo-source-nws", key: "nws", name: "National Weather Service", kind: "NWS", endpoint: "https://api.weather.gov/alerts/active?status=actual", active: true, adapter_version: "1.0.0", last_success_at: "2026-08-17T14:13:02Z", last_attempt_at: "2026-08-17T14:13:02Z", last_error: null, last_http_status: 200, freshness_seconds: 0, health: "HEALTHY" },
  { id: "demo-source-usgs", key: "usgs", name: "United States Geological Survey", kind: "USGS", endpoint: usgsSourceUrl, active: true, adapter_version: "1.0.0", last_success_at: "2026-08-17T14:31:05Z", last_attempt_at: "2026-08-17T14:31:05Z", last_error: null, last_http_status: 200, freshness_seconds: 0, health: "HEALTHY" },
];

const catalogLabels: Array<[string, string, string, string]> = [
  ["nws_alerts", "NWS active alerts", "LIVE", "weather"], ["nws_forecasts", "NWS forecasts", "NOT_CONNECTED", "weather"], ["nws_observations", "NWS observations", "NOT_CONNECTED", "weather"], ["nws_storm_reports", "NWS storm reports", "NOT_CONNECTED", "weather"],
  ["usgs_earthquakes", "USGS earthquakes", "LIVE", "seismic"], ["usgs_water", "USGS water services", "NEAR_REAL_TIME", "hydrology"], ["nasa_firms", "NASA FIRMS active fire", "REQUIRES_CREDENTIALS", "fire"], ["airnow", "AirNow air quality", "REQUIRES_CREDENTIALS", "air_quality"], ["nhc_systems", "NHC current tropical systems", "NEAR_REAL_TIME", "tropical_weather"], ["noaa_coops", "NOAA CO-OPS water levels", "NOT_CONNECTED", "coastal"], ["nasa_eonet", "NASA EONET natural events", "NEAR_REAL_TIME", "natural_hazards"], ["aviation_weather", "Aviation Weather Center PIREPs", "NEAR_REAL_TIME", "aviation"],
  ["bts", "BTS transportation assets", "REFERENCE", "transportation"], ["fra", "FRA rail network", "REFERENCE", "transportation"], ["faa", "FAA facilities and advisories", "NOT_CONNECTED", "aviation"], ["energy", "Energy infrastructure", "NOT_CONNECTED", "energy"], ["dams", "National dam inventory", "REFERENCE", "water_infrastructure"], ["hospitals", "Hospitals", "REFERENCE", "public_safety"], ["shelters", "Emergency shelters", "NOT_CONNECTED", "public_safety"], ["public_safety", "Public safety facilities", "NOT_CONNECTED", "public_safety"], ["mrms", "NOAA MRMS precipitation", "NOT_CONNECTED", "weather"], ["lightning", "NOAA lightning", "NOT_CONNECTED", "weather"], ["snow_temperature", "NOAA snow and temperature", "NOT_CONNECTED", "weather"], ["drought_soil", "Drought and soil moisture", "REFERENCE", "environment"], ["land_elevation", "USGS elevation", "REFERENCE", "terrain"], ["watersheds_hydrography", "USGS watersheds and hydrography", "REFERENCE", "hydrology"], ["census", "U.S. Census geography", "REFERENCE", "demographics"], ["fema_nri", "FEMA National Risk Index", "REFERENCE", "risk"], ["fema_declarations", "FEMA current designated counties", "NEAR_REAL_TIME", "emergency_management"], ["social_vulnerability", "CDC/ATSDR social vulnerability", "REFERENCE", "vulnerability"], ["cdc_wastewater", "CDC wastewater surveillance", "NOT_CONNECTED", "public_health"],
];

export const demoLayerCatalog: LayerCatalogItem[] = catalogLabels.map(([key, name, status, category]) => ({
  key, name, category, geometry_kind: "source geometry", data_kind: "catalog metadata only", temporal_semantics: "source timestamp", applies_to_48h_window: status !== "REFERENCE", endpoint: "", status, adapter_version: "1.0.0", last_refresh: null, counts: {}, source_key: ({ nws_alerts: "nws", nws_observations: "nws_observations", usgs_earthquakes: "usgs", usgs_water: "usgs_water", nhc_systems: "nhc", nasa_firms: "nasa_firms", airnow: "airnow", noaa_coops: "noaa_coops", nasa_eonet: "nasa_eonet", aviation_weather: "aviation_weather", fema_declarations: "fema_declarations" } as Record<string, string>)[key] ?? null, error: null, provenance: {}, coverage: {},
}));

export async function fetchEvents(): Promise<{ events: CanonicalEvent[]; sources: Source[]; infrastructure: InfrastructureAsset[]; assessments: InfrastructureAssessment[]; layers: LayerCatalogItem[]; windowStart: string; windowEnd: string; mode: "LIVE" | "DEMO"; fetchedAt: string }> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  try {
    const [eventsResponse, sourcesResponse, infrastructureResponse, catalogResponse] = await Promise.all([
      fetch(`${base}/events?limit=2000`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
      fetch(`${base}/sources`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
      fetch(`${base}/infrastructure?limit=200`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
      fetch(`${base}/sources/catalog`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
    ]);
    if (!eventsResponse.ok || !sourcesResponse.ok || !infrastructureResponse.ok || !catalogResponse.ok) throw new Error("API unavailable");
    const eventBody = (await eventsResponse.json()) as { items: CanonicalEvent[]; window_start: string; window_end: string };
    const sourceBody = (await sourcesResponse.json()) as Source[];
    const infrastructureBody = (await infrastructureResponse.json()) as { items: InfrastructureAsset[] };
    const catalogBody = (await catalogResponse.json()) as { items: LayerCatalogItem[] };
    let assessments: InfrastructureAssessment[] = [];
    try {
      const assessmentsResponse = await fetch(`${base}/assessments?limit=500`, { cache: "no-store", signal: AbortSignal.timeout(2200) });
      if (assessmentsResponse.ok) {
        const assessmentsBody = (await assessmentsResponse.json()) as { items: InfrastructureAssessment[] };
        assessments = assessmentsBody.items;
      }
    } catch {
      // Assessment data is optional to the source/event live path. The UI
      // keeps the derived panel empty and labeled when this endpoint is down.
    }
    return { events: eventBody.items, sources: sourceBody, infrastructure: infrastructureBody.items, assessments, layers: catalogBody.items, windowStart: eventBody.window_start, windowEnd: eventBody.window_end, mode: "LIVE", fetchedAt: new Date().toISOString() };
  } catch {
    const now = new Date();
    return { events: demoEvents, sources: demoSources, infrastructure: demoInfrastructure, assessments: [], layers: demoLayerCatalog, windowStart: new Date(now.getTime() - 48 * 3600_000).toISOString(), windowEnd: now.toISOString(), mode: "DEMO", fetchedAt: now.toISOString() };
  }
}
