from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class COOPSAdapter(SourceAdapter):
    """Fetch a bounded set of NOAA CO-OPS water-level stations."""

    key = "noaa_coops"
    name = "NOAA CO-OPS Water Levels"

    def __init__(
        self,
        metadata_endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        data_endpoint: str,
        station_ids: list[str] | None = None,
        station_limit: int = 10,
    ):
        super().__init__(metadata_endpoint, user_agent, timeout_seconds, adapter_version)
        self.data_endpoint = data_endpoint
        self.station_ids = tuple(dict.fromkeys(item.strip() for item in (station_ids or []) if item.strip()))
        self.station_limit = max(1, min(25, int(station_limit)))
        self.max_features = self.station_limit

    def _data_endpoint(self, station_id: str) -> str:
        parts = urlsplit(self.data_endpoint)
        query = parse_qs(parts.query)
        query.update(
            {
                "product": ["water_level"],
                "application": ["signalwake"],
                "format": ["json"],
                "datum": ["MSL"],
                "units": ["metric"],
                "time_zone": ["gmt"],
                "station": [station_id],
                "date": ["latest"],
            }
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            metadata_response = await self._request_with_retries(client)
            body = metadata_response.json()
            rows = body.get("stations", []) if isinstance(body, dict) else []
            if not isinstance(rows, list):
                raise AdapterError(f"{self.key} response did not contain station metadata")
            requested = set(self.station_ids)
            selected: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                station_id = str(row.get("id") or row.get("station") or "").strip()
                if not station_id or (requested and station_id not in requested):
                    continue
                if not _coordinates(row):
                    continue
                selected.append(row)
                if len(selected) >= (len(requested) if requested else self.station_limit):
                    break
            features: list[dict[str, Any]] = []
            errors: list[str] = []
            for station in selected:
                station_id = str(station.get("id") or station.get("station"))
                try:
                    data_response = await self._request_with_retries(client, self._data_endpoint(station_id))
                    data_body = data_response.json()
                    records = data_body.get("data", []) if isinstance(data_body, dict) else []
                    if not isinstance(records, list):
                        raise AdapterError("water-level response did not contain data")
                    latest = records[-1] if records else None
                    if not isinstance(latest, dict) or not latest.get("t"):
                        continue
                    coordinates = _coordinates(station)
                    if coordinates is None:
                        continue
                    timestamp = parse_datetime(latest.get("t"), None)
                    if timestamp is None:
                        continue
                    source_event_id = f"{station_id}:{latest.get('t')}"
                    features.append(
                        {
                            "type": "Feature",
                            "id": source_event_id,
                            "properties": {
                                "station_id": station_id,
                                "station_name": station.get("name"),
                                "value": latest.get("v"),
                                "quality": latest.get("q"),
                                "unit": "m",
                                "observed_at": timestamp.isoformat(),
                                "station_metadata": station,
                            },
                            "geometry": {"type": "Point", "coordinates": [coordinates[0], coordinates[1]]},
                        }
                    )
                    if len(features) >= self.max_features:
                        break
                except (httpx.HTTPError, ValueError, TypeError, AdapterError) as exc:
                    errors.append(f"{station_id}: {exc}")
            if not features and errors:
                raise AdapterError(f"{self.key} fetch failed: {'; '.join(errors[:3])}")
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
            raise AdapterError("CO-OPS feature is missing properties or geometry")
        coordinates = geometry.get("coordinates")
        source_event_id = str(feature.get("id") or "")
        if not source_event_id or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("CO-OPS feature is missing id or coordinates")
        observed_at = parse_datetime(properties.get("observed_at"), fetched_at)
        station = str(properties.get("station_name") or properties.get("station_id") or "station")
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.COOPS_WATER_LEVEL.value,
            title=f"NOAA CO-OPS · {station}",
            summary=f"Water level {properties.get('value')} m" if properties.get("value") is not None else None,
            severity=Severity.INFO.value,
            status=EventStatus.OBSERVED.value,
            observed_at=observed_at,
            effective_at=observed_at,
            expires_at=None,
            latitude=float(coordinates[1]),
            longitude=float(coordinates[0]),
            geometry=geometry,
            payload=feature,
        )


def _coordinates(row: dict[str, Any]) -> tuple[float, float] | None:
    try:
        latitude = float(row.get("lat", row.get("latitude")))
        longitude = float(row.get("lng", row.get("lon", row.get("longitude"))))
    except (TypeError, ValueError):
        return None
    return longitude, latitude
