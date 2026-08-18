from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from app.observability import bounded_text

log = structlog.get_logger(__name__)


class AdapterError(RuntimeError):
    """A source could not be fetched or normalized safely."""


@dataclass(frozen=True)
class NormalizedEvent:
    source_event_id: str
    event_type: str
    title: str
    summary: str | None
    severity: str
    status: str
    observed_at: datetime
    effective_at: datetime | None
    expires_at: datetime | None
    latitude: float | None
    longitude: float | None
    geometry: dict[str, Any] | None
    payload: dict[str, Any]


def parse_datetime(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return fallback or datetime.now(timezone.utc)


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SourceAdapter(ABC):
    key: str
    name: str
    endpoint: str
    adapter_version: str

    def __init__(self, endpoint: str, user_agent: str, timeout_seconds: float = 15.0, adapter_version: str = "1.0.0"):
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.adapter_version = adapter_version
        self.last_http_status: int | None = None

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await self._request_with_retries(client)
            body = response.json()
            features = body.get("features") if isinstance(body, dict) else None
            if not isinstance(features, list):
                raise AdapterError(f"{self.key} response did not contain a GeoJSON feature list")
            return features
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            error = bounded_text(exc) or "source fetch failed"
            log.error("source_fetch_failed", source=self.key, error=error)
            raise AdapterError(f"{self.key} fetch failed: {error}") from exc
        finally:
            if own_client:
                await client.aclose()

    async def _request_with_retries(
        self, client: httpx.AsyncClient, endpoint: str | None = None
    ) -> httpx.Response:
        last_error: Exception | None = None
        request_endpoint = endpoint or self.endpoint
        for attempt in range(3):
            try:
                response = await client.get(
                    request_endpoint,
                    headers={"Accept": "application/geo+json, application/json", "User-Agent": self.user_agent},
                )
                self.last_http_status = response.status_code
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    import asyncio

                    await asyncio.sleep(0.2 * (2**attempt))
        raise last_error or AdapterError("request failed")

    @abstractmethod
    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        """Convert one upstream feature to canonical event fields."""
