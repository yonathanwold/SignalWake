"""Database-to-engine adapters and response shaping for graph endpoints."""

from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.graph import GraphEdge, GraphEngine, GraphNode
from app.models import InfrastructureAsset, InfrastructureRelationship, InfrastructureSource
from app.repository import infrastructure_response
from app.schemas import (
    GraphEdgeResponse,
    GraphMetrics,
    GraphNodeResponse,
)


async def load_graph_context(
    session: AsyncSession,
    *,
    asset_type: str | None = None,
    region: str | None = None,
    source: str | None = None,
    relationship_types: set[str] | None = None,
    node_ids: set[str] | None = None,
) -> tuple[list[InfrastructureAsset], GraphEngine]:
    statement = select(InfrastructureAsset).options(joinedload(InfrastructureAsset.source)).order_by(InfrastructureAsset.id)
    if asset_type:
        statement = statement.where(InfrastructureAsset.asset_type == asset_type)
    if region:
        statement = statement.where(InfrastructureAsset.region == region)
    if source:
        statement = statement.join(InfrastructureAsset.source).where(InfrastructureSource.key == source.lower())
    if node_ids:
        statement = statement.where(InfrastructureAsset.id.in_(node_ids))
    assets = list((await session.execute(statement)).unique().scalars())
    asset_id_set = {asset.id for asset in assets}
    relationship_statement = select(InfrastructureRelationship).order_by(
        InfrastructureRelationship.relationship_type,
        InfrastructureRelationship.from_asset_id,
        InfrastructureRelationship.to_asset_id,
        InfrastructureRelationship.id,
    )
    if relationship_types:
        relationship_statement = relationship_statement.where(
            InfrastructureRelationship.relationship_type.in_(relationship_types)
        )
    # Scope both relationship endpoints in SQL.  This avoids loading every
    # relationship row only to discard edges in Python for filtered graph
    # requests (neighbors, subgraphs, and node detail).
    if asset_id_set:
        relationship_statement = relationship_statement.where(
            and_(
                InfrastructureRelationship.from_asset_id.in_(asset_id_set),
                InfrastructureRelationship.to_asset_id.in_(asset_id_set),
            )
        )
    else:
        relationship_statement = relationship_statement.where(False)
    relationships = list((await session.execute(relationship_statement)).scalars().all())
    nodes = [
        GraphNode(
            id=asset.id,
            name=asset.name,
            asset_type=asset.asset_type,
            region=asset.region,
            source_key=asset.source.key if asset.source else None,
        )
        for asset in assets
    ]
    edges = [_graph_edge(relationship) for relationship in relationships]
    return assets, GraphEngine(nodes, edges)


def _json_dict(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _graph_edge(relationship: InfrastructureRelationship) -> GraphEdge:
    return GraphEdge(
        id=relationship.id,
        from_id=relationship.from_asset_id,
        to_id=relationship.to_asset_id,
        relationship_type=relationship.relationship_type,
        directionality=relationship.directionality,
        relationship_source=relationship.relationship_source,
        relationship_key=relationship.relationship_key,
        source_relationship_id=relationship.source_relationship_id,
        derivation_method=relationship.derivation_method,
        derivation_version=relationship.derivation_version,
        confidence=relationship.confidence,
        evidence=_json_dict(relationship.evidence_json),
        distance_km=relationship.distance_km,
        tolerance_m=relationship.tolerance_m,
    )


def edge_response(edge: GraphEdge) -> GraphEdgeResponse:
    return GraphEdgeResponse(
        id=edge.id,
        from_node_id=edge.from_id,
        to_node_id=edge.to_id,
        relationship_key=edge.relationship_key,
        relationship_type=edge.relationship_type,
        directionality=edge.directionality,
        relationship_source=edge.relationship_source,
        source_relationship_id=edge.source_relationship_id,
        derivation_method=edge.derivation_method,
        derivation_version=edge.derivation_version,
        confidence=edge.confidence,
        evidence=edge.evidence,
        distance_km=edge.distance_km,
        tolerance_m=edge.tolerance_m,
    )


def node_response(asset: InfrastructureAsset, engine: GraphEngine, *, relationship_types: set[str] | None = None) -> GraphNodeResponse:
    node = engine.nodes.get(asset.id)
    if node is None:
        raise ValueError(f"asset {asset.id} is not in graph context")
    return GraphNodeResponse(
        id=asset.id,
        name=asset.name,
        type=asset.asset_type,
        region=asset.region,
        source_key=asset.source.key if asset.source else "unknown",
        classification=asset.classification,
        asset=infrastructure_response(asset),
        metrics=GraphMetrics.model_validate(engine.metrics(asset.id, relationship_types)),
    )


def edge_between(engine: GraphEngine, node_ids: set[str]) -> list[GraphEdgeResponse]:
    return [edge_response(edge) for edge in engine.edges.values() if edge.from_id in node_ids and edge.to_id in node_ids]


def assets_by_id(assets: Iterable[InfrastructureAsset]) -> dict[str, InfrastructureAsset]:
    return {asset.id: asset for asset in assets}


async def list_relationship_edges(
    session: AsyncSession,
    *,
    relationship_types: set[str] | None = None,
    limit: int = 100,
    cursor: int = 0,
) -> tuple[list[GraphEdge], int, int | None]:
    """Return a bounded relationship page without materializing a graph."""

    total_column = func.count(InfrastructureRelationship.id).over().label("_total_count")
    statement = select(InfrastructureRelationship, total_column).order_by(
        InfrastructureRelationship.relationship_type,
        InfrastructureRelationship.from_asset_id,
        InfrastructureRelationship.to_asset_id,
        InfrastructureRelationship.id,
    )
    count_statement = select(func.count(InfrastructureRelationship.id))
    if relationship_types:
        predicate = InfrastructureRelationship.relationship_type.in_(relationship_types)
        statement = statement.where(predicate)
        count_statement = count_statement.where(predicate)
    result = await session.execute(statement.offset(cursor).limit(limit + 1))
    rows = list(result.all())
    # Window counts keep page and total in one snapshot. An out-of-range page
    # has no window row, so use one bounded fallback count to preserve the
    # previous total contract for that edge case.
    total = (
        int(rows[0][1])
        if rows
        else int((await session.execute(count_statement)).scalar_one())
    )
    next_cursor = cursor + limit if len(rows) > limit else None
    return [_graph_edge(row[0]) for row in rows[:limit]], total, next_cursor
