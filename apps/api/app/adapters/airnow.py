from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class AirNowAdapter(SourceAdapter):
    """Normalize the bounded AirNow JSON observations endpoint."""

    key = "airnow"
    name = "AirNow Air Quality"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        api_key: str | None = None,
        bbox: str = "-130,20,-60,55",
        parameters: str = "PM25,OZONE",
    ):
        super().__init__(endpoint, user_agent, timeout_seconds, adapter_version)
        self.api_key = api_key.strip() if api_key else None
        self.bbox = bbox.strip()
        self.parameters = parameters.strip() or "PM25,OZONE"
        self.max_features = 1000

    def request_endpoint(self, now: datetime | None = None) -> str:
        end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        start = end - timedelta(hours=48)
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update(
            {
                # AirNow's bounded observations endpoint uses the documented
                # UTC hour form YYYY-MM-DDTHH-0000 rather than relative dates.
                "startDate": [start.strftime("%Y-%m-%dT%H-0000")],
                "endDate": [end.strftime("%Y-%m-%dT%H-0000")],
                "parameters": [self.parameters],
                "BBOX": [self.bbox],
                "dataType": ["B"],
                "format": ["application/json"],
                "verbose": ["1"],
                "monitorType": ["0"],
                "includerawconcentrations": ["0"],
                "API_KEY": [self.api_key or ""],
            }
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        if not self.api_key:
            return []
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await self._request_with_retries(client, self.request_endpoint())
            body = response.json()
            if not isinstance(body, list):
                raise AdapterError(f"{self.key} response did not contain an observation list")
            features: list[dict[str, Any]] = []
            for row in body[: self.max_features]:
                if not isinstance(row, dict):
                    continue
                try:
                    latitude = float(row.get("Latitude", row.get("latitude")))
                    longitude = float(row.get("Longitude", row.get("longitude")))
                except (TypeError, ValueError):
                    continue
                timestamp = _airnow_timestamp(row)
                if timestamp is None:
                    continue
                station = str(row.get("Site") or row.get("Station") or row.get("SiteName") or "unknown")
                parameter = str(row.get("Parameter") or row.get("parameter") or "unknown")
                source_event_id = f"{station}:{parameter}:{timestamp.isoformat()}"
                features.append(
                    {
                        "type": "Feature",
                        "id": source_event_id,
                        "properties": {**row, "observed_at": timestamp.isoformat(), "station": station, "parameter": parameter},
                        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                    }
                )
            return features
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AdapterError(f"{self.key} fetch failed: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()

    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise AdapterError("AirNow feature is missing properties or geometry")
        coordinates = geometry.get("coordinates")
        source_event_id = str(feature.get("id") or "")
        if not source_event_id or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("AirNow feature is missing id or coordinates")
        observed_at = parse_datetime(properties.get("observed_at"), fetched_at)
        try:
            aqi = float(properties.get("AQI"))
        except (TypeError, ValueError):
            aqi = None
        severity = Severity.WARNING.value if aqi is not None and aqi >= 101 else Severity.ADVISORY.value if aqi is not None and aqi >= 51 else Severity.INFO.value
        parameter = str(properties.get("parameter") or "air quality")
        station = str(properties.get("station") or "unknown station")
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.AIR_QUALITY_OBSERVATION.value,
            title=f"{station} · {parameter}",
            summary=f"AQI {properties.get('AQI')}" if properties.get("AQI") not in (None, "") else None,
            severity=severity,
            status=EventStatus.OBSERVED.value,
            observed_at=observed_at,
            effective_at=observed_at,
            expires_at=None,
            latitude=float(coordinates[1]),
            longitude=float(coordinates[0]),
            geometry=geometry,
            payload=feature,
        )


def _airnow_timestamp(row: dict[str, Any]) -> datetime | None:
    value = row.get("UTC") or row.get("utc") or row.get("observed_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except ValueError:
            pass
    date = str(row.get("DateObserved") or "").strip()
    hour = row.get("HourObserved")
    if date and hour not in (None, ""):
        try:
            return datetime.strptime(f"{date} {int(hour):02d}", "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    return None
