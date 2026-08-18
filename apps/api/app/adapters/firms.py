from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class FIRMSAdapter(SourceAdapter):
    """Normalize a bounded NASA FIRMS area CSV request.

    FIRMS requires a user-provided free MAP_KEY.  The key is kept out of the
    adapter endpoint and persisted provenance so it cannot leak into source
    metadata or logs.
    """

    key = "nasa_firms"
    name = "NASA FIRMS Active Fire"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        map_key: str | None = None,
        area: str = "USA",
        product: str = "VIIRS_SNPP_NRT",
        days: int = 2,
    ):
        super().__init__(endpoint, user_agent, timeout_seconds, adapter_version)
        self.map_key = map_key.strip() if map_key else None
        self.area = area.strip() or "USA"
        self.product = product.strip() or "VIIRS_SNPP_NRT"
        self.days = max(1, min(2, int(days)))
        self.max_features = 1000

    @property
    def request_endpoint(self) -> str:
        return "/".join(
            [self.endpoint.rstrip("/"), quote(self.map_key or "", safe=""), quote(self.product, safe=""), quote(self.area, safe=""), str(self.days)]
        )

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        if not self.map_key:
            return []
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await self._request_with_retries(client, self.request_endpoint)
            reader = csv.DictReader(io.StringIO(response.text))
            features: list[dict[str, Any]] = []
            for row in reader:
                if len(features) >= self.max_features or not isinstance(row, dict):
                    break
                normalized = {str(key).strip().lower(): value for key, value in row.items()}
                try:
                    longitude = float(normalized["longitude"])
                    latitude = float(normalized["latitude"])
                except (KeyError, TypeError, ValueError):
                    continue
                timestamp = _firms_timestamp(normalized)
                if timestamp is None:
                    continue
                identity = ":".join(
                    str(normalized.get(key) or "")
                    for key in ("satellite", "instrument", "latitude", "longitude", "acq_date", "acq_time")
                )
                if not identity.strip(":"):
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "id": identity,
                        "properties": {**normalized, "observed_at": timestamp.isoformat()},
                        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                    }
                )
            return features
        except (httpx.HTTPError, ValueError, TypeError, csv.Error) as exc:
            raise AdapterError(f"{self.key} fetch failed: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()

    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise AdapterError("FIRMS feature is missing properties or geometry")
        coordinates = geometry.get("coordinates")
        source_event_id = str(feature.get("id") or "")
        if not source_event_id or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("FIRMS feature is missing id or coordinates")
        observed_at = parse_datetime(properties.get("observed_at"), fetched_at)
        confidence = str(properties.get("confidence") or "").lower()
        severity = Severity.WARNING.value if confidence in {"nominal", "high", "n", "h"} else Severity.INFO.value
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.FIRE_DETECTION.value,
            title="NASA FIRMS active fire detection",
            summary=(
                f"FRP {properties.get('frp')} MW"
                if properties.get("frp") not in (None, "")
                else "Satellite fire detection"
            ),
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


def _firms_timestamp(properties: dict[str, Any]) -> datetime | None:
    date = str(properties.get("acq_date") or "").strip()
    clock = str(properties.get("acq_time") or "").strip().zfill(4)
    if not date or len(clock) < 4:
        return None
    try:
        return datetime.strptime(f"{date} {clock[:4]}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
