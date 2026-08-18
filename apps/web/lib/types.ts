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

export type GraphMetrics = {
  degree: number;
  component_size: number;
  betweenness_centrality: number;
  is_articulation_point: boolean;
  alternate_path_count: number;
};

export type GraphNode = {
  id: string;
  name: string;
  type: string;
  region: string | null;
  source_key: string;
  classification: "REFERENCE" | string;
  asset: InfrastructureAsset;
  metrics: GraphMetrics;
};

export type GraphEdge = {
  id: string;
  from_node_id: string;
  to_node_id: string;
  relationship_key: string;
  relationship_type: "CONNECTED_TO" | "INTERSECTS" | "ADJACENT_TO" | string;
  directionality: string;
  relationship_source: "SOURCE_OBSERVED" | "DERIVED" | string;
  source_relationship_id: string | null;
  derivation_method: string | null;
  derivation_version: string | null;
  confidence: number | null;
  evidence: Record<string, unknown>;
  distance_km: number | null;
  tolerance_m: number | null;
};

export type GraphNodeList = { items: GraphNode[]; total: number; limit: number; next_cursor: string | null };
export type GraphSubgraph = { root_node_id: string; depth: number; max_nodes: number; truncated: boolean; nodes: GraphNode[]; edges: GraphEdge[] };

export type InfrastructureAssessment = {
  classification: "SIGNALWAKE DERIVED ASSESSMENT" | string;
  id: string;
  assessment_key: string;
  assessment_type: "EVENT_INTERSECTS_INFRASTRUCTURE" | "INFRASTRUCTURE_WITHIN_EVENT_RADIUS" | "DEPENDENCY_EXPOSURE" | "REGIONAL_INFRASTRUCTURE_EXPOSURE" | string;
  event_id: string;
  affected_asset_id: string | null;
  affected_region: string | null;
  severity: Severity | string;
  status: string;
  score: number;
  confidence: number | null;
  methodology_version: string;
  evidence: Record<string, unknown>;
  score_components: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type InfrastructureAssessmentList = {
  items: InfrastructureAssessment[];
  total: number;
  limit: number;
  next_cursor: string | null;
};
