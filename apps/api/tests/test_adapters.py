import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.adapters.airnow import AirNowAdapter
from app.adapters.base import AdapterError
from app.adapters.coops import COOPSAdapter
from app.adapters.firms import FIRMSAdapter
from app.adapters.nws import NWSAdapter
from app.adapters.nws_observations import NWSObservationsAdapter
from app.adapters.usgs import USGSAdapter
from app.adapters.usgs_water import USGSWaterAdapter
from app.models import EventType

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


def test_extended_event_types_match_adapter_values():
    assert EventType.WEATHER_OBSERVATION.value == "weather_observation"
    assert EventType.WATER_LEVEL_OBSERVATION.value == "water_level_observation"
    assert EventType.TROPICAL_SYSTEM.value == "tropical_system"
    assert EventType.FIRE_DETECTION.value == "fire_detection"
    assert EventType.AIR_QUALITY_OBSERVATION.value == "air_quality_observation"
    assert EventType.COOPS_WATER_LEVEL.value == "coops_water_level"


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


@pytest.mark.asyncio
async def test_firms_csv_normalizes_exact_point_and_provider_timestamp():
    adapter = FIRMSAdapter(
        "https://example.test/firms",
        "signalwake-test",
        map_key="real-key",
        area="USA",
        product="VIIRS_SNPP_NRT",
    )
    csv_body = "latitude,longitude,acq_date,acq_time,satellite,confidence,frp\n38.85,-77.03,2026-08-18,1430,N,nominal,12.4\n"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=csv_body))
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    assert features[0]["geometry"] == {"type": "Point", "coordinates": [-77.03, 38.85]}
    normalized = adapter.normalize(features[0])
    assert normalized.event_type == "fire_detection"
    assert normalized.observed_at == datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_airnow_json_normalizes_station_coordinates_and_timestamp():
    adapter = AirNowAdapter("https://example.test/airnow", "signalwake-test", api_key="real-key")
    body = [{"Latitude": 38.85, "Longitude": -77.03, "UTC": "2026-08-18T14:00:00Z", "Site": "KDCA", "Parameter": "PM25", "AQI": 81}]
    request_params: dict[str, str] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        request_params.update({key: value for key, value in request.url.params.items()})
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    start = datetime.strptime(request_params["startDate"], "%Y-%m-%dT%H-%M%S").replace(tzinfo=timezone.utc)
    end = datetime.strptime(request_params["endDate"], "%Y-%m-%dT%H-%M%S").replace(tzinfo=timezone.utc)
    assert end > start
    assert end - start <= timedelta(hours=48)
    assert request_params["startDate"].endswith("-0000")
    assert request_params["endDate"].endswith("-0000")
    normalized = adapter.normalize(features[0])
    assert normalized.event_type == "air_quality_observation"
    assert normalized.latitude == 38.85
    assert normalized.longitude == -77.03
    assert normalized.observed_at == datetime(2026, 8, 18, 14, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_coops_uses_provider_metadata_coordinates_and_latest_reading():
    adapter = COOPSAdapter(
        "https://example.test/metadata",
        "signalwake-test",
        data_endpoint="https://example.test/data",
        station_limit=2,
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("metadata"):
            return httpx.Response(200, json={"stations": [{"id": "8410140", "name": "Test Harbor", "lat": 38.85, "lng": -77.03}]})
        return httpx.Response(200, json={"data": [{"t": "2026-08-18 14:00", "v": "1.23", "q": "v"}]})

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    assert features[0]["geometry"] == {"type": "Point", "coordinates": [-77.03, 38.85]}
    normalized = adapter.normalize(features[0])
    assert normalized.event_type == "coops_water_level"
    assert normalized.observed_at == datetime(2026, 8, 18, 14, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_usgs_water_fans_out_only_configured_states_and_caps_request_shape():
    adapter = USGSWaterAdapter(
        "https://example.test/iv/?format=json&parameterCd=00060",
        "signalwake-test",
        states=["VA", "CA"],
    )
    requested_states: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        state = request.url.params.get("stateCd")
        assert state is not None
        requested_states.append(state)
        return httpx.Response(
            200,
            json={
                "value": {
                    "timeSeries": [
                        {
                            "sourceInfo": {
                                "siteName": f"Gauge {state}",
                                "siteCode": [{"value": f"{state}-001"}],
                                "geoLocation": {"geogLocation": {"latitude": "38.8", "longitude": "-77.0"}},
                            },
                            "variable": {"variableCode": [{"value": "00060"}], "unit": "ft3/s"},
                            "values": [{"value": [{"dateTime": "2026-08-18T14:00:00Z", "value": "4.2"}]}],
                        }
                    ]
                }
            },
        )

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    assert requested_states == ["VA", "CA"]
    assert len(features) == 2
    assert features[0]["geometry"]["coordinates"] == [-77.0, 38.8]


@pytest.mark.asyncio
async def test_credentialed_adapters_without_keys_return_no_records_without_network():
    firms = FIRMSAdapter("https://example.test/firms", "signalwake-test")
    airnow = AirNowAdapter("https://example.test/airnow", "signalwake-test")
    transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("network should not be called")))
    async with httpx.AsyncClient(transport=transport) as client:
        assert await firms.fetch(client) == []
        assert await airnow.fetch(client) == []
