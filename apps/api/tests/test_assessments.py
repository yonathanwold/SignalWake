import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.adapters.usgs import USGSAdapter
from app.assessments import METHODOLOGY_VERSION, recompute_event_assessments
from app.infrastructure_import import import_payload
from app.ingest import ensure_source, persist_normalized
from app.main import app
from app.models import InfrastructureAssessment, InfrastructureAsset, InfrastructureRelationship


def _port(identifier: str, point: list[float], state: str = "VA") -> dict:
    return {
        "type": "Feature",
        "id": identifier,
        "properties": {"OBJECTID": identifier, "PORT_NAME": identifier, "STATE": state},
        "geometry": {"type": "Point", "coordinates": point},
    }


async def _event(session, point: list[float], *, magnitude: float = 5.2):
    adapter = USGSAdapter("https://example.test/usgs", "test")
    source = await ensure_source(session, adapter)
    normalized = adapter.normalize(
        {
            "type": "Feature",
            "id": f"quake-{point[0]}-{point[1]}",
            "properties": {"mag": magnitude, "title": "Assessment test quake", "time": 1786972200000},
            "geometry": {"type": "Point", "coordinates": [*point, 5]},
        },
        datetime.now(timezone.utc),
    )
    event = await persist_normalized(session, source, adapter, normalized, classification="DEMO")
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_assessment_intersection_radius_math_and_idempotent_recompute(db_factory):
    async with db_factory() as session:
        event = await _event(session, [-77.0, 37.0])
        await import_payload(
            session,
            "bts_ports",
            {"type": "FeatureCollection", "features": [_port("PORT-ON", [-77.0, 37.0]), _port("PORT-NEAR", [-77.12, 37.0]), _port("PORT-FAR", [-80.0, 37.0])]},
        )
        first = await recompute_event_assessments(session, event.id, radius_km=20, depth=2)
        await session.commit()
        assert first.inserted_count == len(first.items)
        assert {item.assessment_type for item in first.items} == {
            "EVENT_INTERSECTS_INFRASTRUCTURE",
            "INFRASTRUCTURE_WITHIN_EVENT_RADIUS",
        }
        radius = next(item for item in first.items if item.assessment_type.endswith("RADIUS"))
        components = json.loads(radius.score_components_json)
        assert components["formula"]
        assert components["methodology_version"] == METHODOLOGY_VERSION
        assert components["weights"] == {"event_severity": 0.5, "spatial_match": 0.35, "graph_exposure": 0.15}
        assert radius.confidence is None
        keys_before = {item.assessment_key: item.id for item in first.items}

        second = await recompute_event_assessments(session, event.id, radius_km=20, depth=2)
        await session.commit()
        assert second.inserted_count == 0
        assert second.updated_count == len(first.items)
        assert {item.assessment_key: item.id for item in second.items} == keys_before

        stale = await recompute_event_assessments(session, event.id, radius_km=1, depth=2)
        await session.commit()
        assert stale.deleted_count >= 1
        assert await session.scalar(select(func.count(InfrastructureAssessment.id))) == len(stale.items)


@pytest.mark.asyncio
async def test_dependency_exposure_uses_bounded_graph_evidence(db_factory):
    async with db_factory() as session:
        event = await _event(session, [-77.0, 37.0])
        await import_payload(
            session,
            "bts_ports",
            {"type": "FeatureCollection", "features": [_port("PORT-A", [-77.0, 37.0]), _port("PORT-B", [-77.2, 37.0]), _port("PORT-C", [-77.4, 37.0])]},
        )
        assets = list(
            (
                await session.execute(
                    select(InfrastructureAsset).order_by(InfrastructureAsset.source_asset_id)
                )
            ).scalars()
        )
        for left, right in zip(assets, assets[1:]):
            session.add(
                InfrastructureRelationship(
                    from_asset_id=left.id,
                    to_asset_id=right.id,
                    relationship_key=f"test-{left.id}-{right.id}",
                    relationship_type="CONNECTED_TO",
                    directionality="UNDIRECTED",
                    relationship_source="DERIVED",
                    derivation_method="assessment_fixture",
                    derivation_version="test",
                    evidence_json=json.dumps({"fixture": True}),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        await session.flush()
        result = await recompute_event_assessments(session, event.id, radius_km=5, depth=2)
        dependency = [item for item in result.items if item.assessment_type == "DEPENDENCY_EXPOSURE"]
        assert dependency
        evidence = json.loads(dependency[0].evidence_json)
        assert evidence["directionality"] == "UNDIRECTED"
        assert evidence["relationship_ids"]
        assert evidence["path_node_ids"][0] == evidence["seed_asset_id"]
        assert "outage" in evidence["interpretation"]


@pytest.mark.asyncio
async def test_assessment_api_filters_detail_and_validation(db_factory):
    async with db_factory() as session:
        event = await _event(session, [-77.0, 37.0])
        await import_payload(
            session,
            "bts_ports",
            {"type": "FeatureCollection", "features": [_port("PORT-API", [-77.0, 37.0])]},
        )
    app.state.session_factory = db_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post("/assessments/recompute", json={"event_id": event.id, "radius_km": 501})
        assert invalid.status_code == 422
        recompute = await client.post(
            "/assessments/recompute", json={"event_id": event.id, "radius_km": 10, "depth": 1}
        )
        assert recompute.status_code == 200
        body = recompute.json()
        assert body["methodology_version"] == METHODOLOGY_VERSION
        listing = await client.get("/assessments", params={"event_id": event.id, "assessment_type": "EVENT_INTERSECTS_INFRASTRUCTURE"})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assessment_id = listing.json()["items"][0]["id"]
        detail = await client.get(f"/assessments/{assessment_id}")
        assert detail.status_code == 200
        assert detail.json()["classification"] == "SIGNALWAKE DERIVED ASSESSMENT"
        assert detail.json()["metadata"]["classification"] == "SIGNALWAKE DERIVED ASSESSMENT"
        assert (await client.get(f"/events/{event.id}/assessments")).status_code == 200
        asset_id = detail.json()["affected_asset_id"]
        assert (await client.get(f"/infrastructure/{asset_id}/assessments")).status_code == 200
