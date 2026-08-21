from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity
from app.observability import bounded_text


class OpenSkyAdapter(SourceAdapter):
    """Bounded OpenSky state-vector observations for the operational map.

    OpenSky returns positional arrays rather than GeoJSON.  This adapter keeps
    the provider's identity and timestamps intact and turns each current state
    into a point feature without assigning hazard/severity semantics.
    """

    key = "opensky"
    name = "OpenSky Network"

    # OpenSky's documented state-vector column order.  A few optional columns
    # were added over time, so normalization always guards the array length.
    _FIELDS = (
        "icao24",
        "callsign",
        "origin_country",
        "time_position",
        "last_contact",
        "longitude",
        "latitude",
        "baro_altitude",
        "on_ground",
        "velocity",
        "true_track",
        "vertical_rate",
        "sensors",
        "geo_altitude",
        "squawk",
        "spi",
        "position_source",
        "category",
    )

    def __init__(
        self,
        endpoint: str,
        user_agent: str,
        timeout_seconds: float = 15.0,
        adapter_version: str = "1.0.0",
        *,
        bbox: str = "24,-125,50,-66",
        limit: int = 8000,
        refresh_seconds: int = 90,
    ):
        super().__init__(endpoint, user_agent, timeout_seconds, adapter_version)
        self.bbox = _validate_bbox(bbox)
        self.max_features = max(1, min(10000, int(limit)))
        self.refresh_seconds = max(15, min(900, int(refresh_seconds)))
        self._cache_features: list[dict[str, Any]] | None = None
        self._cache_fetched_at: datetime | None = None
        self.last_error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def request_endpoint(self) -> str:
        min_lat, min_lon, max_lat, max_lon = self.bbox
        return (
            f"{self.endpoint}?lamin={min_lat:g}&lomin={min_lon:g}"
            f"&lamax={max_lat:g}&lomax={max_lon:g}"
        )

    @property
    def status(self) -> str:
        return "DEGRADED" if self.last_error and self._cache_features is not None else "LIVE"

    @property
    def cache_age_seconds(self) -> int | None:
        if self._cache_fetched_at is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - self._cache_fetched_at).total_seconds()))

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Any]:
        """Fetch current CONUS states with a conservative LKG cache.

        A fresh cache avoids spending anonymous OpenSky credits on repeated map
        loads.  If a refresh fails, the last successful state vector is returned
        and the caller can expose the degraded status and error honestly.
        """

        async with self._lock:
            if self._cache_features is not None and (self.cache_age_seconds or 0) < self.refresh_seconds:
                return list(self._cache_features)
            own_client = client is None
            client = client or httpx.AsyncClient(timeout=self.timeout_seconds)
            self.last_http_status = None
            try:
                response = await self._request_with_retries(client, self.request_endpoint)
                body = response.json()
                states = body.get("states") if isinstance(body, dict) else None
                if states is None:
                    states = []
                if not isinstance(states, list):
                    raise AdapterError(f"{self.key} response did not contain a state list")
                fetched_at = datetime.now(timezone.utc)
                features: list[dict[str, Any]] = []
                for state in states[: self.max_features]:
                    try:
                        features.append(self.to_feature(state, fetched_at))
                    except (AdapterError, TypeError, ValueError):
                        continue
                self._cache_features = features
                self._cache_fetched_at = fetched_at
                self.last_error = None
                return list(features)
            except (httpx.HTTPError, ValueError, TypeError, AdapterError) as exc:
                self.last_error = bounded_text(exc) or "OpenSky fetch failed"
                if self._cache_features is not None:
                    return list(self._cache_features)
                raise AdapterError(f"{self.key} fetch failed: {self.last_error}") from exc
            finally:
                if own_client:
                    await client.aclose()

    def normalize(self, state: Any, fetched_at: datetime | None = None) -> NormalizedEvent:
        if isinstance(state, dict) and state.get("type") == "Feature":
            geometry = state.get("geometry")
            properties = state.get("properties")
            if not isinstance(geometry, dict) or not isinstance(properties, dict):
                raise AdapterError("OpenSky feature is missing geometry or properties")
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                raise AdapterError("OpenSky feature is missing coordinates")
            payload = properties.get("state") if isinstance(properties.get("state"), list) else state
            icao24 = str(properties.get("icao24") or state.get("id") or "").strip().lower()
            if not icao24:
                raise AdapterError("OpenSky state is missing icao24")
            observed_at = _state_time(payload, fetched_at)
            return NormalizedEvent(
                source_event_id=icao24,
                event_type=EventType.AIRCRAFT_OBSERVATION.value,
                title=_aircraft_title(properties),
                summary=_aircraft_summary(properties),
                severity=Severity.INFO.value,
                status=EventStatus.OBSERVED.value,
                observed_at=observed_at,
                effective_at=observed_at,
                expires_at=None,
                latitude=float(coordinates[1]),
                longitude=float(coordinates[0]),
                geometry=geometry,
                payload=payload if isinstance(payload, dict) else state,
            )
        if not isinstance(state, list):
            raise AdapterError("OpenSky state is not an array")
        feature = self.to_feature(state, fetched_at)
        return self.normalize(feature, fetched_at)

    def to_feature(self, state: Any, fetched_at: datetime | None = None) -> dict[str, Any]:
        if not isinstance(state, list):
            raise AdapterError("OpenSky state is not an array")
        fields = {name: state[index] if index < len(state) else None for index, name in enumerate(self._FIELDS)}
        icao24 = str(fields.get("icao24") or "").strip().lower()
        longitude, latitude = _number(fields.get("longitude")), _number(fields.get("latitude"))
        if not icao24 or latitude is None or longitude is None:
            raise AdapterError("OpenSky state is missing identity or coordinates")
        observed_at = _state_time(state, fetched_at)
        properties = {
            "icao24": icao24,
            "callsign": str(fields.get("callsign") or "").strip() or None,
            "origin_country": fields.get("origin_country"),
            "observed_at": observed_at.isoformat(),
            "last_contact": _epoch_iso(fields.get("last_contact")),
            "time_position": _epoch_iso(fields.get("time_position")),
            "baro_altitude": fields.get("baro_altitude"),
            "geo_altitude": fields.get("geo_altitude"),
            "on_ground": bool(fields.get("on_ground")) if fields.get("on_ground") is not None else None,
            "velocity": fields.get("velocity"),
            "true_track": fields.get("true_track"),
            "vertical_rate": fields.get("vertical_rate"),
            "category": fields.get("category"),
            "classification": "OBSERVATION",
            "source": self.key,
            "state": state,
        }
        return {
            "type": "Feature",
            "id": icao24,
            "properties": properties,
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        }


def _validate_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(item.strip()) for item in value.split(",")]
        if len(parts) != 4:
            raise ValueError
        min_lat, min_lon, max_lat, max_lon = parts
        if not (-90 <= min_lat < max_lat <= 90 and -180 <= min_lon < max_lon <= 180):
            raise ValueError
        return min_lat, min_lon, max_lat, max_lon
    except (TypeError, ValueError) as exc:
        raise ValueError("OPENSKY_BBOX must be minLat,minLon,maxLat,maxLon") from exc


def _number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _epoch_iso(value: Any) -> str | None:
    numeric = _number(value)
    if numeric is None:
        return None
    return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()


def _state_time(state: Any, fallback: datetime | None) -> datetime:
    values: list[Any] = []
    if isinstance(state, list):
        values = [state[3] if len(state) > 3 else None, state[4] if len(state) > 4 else None]
    elif isinstance(state, dict):
        values = [state.get("time_position"), state.get("last_contact")]
    for value in values:
        numeric = _number(value)
        if numeric is not None:
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        if isinstance(value, str) and value:
            parsed = parse_datetime(value, None)
            if parsed:
                return parsed
    return parse_datetime(None, fallback)


def _aircraft_title(properties: dict[str, Any]) -> str:
    callsign = str(properties.get("callsign") or "").strip()
    icao24 = str(properties.get("icao24") or "").strip().upper()
    return f"{callsign} · {icao24}" if callsign else f"Aircraft · {icao24}"


def _aircraft_summary(properties: dict[str, Any]) -> str | None:
    country = str(properties.get("origin_country") or "").strip()
    on_ground = properties.get("on_ground")
    state = "ON GROUND" if on_ground else "AIRBORNE" if on_ground is not None else None
    values = [item for item in (country, state) if item]
    return " · ".join(values) or None
