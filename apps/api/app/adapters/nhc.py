from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, Severity


class NHCAdapter(SourceAdapter):
    """Normalize the NHC CurrentStorms JSON without inventing positions."""

    key = "nhc"
    name = "National Hurricane Center"

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await self._request_with_retries(client)
            body = response.json()
            raw_storms = body.get("activeStorms", body.get("storms", [])) if isinstance(body, dict) else body
            if not isinstance(raw_storms, list):
                raise AdapterError(f"{self.key} response did not contain a storm list")
            features: list[dict[str, Any]] = []
            for storm in raw_storms[:100]:
                if not isinstance(storm, dict):
                    continue
                latitude = storm.get("lat", storm.get("latitude"))
                longitude = storm.get("lon", storm.get("longitude"))
                try:
                    latitude, longitude = float(latitude), float(longitude)
                except (TypeError, ValueError):
                    continue
                storm_id = str(storm.get("id") or storm.get("bin_number") or storm.get("name") or "")
                if not storm_id:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "id": storm_id,
                        "properties": storm,
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
            raise AdapterError("NHC feature is missing properties or geometry")
        source_event_id = str(feature.get("id") or properties.get("id") or "")
        coordinates = geometry.get("coordinates")
        if not source_event_id or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("NHC feature is missing id or coordinates")
        observed_at = parse_datetime(
            properties.get("lastUpdate") or properties.get("last_update") or properties.get("issued"),
            fetched_at,
        )
        classification = str(properties.get("classification") or properties.get("type") or "").lower()
        severity = Severity.WARNING.value if "hurricane" in classification else Severity.ADVISORY.value
        name = str(properties.get("name") or source_event_id).strip()
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type="tropical_system",
            title=f"NHC {name}",
            summary=properties.get("headline") or properties.get("classification"),
            severity=severity,
            status=EventStatus.ACTIVE.value,
            observed_at=observed_at,
            effective_at=observed_at,
            expires_at=None,
            latitude=float(coordinates[1]),
            longitude=float(coordinates[0]),
            geometry=geometry,
            payload=feature,
        )
