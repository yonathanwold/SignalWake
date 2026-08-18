import type { CanonicalEvent, InfrastructureAsset, InfrastructureAssessment, Source } from "./types";

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

export async function fetchEvents(): Promise<{ events: CanonicalEvent[]; sources: Source[]; infrastructure: InfrastructureAsset[]; assessments: InfrastructureAssessment[]; mode: "LIVE" | "DEMO"; fetchedAt: string }> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  try {
    const [eventsResponse, sourcesResponse, infrastructureResponse] = await Promise.all([
      fetch(`${base}/events?limit=200`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
      fetch(`${base}/sources`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
      fetch(`${base}/infrastructure?limit=200`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
    ]);
    if (!eventsResponse.ok || !sourcesResponse.ok || !infrastructureResponse.ok) throw new Error("API unavailable");
    const eventBody = (await eventsResponse.json()) as { items: CanonicalEvent[] };
    const sourceBody = (await sourcesResponse.json()) as Source[];
    const infrastructureBody = (await infrastructureResponse.json()) as { items: InfrastructureAsset[] };
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
    return { events: eventBody.items, sources: sourceBody, infrastructure: infrastructureBody.items, assessments, mode: "LIVE", fetchedAt: new Date().toISOString() };
  } catch {
    return { events: demoEvents, sources: demoSources, infrastructure: demoInfrastructure, assessments: [], mode: "DEMO", fetchedAt: new Date().toISOString() };
  }
}
