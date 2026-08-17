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

export type InfrastructureProvenance = {
  source_record_id: string;
  source_url: string;
  source_name: string;
  attribution: string;
  license: string;
  fetched_at: string;
  raw_record_id: string | null;
  adapter_version: string;
  payload_hash: string;
};

export type InfrastructureAsset = {
  id: string;
  source_id: string;
  source_key: string;
  source_name: string;
  source_url: string;
  source_attribution: string;
  source_license: string;
  source_asset_id: string;
  name: string;
  type: "port" | "rail_corridor" | string;
  subtype: string | null;
  operator: string | null;
  owner: string | null;
  status: string | null;
  region: string | null;
  latitude: number | null;
  longitude: number | null;
  geometry_type: "Point" | "LineString" | "Polygon";
  geometry: { type: string; coordinates: unknown };
  metadata: Record<string, unknown>;
  classification: "REFERENCE";
  source_updated_at: string | null;
  imported_at: string;
  updated_at: string;
  provenance: InfrastructureProvenance[];
};
