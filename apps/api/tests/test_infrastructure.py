import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.infrastructure_import import import_payload
from app.main import app
from app.models import InfrastructureAsset, InfrastructureSource, RawInfrastructureRecord
from app.spatial import (
    GeometryValidationError,
    distance_geometry_to_point_km,
    geometry_intersects_bbox,
    validate_geometry,
)
from app.spatial_queries import assets_intersecting_geometry, assets_within_distance

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_import_is_repeatable_and_keeps_source_identity(db_factory):
    payload = fixture("infrastructure_ports.geojson")
    async with db_factory() as session:
        first = await import_payload(
            session,
            "bts_ports",
            payload,
            fetched_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
            batch_size=1,
        )
        second = await import_payload(session, "bts_ports", payload, batch_size=1)

        assert first.inserted_count == 2
        assert second.inserted_count == 0
        assert second.updated_count == 2
        assert second.duplicate_count == 2
        assert await session.scalar(select(func.count(InfrastructureAsset.id))) == 2
        assert await session.scalar(select(func.count(RawInfrastructureRecord.id))) == 2
        source = await session.scalar(select(InfrastructureSource).where(InfrastructureSource.key == "bts_ports"))
        assert source is not None
        assert source.last_import_count == 2
        asset = await session.scalar(select(InfrastructureAsset).where(InfrastructureAsset.source_asset_id == "PORT-VA-001"))
        assert asset is not None
        assert asset.classification == "REFERENCE"
        assert asset.asset_type == "port"
        assert asset.latitude == pytest.approx(36.95)


@pytest.mark.asyncio
async def test_import_skips_malformed_records_without_network(db_factory):
    payload = fixture("infrastructure_rail.geojson")
    payload["features"].append({"type": "Feature", "properties": {"OBJECTID": "bad"}, "geometry": {"type": "Point", "coordinates": [999, 5]}})
    payload["features"].append({"type": "Feature", "properties": {}, "geometry": None})
    async with db_factory() as session:
        report = await import_payload(session, "fra_rail", payload)
        assert report.fetched_count == 4
        assert report.inserted_count == 2
        assert report.skipped_count == 2
        assert await session.scalar(select(func.count(InfrastructureAsset.id))) == 2


def test_spatial_validation_intersection_and_distance():
    point = {"type": "Point", "coordinates": [-76.34, 36.95]}
    line = {"type": "LineString", "coordinates": [[-77, 36], [-76, 37]]}
    polygon = {"type": "Polygon", "coordinates": [[[-77, 36], [-76, 36], [-76, 37], [-77, 37], [-77, 36]]]}
    assert geometry_intersects_bbox(point, (-77, 36, -76, 37))
    assert geometry_intersects_bbox(line, (-76.6, 36.4, -76.4, 36.6))
    assert geometry_intersects_bbox(polygon, (-76.5, 36.5, -76.2, 36.8))
    assert distance_geometry_to_point_km(point, -76.34, 36.95) == pytest.approx(0)
    with pytest.raises(GeometryValidationError):
        validate_geometry({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 1]]]})


@pytest.mark.asyncio
async def test_spatial_queries_and_api_filters(db_factory):
    async with db_factory() as session:
        await import_payload(session, "bts_ports", fixture("infrastructure_ports.geojson"))
        await import_payload(session, "fra_rail", fixture("infrastructure_rail.geojson"))
        intersecting = await assets_intersecting_geometry(
            session,
            {"type": "Point", "coordinates": [-76.34, 36.95]},
        )
        nearby = await assets_within_distance(session, -76.34, 36.95, 100)
        assert any(item.source_asset_id == "PORT-VA-001" for item in intersecting)
        assert any(item.source_asset_id == "PORT-VA-001" for item in nearby)

    app.state.session_factory = db_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/infrastructure",
            params={"bbox": "-77,36,-76,37.5", "type": "port", "source": "bts_ports", "limit": 10},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["classification"] == "REFERENCE"
        assert body["items"][0]["provenance"][0]["source_record_id"] == "PORT-VA-001"
        detail = await client.get(f"/infrastructure/{body['items'][0]['id']}")
        assert detail.status_code == 200
        assert detail.json()["source_attribution"].startswith("U.S. Department of Transportation")
        malformed = await client.get("/infrastructure", params={"bbox": "bad"})
        assert malformed.status_code == 422
