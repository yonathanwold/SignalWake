export type EventType = "weather_alert" | "earthquake";
export type Severity = "info" | "advisory" | "watch" | "warning" | "critical";

export type Provenance = {
  source_record_id: string;
  source_url: string;
  fetched_at: string;
  raw_observation_id: string | null;
  adapter_version: string;
  payload_hash: string;
};

export type CanonicalEvent = {
  id: string;
  source_id: string;
  source_key: string;
  source_name: string;
  source_event_id: string;
  type: EventType;
  title: string;
  summary: string | null;
  severity: Severity;
  status: string;
  observed_at: string;
  effective_at: string | null;
  expires_at: string | null;
  received_at: string;
  latitude: number | null;
  longitude: number | null;
  geometry: { type: string; coordinates: unknown } | null;
  classification: "LIVE" | "DEMO" | "HISTORICAL" | "SIMULATED";
  provenance: Provenance[];
};

export type Source = {
  id: string;
  key: string;
  name: string;
  kind: string;
  endpoint: string;
  active: boolean;
  adapter_version: string;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
  last_http_status: number | null;
  freshness_seconds: number | null;
  health: "HEALTHY" | "STALE" | "ERROR" | "UNKNOWN";
};

