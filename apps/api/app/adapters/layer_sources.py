from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from app.adapters.base import AdapterError


class BoundedLayerAdapter:
    """Small, non-event adapter for map-ready fields and reference assets."""

    def __init__(self, endpoint: str, user_agent: str, timeout_seconds: float = 15.0):
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.last_http_status: int | None = None

    async def _json(self, client: httpx.AsyncClient | None = None, *, endpoint: str | None = None, headers: dict[str, str] | None = None) -> Any:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
        self.last_http_status = None
        try:
            response = await client.get(endpoint or self.endpoint, headers={"Accept": "application/json", "User-Agent": self.user_agent, **(headers or {})})
            self.last_http_status = response.status_code
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AdapterError(f"layer fetch failed: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()


class OpenMeteoAdapter(BoundedLayerAdapter):
    key = "open_meteo"
    name = "Open-Meteo Model Fields"

    def __init__(self, endpoint: str, user_agent: str, timeout_seconds: float = 15.0, *, coordinates: str, past_hours: int = 6, limit: int = 108):
        super().__init__(endpoint, user_agent, timeout_seconds)
        self.coordinates = _coordinates(coordinates)[: max(1, min(200, int(limit)))]
        self.past_hours = max(1, min(24, int(past_hours)))
        self.max_features = len(self.coordinates)

    def request_endpoint(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update(
            {
                "latitude": [",".join(str(item[1]) for item in self.coordinates)],
                "longitude": [",".join(str(item[0]) for item in self.coordinates)],
                "current": ["temperature_2m,precipitation,wind_speed_10m"],
                "past_hours": [str(self.past_hours)],
                "forecast_days": ["1"],
                "timezone": ["UTC"],
            }
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
        if not self.coordinates:
            return []
        body = await self._json(client, endpoint=self.request_endpoint())
        responses = body if isinstance(body, list) else [body]
        features: list[dict[str, Any]] = []
        for index, response in enumerate(responses[: self.max_features]):
            if not isinstance(response, dict):
                continue
            current = response.get("current") if isinstance(response.get("current"), dict) else {}
            latitude = _number(response.get("latitude"))
            longitude = _number(response.get("longitude"))
            if latitude is None or longitude is None:
                if index >= len(self.coordinates):
                    continue
                longitude, latitude = self.coordinates[index]
            timestamp = str(current.get("time") or response.get("current_time") or datetime.now(timezone.utc).isoformat())
            features.append(
                {
                    "type": "Feature",
                    "id": f"open-meteo:{latitude:.4f}:{longitude:.4f}:{timestamp}",
                    "properties": {
                        "classification": "MODEL_FIELD",
                        "model": response.get("model") or "Open-Meteo forecast model",
                        "model_timestamp": timestamp,
                        "variables": {key: current.get(key) for key in ("temperature_2m", "precipitation", "wind_speed_10m") if key in current},
                        "source": self.key,
                        "provenance": {"endpoint": self.endpoint, "request": self.request_endpoint()},
                    },
                    "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                }
            )
        return features


class RainViewerAdapter(BoundedLayerAdapter):
    key = "rainviewer"
    name = "RainViewer Radar"

    async def fetch_metadata(self, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        body = await self._json(client)
        if not isinstance(body, dict):
            raise AdapterError("rainviewer response was not an object")
        host = str(body.get("host") or "https://tilecache.rainviewer.com").rstrip("/")
        radar = body.get("radar") if isinstance(body.get("radar"), dict) else {}
        frames = radar.get("past") if isinstance(radar.get("past"), list) else []
        frame = next((item for item in reversed(frames) if isinstance(item, dict) and item.get("path") and item.get("time")), None)
        if not isinstance(frame, dict):
            raise AdapterError("rainviewer metadata contained no past radar frame")
        path = str(frame["path"])
        try:
            timestamp = datetime.fromtimestamp(float(frame["time"]), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise AdapterError("rainviewer metadata contained an invalid frame timestamp") from exc
        return {
            "status": "LIVE",
            "timestamp": timestamp,
            "tile_url_template": f"{host}{path}/256/{{z}}/{{x}}/{{y}}/2/1_1.png",
            "attribution": "RainViewer radar data",
            "source_url": self.endpoint,
            "frame": frame,
            "provenance": {"endpoint": self.endpoint, "frame": frame},
        }


class NPPESAdapter(BoundedLayerAdapter):
    key = "nppes"
    name = "CMS NPPES Provider Locations"

    def __init__(self, endpoint: str, user_agent: str, timeout_seconds: float = 15.0, *, state: str = "VA", limit: int = 200):
        super().__init__(endpoint, user_agent, timeout_seconds)
        self.state = state.strip().upper()
        self.max_features = max(1, min(200, int(limit)))

    def request_endpoint(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update({"version": ["2.1"], "state": [self.state], "enumeration_type": ["NPI-2"], "address_purpose": ["LOCATION"], "limit": [str(self.max_features)]})
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
        body = await self._json(client, endpoint=self.request_endpoint())
        rows = body.get("results") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise AdapterError("nppes response did not contain results")
        features: list[dict[str, Any]] = []
        for row in rows[: self.max_features]:
            if not isinstance(row, dict):
                continue
            addresses = row.get("addresses") if isinstance(row.get("addresses"), list) else []
            address = next((item for item in addresses if isinstance(item, dict) and item.get("address_purpose") == "LOCATION"), None)
            if not isinstance(address, dict):
                continue
            longitude = _number(address.get("longitude"))
            latitude = _number(address.get("latitude"))
            if latitude is None or longitude is None:
                continue
            npi = str(row.get("number") or "").strip()
            if not npi:
                continue
            basic = row.get("basic") if isinstance(row.get("basic"), dict) else {}
            name = str(basic.get("organization_name") or basic.get("name") or npi)
            features.append({"type": "Feature", "id": f"nppes:{npi}", "properties": {"classification": "REFERENCE", "npi": npi, "name": name, "state": address.get("state"), "source": self.key, "payload": row}, "geometry": {"type": "Point", "coordinates": [longitude, latitude]}})
        return features


class CensusStatesAdapter(BoundedLayerAdapter):
    key = "census"
    name = "U.S. Census State Geography"

    def __init__(self, endpoint: str, user_agent: str, timeout_seconds: float = 15.0, *, limit: int = 60):
        super().__init__(endpoint, user_agent, timeout_seconds)
        self.max_features = max(1, min(60, int(limit)))

    def request_endpoint(self) -> str:
        parts = urlsplit(self.endpoint)
        query = parse_qs(parts.query)
        query.update({"resultRecordCount": [str(self.max_features)], "returnGeometry": ["true"], "outSR": ["4326"], "f": ["geojson"]})
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
        body = await self._json(client, endpoint=self.request_endpoint())
        rows = body.get("features") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise AdapterError("census response did not contain GeoJSON features")
        return [row for row in rows[: self.max_features] if isinstance(row, dict) and isinstance(row.get("geometry"), dict)]


def _coordinates(value: str) -> list[tuple[float, float]]:
    output: list[tuple[float, float]] = []
    for item in value.split(";"):
        try:
            latitude, longitude = [float(part.strip()) for part in item.split(",", 1)]
        except (TypeError, ValueError):
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            output.append((longitude, latitude))
    return output


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None
