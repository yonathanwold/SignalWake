from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.adapters.usgs import USGSAdapter
from app.infrastructure_import import import_payload
from app.ingest import ensure_source, persist_normalized
from app.main import app
from app.models import InfrastructureAsset, InfrastructureRelationship


@pytest.mark.asyncio
async def test_lineage_exposes_raw_event_source_and_bounds(db_factory):
    async with db_factory() as session:
        adapter = USGSAdapter("https://example.test/usgs", "test")
        source = await ensure_source(session, adapter)
        event = await persist_normalized(
            session,
            source,
            adapter,
            adapter.normalize(
                {
                    "type": "Feature",
                    "id": "quake-lineage",
                    "properties": {"mag": 3.1, "title": "Lineage quake", "time": 1786972200000},
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.9, 5]},
                },
            ),
            fetched_at=datetime.now(timezone.utc),
        )
        await session.commit()
    app.state.session_factory = db_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/provenance/lineage",
            params={"object_type": "event", "object_id": event.id, "direction": "upstream", "limit": 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["truncated"] is True
        assert body["edges"]
        assert body["edges"][0]["downstream"] == {"type": "event", "id": event.id}
        missing = await client.get("/provenance/lineage", params={"object_type": "event", "object_id": "missing"})
        assert missing.status_code == 404
        invalid = await client.get("/provenance/lineage", params={"object_type": "event", "object_id": event.id, "direction": "sideways"})
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_lineage_exposes_infrastructure_raw_and_relationship(db_factory):
    async with db_factory() as session:
        await import_payload(
            session,
            "bts_ports",
            {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "port-lineage", "properties": {"OBJECTID": "port-lineage", "NAME": "Lineage Port"}, "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]}}, {"type": "Feature", "id": "port-lineage-2", "properties": {"OBJECTID": "port-lineage-2", "NAME": "Lineage Port Two"}, "geometry": {"type": "Point", "coordinates": [-77.1, 38.8]}}]},
        )
        assets = list((await session.execute(select(InfrastructureAsset).order_by(InfrastructureAsset.source_asset_id))).scalars().all())
        asset, other = assets
        relationship = InfrastructureRelationship(
            from_asset_id=asset.id,
            to_asset_id=other.id,
            relationship_key="test-lineage-edge",
            relationship_type="INTERSECTS",
            directionality="UNDIRECTED",
            relationship_source="SOURCE_OBSERVED",
            evidence_json="{}",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(relationship)
        await session.commit()
        asset_id = asset.id
        raw_id = asset.raw_infrastructure_record_id
        relationship_id = relationship.id
    app.state.session_factory = db_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/provenance/lineage", params={"object_type": "asset", "object_id": asset_id, "direction": "upstream"})
        assert response.status_code == 200
        assert any(edge["upstream"]["type"] == "raw_infrastructure_record" and edge["upstream"]["id"] == raw_id for edge in response.json()["edges"])
        edge_response = await client.get("/provenance/lineage", params={"object_type": "relationship", "object_id": relationship_id, "direction": "upstream"})
        assert edge_response.status_code == 200
        assert {item["upstream"]["type"] for item in edge_response.json()["edges"]} == {"asset"}
