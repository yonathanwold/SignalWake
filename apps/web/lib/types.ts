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
  last_failure_at?: string | null;
  last_error_category?: string | null;
  last_http_status: number | null;
  freshness_seconds: number | null;
  expected_update_interval_seconds?: number | null;
  last_run_id?: string | null;
  last_records_retrieved?: number | null;
  last_records_accepted?: number | null;
  last_records_rejected?: number | null;
  health: "HEALTHY" | "STALE" | "ERROR" | "UNKNOWN";
  operational_state?: "ACTIVE" | "DEGRADED" | "DOWN" | "UNKNOWN";
};

export type HealthSource = {
  source_type: "event" | "infrastructure" | string;
  id: string;
  key: string;
  name: string;
  kind: string | null;
  endpoint: string;
  active: boolean;
  adapter_version: string;
  operational_state: "ACTIVE" | "DEGRADED" | "DOWN" | "UNKNOWN" | string;
  health: "HEALTHY" | "STALE" | "ERROR" | "UNKNOWN" | string;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_failure_at: string | null;
  expected_update_interval_seconds: number | null;
  freshness_seconds: number | null;
  freshness_threshold_seconds: number;
  records_received: number | null;
  records_accepted: number | null;
  records_rejected: number | null;
  last_run_id: string | null;
  last_error_category: string | null;
  last_error: string | null;
};

export type HealthSummary = {
  status: string;
  database: string;
  database_state: "connected" | "disconnected" | string;
  overall_state: "ACTIVE" | "DEGRADED" | "DOWN" | "UNKNOWN" | string;
  readiness: "ready" | "not_ready" | string;
  generated_at: string;
  source_counts: Record<string, number>;
};

export type HealthMetrics = {
  generated_at: string;
  process_local: {
    uptime_seconds: number;
    requests: number;
    errors: number;
    error_rate: number;
    average_latency_ms: number;
    max_latency_ms: number;
    endpoints: Array<{ method: string; route: string; requests: number; errors: number; average_latency_ms: number; max_latency_ms: number; error_rate: number }>;
    recent_incidents: Array<{ occurred_at: string; route: string; method: string; status_code: number; category: string; request_id: string; message: string | null }>;
  };
  persisted_runs: { bounded_limit: number; by_kind: Array<{ run_kind: string; run_count: number; completed: number; failed: number; partial: number; average_latency_ms: number; max_latency_ms: number; records_retrieved: number; records_accepted: number; records_rejected: number }> };
  sources: { generated_at: string; items: HealthSource[]; counts: Record<string, number> };
  recent_failures: Array<Record<string, unknown>>;
};

export type LineageNode = {
  type: string;
  id: string;
  label: string;
  direct_or_derived: "direct" | "derived" | string;
  source: Record<string, unknown> | null;
  observed_at: string | null;
  ingested_at: string | null;
  generated_at: string | null;
  transformation: Record<string, unknown> | null;
  freshness_seconds: number | null;
  confidence: number | null;
  evidence: Record<string, unknown>;
};

export type LineageEdge = {
  id: string;
  upstream: { type: string; id: string };
  downstream: { type: string; id: string };
  relation_kind: string;
  transformation_run_id: string | null;
  evidence: Record<string, unknown>;
  observed_at: string | null;
  ingested_at: string | null;
  generated_at: string | null;
};

export type LineageResponse = {
  object_type: string;
  object_id: string;
  direction: "upstream" | "downstream" | "both" | string;
  limit: number;
  truncated: boolean;
  nodes: LineageNode[];
  edges: LineageEdge[];
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

export type GraphEdgeList = { items: GraphEdge[]; total: number; limit: number; next_cursor: string | null };

export type ScenarioTarget = {
  id: string;
  target_kind: "NODE" | "EDGE" | string;
  target_id: string;
  position: number;
  snapshot: Record<string, unknown>;
};

export type Scenario = {
  id: string;
  name: string;
  scenario_type: "ASSET_UNAVAILABLE" | "EDGE_UNAVAILABLE" | "MULTIPLE_ASSETS_UNAVAILABLE" | string;
  created_by: string;
  assumption: string;
  duration_seconds: number | null;
  methodology_version: string;
  input_hash: string;
  baseline_graph_hash: string;
  baseline_node_count: number;
  baseline_edge_count: number;
  baseline: { nodes?: Record<string, unknown>[]; edges?: Record<string, unknown>[]; hash?: string; node_count?: number; edge_count?: number };
  assumptions: Record<string, unknown>;
  targets: ScenarioTarget[];
  created_at: string;
  updated_at: string;
};

export type ScenarioList = { items: Scenario[]; total: number; limit: number; next_cursor: string | null };

export type ScenarioResult = {
  id: string;
  run_id: string;
  baseline: { nodes: Record<string, unknown>[]; edges: Record<string, unknown>[]; hash: string; node_count: number; edge_count: number };
  modified: { nodes: Record<string, unknown>[]; edges: Record<string, unknown>[]; hash: string; node_count: number; edge_count: number };
  metrics: {
    baseline: { node_count: number; edge_count: number; component_count: number; largest_component_size: number; articulation_point_ids: string[] };
    scenario: { node_count: number; edge_count: number; component_count: number; largest_component_size: number; articulation_point_ids: string[] };
    removed_node_ids: string[];
    removed_edge_ids: string[];
    disconnected_node_ids: string[];
    newly_articulation_point_ids: string[];
    no_longer_articulation_point_ids: string[];
    path_analysis: { pairs_evaluated: number; baseline_reachable_pairs: number; scenario_reachable_pairs: number; changed_path_count: number; changed_paths: Record<string, unknown>[]; average_positive_path_increase: number };
    alternate_routes: { baseline_alternate_route_edges: number; scenario_alternate_route_edges: number; preserved_alternate_route_edges: number; lost_alternate_route_edge_ids: string[] };
    resilience: { score: number; delta_from_intact: number; components: Record<string, number>; weights: Record<string, number> };
  };
  evidence: Record<string, unknown>;
  created_at: string;
};

export type ScenarioRun = {
  id: string;
  scenario_id: string;
  run_key: string;
  status: string;
  methodology_version: string;
  baseline_graph_hash: string;
  modified_graph_hash: string;
  started_at: string;
  completed_at: string;
  created_at: string;
  reproducibility: Record<string, unknown>;
  result: ScenarioResult | null;
};
