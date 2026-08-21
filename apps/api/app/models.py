from __future__ import annotations

import enum
import json
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator, UserDefinedType
from sqlalchemy.types import Text as SQLText


class Base(DeclarativeBase):
    pass


class _PostGISGeometryImpl(UserDefinedType):
    """PostGIS column declaration used only by the PostgreSQL dialect."""

    cache_ok = True

    def get_col_spec(self, **kwargs):  # noqa: ARG002 - SQLAlchemy type protocol
        return "geometry(Geometry,4326)"


class PostGISGeometry(TypeDecorator):
    """PostGIS geometry on production, text storage for SQLite tests."""

    impl = SQLText
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PostGISGeometryImpl())
        return dialect.type_descriptor(SQLText())

    def process_bind_param(self, value, dialect):
        if value is None or dialect.name != "postgresql":
            return value
        geometry = json.loads(value) if isinstance(value, str) else value
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Point":
            return f"POINT ({coordinates[0]} {coordinates[1]})"
        if geometry_type == "LineString":
            points = ", ".join(f"{point[0]} {point[1]}" for point in coordinates)
            return f"LINESTRING ({points})"
        if geometry_type == "Polygon":
            rings = ", ".join(
                f"({', '.join(f'{point[0]} {point[1]}' for point in ring)})" for ring in coordinates
            )
            return f"POLYGON ({rings})"
        raise ValueError(f"unsupported geometry type: {geometry_type}")


class JSONText(TypeDecorator):
    """JSON text on SQLite and native JSONB on PostgreSQL."""

    impl = SQLText
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSON() if dialect.name == "postgresql" else SQLText())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return json.loads(value) if isinstance(value, str) else value
        return value if isinstance(value, str) else json.dumps(value, sort_keys=True)

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True)


class SourceKind(str, enum.Enum):
    NWS = "NWS"
    USGS = "USGS"


class EventType(str, enum.Enum):
    WEATHER_ALERT = "weather_alert"
    WEATHER_OBSERVATION = "weather_observation"
    EARTHQUAKE = "earthquake"
    WATER_LEVEL_OBSERVATION = "water_level_observation"
    TROPICAL_SYSTEM = "tropical_system"
    FIRE_DETECTION = "fire_detection"
    AIR_QUALITY_OBSERVATION = "air_quality_observation"
    COOPS_WATER_LEVEL = "coops_water_level"
    NATURAL_EVENT = "natural_event"
    AVIATION_REPORT = "aviation_report"
    FEMA_DESIGNATION = "fema_designation"
    TRAFFIC_EVENT = "traffic_event"
    AIRCRAFT_OBSERVATION = "aircraft_observation"


class Severity(str, enum.Enum):
    INFO = "info"
    ADVISORY = "advisory"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


class EventStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    OBSERVED = "observed"


class ProcessingState(str, enum.Enum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    REJECTED = "rejected"


class InfrastructureClassification(str, enum.Enum):
    REFERENCE = "REFERENCE"


class InfrastructureRelationshipType(str, enum.Enum):
    CONNECTED_TO = "CONNECTED_TO"
    INTERSECTS = "INTERSECTS"
    ADJACENT_TO = "ADJACENT_TO"


class InfrastructureRelationshipSource(str, enum.Enum):
    SOURCE_OBSERVED = "SOURCE_OBSERVED"
    DERIVED = "DERIVED"


class RelationshipDirectionality(str, enum.Enum):
    UNDIRECTED = "UNDIRECTED"
    DIRECTED = "DIRECTED"


class AssessmentType(str, enum.Enum):
    EVENT_INTERSECTS_INFRASTRUCTURE = "EVENT_INTERSECTS_INFRASTRUCTURE"
    INFRASTRUCTURE_WITHIN_EVENT_RADIUS = "INFRASTRUCTURE_WITHIN_EVENT_RADIUS"
    DEPENDENCY_EXPOSURE = "DEPENDENCY_EXPOSURE"
    REGIONAL_INFRASTRUCTURE_EXPOSURE = "REGIONAL_INFRASTRUCTURE_EXPOSURE"


class AssessmentStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    OBSERVED = "observed"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    adapter_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    freshness_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_update_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    last_records_retrieved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_records_accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_records_rejected: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_observations: Mapped[list[RawObservation]] = relationship(back_populates="source")
    events: Mapped[list[Event]] = relationship(back_populates="source")
    history: Mapped[list[SourceStateVersion]] = relationship(back_populates="source")


class InfrastructureSource(Base):
    __tablename__ = "infrastructure_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    endpoint: Mapped[str] = mapped_column(String(1024))
    attribution: Mapped[str] = mapped_column(String(512))
    license: Mapped[str] = mapped_column(String(512))
    adapter_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_import_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_import_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_import_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_update_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    last_records_retrieved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_records_accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_records_rejected: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_records: Mapped[list[RawInfrastructureRecord]] = relationship(back_populates="source")
    assets: Mapped[list[InfrastructureAsset]] = relationship(back_populates="source")
    history: Mapped[list[InfrastructureSourceVersion]] = relationship(back_populates="source")


class RawInfrastructureRecord(Base):
    __tablename__ = "raw_infrastructure_records"
    __table_args__ = (
        UniqueConstraint("source_id", "payload_hash", name="uq_raw_infrastructure_source_payload"),
        Index("ix_raw_infrastructure_source_record", "source_id", "source_record_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_sources.id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(512), index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    processing_state: Mapped[str] = mapped_column(String(32), default=ProcessingState.RECEIVED.value)
    adapter_version: Mapped[str] = mapped_column(String(32))

    source: Mapped[InfrastructureSource] = relationship(back_populates="raw_records")


class InfrastructureAsset(Base):
    __tablename__ = "infrastructure_assets"
    __table_args__ = (
        UniqueConstraint("source_id", "source_asset_id", name="uq_infrastructure_source_asset"),
        Index("ix_infrastructure_asset_type_region", "asset_type", "region"),
        Index("ix_infrastructure_asset_source_type", "source_id", "asset_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_sources.id"), index=True)
    raw_infrastructure_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_infrastructure_records.id"), nullable=True, index=True
    )
    source_asset_id: Mapped[str] = mapped_column(String(512), index=True)
    name: Mapped[str] = mapped_column(String(512))
    asset_type: Mapped[str] = mapped_column(String(64), index=True)
    asset_subtype: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    operator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    geometry_type: Mapped[str] = mapped_column(String(32))
    geometry_geojson: Mapped[str] = mapped_column(JSONText())
    # The migration uses PostGIS geometry(Geometry, 4326). SQLite stores no value here;
    # geometry_geojson remains the deterministic test/dev representation.
    geometry: Mapped[str | None] = mapped_column(PostGISGeometry(), nullable=True)
    metadata_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    provenance_json: Mapped[str] = mapped_column(JSONText(), default="[]")
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    classification: Mapped[str] = mapped_column(String(16), default=InfrastructureClassification.REFERENCE.value)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    normalized_version: Mapped[str] = mapped_column(String(32))

    source: Mapped[InfrastructureSource] = relationship(back_populates="assets")
    history: Mapped[list[InfrastructureAssetVersion]] = relationship(back_populates="asset")


class InfrastructureRelationship(Base):
    """A provenance-aware edge between two canonical infrastructure assets.

    Current Phase 3 derivations are undirected.  ``relationship_key`` is
    generated by the derivation service (or an observed source adapter) and is
    the idempotency boundary, so rebuilding cannot create duplicate edges.
    """

    __tablename__ = "infrastructure_relationships"
    __table_args__ = (
        UniqueConstraint("relationship_key", name="uq_infrastructure_relationship_key"),
        Index("ix_infrastructure_relationship_from", "from_asset_id"),
        Index("ix_infrastructure_relationship_to", "to_asset_id"),
        Index("ix_infrastructure_relationship_from_type", "from_asset_id", "relationship_type"),
        Index("ix_infrastructure_relationship_to_type", "to_asset_id", "relationship_type"),
        Index("ix_infrastructure_relationship_type_source", "relationship_type", "relationship_source"),
        Index("ix_infrastructure_relationship_derived", "relationship_source", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    from_asset_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_assets.id"), index=True)
    to_asset_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_assets.id"), index=True)
    relationship_key: Mapped[str] = mapped_column(String(512))
    relationship_type: Mapped[str] = mapped_column(String(64), index=True)
    directionality: Mapped[str] = mapped_column(String(32), default=RelationshipDirectionality.UNDIRECTED.value)
    relationship_source: Mapped[str] = mapped_column(String(32), index=True)
    source_relationship_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    derivation_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    derivation_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    from_asset: Mapped[InfrastructureAsset] = relationship(
        foreign_keys=[from_asset_id], backref="relationships_from"
    )
    to_asset: Mapped[InfrastructureAsset] = relationship(
        foreign_keys=[to_asset_id], backref="relationships_to"
    )


class RawObservation(Base):
    __tablename__ = "raw_observations"
    __table_args__ = (
        UniqueConstraint("source_id", "payload_hash", name="uq_raw_source_payload"),
        Index("ix_raw_source_record", "source_id", "source_record_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(512), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    processing_state: Mapped[str] = mapped_column(String(32), default=ProcessingState.RECEIVED.value)
    adapter_version: Mapped[str] = mapped_column(String(32))

    source: Mapped[Source] = relationship(back_populates="raw_observations")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source_id", "source_event_id", name="uq_event_source_record"),
        Index("ix_event_time", "observed_at"),
        Index("ix_event_observed_id", "observed_at", "id"),
        Index("ix_event_filters", "source_id", "event_type", "severity", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    raw_observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_observations.id"), nullable=True, index=True
    )
    source_event_id: Mapped[str] = mapped_column(String(512), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default=EventStatus.ACTIVE.value)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    geometry_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_json: Mapped[str] = mapped_column(Text, default="[]")
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_version: Mapped[str] = mapped_column(String(32))
    classification: Mapped[str] = mapped_column(String(16), default="LIVE")

    source: Mapped[Source] = relationship(back_populates="events")
    history: Mapped[list[EventVersion]] = relationship(back_populates="event")


class InfrastructureAssessment(Base):
    """Deterministic, persisted assessment derived from an event and assets.

    Assessments intentionally sit apart from source facts and graph edges.  A
    stable key makes event-scoped recomputation idempotent while preserving
    the identity of each derived result across refreshes.
    """

    __tablename__ = "infrastructure_assessments"
    __table_args__ = (
        UniqueConstraint("assessment_key", name="uq_infrastructure_assessment_key"),
        Index("ix_assessment_event_type", "event_id", "assessment_type"),
        Index("ix_assessment_event_score", "event_id", "score"),
        Index("ix_assessment_asset", "affected_asset_id"),
        Index("ix_assessment_asset_score", "affected_asset_id", "score"),
        Index("ix_assessment_status_score", "status", "score"),
        Index("ix_assessment_methodology", "event_id", "methodology_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    assessment_key: Mapped[str] = mapped_column(String(768))
    assessment_type: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    affected_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("infrastructure_assets.id"), nullable=True, index=True
    )
    affected_region: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    methodology_version: Mapped[str] = mapped_column(String(32), index=True)
    evidence_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    score_components_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    metadata_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    event: Mapped[Event] = relationship(backref="assessments")
    affected_asset: Mapped[InfrastructureAsset | None] = relationship(backref="assessments")
    history: Mapped[list[InfrastructureAssessmentVersion]] = relationship(back_populates="assessment")


class EventVersion(Base):
    """Append-only knowledge-time snapshot for one canonical source event.

    ``recorded_at`` is when SIGNALWAKE learned this version, not when the
    source says the event occurred.  ``valid_to`` is maintained as the next
    recorded knowledge time for the same stable event identity.
    """

    __tablename__ = "event_versions"
    __table_args__ = (
        UniqueConstraint("event_id", "payload_hash", name="uq_event_version_payload"),
        Index("ix_event_version_identity_recorded", "source_id", "source_event_id", "recorded_at"),
        Index("ix_event_version_recorded", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    source_event_id: Mapped[str] = mapped_column(String(512), index=True)
    raw_observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_observations.id"), nullable=True, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_json: Mapped[str] = mapped_column(Text)

    event: Mapped[Event] = relationship(back_populates="history")


class SourceStateVersion(Base):
    """Append-only source ingest/freshness state at a knowledge-time boundary."""

    __tablename__ = "source_state_versions"
    __table_args__ = (
        Index("ix_source_state_source_recorded", "source_id", "recorded_at"),
        Index("ix_source_state_recorded", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    snapshot_json: Mapped[str] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="history")


class InfrastructureSourceVersion(Base):
    """Historical import state for a reference infrastructure source."""

    __tablename__ = "infrastructure_source_versions"
    __table_args__ = (
        Index("ix_infra_source_state_source_recorded", "source_id", "recorded_at"),
        Index("ix_infra_source_state_recorded", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_sources.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    snapshot_json: Mapped[str] = mapped_column(Text)

    source: Mapped[InfrastructureSource] = relationship(back_populates="history")


class InfrastructureAssetVersion(Base):
    """Append-only imported asset snapshot keyed by source asset identity."""

    __tablename__ = "infrastructure_asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "payload_hash", name="uq_infrastructure_asset_version_payload"),
        Index("ix_infra_asset_version_identity_recorded", "source_id", "source_asset_id", "recorded_at"),
        Index("ix_infra_asset_version_recorded", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_assets.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_sources.id"), index=True)
    source_asset_id: Mapped[str] = mapped_column(String(512), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_json: Mapped[str] = mapped_column(Text)

    asset: Mapped[InfrastructureAsset] = relationship(back_populates="history")


class InfrastructureAssessmentVersion(Base):
    """Append-only generated assessment snapshot, including tombstones."""

    __tablename__ = "infrastructure_assessment_versions"
    __table_args__ = (
        Index("ix_assessment_version_key_generated", "assessment_key", "generated_at"),
        Index("ix_assessment_version_generated", "generated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("infrastructure_assessments.id"), nullable=True, index=True
    )
    assessment_key: Mapped[str] = mapped_column(String(768), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    methodology_version: Mapped[str] = mapped_column(String(32), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot_json: Mapped[str] = mapped_column(Text)

    assessment: Mapped[InfrastructureAssessment | None] = relationship(back_populates="history")


class ScenarioType(str, enum.Enum):
    """Supported second-order graph mutations.

    These values describe only removal in the modeled relationship graph. They
    are deliberately not outage, service, or economic event types.
    """

    ASSET_UNAVAILABLE = "ASSET_UNAVAILABLE"
    EDGE_UNAVAILABLE = "EDGE_UNAVAILABLE"
    MULTIPLE_ASSETS_UNAVAILABLE = "MULTIPLE_ASSETS_UNAVAILABLE"


class ScenarioTargetKind(str, enum.Enum):
    NODE = "NODE"
    EDGE = "EDGE"


class Scenario(Base):
    """A reproducible, user-authored graph mutation definition."""

    __tablename__ = "scenarios"
    __table_args__ = (
        Index("ix_scenario_type_created", "scenario_type", "created_at"),
        Index("ix_scenario_methodology", "methodology_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    scenario_type: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="operator")
    assumption: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    methodology_version: Mapped[str] = mapped_column(String(64), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    baseline_graph_hash: Mapped[str] = mapped_column(String(64), index=True)
    baseline_node_count: Mapped[int] = mapped_column(Integer)
    baseline_edge_count: Mapped[int] = mapped_column(Integer)
    baseline_snapshot_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    assumptions_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    targets: Mapped[list[ScenarioTarget]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="ScenarioTarget.position"
    )
    runs: Mapped[list[ScenarioRun]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="ScenarioRun.created_at"
    )


class ScenarioTarget(Base):
    """Explicit node/edge targets captured at scenario creation time."""

    __tablename__ = "scenario_targets"
    __table_args__ = (
        UniqueConstraint("scenario_id", "target_kind", "target_id", name="uq_scenario_target"),
        Index("ix_scenario_target_lookup", "target_kind", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(String(36))
    position: Mapped[int] = mapped_column(Integer)
    target_snapshot_json: Mapped[str] = mapped_column(JSONText(), default="{}")

    scenario: Mapped[Scenario] = relationship(back_populates="targets")


class ScenarioRun(Base):
    """One explicit deterministic execution of a scenario definition."""

    __tablename__ = "scenario_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_scenario_run_key"),
        Index("ix_scenario_run_scenario_created", "scenario_id", "created_at"),
        Index("ix_scenario_run_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    run_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    methodology_version: Mapped[str] = mapped_column(String(64), index=True)
    baseline_graph_hash: Mapped[str] = mapped_column(String(64))
    modified_graph_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reproducibility_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    scenario: Mapped[Scenario] = relationship(back_populates="runs")
    result: Mapped[ScenarioResult | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class ScenarioResult(Base):
    """Persisted baseline/modified evidence for one scenario run."""

    __tablename__ = "scenario_results"
    __table_args__ = (UniqueConstraint("run_id", name="uq_scenario_result_run"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.id", ondelete="CASCADE"), index=True)
    baseline_snapshot_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    modified_snapshot_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    metrics_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    evidence_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    run: Mapped[ScenarioRun] = relationship(back_populates="result")


class TransformationRun(Base):
    """Bounded metadata for one ingest/import/derivation/assessment run.

    ``source_id`` is intentionally a string without a foreign key because the
    source namespace includes both event and infrastructure sources.  This
    table records operational facts only; it is not an event-sourcing log.
    """

    __tablename__ = "transformation_runs"
    __table_args__ = (
        Index("ix_transformation_run_kind_started", "run_kind", "started_at"),
        Index("ix_transformation_run_source_started", "source_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_kind: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    records_retrieved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_rejected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LineageRecord(Base):
    """Explicit bounded dependency edge between persisted SIGNALWAKE objects."""

    __tablename__ = "lineage_records"
    __table_args__ = (
        Index("ix_lineage_upstream", "upstream_type", "upstream_id"),
        Index("ix_lineage_downstream", "downstream_type", "downstream_id"),
        Index("ix_lineage_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    upstream_type: Mapped[str] = mapped_column(String(64), index=True)
    upstream_id: Mapped[str] = mapped_column(String(512), index=True)
    downstream_type: Mapped[str] = mapped_column(String(64), index=True)
    downstream_id: Mapped[str] = mapped_column(String(512), index=True)
    relation_kind: Mapped[str] = mapped_column(String(64))
    transformation_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("transformation_runs.id"), nullable=True, index=True
    )
    evidence_json: Mapped[str] = mapped_column(JSONText(), default="{}")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    transformation_run: Mapped[TransformationRun | None] = relationship()
