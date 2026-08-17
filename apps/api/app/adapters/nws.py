from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters.base import AdapterError, NormalizedEvent, SourceAdapter, parse_datetime
from app.models import EventStatus, EventType, Severity


class NWSAdapter(SourceAdapter):
    key = "nws"
    name = "National Weather Service"

    def normalize(self, feature: dict[str, Any], fetched_at: datetime | None = None) -> NormalizedEvent:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise AdapterError("NWS feature has no properties object")
        source_event_id = str(properties.get("id") or feature.get("id") or "")
        title = str(properties.get("headline") or properties.get("event") or "Weather alert").strip()
        if not source_event_id or not title:
            raise AdapterError("NWS feature is missing an id or title")
        severity_value = str(properties.get("severity") or "Unknown").lower()
        severity = {
            "extreme": Severity.CRITICAL.value,
            "severe": Severity.WARNING.value,
            "moderate": Severity.ADVISORY.value,
            "minor": Severity.INFO.value,
        }.get(severity_value, Severity.INFO.value)
        status = str(properties.get("status") or "Actual").lower()
        event_status = EventStatus.ACTIVE.value if status in {"actual", "active"} else EventStatus.OBSERVED.value
        effective_at = parse_datetime(properties.get("effective"), fetched_at)
        expires_at = parse_datetime(properties.get("expires"), None) if properties.get("expires") else None
        return NormalizedEvent(
            source_event_id=source_event_id,
            event_type=EventType.WEATHER_ALERT.value,
            title=title,
            summary=properties.get("description") or properties.get("instruction"),
            severity=severity,
            status=event_status,
            observed_at=effective_at,
            effective_at=effective_at,
            expires_at=expires_at,
            latitude=None,
            longitude=None,
            geometry=feature.get("geometry") if isinstance(feature.get("geometry"), dict) else None,
            payload=feature,
        )

