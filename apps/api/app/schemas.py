from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    source_record_id: str
    source_url: str
    fetched_at: datetime
    raw_observation_id: str | None = None
    adapter_version: str
    payload_hash: str


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    kind: str
    endpoint: str
    active: bool
    adapter_version: str
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    last_http_status: int | None = None
    freshness_seconds: int | None = None
    expected_update_interval_seconds: int | None = None
    last_run_id: str | None = None
    last_records_retrieved: int | None = None
    last_records_accepted: int | None = None
    last_records_rejected: int | None = None
    health: str = "UNKNOWN"


class LineageNode(BaseModel):
    type: str
    id: str
    label: str
    direct_or_derived: str
    source: dict[str, Any] | None = None
    observed_at: datetime | None = None
    ingested_at: datetime | None = None
    generated_at: datetime | None = None
    transformation: dict[str, Any] | None = None
    freshness_seconds: int | None = None
    confidence: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class LineageEdge(BaseModel):
    id: str
    upstream: dict[str, str]
    downstream: dict[str, str]
    relation_kind: str
    transformation_run_id: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None
    ingested_at: datetime | None = None
    generated_at: datetime | None = None


class LineageResponse(BaseModel):
    object_type: str
    object_id: str
    direction: str
    limit: int
    truncated: bool
    nodes: list[LineageNode] = Field(default_factory=list)
    edges: list[LineageEdge] = Field(default_factory=list)


class EventResponse(BaseModel):
    id: str
    source_id: str
    source_key: str
    source_name: str
    source_event_id: str
    type: str
    title: str
    summary: str | None = None
    severity: str
    status: str
    observed_at: datetime
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    received_at: datetime
    latitude: float | None = None
    longitude: float | None = None
    geometry: dict[str, Any] | None = None
    classification: str = "DERIVED"
    provenance: list[Provenance] = Field(default_factory=list)


class EventListResponse(BaseModel):
    items: list[EventResponse]
    total: int
    limit: int
    next_cursor: str | None = None


class InfrastructureProvenance(BaseModel):
    source_record_id: str
    source_url: str
    source_name: str
    attribution: str
    license: str
    fetched_at: datetime
    raw_record_id: str | None = None
    adapter_version: str
    payload_hash: str


class InfrastructureResponse(BaseModel):
    id: str
    source_id: str
    source_key: str
    source_name: str
    source_url: str
    source_attribution: str
    source_license: str
    source_asset_id: str
    name: str
    type: str
    subtype: str | None = None
    operator: str | None = None
    owner: str | None = None
    status: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geometry_type: str
    geometry: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    classification: str = "REFERENCE"
    source_updated_at: datetime | None = None
    imported_at: datetime
    updated_at: datetime
    provenance: list[InfrastructureProvenance] = Field(default_factory=list)


class InfrastructureListResponse(BaseModel):
    items: list[InfrastructureResponse]
    total: int
    limit: int
    next_cursor: str | None = None


class GraphMetrics(BaseModel):
    degree: int
    component_size: int
    betweenness_centrality: float
    is_articulation_point: bool
    alternate_path_count: int


class GraphNodeResponse(BaseModel):
    id: str
    name: str
    type: str
    region: str | None = None
    source_key: str
    classification: str = "REFERENCE"
    asset: InfrastructureResponse
    metrics: GraphMetrics


class GraphEdgeResponse(BaseModel):
    id: str
    from_node_id: str
    to_node_id: str
    relationship_key: str
    relationship_type: str
    directionality: str
    relationship_source: str
    source_relationship_id: str | None = None
    derivation_method: str | None = None
    derivation_version: str | None = None
    confidence: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    distance_km: float | None = None
    tolerance_m: float | None = None


class GraphNodeListResponse(BaseModel):
    items: list[GraphNodeResponse]
    total: int
    limit: int
    next_cursor: str | None = None


class GraphNeighborsResponse(BaseModel):
    root: GraphNodeResponse
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    depth: int
    limit: int


class GraphPathResponse(BaseModel):
    from_node_id: str
    to_node_id: str
    max_hops: int
    hops: int
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class GraphSubgraphResponse(BaseModel):
    root_node_id: str
    depth: int
    max_nodes: int
    truncated: bool
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class GraphMetricsResponse(BaseModel):
    items: list[GraphNodeResponse]
    total: int
    limit: int


class GraphRebuildResponse(BaseModel):
    assets_considered: int
    candidate_pairs: int
    derived_edges: int
    inserted_count: int
    updated_count: int
    deleted_count: int
    settings: dict[str, Any]


class AssessmentResponse(BaseModel):
    classification: str = "SIGNALWAKE DERIVED ASSESSMENT"
    id: str
    assessment_key: str
    assessment_type: str
    event_id: str
    affected_asset_id: str | None = None
    affected_region: str | None = None
    severity: str
    status: str
    score: float = Field(ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    methodology_version: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    score_components: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AssessmentListResponse(BaseModel):
    items: list[AssessmentResponse]
    total: int
    limit: int
    next_cursor: str | None = None


class AssessmentRecomputeRequest(BaseModel):
    event_id: str
    radius_km: float = Field(default=50.0, gt=0, le=500)
    depth: int = Field(default=2, ge=1, le=4)
    asset_limit: int = Field(default=200, ge=1, le=5000)


class AssessmentRecomputeResponse(BaseModel):
    event_id: str
    methodology_version: str
    inserted_count: int
    updated_count: int
    deleted_count: int
    total: int
    settings: dict[str, Any]
    items: list[AssessmentResponse]


class ScenarioCreateRequest(BaseModel):
    name: str = Field(default="Untitled graph scenario", min_length=1, max_length=200)
    scenario_type: str = Field(min_length=1, max_length=64)
    target_node_ids: list[str] = Field(default_factory=list, max_length=50)
    target_edge_ids: list[str] = Field(default_factory=list, max_length=50)
    assumption: str = Field(
        default="Selected targets are unavailable in the modeled infrastructure graph.",
        min_length=1,
        max_length=1000,
    )
    duration_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    created_by: str = Field(default="operator", min_length=1, max_length=128)


class ScenarioTargetResponse(BaseModel):
    id: str
    target_kind: str
    target_id: str
    position: int
    snapshot: dict[str, Any] = Field(default_factory=dict)


class ScenarioResponse(BaseModel):
    id: str
    name: str
    scenario_type: str
    created_by: str
    assumption: str
    duration_seconds: int | None = None
    methodology_version: str
    input_hash: str
    baseline_graph_hash: str
    baseline_node_count: int
    baseline_edge_count: int
    baseline: dict[str, Any] = Field(default_factory=dict)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    targets: list[ScenarioTargetResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ScenarioListResponse(BaseModel):
    items: list[ScenarioResponse]
    total: int
    limit: int
    next_cursor: str | None = None


class ScenarioResultResponse(BaseModel):
    id: str
    run_id: str
    baseline: dict[str, Any] = Field(default_factory=dict)
    modified: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ScenarioRunResponse(BaseModel):
    id: str
    scenario_id: str
    run_key: str
    status: str
    methodology_version: str
    baseline_graph_hash: str
    modified_graph_hash: str
    started_at: datetime
    completed_at: datetime
    created_at: datetime
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    result: ScenarioResultResponse | None = None


class ScenarioGraphResponse(BaseModel):
    run_id: str
    state: str
    graph_hash: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    max_nodes: int


class GraphEdgeListResponse(BaseModel):
    items: list[GraphEdgeResponse]
    total: int
    limit: int


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    database: str
    sources: list[SourceResponse]
    generated_at: datetime


class ReplayTimelineMarker(BaseModel):
    timestamp: datetime
    recorded_at: datetime
    kind: str
    id: str
    identity: str
    label: str
    change: str


class ReplayTimelineResponse(BaseModel):
    start_time: datetime
    end_time: datetime
    items: list[ReplayTimelineMarker]
    total: int
    limit: int
    truncated: bool = False


class ReplayStateResponse(BaseModel):
    timestamp: datetime
    as_of: datetime
    events: list[dict[str, Any]] = Field(default_factory=list)
    assessments: list[dict[str, Any]] = Field(default_factory=list)
    infrastructure: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    infrastructure_sources: list[dict[str, Any]] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    limit: int
    truncated: bool = False
    semantics: dict[str, str] = Field(default_factory=dict)


class ReplayCompareResponse(BaseModel):
    from_time: datetime
    to_time: datetime
    summary: dict[str, int] = Field(default_factory=dict)
    changes: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    limit: int
    truncated: bool = False
