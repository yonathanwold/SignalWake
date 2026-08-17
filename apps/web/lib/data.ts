import type { CanonicalEvent, Source } from "./types";

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
    provenance: [{ source_record_id: "demo-usgs-001", source_url: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson", fetched_at: "2026-08-17T14:31:05Z", raw_observation_id: "demo-raw-usgs-001", adapter_version: "1.0.0", payload_hash: "demo-hash-usgs-001" }],
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
    provenance: [{ source_record_id: "demo-usgs-002", source_url: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson", fetched_at: "2026-08-17T14:01:05Z", raw_observation_id: "demo-raw-usgs-002", adapter_version: "1.0.0", payload_hash: "demo-hash-usgs-002" }],
  },
];

export const demoSources: Source[] = [
  { id: "demo-source-nws", key: "nws", name: "National Weather Service", kind: "NWS", endpoint: "https://api.weather.gov/alerts/active?status=actual", active: true, adapter_version: "1.0.0", last_success_at: "2026-08-17T14:13:02Z", last_attempt_at: "2026-08-17T14:13:02Z", last_error: null, last_http_status: 200, freshness_seconds: 0, health: "HEALTHY" },
  { id: "demo-source-usgs", key: "usgs", name: "United States Geological Survey", kind: "USGS", endpoint: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson", active: true, adapter_version: "1.0.0", last_success_at: "2026-08-17T14:31:05Z", last_attempt_at: "2026-08-17T14:31:05Z", last_error: null, last_http_status: 200, freshness_seconds: 0, health: "HEALTHY" },
];

export async function fetchEvents(): Promise<{ events: CanonicalEvent[]; sources: Source[]; mode: "LIVE" | "DEMO"; fetchedAt: string }> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  try {
    const [eventsResponse, sourcesResponse] = await Promise.all([
      fetch(`${base}/events?limit=100`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
      fetch(`${base}/sources`, { cache: "no-store", signal: AbortSignal.timeout(2200) }),
    ]);
    if (!eventsResponse.ok || !sourcesResponse.ok) throw new Error("API unavailable");
    const eventBody = (await eventsResponse.json()) as { items: CanonicalEvent[] };
    const sourceBody = (await sourcesResponse.json()) as Source[];
    return { events: eventBody.items, sources: sourceBody, mode: "LIVE", fetchedAt: new Date().toISOString() };
  } catch {
    return { events: demoEvents, sources: demoSources, mode: "DEMO", fetchedAt: new Date().toISOString() };
  }
}

