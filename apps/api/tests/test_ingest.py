import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterError
from app.adapters.nws import NWSAdapter
from app.adapters.usgs import USGSAdapter
from app.config import Settings
from app.history import record_source_state
from app.ingest import ensure_source, ingest_once, persist_normalized
from app.main import seed_demo_data
from app.models import Event, RawObservation, Source, SourceStateVersion
from app.repository import source_response

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


@pytest.mark.asyncio
async def test_ensure_source_refreshes_configured_metadata_without_rewriting_history(db_factory):
    old_endpoint = "https://example.test/usgs-all-hour"
    new_endpoint = "https://example.test/usgs-all-day"
    first_adapter = USGSAdapter(old_endpoint, "signalwake-test", adapter_version="1.0.0")
    updated_adapter = USGSAdapter(new_endpoint, "signalwake-test", adapter_version="2.0.0")

    async with db_factory() as session:
        source = await ensure_source(session, first_adapter)
        await record_source_state(session, source, datetime(2026, 8, 17, tzinfo=timezone.utc))
        await session.commit()
        source_id = source.id

        refreshed = await ensure_source(session, updated_adapter)
        assert refreshed.id == source_id
        assert refreshed.endpoint == new_endpoint
        assert refreshed.name == updated_adapter.name
        assert refreshed.kind == updated_adapter.key.upper()
        assert refreshed.adapter_version == "2.0.0"
        await session.commit()

        history = list((await session.execute(select(SourceStateVersion))).scalars())
        assert len(history) == 1
        assert json.loads(history[0].snapshot_json)["endpoint"] == old_endpoint


@pytest.mark.asyncio
async def test_ingest_once_persists_live_events_and_records_source_health(db_factory, monkeypatch):
    nws_feature = json.loads((FIXTURES / "nws_alerts.json").read_text())["features"][0]

    async def fake_nws_fetch(self, client=None):
        self.last_http_status = 200
        return [nws_feature, {"type": "Feature", "properties": {}}]

    async def unavailable_usgs(self, client=None):
        self.last_http_status = 503
        raise AdapterError("USGS upstream unavailable")

    monkeypatch.setattr(NWSAdapter, "fetch", fake_nws_fetch)
    monkeypatch.setattr(USGSAdapter, "fetch", unavailable_usgs)

    nws = NWSAdapter("https://example.test/nws", "signalwake-test")
    usgs = USGSAdapter("https://example.test/usgs", "signalwake-test")
    async with db_factory() as session:
        report = await ingest_once(session, [nws, usgs])
        await session.commit()

        assert report.usable_source_keys == {"nws"}
        assert report.fallback_source_keys == {"usgs"}
        assert report.results[0].normalized_count == 1
        assert report.results[0].skipped_count == 1
        assert report.results[1].fetch_succeeded is False

        assert await session.scalar(select(func.count(Event.id))) == 1
        assert await session.scalar(select(func.count(RawObservation.id))) == 1
        sources = {source.key: source for source in (await session.execute(select(Source))).scalars()}
        assert source_response(sources["nws"]).health == "ERROR"
        assert "malformed" in (sources["nws"].last_error or "")
        assert source_response(sources["usgs"]).health == "ERROR"
        assert sources["usgs"].last_http_status == 503

        second_report = await ingest_once(session, [nws, usgs])
        await session.commit()
        assert second_report.results[0].normalized_count == 1
        assert await session.scalar(select(func.count(Event.id))) == 1
        assert await session.scalar(select(func.count(RawObservation.id))) == 1


@pytest.mark.asyncio
async def test_demo_fallback_skips_sources_with_live_events(db_factory):
    settings = Settings(use_demo_data=True, ingest_on_startup=False)
    fixture = json.loads((FIXTURES / "nws_alerts.json").read_text())["features"][0]
    adapter = NWSAdapter(settings.nws_alerts_url, settings.source_user_agent)
    async with db_factory() as session:
        source = await ensure_source(session, adapter)
        normalized = adapter.normalize(fixture)
        await persist_normalized(session, source, adapter, normalized, classification="LIVE")
        await session.commit()

        await seed_demo_data(session, settings, fallback_source_keys={"nws", "usgs"})

        nws_events = (await session.execute(select(Event).where(Event.source_id == source.id))).scalars().all()
        assert len(nws_events) == 1
        assert nws_events[0].classification == "LIVE"
        assert await session.scalar(select(func.count(Event.id))) == 3
