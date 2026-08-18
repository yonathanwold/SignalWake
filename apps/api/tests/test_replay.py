from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.adapters.nws import NWSAdapter
from app.assessments import recompute_event_assessments
from app.history import record_source_state
from app.infrastructure_import import import_payload
from app.ingest import ensure_source, persist_normalized
from app.main import app
from app.models import (
    InfrastructureAssessmentVersion,
    InfrastructureAsset,
    InfrastructureAssetVersion,
)
from app.replay import replay_compare, replay_state, replay_timeline


def _time(hour: int) -> datetime:
    return datetime(2026, 8, 17, hour, tzinfo=timezone.utc)


def _feature(title: str, *, expires: str = "2026-08-17T13:00:00Z") -> dict:
    return {
        "type": "Feature",
        "id": "nws-replay-1",
        "properties": {
            "id": "nws-replay-1",
            "headline": title,
            "severity": "Severe",
            "effective": "2026-08-17T08:00:00Z",
            "expires": expires,
        },
        "geometry": {"type": "Point", "coordinates": [-77.0, 37.0]},
    }


@pytest.mark.asyncio
async def test_replay_preserves_late_arrival_updates_boundaries_and_expiration(db_factory):
    adapter = NWSAdapter("https://example.test/nws", "test")
    async with db_factory() as session:
        source = await ensure_source(session, adapter)
        first = adapter.normalize(_feature("Initial warning"), _time(10))
        await persist_normalized(session, source, adapter, first, fetched_at=_time(10), classification="LIVE")
        second = adapter.normalize(_feature("Updated warning"), _time(12))
        await persist_normalized(session, source, adapter, second, fetched_at=_time(12), classification="LIVE")
        late_feature = _feature("Late warning", expires="2026-08-17T18:00:00Z")
        late_feature["id"] = "nws-replay-late"
        late_feature["properties"]["id"] = "nws-replay-late"
        late = adapter.normalize(late_feature, _time(8))
        await persist_normalized(session, source, adapter, late, fetched_at=_time(14), classification="LIVE")
        await record_source_state(session, source, _time(14))
        await session.commit()

        before = await replay_state(session, _time(9), limit=10)
        at_first = await replay_state(session, _time(10), limit=10)
        at_update = await replay_state(session, _time(12), limit=10)
        at_expiry = await replay_state(session, _time(13), limit=10)
        late_before = await replay_state(session, _time(13), limit=10)
        late_after = await replay_state(session, _time(14), limit=10)
        assert before["events"] == []
        assert at_first["events"][0]["title"] == "Initial warning"
        assert at_update["events"][0]["title"] == "Updated warning"
        assert at_expiry["events"][0]["temporal_status"] == "expired"
        assert len(late_before["events"]) == 1
        assert len(late_after["events"]) == 2
        assert any(item["knowledge_at"] == _time(14) for item in late_after["events"])
        assert late_after["sources"][0]["knowledge_at"] == _time(14)

        timeline = await replay_timeline(session, _time(9), _time(14), limit=20)
        assert [item["kind"] for item in timeline["items"]].count("event") == 3
        compare = await replay_compare(session, _time(10), _time(14), limit=20)
        assert compare["summary"]["newly_known_events"] == 1
        assert compare["summary"]["updated_events"] == 1


@pytest.mark.asyncio
async def test_replay_api_rejects_naive_time_and_bounds(db_factory):
    adapter = NWSAdapter("https://example.test/nws", "test")
    async with db_factory() as session:
        source = await ensure_source(session, adapter)
        await persist_normalized(
            session, source, adapter, adapter.normalize(_feature("API replay"), _time(10)), fetched_at=_time(10)
        )
        await session.commit()
    app.state.session_factory = db_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        state = await client.get("/replay/state", params={"at": "2026-08-17T10:00:00Z", "limit": 10})
        assert state.status_code == 200
        assert state.json()["events"][0]["knowledge_at"].startswith("2026-08-17T10:00:00")
        timeline = await client.get(
            "/replay/timeline",
            params={"start_time": "2026-08-17T09:00:00Z", "end_time": "2026-08-17T10:00:00Z", "limit": 10},
        )
        assert timeline.status_code == 200
        compare = await client.get(
            "/replay/compare",
            params={"from_time": "2026-08-17T09:00:00Z", "to_time": "2026-08-17T10:00:00Z", "limit": 10},
        )
        assert compare.status_code == 200
        naive = await client.get("/replay/state", params={"at": "2026-08-17T12:00:00", "limit": 10})
        assert naive.status_code == 422
        too_many = await client.get(
            "/replay/timeline",
            params={"start_time": "2026-08-17T00:00:00Z", "end_time": "2026-08-17T01:00:00Z", "limit": 101},
        )
        assert too_many.status_code == 422


@pytest.mark.asyncio
async def test_replay_keeps_asset_and_assessment_history(db_factory):
    adapter = NWSAdapter("https://example.test/nws", "test")
    asset_feature = {
        "type": "Feature",
        "id": "PORT-REPLAY",
        "properties": {"OBJECTID": "PORT-REPLAY", "PORT_NAME": "Replay Port", "STATE": "VA"},
        "geometry": {"type": "Point", "coordinates": [-77.0, 37.0]},
    }
    async with db_factory() as session:
        source = await ensure_source(session, adapter)
        event = await persist_normalized(
            session, source, adapter, adapter.normalize(_feature("Assessment warning"), _time(10)), fetched_at=_time(10)
        )
        await import_payload(session, "bts_ports", {"type": "FeatureCollection", "features": [asset_feature]}, fetched_at=_time(11))
        first_assessment = await recompute_event_assessments(session, event.id, radius_km=10)
        await session.commit()
        asset = await session.scalar(select(InfrastructureAsset).where(InfrastructureAsset.source_asset_id == "PORT-REPLAY"))
        assert asset is not None
        assert first_assessment.items
        first_state = await replay_state(session, datetime.now(timezone.utc), limit=20)
        assert first_state["infrastructure"]
        assert first_state["assessments"]
        assert await session.scalar(select(InfrastructureAssetVersion.id)) is not None
        assert await session.scalar(select(InfrastructureAssessmentVersion.id)) is not None
