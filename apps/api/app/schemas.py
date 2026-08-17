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


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    database: str
    sources: list[SourceResponse]
    generated_at: datetime

