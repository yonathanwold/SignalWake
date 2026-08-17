"""Deterministic Phase 3 relationship derivation from Phase 2 assets only."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import (
    InfrastructureAsset,
    InfrastructureRelationship,
    InfrastructureRelationshipSource,
    InfrastructureRelationshipType,
    RelationshipDirectionality,
)
from app.spatial import (
    distance_geometry_to_point_km,
    distance_points_km,
    geometry_bounds,
    geometry_endpoints,
    geometry_intersects,
)

DERIVATION_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class DerivationSettings:
    """Defaults are deliberately small and expressed in WGS84 distance units."""

    endpoint_tolerance_m: float = 100.0
    adjacency_distance_km: float = 25.0
    grid_size_km: float = 30.0
    version: str = DERIVATION_VERSION

    def __post_init__(self) -> None:
        if self.endpoint_tolerance_m <= 0 or self.adjacency_distance_km <= 0 or self.grid_size_km <= 0:
            raise ValueError("derivation distances must be greater than zero")


@dataclass(frozen=True, slots=True)
class DerivedRelationship:
    relationship_key: str
    from_asset_id: str
    to_asset_id: str
    relationship_type: str
    distance_km: float | None
    tolerance_m: float | None
    evidence: dict[str, Any]
    derivation_method: str


@dataclass(frozen=True, slots=True)
class RebuildStats:
    assets_considered: int
    candidate_pairs: int
    derived_edges: int
    inserted_count: int
    updated_count: int
    deleted_count: int
    settings: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _geometry(asset: InfrastructureAsset) -> dict[str, Any]:
    try:
        return json.loads(asset.geometry_geojson)
    except (TypeError, json.JSONDecodeError):
        return {"type": asset.geometry_type, "coordinates": []}


def _asset_source_url(asset: InfrastructureAsset) -> str:
    if asset.source is not None:
        return asset.source.endpoint
    try:
        provenance = json.loads(asset.provenance_json or "[]")
        return str(provenance[0].get("source_url", "")) if provenance else ""
    except (TypeError, json.JSONDecodeError, IndexError):
        return ""


def _asset_evidence(asset: InfrastructureAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.id,
        "source_id": asset.source_id,
        "source_record_id": asset.source_asset_id,
        "source_url": _asset_source_url(asset),
    }


def _region_compatible(first: InfrastructureAsset, second: InfrastructureAsset) -> bool:
    if not first.region or not second.region:
        return True
    return first.region.strip().casefold() == second.region.strip().casefold()


def _grid_cell(point: tuple[float, float], cell_degrees: float) -> tuple[int, int]:
    return (int(point[0] // cell_degrees), int(point[1] // cell_degrees))


def _cells_for_bounds(bounds: tuple[float, float, float, float], cell_degrees: float, expansion_km: float):
    expansion_degrees = expansion_km / 111.32
    min_lon, min_lat, max_lon, max_lat = bounds
    left, bottom = _grid_cell((min_lon - expansion_degrees, min_lat - expansion_degrees), cell_degrees)
    right, top = _grid_cell((max_lon + expansion_degrees, max_lat + expansion_degrees), cell_degrees)
    return {
        (column, row)
        for column in range(left, right + 1)
        for row in range(bottom, top + 1)
    }


def _candidate_pairs(assets: list[InfrastructureAsset], settings: DerivationSettings) -> list[tuple[InfrastructureAsset, InfrastructureAsset]]:
    """Return bounded spatial candidates using a deterministic lon/lat grid."""

    cell_degrees = settings.grid_size_km / 111.32
    cells: dict[tuple[int, int], list[InfrastructureAsset]] = defaultdict(list)
    geometries: dict[str, dict[str, Any]] = {}
    for asset in assets:
        geometry = _geometry(asset)
        geometries[asset.id] = geometry
        try:
            bounds = geometry_bounds(geometry)
        except (TypeError, ValueError, KeyError):
            continue
        for cell in _cells_for_bounds(bounds, cell_degrees, settings.adjacency_distance_km):
            cells[cell].append(asset)
    pairs: set[tuple[str, str]] = set()
    by_id = {asset.id: asset for asset in assets}
    for members in cells.values():
        ordered = sorted(members, key=lambda asset: asset.id)
        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                key = (first.id, second.id) if first.id < second.id else (second.id, first.id)
                pairs.add(key)
    return [(by_id[first], by_id[second]) for first, second in sorted(pairs)]


def _relationship(
    first: InfrastructureAsset,
    second: InfrastructureAsset,
    relationship_type: str,
    *,
    derivation_method: str,
    evidence: dict[str, Any],
    distance_km: float | None = None,
    tolerance_m: float | None = None,
) -> DerivedRelationship:
    from_id, to_id = sorted((first.id, second.id))
    return DerivedRelationship(
        relationship_key=f"DERIVED:{relationship_type}:{from_id}:{to_id}",
        from_asset_id=from_id,
        to_asset_id=to_id,
        relationship_type=relationship_type,
        distance_km=distance_km,
        tolerance_m=tolerance_m,
        evidence=evidence,
        derivation_method=derivation_method,
    )


def derive_relationships(
    assets: list[InfrastructureAsset], settings: DerivationSettings | None = None
) -> tuple[list[DerivedRelationship], int]:
    """Derive only defensible edges from BTS ports and FRA rail geometry.

    Rail endpoint topology has priority over ``INTERSECTS``.  Port-to-rail
    adjacency uses a measured great-circle/segment distance and region guard.
    No dependency, supply, alternative, or location edges are generated.
    """

    settings = settings or DerivationSettings()
    valid_assets = [asset for asset in assets if asset.asset_type in {"port", "rail_corridor"}]
    geometries = {asset.id: _geometry(asset) for asset in valid_assets}
    candidates = _candidate_pairs(valid_assets, settings)
    result: list[DerivedRelationship] = []
    tolerance_km = settings.endpoint_tolerance_m / 1000.0
    for first, second in candidates:
        first_geometry = geometries[first.id]
        second_geometry = geometries[second.id]
        evidence_base = {
            "assets": sorted((_asset_evidence(first), _asset_evidence(second)), key=lambda item: item["asset_id"]),
            "geometry_predicate": "",
            "derivation_version": settings.version,
        }
        first_is_rail = first.asset_type == "rail_corridor"
        second_is_rail = second.asset_type == "rail_corridor"
        if first_is_rail and second_is_rail:
            first_endpoints = geometry_endpoints(first_geometry)
            second_endpoints = geometry_endpoints(second_geometry)
            endpoint_distance = min(
                (distance_points_km(left, right) for left in first_endpoints for right in second_endpoints),
                default=float("inf"),
            )
            if endpoint_distance <= tolerance_km:
                evidence = {
                    **evidence_base,
                    "geometry_predicate": "LINESTRING endpoint topology",
                    "tolerance_m": settings.endpoint_tolerance_m,
                    "measured_distance_km": round(endpoint_distance, 8),
                }
                result.append(
                    _relationship(
                        first,
                        second,
                        InfrastructureRelationshipType.CONNECTED_TO.value,
                        derivation_method="rail_endpoint_topology",
                        evidence=evidence,
                        distance_km=endpoint_distance,
                        tolerance_m=settings.endpoint_tolerance_m,
                    )
                )
                continue
            if geometry_intersects(first_geometry, second_geometry):
                evidence = {
                    **evidence_base,
                    "geometry_predicate": "ST_Intersects / segment intersection",
                    "endpoint_connectivity_checked": True,
                    "endpoint_tolerance_m": settings.endpoint_tolerance_m,
                }
                result.append(
                    _relationship(
                        first,
                        second,
                        InfrastructureRelationshipType.INTERSECTS.value,
                        derivation_method="geometry_intersection",
                        evidence=evidence,
                    )
                )
            continue

        if first_is_rail != second_is_rail:
            rail = first if first_is_rail else second
            port = second if first_is_rail else first
            rail_geometry = first_geometry if first_is_rail else second_geometry
            port_geometry = second_geometry if first_is_rail else first_geometry
            if geometry_intersects(first_geometry, second_geometry):
                evidence = {
                    **evidence_base,
                    "geometry_predicate": "ST_Intersects / point on rail geometry",
                    "endpoint_connectivity_checked": False,
                }
                result.append(
                    _relationship(
                        first,
                        second,
                        InfrastructureRelationshipType.INTERSECTS.value,
                        derivation_method="geometry_intersection",
                        evidence=evidence,
                    )
                )
            coordinates = port_geometry.get("coordinates", [])
            if port_geometry.get("type") == "Point" and len(coordinates) >= 2:
                measured_distance = distance_geometry_to_point_km(
                    rail_geometry, float(coordinates[0]), float(coordinates[1])
                )
                if measured_distance <= settings.adjacency_distance_km and _region_compatible(port, rail):
                    evidence = {
                        **evidence_base,
                        "geometry_predicate": "ST_DWithin / port point to rail corridor",
                        "threshold_km": settings.adjacency_distance_km,
                        "measured_distance_km": round(measured_distance, 8),
                        "region_compatible": True,
                    }
                    result.append(
                        _relationship(
                            first,
                            second,
                            InfrastructureRelationshipType.ADJACENT_TO.value,
                            derivation_method="port_rail_distance_and_region",
                            evidence=evidence,
                            distance_km=measured_distance,
                        )
                    )
            continue

        # Future source types are intentionally not connected by proximity.
    return sorted(result, key=lambda item: item.relationship_key), len(candidates)


async def rebuild_derived_relationships(
    session: AsyncSession, settings: DerivationSettings | None = None
) -> RebuildStats:
    """Rebuild derived edges idempotently and remove stale derived rows only."""

    settings = settings or DerivationSettings()
    result = await session.execute(
        select(InfrastructureAsset)
        .options(joinedload(InfrastructureAsset.source))
        .order_by(InfrastructureAsset.id)
    )
    assets = list(result.unique().scalars())
    desired, candidate_count = derive_relationships(assets, settings)
    existing_result = await session.execute(
        select(InfrastructureRelationship).where(
            InfrastructureRelationship.relationship_source == InfrastructureRelationshipSource.DERIVED.value
        )
    )
    existing = {item.relationship_key: item for item in existing_result.scalars().all()}
    desired_keys = {item.relationship_key for item in desired}
    deleted_count = 0
    for key, item in existing.items():
        if key not in desired_keys:
            await session.delete(item)
            deleted_count += 1
    inserted_count = updated_count = 0
    now = datetime.now(timezone.utc)
    for item in desired:
        values = {
            "from_asset_id": item.from_asset_id,
            "to_asset_id": item.to_asset_id,
            "relationship_type": item.relationship_type,
            "directionality": RelationshipDirectionality.UNDIRECTED.value,
            "relationship_source": InfrastructureRelationshipSource.DERIVED.value,
            "source_relationship_id": None,
            "derivation_method": item.derivation_method,
            "derivation_version": settings.version,
            "confidence": None,
            "evidence_json": json.dumps(item.evidence, sort_keys=True),
            "distance_km": item.distance_km,
            "tolerance_m": item.tolerance_m,
            "updated_at": now,
        }
        current = existing.get(item.relationship_key)
        if current is None:
            session.add(
                InfrastructureRelationship(
                    relationship_key=item.relationship_key,
                    created_at=now,
                    **values,
                )
            )
            inserted_count += 1
        else:
            for key, value in values.items():
                setattr(current, key, value)
            updated_count += 1
    await session.commit()
    return RebuildStats(
        assets_considered=len(assets),
        candidate_pairs=candidate_count,
        derived_edges=len(desired),
        inserted_count=inserted_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
        settings=asdict(settings),
    )


def _cli() -> None:
    import argparse
    import asyncio
    import logging
    import sys

    parser = argparse.ArgumentParser(description="Rebuild deterministic derived infrastructure relationships")
    parser.add_argument("--database-url")
    parser.add_argument("--endpoint-tolerance-m", type=float, default=100.0)
    parser.add_argument("--adjacency-distance-km", type=float, default=25.0)
    args = parser.parse_args()

    async def run() -> None:
        from app.config import Settings
        from app.database import create_engine, init_db, session_factory

        settings = Settings(database_url=args.database_url) if args.database_url else Settings()
        engine = create_engine(settings)
        await init_db(engine)
        async with session_factory(engine)() as session:
            stats = await rebuild_derived_relationships(
                session,
                DerivationSettings(
                    endpoint_tolerance_m=args.endpoint_tolerance_m,
                    adjacency_distance_km=args.adjacency_distance_km,
                ),
            )
            print(json.dumps(stats.as_dict(), sort_keys=True))
        await engine.dispose()

    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(str(exc), file=sys.stderr)
        raise


if __name__ == "__main__":
    _cli()
