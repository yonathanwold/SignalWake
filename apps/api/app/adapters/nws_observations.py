from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class NWSObservationsAdapter(SourceAdapter):
    """Normalize the bounded NWS latest station-observation GeoJSON feed."""

    key = "nws_observations"
    name = "National Weather Service Station Observations"

    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise AdapterError("NWS observation feature is missing properties or geometry")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("NWS observation feature is missing point coordinates")
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError) as exc:
            raise AdapterError("NWS observation coordinates are not numeric") from exc
        source_event_id = str(feature.get("id") or properties.get("id") or "")
        if not source_event_id:
            raise AdapterError("NWS observation feature is missing an id")
        station = str(properties.get("station") or properties.get("stationIdentifier") or "")
        if station.startswith("https://api.weather.gov/stations/"):
            station = station.rstrip("/").rsplit("/", 1)[-1]
        station = station or "unknown station"
        observed_at = parse_datetime(properties.get("timestamp"), fetched_at)
        description = str(properties.get("textDescription") or "Observation").strip()
        temperature = properties.get("temperature")
        temp_value = temperature.get("value") if isinstance(temperature, dict) else None
        temp_unit = temperature.get("unitCode") if isinstance(temperature, dict) else None
        summary = description
        if temp_value is not None:
            summary = f"{description} · temperature {temp_value} {temp_unit or ''}".strip()
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.WEATHER_OBSERVATION.value,
            title=f"{station} · {description}",
            summary=summary,
            severity=Severity.INFO.value,
            status=EventStatus.OBSERVED.value,
            observed_at=observed_at,
            effective_at=observed_at,
            expires_at=None,
            latitude=latitude,
            longitude=longitude,
            geometry=geometry,
            payload=feature,
        )
