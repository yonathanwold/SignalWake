from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class EONETAdapter(SourceAdapter):
    """Normalize NASA EONET's bounded natural-event GeoJSON feed."""

    key = "nasa_eonet"
    name = "NASA EONET Natural Events"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        bbox: str = "-130,55,-60,20",
        days: int = 2,
        limit: int = 500,
    ):
        super().__init__(endpoint, user_agent, timeout_seconds, adapter_version)
        self.bbox = bbox.strip()
        self.days = max(1, min(2, int(days)))
        self.max_features = max(1, min(500, int(limit)))

    @property
    def request_endpoint(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update(
            {
                "status": ["all"],
                "days": [str(self.days)],
                "bbox": [self.bbox],
                "limit": [str(self.max_features)],
            }
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await self._request_with_retries(client, self.request_endpoint)
            body = response.json()
            features = body.get("features") if isinstance(body, dict) else None
            if not isinstance(features, list):
                raise AdapterError(f"{self.key} response did not contain a GeoJSON feature list")
            return features[: self.max_features]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AdapterError(f"{self.key} fetch failed: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()

    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise AdapterError("EONET feature is missing properties")
        source_event_id = str(feature.get("id") or properties.get("id") or "").strip()
        if not source_event_id:
            raise AdapterError("EONET feature is missing id")
        geometry = _selected_geometry(feature)
        if geometry is None:
            raise AdapterError("EONET feature is missing geometry")
        geometry_properties = geometry if isinstance(geometry, dict) else {}
        closed = properties.get("closed") or feature.get("closed")
        observed_at = parse_datetime(
            geometry_properties.get("date") or properties.get("date") or properties.get("lastUpdated") or _latest_geometry_date(properties.get("geometryDates")) or closed,
            fetched_at,
        )
        categories = _category_titles(properties.get("categories"))
        status = EventStatus.OBSERVED.value if closed else EventStatus.ACTIVE.value
        expires_at = parse_datetime(closed, None) if closed else None
        coordinates = geometry.get("coordinates")
        latitude: float | None = None
        longitude: float | None = None
        if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
            try:
                longitude, latitude = float(coordinates[0]), float(coordinates[1])
            except (TypeError, ValueError) as exc:
                raise AdapterError("EONET point geometry has invalid coordinates") from exc
        title = str(feature.get("title") or properties.get("title") or source_event_id).strip()
        description = feature.get("description") or properties.get("description")
        summary = str(description).strip() if description else ", ".join(categories) or None
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.NATURAL_EVENT.value,
            title=title,
            summary=summary,
            severity=_severity(categories),
            status=status,
            observed_at=observed_at,
            effective_at=observed_at,
            expires_at=expires_at,
            latitude=latitude,
            longitude=longitude,
            geometry=geometry,
            payload=feature,
        )


def _selected_geometry(feature: dict[str, Any]) -> dict[str, Any] | None:
    value = feature.get("geometry")
    candidates = value if isinstance(value, list) else [value]
    usable = [item for item in candidates if isinstance(item, dict) and isinstance(item.get("type"), str) and "coordinates" in item]
    if not usable:
        return None
    return max(usable, key=lambda item: parse_datetime(item.get("date"), datetime.min.replace(tzinfo=timezone.utc)))


def _category_titles(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item.get("title") or item.get("id") or "").strip() for item in value if isinstance(item, dict) and (item.get("title") or item.get("id"))]


def _severity(categories: list[str]) -> str:
    text = " ".join(categories).lower()
    if not text:
        return Severity.INFO.value
    return Severity.WARNING.value if any(term in text for term in ("wildfire", "volcano", "earthquake", "severe storm")) else Severity.ADVISORY.value


def _latest_geometry_date(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    dates = [item.get("date") for item in value if isinstance(item, dict) and item.get("date")]
    return str(dates[-1]) if dates else None
