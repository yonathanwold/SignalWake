import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.adapters.airnow import AirNowAdapter
from app.adapters.aviation_weather import AviationWeatherAdapter
from app.adapters.base import AdapterError
from app.adapters.coops import COOPSAdapter
from app.adapters.eonet import EONETAdapter
from app.adapters.fema import FEMADeclarationsAdapter
from app.adapters.firms import FIRMSAdapter
from app.adapters.layer_sources import (
    CensusStatesAdapter,
    NPPESAdapter,
    OpenMeteoAdapter,
    RainViewerAdapter,
)
from app.adapters.nws import NWSAdapter
from app.adapters.nws_observations import NWSObservationsAdapter
from app.adapters.opensky import OpenSkyAdapter
from app.adapters.road511 import Road511Adapter
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
    assert EventType.NATURAL_EVENT.value == "natural_event"
    assert EventType.AVIATION_REPORT.value == "aviation_report"
    assert EventType.FEMA_DESIGNATION.value == "fema_designation"
    assert EventType.TRAFFIC_EVENT.value == "traffic_event"


@pytest.mark.asyncio
async def test_road511_requires_key_and_normalizes_bounded_event():
    adapter = Road511Adapter("https://api.road511.com/api/v1/events", "signalwake-test", api_key="real-key", bbox="-130,20,-60,55", jurisdiction="WA", limit=2)
    request_params: dict[str, str] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        request_params.update({key: value for key, value in request.url.params.items()})
        assert request.headers["X-API-Key"] == "real-key"
        return httpx.Response(200, json={"data": [{"id": "WA-1", "title": "Closure", "severity": "major", "latitude": 46.4, "longitude": -123.8, "start_time": "2026-08-18T14:00:00Z"}]})

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    assert request_params["jurisdiction"] == "WA"
    assert request_params["limit"] == "2"
    assert features[0]["geometry"] == {"type": "Point", "coordinates": [-123.8, 46.4]}
    assert adapter.normalize(features[0]).event_type == "traffic_event"
    assert await Road511Adapter("https://example.test", "signalwake-test").fetch(client) == []


@pytest.mark.asyncio
async def test_open_meteo_model_field_and_reference_layers_preserve_geometry():
    meteo = OpenMeteoAdapter("https://example.test/open-meteo", "signalwake-test", coordinates="35,-78;40,-75", limit=2)
    nppes = NPPESAdapter("https://example.test/nppes", "signalwake-test", state="VA", limit=2)
    census = CensusStatesAdapter("https://example.test/census", "signalwake-test", limit=2)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("open-meteo"):
            return httpx.Response(200, json=[{"latitude": 35, "longitude": -78, "current": {"time": "2026-08-18T14:00", "temperature_2m": 27.0}}])
        if request.url.path.endswith("nppes"):
            return httpx.Response(200, json={"results": [{"number": "1234567890", "basic": {"organization_name": "Test Clinic"}, "addresses": [{"address_purpose": "LOCATION", "latitude": "38.85", "longitude": "-77.03", "state": "VA"}]}]})
        return httpx.Response(200, json={"features": [{"type": "Feature", "id": "state-VA", "properties": {"NAME": "Virginia"}, "geometry": {"type": "Polygon", "coordinates": [[[1, 2], [3, 4], [1, 2]]]}}]})

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        model_features = await meteo.fetch(client)
        provider_features = await nppes.fetch(client)
        census_features = await census.fetch(client)
    query = httpx.URL(meteo.request_endpoint()).params
    assert len(query["latitude"].split(",")) == 2
    assert query["past_hours"] == "6"
    assert model_features[0]["properties"]["classification"] == "MODEL_FIELD"
    assert model_features[0]["geometry"]["coordinates"] == [-78.0, 35.0]
    assert provider_features[0]["geometry"]["coordinates"] == [-77.03, 38.85]
    assert census_features[0]["geometry"]["type"] == "Polygon"


@pytest.mark.asyncio
async def test_rainviewer_metadata_builds_provider_tile_template():
    adapter = RainViewerAdapter("https://example.test/rainviewer", "signalwake-test")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"host": "https://tiles.example", "radar": {"past": [{"time": 1787050000, "path": "/v2/radar/1787050000"}]}}))
    async with httpx.AsyncClient(transport=transport) as client:
        metadata = await adapter.fetch_metadata(client)
    assert metadata["tile_url_template"].startswith("https://tiles.example/v2/radar/")
    assert "{z}/{x}/{y}" in metadata["tile_url_template"]


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


@pytest.mark.asyncio
async def test_eonet_bounds_request_and_preserves_latest_polygon_geometry():
    adapter = EONETAdapter(
        "https://example.test/eonet?status=all",
        "signalwake-test",
        bbox="-130,55,-60,20",
        days=2,
        limit=3,
    )
    requests: list[httpx.QueryParams] = []
    body = {
        "features": [
            {
                "id": "EONET_123",
                "properties": {
                    "title": "Test natural event",
                    "description": "Provider description",
                    "categories": [{"id": "wildfires", "title": "Wildfires"}],
                },
                "geometry": [
                    {"date": "2026-08-18T12:00:00Z", "type": "Polygon", "coordinates": [[[1, 2], [3, 4], [1, 2]]]},
                    {"date": "2026-08-18T14:00:00Z", "type": "Polygon", "coordinates": [[[5, 6], [7, 8], [5, 6]]]},
                ],
            }
        ]
    }

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.params)
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    assert requests[0]["days"] == "2"
    assert requests[0]["limit"] == "3"
    assert requests[0]["bbox"] == "-130,55,-60,20"
    normalized = adapter.normalize(features[0])
    assert normalized.event_type == "natural_event"
    assert normalized.severity == "warning"
    assert normalized.observed_at == datetime(2026, 8, 18, 14, tzinfo=timezone.utc)
    assert normalized.geometry == body["features"][0]["geometry"][1]
    assert normalized.latitude is None and normalized.longitude is None


@pytest.mark.asyncio
async def test_aviation_weather_204_is_successful_empty_and_query_is_bounded():
    adapter = AviationWeatherAdapter("https://example.test/pirep?format=json", "signalwake-test", age_hours=48, limit=400)
    request_params: dict[str, str] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        request_params.update({key: value for key, value in request.url.params.items()})
        return httpx.Response(204)

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    assert features == []
    assert adapter.last_http_status == 204
    assert request_params == {"format": "geojson", "age": "48"}


@pytest.mark.asyncio
async def test_aviation_weather_normalizes_provider_epoch_and_exact_point():
    adapter = AviationWeatherAdapter("https://example.test/pirep", "signalwake-test")
    feature = {
        "type": "Feature",
        "id": "PIREP-7",
        "properties": {"hazard": "TURB", "intensity": "SEVERE", "obsTime": 1787061600000, "raw": "UA /OV DCA"},
        "geometry": {"type": "Point", "coordinates": [-77.04, 38.85]},
    }
    normalized = adapter.normalize(feature)
    assert normalized.event_type == "aviation_report"
    assert normalized.severity == "warning"
    assert normalized.observed_at == datetime(2026, 8, 18, 14, tzinfo=timezone.utc)
    assert normalized.geometry == feature["geometry"]
    assert normalized.latitude == 38.85 and normalized.longitude == -77.04


@pytest.mark.asyncio
async def test_fema_bounds_request_and_preserves_current_designated_polygon():
    adapter = FEMADeclarationsAdapter("https://example.test/fema/query", "signalwake-test", limit=7)
    request_params: dict[str, str] = {}
    feature = {
        "type": "Feature",
        "id": "fid-1",
        "properties": {
            "dec_number": 1234,
            "state_name": "Virginia",
            "state_fips": "51",
            "cnty_fips": "001",
            "name": "Example County",
            "designate": "DR",
            "declarationTitle": "Flood",
            "fema_postdate": "2026-08-18T14:00:00Z",
        },
        "geometry": {"type": "Polygon", "coordinates": [[[1, 2], [3, 4], [1, 2]]]},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        request_params.update({key: value for key, value in request.url.params.items()})
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [feature]})

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as client:
        features = await adapter.fetch(client)
    assert request_params["resultRecordCount"] == "7"
    assert request_params["returnGeometry"] == "true"
    assert request_params["outSR"] == "4326"
    normalized = adapter.normalize(features[0])
    assert normalized.source_event_id == "1234:51:001:DR"
    assert normalized.event_type == "fema_designation"
    assert normalized.severity == "warning"
    assert normalized.observed_at == datetime(2026, 8, 18, 14, tzinfo=timezone.utc)
    assert normalized.geometry == feature["geometry"]


def _opensky_state(icao24: str = "abc123") -> list[object]:
    return [icao24, "TEST123 ", "United States", 1787061600, 1787061605, -77.03, 38.85, 9200.0, False, 210.5, 180.0, -1.2, None, 9180.0, None, None, 0, 2]


@pytest.mark.asyncio
async def test_opensky_normalizes_stable_identity_provider_time_and_observation_class():
    adapter = OpenSkyAdapter("https://example.test/states/all", "signalwake-test")
    feature = adapter.to_feature(_opensky_state())
    normalized = adapter.normalize(feature)
    assert normalized.source_event_id == "abc123"
    assert normalized.event_type == "aircraft_observation"
    assert normalized.severity == "info"
    assert normalized.latitude == 38.85
    assert normalized.longitude == -77.03
    assert normalized.observed_at == datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)
    assert feature["properties"]["classification"] == "OBSERVATION"


@pytest.mark.asyncio
async def test_opensky_fetch_is_bounded_and_surfaces_429_without_last_known_good():
    adapter = OpenSkyAdapter("https://example.test/states/all", "signalwake-test", refresh_seconds=15)
    request_params: dict[str, str] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        request_params.update({key: value for key, value in request.url.params.items()})
        return httpx.Response(429, text="rate limited")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AdapterError, match="429"):
            await adapter.fetch(client)
    assert request_params == {"lamin": "24", "lomin": "-125", "lamax": "50", "lomax": "-66"}
    assert adapter.last_http_status == 429
