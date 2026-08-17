import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.derivation import DerivationSettings, rebuild_derived_relationships
from app.graph import GraphEdge, GraphEngine, GraphNode
from app.infrastructure_import import import_payload
from app.main import app
from app.models import InfrastructureRelationship
from app.spatial import geometry_intersects

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


def test_relationship_migration_is_postgis_ready():
    migration = (Path(__file__).parents[1] / "migrations" / "003_infrastructure_relationships.sql").read_text()
    assert "REFERENCES infrastructure_assets(id)" in migration
    assert "relationship_key text NOT NULL UNIQUE" in migration
    assert "geometry::geography" in migration or "ST_DWithin" in migration
    assert "ix_infrastructure_relationship_from" in migration
    assert "ix_infrastructure_relationship_to" in migration


def _payload(features):
    return {"type": "FeatureCollection", "features": features}


def _line(identifier, points, state="VA"):
    return {
        "type": "Feature",
        "id": identifier,
        "properties": {"OBJECTID": identifier, "RAILROAD": identifier, "STATE": state},
        "geometry": {"type": "LineString", "coordinates": points},
    }


def _port(identifier, point, state="VA"):
    return {
        "type": "Feature",
        "id": identifier,
        "properties": {"OBJECTID": identifier, "PORT_NAME": identifier, "STATE": state},
        "geometry": {"type": "Point", "coordinates": point},
    }


def test_graph_engine_exact_small_graph():
    nodes = [GraphNode(identifier, identifier) for identifier in "abcd"]
    edges = [
        GraphEdge("ab", "a", "b", "CONNECTED_TO"),
        GraphEdge("bc", "b", "c", "CONNECTED_TO"),
        GraphEdge("cd", "c", "d", "CONNECTED_TO"),
    ]
    engine = GraphEngine(nodes, edges)
    assert engine.neighbor_ids("a", depth=2) == ["b", "c"]
    assert engine.shortest_path("a", "d") == ["a", "b", "c", "d"]
    assert engine.connected_components() == [["a", "b", "c", "d"]]
    assert engine.degree("b") == 2
    assert engine.articulation_points() == {"b", "c"}
    assert engine.betweenness_centrality()["b"] == pytest.approx(2 / 3)
    assert engine.metrics("b")["alternate_path_count"] == 0
    subgraph, sub_edges, truncated = engine.subgraph("a", depth=2, max_nodes=2)
    assert [node.id for node in subgraph] == ["a", "b"]
    assert [edge.id for edge in sub_edges] == ["ab"]
    assert truncated is True


def test_point_on_line_is_an_actual_intersection():
    assert geometry_intersects(
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "LineString", "coordinates": [[-1, 0], [1, 0]]},
    )


@pytest.mark.asyncio
async def test_derivation_topology_intersection_adjacency_and_repeatability(db_factory):
    async with db_factory() as session:
        await import_payload(
            session,
            "fra_rail",
            _payload(
                [
                    _line("RAIL-A", [[-77.0, 37.0], [-76.9, 37.0]]),
                    _line("RAIL-B", [[-76.9, 37.0], [-76.8, 37.0]]),
                    _line("RAIL-C", [[-76.95, 36.95], [-76.95, 37.05]]),
                    _line("RAIL-TX", [[-95.0, 29.0], [-94.8, 29.0]], state="TX"),
                ]
            ),
        )
        await import_payload(session, "bts_ports", _payload([_port("PORT-VA", [-76.95, 37.03]), _port("PORT-FAR", [-77.5, 37.0])]))
        first = await rebuild_derived_relationships(session, DerivationSettings(adjacency_distance_km=10))
        second = await rebuild_derived_relationships(session, DerivationSettings(adjacency_distance_km=10))
        relationships = list((await session.execute(select(InfrastructureRelationship))).scalars())
        types = [relationship.relationship_type for relationship in relationships]
        assert "CONNECTED_TO" in types
        assert "INTERSECTS" in types
        assert "ADJACENT_TO" in types
        assert first.inserted_count == len(relationships)
        assert second.inserted_count == 0
        assert await session.scalar(select(func.count(InfrastructureRelationship.id))) == len(set(item.relationship_key for item in relationships))
        adjacent = next(item for item in relationships if item.relationship_type == "ADJACENT_TO")
        assert json.loads(adjacent.evidence_json)["threshold_km"] == 10


@pytest.mark.asyncio
async def test_derivation_negative_region_and_unsupported_nearby(db_factory):
    async with db_factory() as session:
        await import_payload(session, "fra_rail", _payload([_line("RAIL-VA", [[-76.0, 37.0], [-75.9, 37.0]])]))
        await import_payload(session, "bts_ports", _payload([_port("PORT-NC", [-75.95, 37.01], state="NC")]))
        report = await rebuild_derived_relationships(session, DerivationSettings(adjacency_distance_km=10))
        assert report.derived_edges == 0
        assert await session.scalar(select(func.count(InfrastructureRelationship.id))) == 0


@pytest.mark.asyncio
async def test_graph_api_bounds_filters_and_provenance(db_factory):
    async with db_factory() as session:
        await import_payload(session, "bts_ports", json.loads((FIXTURES / "infrastructure_ports.geojson").read_text()))
        await import_payload(session, "fra_rail", json.loads((FIXTURES / "infrastructure_rail.geojson").read_text()))
        await rebuild_derived_relationships(session)
    app.state.session_factory = db_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/graph/nodes", params={"type": "port", "region": "TX", "limit": 1})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["asset"]["provenance"][0]["source_record_id"] == "PORT-TX-002"
        node_id = body["items"][0]["id"]
        neighbors = await client.get(f"/graph/nodes/{node_id}/neighbors")
        assert neighbors.status_code == 200
        assert neighbors.json()["edges"][0]["relationship_source"] == "DERIVED"
        assert neighbors.json()["edges"][0]["evidence"]["assets"]
        assert (await client.get(f"/graph/nodes/{node_id}/neighbors", params={"direction": "in"})).status_code == 400
        assert (await client.get("/graph/subgraph", params={"root": node_id, "max_nodes": 1})).status_code == 200
