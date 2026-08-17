import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.nws import NWSAdapter
from app.adapters.usgs import USGSAdapter
from app.ingest import ensure_source, persist_normalized
from app.main import app


@pytest.mark.asyncio
async def test_event_filters_and_idempotency(db_factory):
    async with db_factory() as session:
        nws = NWSAdapter("https://example.test/nws", "test")
        usgs = USGSAdapter("https://example.test/usgs", "test")
        nws_source = await ensure_source(session, nws)
        usgs_source = await ensure_source(session, usgs)
        nws_feature = {
            "type": "Feature",
            "id": "nws-1",
            "properties": {
                "id": "nws-1",
                "headline": "Demo storm",
                "severity": "Severe",
                "effective": "2026-08-17T14:00:00Z",
            },
            "geometry": None,
        }
        usgs_feature = {
            "type": "Feature",
            "id": "usgs-1",
            "properties": {"mag": 3.1, "title": "M 3.1 demo", "time": 1786972200000},
            "geometry": {"type": "Point", "coordinates": [-77.0, 38.9, 5]},
        }
        n = nws.normalize(nws_feature)
        u = usgs.normalize(usgs_feature)
        await persist_normalized(session, nws_source, nws, n, classification="DEMO")
        await persist_normalized(session, nws_source, nws, n, classification="DEMO")
        await persist_normalized(session, usgs_source, usgs, u, classification="DEMO")
        await session.commit()
    app.state.session_factory = db_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/events", params={"source": "usgs", "limit": 10})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["classification"] == "DEMO"
        detail = await client.get(f"/events/{body['items'][0]['id']}")
        assert detail.status_code == 200
        assert detail.json()["provenance"][0]["source_record_id"] == "usgs-1"
