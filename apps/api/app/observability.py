"""Small, process-local observability primitives for SIGNALWAKE.

This module deliberately avoids a metrics backend.  It keeps bounded counters
and recent incident metadata in memory for the lifetime of one API process.
Persisted processing facts continue to come from ``TransformationRun``.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Callable
from uuid import uuid4

MAX_ENDPOINTS = 100
MAX_INCIDENTS = 50
MAX_ERROR_TEXT = 240
DEFAULT_FRESHNESS_SECONDS = 3600


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def bounded_text(value: object | None, limit: int = MAX_ERROR_TEXT) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:limit] if text else None


def error_category(error: object | None, status_code: int | None = None) -> str | None:
    """Return a bounded, stable category without retaining exception details."""

    if status_code is not None:
        if status_code >= 500:
            return "server_error"
        if status_code >= 400:
            return "client_error"
    if error is None:
        return None
    name = getattr(error, "__class__", type(error)).__name__.lower()
    message = str(error).lower()
    if "timeout" in name or "timeout" in message:
        return "timeout"
    if "connection" in name or "connect" in message:
        return "upstream_unavailable"
    if "adapter" in name or "normalize" in message or "malformed" in message:
        return "normalization_error"
    if "integrity" in name or "constraint" in message:
        return "persistence_error"
    return "processing_error"


@dataclass(frozen=True)
class Incident:
    occurred_at: datetime
    route: str
    method: str
    status_code: int
    category: str
    request_id: str
    message: str | None = None


@dataclass
class EndpointAggregate:
    method: str
    route: str
    requests: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    status_counts: Counter[str] | None = None

    def __post_init__(self) -> None:
        self.status_counts = self.status_counts or Counter()

    def record(self, status_code: int, duration_ms: float) -> None:
        self.requests += 1
        if status_code >= 400:
            self.errors += 1
        self.total_latency_ms += duration_ms
        self.max_latency_ms = max(self.max_latency_ms, duration_ms)
        assert self.status_counts is not None
        self.status_counts[str(status_code)] += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "method": self.method,
            "route": self.route,
            "requests": self.requests,
            "errors": self.errors,
            "error_rate": round(self.errors / self.requests, 4) if self.requests else 0.0,
            "total_latency_ms": round(self.total_latency_ms, 3),
            "average_latency_ms": round(self.total_latency_ms / self.requests, 3) if self.requests else 0.0,
            "max_latency_ms": round(self.max_latency_ms, 3),
            "status_counts": dict(sorted((self.status_counts or {}).items())),
        }


class MetricsRegistry:
    """Thread-safe bounded request registry with injectable UTC clock."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock
        self.process_started_at = clock()
        self._lock = RLock()
        self._requests = 0
        self._errors = 0
        self._total_latency_ms = 0.0
        self._max_latency_ms = 0.0
        self._status_counts: Counter[str] = Counter()
        self._endpoints: dict[tuple[str, str], EndpointAggregate] = {}
        self._incidents: deque[Incident] = deque(maxlen=MAX_INCIDENTS)

    def record_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
        request_id: str,
        category: str | None = None,
        message: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        duration_ms = max(0.0, float(duration_ms))
        method = method.upper()[:12]
        route = route[:160]
        with self._lock:
            self._requests += 1
            if status_code >= 400:
                self._errors += 1
            self._total_latency_ms += duration_ms
            self._max_latency_ms = max(self._max_latency_ms, duration_ms)
            self._status_counts[str(status_code)] += 1
            key = (method, route)
            if key not in self._endpoints and len(self._endpoints) < MAX_ENDPOINTS:
                self._endpoints[key] = EndpointAggregate(method, route)
            endpoint = self._endpoints.get(key)
            if endpoint:
                endpoint.record(status_code, duration_ms)
            if status_code >= 400:
                self._incidents.append(
                    Incident(
                        occurred_at=occurred_at or self.clock(),
                        route=route,
                        method=method,
                        status_code=status_code,
                        category=category or error_category(None, status_code) or "request_error",
                        request_id=request_id[:80],
                        message=bounded_text(message),
                    )
                )

    def snapshot(self, *, now: datetime | None = None) -> dict[str, object]:
        with self._lock:
            current = now or self.clock()
            uptime = max(0.0, (current - self.process_started_at).total_seconds())
            incidents = [
                {
                    "occurred_at": item.occurred_at,
                    "route": item.route,
                    "method": item.method,
                    "status_code": item.status_code,
                    "category": item.category,
                    "request_id": item.request_id,
                    "message": item.message,
                    "source": "process_local",
                }
                for item in reversed(self._incidents)
            ]
            return {
                "collection_scope": "process_local",
                "process_started_at": self.process_started_at,
                "uptime_seconds": round(uptime, 3),
                "requests": self._requests,
                "errors": self._errors,
                "error_rate": round(self._errors / self._requests, 4) if self._requests else 0.0,
                "total_latency_ms": round(self._total_latency_ms, 3),
                "average_latency_ms": round(self._total_latency_ms / self._requests, 3) if self._requests else 0.0,
                "max_latency_ms": round(self._max_latency_ms, 3),
                "status_counts": dict(sorted(self._status_counts.items())),
                "endpoints": [self._endpoints[key].snapshot() for key in sorted(self._endpoints)],
                "recent_incidents": incidents,
            }

    def reset(self) -> None:
        with self._lock:
            self._requests = 0
            self._errors = 0
            self._total_latency_ms = 0.0
            self._max_latency_ms = 0.0
            self._status_counts.clear()
            self._endpoints.clear()
            self._incidents.clear()


metrics = MetricsRegistry()


def request_id(value: str | None) -> str:
    """Accept a bounded caller ID or create one; never log a request body."""

    cleaned = (value or "").strip()
    if not cleaned or len(cleaned) > 80 or any(ord(char) < 32 for char in cleaned):
        return str(uuid4())
    return cleaned


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def source_threshold_seconds(expected_interval_seconds: int | None) -> int:
    return max(60, expected_interval_seconds) if expected_interval_seconds else DEFAULT_FRESHNESS_SECONDS


def operational_state(
    *,
    last_success_at: datetime | None,
    last_attempt_at: datetime | None,
    last_failure_at: datetime | None,
    records_rejected: int | None,
    expected_interval_seconds: int | None,
    now: datetime | None = None,
) -> str:
    """Map source telemetry to ACTIVE, DEGRADED, DOWN, or UNKNOWN."""

    now = normalize_datetime(now or utc_now())
    success = normalize_datetime(last_success_at)
    attempt = normalize_datetime(last_attempt_at)
    failure = normalize_datetime(last_failure_at)
    if success is None and attempt is None and failure is None:
        return "UNKNOWN"
    if success is None:
        return "DOWN" if failure is not None or attempt is not None else "UNKNOWN"
    age = max(0.0, (now - success).total_seconds()) if now else 0.0
    threshold = source_threshold_seconds(expected_interval_seconds)
    if age > threshold:
        return "DEGRADED"
    if failure and (attempt is None or failure >= attempt):
        return "DEGRADED"
    if records_rejected and records_rejected > 0:
        return "DEGRADED"
    return "ACTIVE"
