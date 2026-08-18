from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.nws import NWSAdapter
from app.adapters.nws_observations import NWSObservationsAdapter
from app.ingest import ensure_source, persist_normalized
from app.main import app
from app.repository import list_events
from app.temporal import TemporalWindow


def _nws_feature(event_id: str, *, effective: datetime, expires: datetime | None = None) -> dict:
    properties = {
        "id": event_id,
        "headline": event_id,
        "severity": "Moderate",
        "effective": effective.isoformat(),
    }
    if expires is not None:
        properties["expires"] = expires.isoformat()
    return {"type": "Feature", "id": event_id, "properties": properties, "geometry": None}


@pytest.mark.asyncio
async def test_operational_window_includes_validity_overlap_but_not_old_events(db_factory):
    now = datetime.now(timezone.utc)
    adapter = NWSAdapter("https://example.test/nws", "signalwake-test")
    async with db_factory() as session:
        source = await ensure_source(session, adapter)
        old = adapter.normalize(
            _nws_feature("old", effective=now - timedelta(hours=50), expires=now - timedelta(hours=49)), now
        )
        active_overlap = adapter.normalize(
            _nws_feature("overlap", effective=now - timedelta(hours=72), expires=now + timedelta(hours=1)), now
        )
        await persist_normalized(
            session, source, adapter, old, fetched_at=now - timedelta(hours=49), classification="LIVE"
        )
        await persist_normalized(session, source, adapter, active_overlap, classification="LIVE")
        await session.commit()
        rows, total, _ = await list_events(
            session,
            window=TemporalWindow(now - timedelta(hours=48), now),
            limit=20,
        )
    assert total == 1
    assert [item.source_event_id for item in rows] == ["overlap"]


@pytest.mark.asyncio
async def test_catalog_and_unavailable_layer_never_emit_fake_records(db_factory):
    app.state.session_factory = db_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        catalog = await client.get("/sources/catalog")
        assert catalog.status_code == 200
        rows = {item["key"]: item for item in catalog.json()["items"]}
        assert {"nws_alerts", "usgs_earthquakes", "nasa_firms", "cdc_wastewater"} <= rows.keys()
        assert rows["nasa_firms"]["status"] == "REQUIRES_CREDENTIALS"
        unavailable = await client.get("/layers/nasa_firms/data")
        assert unavailable.status_code == 200
        assert unavailable.json()["feature_count"] == 0
        assert unavailable.json()["features"] == []


@pytest.mark.asyncio
async def test_nws_observation_layer_projects_only_persisted_provider_points(db_factory):
    adapter = NWSObservationsAdapter("https://example.test/nws-observations", "signalwake-test")
    feature = {
        "type": "Feature",
        "id": "station-observation-1",
        "geometry": {"type": "Point", "coordinates": [-77.0377, 38.8512]},
        "properties": {
            "station": "https://api.weather.gov/stations/KDCA",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "textDescription": "Clear",
        },
    }
    async with db_factory() as session:
        source = await ensure_source(session, adapter)
        normalized = adapter.normalize(feature)
        await persist_normalized(session, source, adapter, normalized, classification="LIVE")
        await session.commit()
    app.state.session_factory = db_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/layers/nws_observations/data?limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["feature_count"] == 1
    assert body["features"][0]["geometry"] == feature["geometry"]


@pytest.mark.asyncio
async def test_events_response_exposes_bounded_window_metadata(db_factory):
    app.state.session_factory = db_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/events", params={"limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["window_hours"] == 48
    assert body["window_start"] < body["window_end"]
    assert "validity interval overlaps window" in body["temporal_semantics"]


@pytest.mark.asyncio
async def test_events_rejects_historical_override_outside_current_48_hours(db_factory):
    app.state.session_factory = db_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/events",
            params={"start_time": "2020-01-01T00:00:00Z", "end_time": "2020-01-02T00:00:00Z"},
        )
    assert response.status_code == 422
    assert "past 48 hours" in response.json()["detail"]


@pytest.mark.asyncio
async def test_events_and_layers_accept_1000_but_reject_larger_limits(db_factory):
    app.state.session_factory = db_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        events = await client.get("/events", params={"limit": 1000})
        too_many_events = await client.get("/events", params={"limit": 1001})
        layer = await client.get("/layers/nasa_firms/data", params={"limit": 1000})
        too_many_layer = await client.get("/layers/nasa_firms/data", params={"limit": 1001})
    assert events.status_code == 200
    assert events.json()["limit"] == 1000
    assert too_many_events.status_code == 422
    assert layer.status_code == 200
    assert layer.json()["bounded_limit"] == 1000
    assert too_many_layer.status_code == 422
