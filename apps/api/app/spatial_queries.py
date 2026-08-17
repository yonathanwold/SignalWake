from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import InfrastructureAsset
from app.repository import infrastructure_response
from app.schemas import InfrastructureResponse
from app.spatial import distance_geometry_to_point_km, geometry_intersects, validate_geometry


def _postgres(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bool(bind is not None and bind.dialect.name == "postgresql")


async def assets_intersecting_geometry(
    session: AsyncSession, geometry: dict, *, limit: int = 200
) -> list[InfrastructureResponse]:
    normalized = validate_geometry(geometry)
    statement = (
        select(InfrastructureAsset)
        .options(joinedload(InfrastructureAsset.source))
        .order_by(InfrastructureAsset.name.asc())
    )
    if _postgres(session):
        statement = statement.where(
            text(
                "ST_Intersects(infrastructure_assets.geometry, "
                "ST_SetSRID(ST_GeomFromGeoJSON(:query_geometry), 4326))"
            )
        ).params(query_geometry=json.dumps(normalized, separators=(",", ":")))
        result = await session.execute(statement.limit(limit))
        assets = list(result.unique().scalars())
    else:
        result = await session.execute(statement)
        assets = [
            asset
            for asset in result.unique().scalars()
            if geometry_intersects(json.loads(asset.geometry_geojson), normalized)
        ][:limit]
    return [infrastructure_response(asset) for asset in assets]


async def assets_within_distance(
    session: AsyncSession,
    longitude: float,
    latitude: float,
    distance_km: float,
    *,
    limit: int = 200,
) -> list[InfrastructureResponse]:
    if distance_km <= 0 or distance_km > 20_000:
        raise ValueError("distance_km must be greater than zero and at most 20000")
    statement = (
        select(InfrastructureAsset)
        .options(joinedload(InfrastructureAsset.source))
        .order_by(InfrastructureAsset.name.asc())
    )
    if _postgres(session):
        statement = statement.where(
            text(
                "ST_DWithin(infrastructure_assets.geometry::geography, "
                "ST_SetSRID(ST_Point(:query_lon, :query_lat), 4326)::geography, :query_metres)"
            )
        ).params(query_lon=longitude, query_lat=latitude, query_metres=distance_km * 1000)
        result = await session.execute(statement.limit(limit))
        assets = list(result.unique().scalars())
    else:
        result = await session.execute(statement)
        assets = [
            asset
            for asset in result.unique().scalars()
            if distance_geometry_to_point_km(
                json.loads(asset.geometry_geojson), longitude, latitude
            )
            <= distance_km
        ][:limit]
    return [infrastructure_response(asset) for asset in assets]
