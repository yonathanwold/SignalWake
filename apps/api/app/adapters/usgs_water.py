from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, Severity


class USGSWaterAdapter(SourceAdapter):
    """Bounded normalizer for the public USGS instantaneous-value endpoint."""

    key = "usgs_water"
    name = "United States Geological Survey Water Services"

    def __init__(self, *args, states: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        query_states = parse_qs(urlsplit(self.endpoint).query).get("stateCd", [])
        configured = states or query_states or ["VA"]
        self.coverage_states = tuple(dict.fromkeys(state.strip().upper() for state in configured if state.strip()))[:25]
        self.max_features = 1000

    def _state_endpoint(self, state: str) -> str:
        parsed = urlsplit(self.endpoint)
        query = parse_qs(parsed.query)
        query["format"] = ["json"]
        query["stateCd"] = [state]
        query.setdefault("parameterCd", ["00060"])
        query.setdefault("siteStatus", ["active"])
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            features: list[dict[str, Any]] = []
            errors: list[str] = []
            for state in self.coverage_states:
                try:
                    response = await self._request_with_retries(client, self._state_endpoint(state))
                    body = response.json()
                    series = body.get("value", {}).get("timeSeries", []) if isinstance(body, dict) else []
                    if not isinstance(series, list):
                        raise AdapterError(f"{self.key} response did not contain time series")
                except (httpx.HTTPError, ValueError, TypeError, AdapterError) as exc:
                    errors.append(f"{state}: {exc}")
                    continue
                for item in series:
                    if len(features) >= self.max_features:
                        break
                    if not isinstance(item, dict):
                        continue
                    source_info = item.get("sourceInfo") or {}
                    geo = ((source_info.get("geoLocation") or {}).get("geogLocation") or {})
                    try:
                        longitude, latitude = float(geo["longitude"]), float(geo["latitude"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    values = item.get("values") or []
                    points = values[0].get("value", []) if isinstance(values, list) and values else []
                    latest = points[-1] if isinstance(points, list) and points else {}
                    if not isinstance(latest, dict):
                        latest = {}
                    site_code = str((source_info.get("siteCode") or [{}])[0].get("value") or "")
                    if not site_code:
                        site_code = str(source_info.get("siteName") or "")
                    if not site_code:
                        continue
                    parameter = str((item.get("variable") or {}).get("variableCode", [{}])[0].get("value") or "00060")
                    timestamp = str(latest.get("dateTime") or "")
                    features.append(
                        {
                            "type": "Feature",
                            "id": f"{site_code}:{parameter}:{timestamp}",
                            "properties": {
                                "site_code": site_code,
                                "site_name": source_info.get("siteName"),
                                "state": state,
                                "parameter": parameter,
                                "value": latest.get("value"),
                                "unit": (item.get("variable") or {}).get("unit"),
                                "dateTime": latest.get("dateTime"),
                            },
                            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                        }
                    )
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
            raise AdapterError("USGS water feature is missing properties or geometry")
        source_event_id = str(feature.get("id") or properties.get("site_code") or "")
        coordinates = geometry.get("coordinates")
        if not source_event_id or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("USGS water feature is missing id or coordinates")
        observed_at = parse_datetime(properties.get("dateTime"), fetched_at)
        value = properties.get("value")
        title = str(properties.get("site_name") or properties.get("site_code") or "USGS water observation")
        summary = f"Value {value} {properties.get('unit') or ''}".strip() if value is not None else None
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type="water_level_observation",
            title=title,
            summary=summary,
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
