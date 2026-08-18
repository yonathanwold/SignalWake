import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.adapters.base import AdapterError
from app.adapters.nws import NWSAdapter
from app.adapters.nws_observations import NWSObservationsAdapter
from app.adapters.usgs import USGSAdapter
from app.models import EventType

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


def test_extended_event_types_match_adapter_values():
    assert EventType.WEATHER_OBSERVATION.value == "weather_observation"
    assert EventType.WATER_LEVEL_OBSERVATION.value == "water_level_observation"
    assert EventType.TROPICAL_SYSTEM.value == "tropical_system"


@pytest.mark.asyncio
async def test_nws_fixture_normalizes_alert():
    adapter = NWSAdapter("https://example.test/nws", "signalwake-test")
    feature = json.loads((FIXTURES / "nws_alerts.json").read_text())["features"][0]
    normalized = adapter.normalize(feature, datetime(2026, 8, 17, tzinfo=timezone.utc))
    assert normalized.event_type == "weather_alert"
    assert normalized.severity == "warning"
    assert normalized.source_event_id.endswith("001")
    assert normalized.geometry and normalized.geometry["type"] == "Polygon"


@pytest.mark.asyncio
async def test_usgs_fixture_normalizes_magnitude_and_point():
    adapter = USGSAdapter("https://example.test/usgs", "signalwake-test")
    feature = json.loads((FIXTURES / "usgs_earthquakes.json").read_text())["features"][0]
    normalized = adapter.normalize(feature, datetime(2026, 8, 17, tzinfo=timezone.utc))
    assert normalized.event_type == "earthquake"
    assert normalized.severity == "advisory"
    assert normalized.latitude == 34.0522
    assert normalized.longitude == -118.2437


@pytest.mark.asyncio
async def test_nws_observation_fixture_normalizes_station_point_and_timestamp():
    adapter = NWSObservationsAdapter("https://example.test/nws-observations", "signalwake-test")
    feature = json.loads((FIXTURES / "nws_observations.json").read_text())["features"][0]
    normalized = adapter.normalize(feature, datetime(2026, 8, 18, tzinfo=timezone.utc))
    assert normalized.event_type == "weather_observation"
    assert normalized.source_event_id.endswith("2026-08-18T14:00:00Z")
    assert normalized.title.startswith("KDCA")
    assert normalized.latitude == 38.8512
    assert normalized.longitude == -77.0377
    assert normalized.observed_at == datetime(2026, 8, 18, 14, tzinfo=timezone.utc)
    assert normalized.geometry == feature["geometry"]


@pytest.mark.asyncio
async def test_fetch_rejects_malformed_feature_collection():
    adapter = NWSAdapter("https://example.test/nws", "signalwake-test")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"features": {}}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AdapterError, match="feature list"):
            await adapter.fetch(client)
