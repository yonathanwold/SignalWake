from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.derivation import rebuild_derived_relationships
from app.graph import GraphEdge, GraphEngine, GraphNode
from app.infrastructure_import import import_payload
from app.main import app
from app.models import InfrastructureAsset, InfrastructureRelationship, Scenario, ScenarioRun
from app.scenarios import execute_graph_scenario

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


def _line(identifier, points, state="VA"):
    return {
        "type": "Feature",
        "id": identifier,
        "properties": {"OBJECTID": identifier, "RAILROAD": identifier, "STATE": state},
        "geometry": {"type": "LineString", "coordinates": points},
    }


@pytest.fixture
def chain_graph():
    nodes = [GraphNode(item, item) for item in "abcd"]
    edges = [
        GraphEdge("ab", "a", "b", "CONNECTED_TO"),
        GraphEdge("bc", "b", "c", "CONNECTED_TO"),
        GraphEdge("cd", "c", "d", "CONNECTED_TO"),
    ]
    return GraphEngine(nodes, edges)


def test_scenario_engine_node_edge_and_multi_removals(chain_graph):
    node_result = execute_graph_scenario(
        chain_graph,
        scenario_type="ASSET_UNAVAILABLE",
        target_node_ids=["b"],
        target_edge_ids=[],
        assumption="fixture node unavailable",
    )
    assert node_result.metrics["removed_node_ids"] == ["b"]
    assert node_result.metrics["removed_edge_ids"] == ["ab", "bc"]
    assert node_result.metrics["scenario"]["component_count"] == 2
    assert node_result.metrics["path_analysis"]["scenario_reachable_pairs"] == 1

    edge_result = execute_graph_scenario(
        chain_graph,
        scenario_type="EDGE_UNAVAILABLE",
        target_node_ids=[],
        target_edge_ids=["bc"],
        assumption="fixture edge unavailable",
    )
    assert edge_result.metrics["removed_edge_ids"] == ["bc"]
    assert edge_result.metrics["path_analysis"]["changed_path_count"] == 4

    multi_result = execute_graph_scenario(
        chain_graph,
        scenario_type="MULTIPLE_ASSETS_UNAVAILABLE",
        target_node_ids=["b", "c"],
        target_edge_ids=[],
        assumption="fixture nodes unavailable",
    )
    assert multi_result.metrics["removed_node_ids"] == ["b", "c"]
    assert multi_result.metrics["scenario"]["node_count"] == 2
    repeat = execute_graph_scenario(
        chain_graph,
        scenario_type="EDGE_UNAVAILABLE",
        target_node_ids=[],
        target_edge_ids=["bc"],
        assumption="fixture edge unavailable",
    )
    assert repeat.metrics == edge_result.metrics
    assert repeat.evidence == edge_result.evidence


@pytest.mark.asyncio
async def test_scenario_persistence_api_and_invalid_inputs(db_factory):
    async with db_factory() as session:
        await import_payload(
            session,
            "fra_rail",
            {"type": "FeatureCollection", "features": [_line("RAIL-A", [[-77.0, 37.0], [-76.9, 37.0]]), _line("RAIL-B", [[-76.9, 37.0], [-76.8, 37.0]])]},
        )
        await rebuild_derived_relationships(session)
        assets = list((await session.execute(select(InfrastructureAsset).order_by(InfrastructureAsset.id))).scalars())
        relationships = list((await session.execute(select(InfrastructureRelationship))).scalars())
        assert len(assets) == 2
        assert len(relationships) == 1
        node_id = assets[0].id
        edge_id = relationships[0].id
        original_edge_count = await session.scalar(select(func.count(InfrastructureRelationship.id)))
    app.state.session_factory = db_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post(
            "/scenarios",
            json={"scenario_type": "ASSET_UNAVAILABLE", "target_node_ids": [node_id, node_id]},
        )
        assert invalid.status_code == 422
        missing = await client.post(
            "/scenarios",
            json={"scenario_type": "EDGE_UNAVAILABLE", "target_edge_ids": ["missing-edge"]},
        )
        assert missing.status_code == 404
        created = await client.post(
            "/scenarios",
            json={"name": "API fixture removal", "scenario_type": "EDGE_UNAVAILABLE", "target_edge_ids": [edge_id]},
        )
        assert created.status_code == 201, created.text
        scenario = created.json()
        assert scenario["methodology_version"] == "second-order-v1"
        assert scenario["baseline"]["edge_count"] == 1
        run_response = await client.post(f"/scenarios/{scenario['id']}/runs")
        assert run_response.status_code == 201, run_response.text
        run = run_response.json()
        assert run["result"]["metrics"]["removed_edge_ids"] == [edge_id]
        repeated = await client.post(f"/scenarios/{scenario['id']}/runs")
        assert repeated.status_code == 201
        assert repeated.json()["id"] == run["id"]
        detail = await client.get(f"/scenario-runs/{run['id']}")
        assert detail.status_code == 200
        graph = await client.get(f"/scenario-runs/{run['id']}/graph", params={"state": "modified"})
        assert graph.status_code == 200
        assert graph.json()["edges"] == []
        listed = await client.get("/scenarios")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
    async with db_factory() as session:
        assert await session.scalar(select(func.count(InfrastructureRelationship.id))) == original_edge_count
        assert await session.scalar(select(func.count(Scenario.id))) == 1
        assert await session.scalar(select(func.count(ScenarioRun.id))) == 1
