from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class FEMADeclarationsAdapter(SourceAdapter):
    """Normalize FEMA's current designated-county FeatureServer layer."""

    key = "fema_declarations"
    name = "FEMA Current Designated Counties"

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        limit: int = 2000,
    ):
        super().__init__(endpoint, user_agent, timeout_seconds, adapter_version)
        self.max_features = max(1, min(2000, int(limit)))

    @property
    def request_endpoint(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update(
            {
                "where": ["1=1"],
                "outFields": ["*"],
                "returnGeometry": ["true"],
                "outSR": ["4326"],
                "f": ["geojson"],
                "resultRecordCount": [str(self.max_features)],
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
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise AdapterError("FEMA feature is missing properties or geometry")
        source_event_id = _source_id(feature, properties)
        if not source_event_id:
            raise AdapterError("FEMA feature is missing stable designation fields")
        observed_at = _first_datetime(properties, ("lastUpdated", "last_update", "amd_date", "amendmentDate", "fema_postdate", "postDate"), fetched_at)
        effective_at = _first_datetime(properties, ("declarationDate", "declaration_date", "incidentBeginDate"), None)
        expires_at = _first_datetime(properties, ("incidentEndDate", "incident_end_date"), None)
        coordinates = geometry.get("coordinates")
        latitude: float | None = None
        longitude: float | None = None
        if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
            try:
                longitude, latitude = float(coordinates[0]), float(coordinates[1])
            except (TypeError, ValueError) as exc:
                raise AdapterError("FEMA point geometry has invalid coordinates") from exc
        state = _property(properties, "state", "stateAbbreviation", "state_name", "fipsStateCode", "state_fips") or "US"
        area = _property(properties, "designatedArea", "county", "countyName", "name") or "designated county"
        disaster_type = str(_property(properties, "declarationType", "disasterType", "designate", "curr_amd", "amd") or "").upper()
        number = _property(properties, "disasterNumber", "disaster_number", "dec_number", "dec_num")
        title = f"FEMA designation · {state} · {area}"
        summary = " · ".join(value for value in (str(_property(properties, "declarationTitle") or "").strip(), f"Disaster {number}" if number else "") if value) or "Current FEMA designated county"
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.FEMA_DESIGNATION.value,
            title=title,
            summary=summary,
            severity=Severity.WARNING.value if disaster_type == "DR" else Severity.ADVISORY.value,
            status=EventStatus.ACTIVE.value,
            observed_at=observed_at,
            effective_at=effective_at,
            expires_at=expires_at,
            latitude=latitude,
            longitude=longitude,
            geometry=geometry,
            payload=feature,
        )


def _property(properties: dict[str, Any], *names: str) -> Any:
    for name in names:
        if properties.get(name) not in (None, ""):
            return properties[name]
    lowered = {str(key).lower(): value for key, value in properties.items()}
    for name in names:
        if lowered.get(name.lower()) not in (None, ""):
            return lowered[name.lower()]
    return None


def _source_id(feature: dict[str, Any], properties: dict[str, Any]) -> str:
    disaster = _property(properties, "disasterNumber", "disaster_number", "disasterNo", "dec_number", "dec_num")
    state = _property(properties, "state_fips", "fipsStateCode", "stateAbbreviation", "state", "state_name")
    county = _property(properties, "fips", "fipsCountyCode", "cnty_fips", "designatedArea", "county", "countyName", "name")
    designation = _property(properties, "declarationType", "disasterType", "designate", "curr_amd", "amd")
    components = [str(value).strip() for value in (disaster, state, county, designation) if value not in (None, "")]
    return ":".join(components) or str(feature.get("id") or "").strip()


def _first_datetime(properties: dict[str, Any], names: tuple[str, ...], fallback: datetime | None) -> datetime:
    for name in names:
        value = _property(properties, name)
        if value not in (None, ""):
            return parse_datetime(value, fallback)
    return parse_datetime(None, fallback)
