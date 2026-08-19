from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class Road511Adapter(SourceAdapter):
    """Bounded Road511 traffic events. A real X-API-Key is required."""

    key = "road511"
    name = "Road511 Traffic Events"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        api_key: str | None = None,
        bbox: str = "-130,20,-60,55",
        jurisdiction: str = "WA",
        limit: int = 200,
    ):
        super().__init__(endpoint, user_agent, timeout_seconds, adapter_version)
        self.api_key = api_key.strip() if api_key else None
        self.bbox = bbox.strip()
        self.jurisdiction = jurisdiction.strip().upper()
        self.max_features = max(1, min(500, int(limit)))

    def request_endpoint(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update({"bbox": [self.bbox], "limit": [str(self.max_features)], "offset": ["0"]})
        if self.jurisdiction:
            query["jurisdiction"] = [self.jurisdiction]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        if not self.api_key:
            return []
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await self._request_with_retries_with_key(client)
            body = response.json()
            rows = body.get("data") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                raise AdapterError(f"{self.key} response did not contain a data list")
            features: list[dict[str, Any]] = []
            for row in rows[: self.max_features]:
                if not isinstance(row, dict):
                    continue
                coordinates = _coordinates(row)
                if coordinates is None:
                    continue
                source_event_id = str(row.get("id") or row.get("source_id") or "").strip()
                if not source_event_id:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "id": source_event_id,
                        "properties": row,
                        "geometry": {"type": "Point", "coordinates": [coordinates[0], coordinates[1]]},
                    }
                )
            return features
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AdapterError(f"{self.key} fetch failed: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()

    async def _request_with_retries_with_key(self, client: httpx.AsyncClient) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await client.get(
                    self.request_endpoint(),
                    headers={"Accept": "application/json", "User-Agent": self.user_agent, "X-API-Key": self.api_key or ""},
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

    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise AdapterError("Road511 feature is missing properties or geometry")
        coordinates = geometry.get("coordinates")
        source_event_id = str(feature.get("id") or "").strip()
        if not source_event_id or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("Road511 feature is missing id or coordinates")
        observed_at = parse_datetime(
            properties.get("last_updated") or properties.get("source_updated_at") or properties.get("start_time"),
            fetched_at,
        )
        status_raw = str(properties.get("status") or "active").lower()
        status = EventStatus.EXPIRED.value if status_raw in {"closed", "archived", "expired"} else EventStatus.ACTIVE.value
        end_value = properties.get("end_time") or properties.get("estimated_end_time")
        expires_at = parse_datetime(end_value, None) if end_value else None
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.TRAFFIC_EVENT.value,
            title=str(properties.get("title") or properties.get("type") or "Road511 traffic event"),
            summary=str(properties.get("description") or properties.get("affected_roads") or "") or None,
            severity=_severity(properties.get("severity")),
            status=status,
            observed_at=observed_at,
            effective_at=parse_datetime(properties.get("start_time"), observed_at),
            expires_at=expires_at,
            latitude=float(coordinates[1]),
            longitude=float(coordinates[0]),
            geometry=geometry,
            payload=feature,
        )


def _coordinates(row: dict[str, Any]) -> tuple[float, float] | None:
    location = row.get("location")
    if isinstance(location, dict):
        coords = location.get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            try:
                longitude, latitude = float(coords[0]), float(coords[1])
                return (longitude, latitude) if isfinite(longitude) and isfinite(latitude) else None
            except (TypeError, ValueError):
                return None
    try:
        longitude, latitude = float(row.get("longitude", row.get("lng"))), float(row.get("latitude", row.get("lat")))
        return (longitude, latitude) if isfinite(longitude) and isfinite(latitude) else None
    except (TypeError, ValueError):
        return None


def _severity(value: Any) -> str:
    return {"minor": Severity.ADVISORY.value, "moderate": Severity.WATCH.value, "major": Severity.WARNING.value, "critical": Severity.CRITICAL.value}.get(str(value or "").lower(), Severity.INFO.value)
