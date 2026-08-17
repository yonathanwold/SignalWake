from __future__ import annotations

import enum
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


class Base(DeclarativeBase):
    pass


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
