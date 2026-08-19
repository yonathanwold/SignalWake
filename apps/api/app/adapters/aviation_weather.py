from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class AviationWeatherAdapter(SourceAdapter):
    """Normalize bounded AviationWeather.gov pilot reports (PIREPs)."""

    key = "aviation_weather"
    name = "Aviation Weather Center"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        bbox: str = "",
        age_hours: int = 48,
        limit: int = 400,
    ):
        super().__init__(endpoint, user_agent, timeout_seconds, adapter_version)
        self.bbox = bbox.strip()
        self.age_hours = max(1, min(48, int(age_hours)))
        self.max_features = max(1, min(400, int(limit)))

    @property
    def request_endpoint(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update({"age": [str(self.age_hours)], "format": ["geojson"]})
        if self.bbox:
            query["bbox"] = [self.bbox]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await self._request_with_retries(client, self.request_endpoint)
            if response.status_code == 204:
                return []
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
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise AdapterError("PIREP feature is missing properties or geometry")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("PIREP feature is missing coordinates")
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError) as exc:
            raise AdapterError("PIREP geometry has invalid coordinates") from exc
        observed_at = _provider_datetime(
            properties.get("obsTime")
            or properties.get("observationTime")
            or properties.get("receiptTime")
            or properties.get("time"),
            fetched_at,
        )
        source_event_id = _source_id(feature, properties, geometry, observed_at)
        hazard = str(properties.get("hazard") or properties.get("type") or properties.get("reportType") or "PIREP").strip()
        intensity = str(properties.get("intensity") or properties.get("severity") or "").lower()
        severity = Severity.WARNING.value if any(term in intensity for term in ("severe", "extreme")) else Severity.ADVISORY.value if hazard.lower() not in {"pirep", "routine", ""} else Severity.INFO.value
        raw = properties.get("raw") or properties.get("rawText")
        title = f"Aviation report · {hazard}" if hazard else "Aviation report"
        summary = str(raw).strip() if raw else _summary(properties)
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.AVIATION_REPORT.value,
            title=title,
            summary=summary or None,
            severity=severity,
            status=EventStatus.OBSERVED.value,
            observed_at=observed_at,
            effective_at=observed_at,
            expires_at=None,
            latitude=latitude,
            longitude=longitude,
            geometry=geometry,
            payload=feature,
        )


def _provider_datetime(value: Any, fallback: datetime | None) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return parse_datetime(None, fallback)
    if isinstance(value, str) and value.strip():
        try:
            numeric = float(value.strip())
            seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    return parse_datetime(value, fallback)


def _source_id(feature: dict[str, Any], properties: dict[str, Any], geometry: dict[str, Any], observed_at: datetime) -> str:
    for value in (feature.get("id"), properties.get("id"), properties.get("pirepId"), properties.get("reportId")):
        if value not in (None, ""):
            return str(value).strip()
    raw = str(properties.get("raw") or properties.get("rawText") or "")
    material = f"{raw}|{observed_at.isoformat()}|{geometry.get('coordinates')}".encode()
    return f"pirep:{hashlib.sha256(material).hexdigest()[:24]}"


def _summary(properties: dict[str, Any]) -> str | None:
    fields = [properties.get("aircraft"), properties.get("altitude"), properties.get("location")]
    values = [str(value).strip() for value in fields if value not in (None, "")]
    return " · ".join(values) if values else None
