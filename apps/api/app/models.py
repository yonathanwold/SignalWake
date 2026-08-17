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
    EARTHQUAKE = "earthquake"


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
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    freshness_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_observations: Mapped[list[RawObservation]] = relationship(back_populates="source")
    events: Mapped[list[Event]] = relationship(back_populates="source")


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
    last_import_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_import_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_import_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_records: Mapped[list[RawInfrastructureRecord]] = relationship(back_populates="source")
    assets: Mapped[list[InfrastructureAsset]] = relationship(back_populates="source")


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
