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
    health: str = "UNKNOWN"


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


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    database: str
    sources: list[SourceResponse]
    generated_at: datetime
