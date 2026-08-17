import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.adapters.base import AdapterError
from app.adapters.nws import NWSAdapter
from app.adapters.usgs import USGSAdapter

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


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
async def test_fetch_rejects_malformed_feature_collection():
    adapter = NWSAdapter("https://example.test/nws", "signalwake-test")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"features": {}}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AdapterError, match="feature list"):
            await adapter.fetch(client)

