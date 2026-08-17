from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class USGSAdapter(SourceAdapter):
    key = "usgs"
    name = "United States Geological Survey"

    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise AdapterError("USGS feature is missing properties or geometry")
        source_event_id = str(feature.get("id") or "")
        coordinates = geometry.get("coordinates")
        if not source_event_id or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise AdapterError("USGS feature is missing an id or coordinates")
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        magnitude = properties.get("mag")
        try:
            magnitude_number = float(magnitude)
        except (TypeError, ValueError):
            magnitude_number = 0.0
        severity = (
            Severity.CRITICAL.value
            if magnitude_number >= 6
            else Severity.WARNING.value
            if magnitude_number >= 5
            else Severity.ADVISORY.value
            if magnitude_number >= 4
            else Severity.INFO.value
        )
        observed_at = parse_datetime(
            datetime.fromtimestamp(properties.get("time", 0) / 1000, tz=timezone.utc)
            if isinstance(properties.get("time"), (int, float))
            else None,
            fetched_at,
        )
        title = str(properties.get("title") or "Earthquake observation").strip()
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.EARTHQUAKE.value,
            title=title,
            summary=f"Magnitude {magnitude_number:.1f} · {properties.get('place') or 'Location unavailable'}",
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

