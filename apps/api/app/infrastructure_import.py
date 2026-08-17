from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InfrastructureAsset,
    InfrastructureSource,
    ProcessingState,
    RawInfrastructureRecord,
)
from app.spatial import GeometryValidationError, geometry_centroid, validate_geometry

log = logging.getLogger(__name__)

SOURCE_DEFINITIONS: dict[str, dict[str, str]] = {
    "bts_ports": {
        "name": "Bureau of Transportation Statistics Port Facilities",
        "endpoint": "https://data-usdot.opendata.arcgis.com/datasets/usdot::port-facilities/about",
        "attribution": "U.S. Department of Transportation, Bureau of Transportation Statistics",
        "license": "U.S. Government public data; confirm dataset terms on the source page",
        "asset_type": "port",
    },
    "fra_rail": {
        "name": "Federal Railroad Administration Rail Lines",
        "endpoint": "https://data-usdot.opendata.arcgis.com/datasets/usdot::rail-lines/about",
        "attribution": "U.S. Department of Transportation, Federal Railroad Administration",
        "license": "U.S. Government public data; confirm dataset terms on the source page",
        "asset_type": "rail_corridor",
    },
}


@dataclass(frozen=True)
class InfrastructureImportStats:
    source_key: str
    fetched_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    duplicate_count: int
    imported_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _first(properties: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = properties.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # ArcGIS date properties are milliseconds from Unix epoch.
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _arcgis_geometry(geometry: dict[str, Any]) -> dict[str, Any] | None:
    if "x" in geometry and "y" in geometry:
        return {"type": "Point", "coordinates": [geometry["x"], geometry["y"]]}
    if isinstance(geometry.get("paths"), list) and geometry["paths"]:
        return {"type": "LineString", "coordinates": geometry["paths"][0]}
    if isinstance(geometry.get("rings"), list) and geometry["rings"]:
        return {"type": "Polygon", "coordinates": geometry["rings"]}
    return None


def normalize_feature(feature: dict[str, Any], source_key: str) -> dict[str, Any]:
    if not isinstance(feature, dict):
        raise ValueError("feature must be an object")
    properties = feature.get("properties") or feature.get("attributes") or {}
    if not isinstance(properties, dict):
        raise ValueError("feature properties must be an object")
    source_record_id = _first(
        properties,
        "source_asset_id",
        "SOURCE_ID",
        "OBJECTID",
        "OBJECTID_1",
        "FID",
        "UNLOCODE",
        "id",
    )
    source_record_id = source_record_id or feature.get("id")
    if source_record_id in (None, ""):
        raise ValueError("feature has no stable source identifier")

    geometry = feature.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") not in {"Point", "LineString", "Polygon"}:
        geometry = _arcgis_geometry(geometry)
    if geometry is None:
        longitude = _first(properties, "longitude", "LONGITUDE", "lon", "x", "X")
        latitude = _first(properties, "latitude", "LATITUDE", "lat", "y", "Y")
        if longitude is not None and latitude is not None:
            geometry = {"type": "Point", "coordinates": [longitude, latitude]}
    geometry = validate_geometry(geometry)
    longitude, latitude = geometry_centroid(geometry)

    if source_key == "bts_ports":
        asset_type = "port"
        subtype = _first(properties, "PORT_TYPE", "port_type", "FACILITY_TYPE", "facility_type")
        name = _first(properties, "PORT_NAME", "port_name", "NAME", "name") or f"Port {source_record_id}"
    elif source_key == "fra_rail":
        asset_type = "rail_corridor"
        subtype = _first(properties, "SUBDIVISION", "subdivision", "RAIL_TYPE", "rail_type", "TYPE", "type")
        name = _first(properties, "RAILROAD", "railroad", "NAME", "name", "ROUTE_NAME") or f"Rail corridor {source_record_id}"
    else:
        definition = SOURCE_DEFINITIONS.get(source_key)
        if definition is None:
            raise ValueError(f"unknown infrastructure source: {source_key}")
        asset_type = definition["asset_type"]
        subtype = _first(properties, "SUBTYPE", "subtype", "TYPE", "type")
        name = _first(properties, "NAME", "name") or f"Infrastructure asset {source_record_id}"

    return {
        "source_asset_id": str(source_record_id),
        "name": str(name),
        "asset_type": asset_type,
        "asset_subtype": str(subtype) if subtype is not None else None,
        "operator": _first(properties, "OPERATOR", "operator", "RAILROAD_OWNER"),
        "owner": _first(properties, "OWNER", "owner", "OWNER_NAME"),
        "status": _first(properties, "STATUS", "status", "OPERATIONAL_STATUS"),
        "region": _first(properties, "STATE", "state", "REGION", "region", "COUNTRY", "country"),
        "latitude": latitude,
        "longitude": longitude,
        "geometry": geometry,
        "geometry_type": geometry["type"],
        "metadata": properties,
        "source_updated_at": _parse_datetime(
            _first(properties, "source_updated_at", "LAST_EDITED_DATE", "last_edited_date", "UPDATED_AT", "updated_at")
        ),
    }


def _feature_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("infrastructure payload must be a JSON object or feature list")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("infrastructure payload must contain a features list")
    return features


async def load_payload(*, file_path: str | None = None, url: str | None = None, timeout: float = 30) -> Any:
    if bool(file_path) == bool(url):
        raise ValueError("provide exactly one of --file or --url")
    if file_path:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url or "")
        response.raise_for_status()
        return response.json()


async def ensure_infrastructure_source(
    session: AsyncSession,
    source_key: str,
    *,
    endpoint: str | None = None,
    adapter_version: str = "1.0.0",
) -> InfrastructureSource:
    definition = SOURCE_DEFINITIONS.get(source_key)
    if definition is None:
        raise ValueError(f"unknown infrastructure source: {source_key}")
    source = (
        await session.execute(select(InfrastructureSource).where(InfrastructureSource.key == source_key))
    ).scalar_one_or_none()
    if source is None:
        source = InfrastructureSource(
            key=source_key,
            name=definition["name"],
            endpoint=endpoint or definition["endpoint"],
            attribution=definition["attribution"],
            license=definition["license"],
            adapter_version=adapter_version,
        )
        session.add(source)
        await session.flush()
    elif endpoint:
        source.endpoint = endpoint
    return source


async def _sync_postgis_geometry(session: AsyncSession, asset: InfrastructureAsset) -> None:
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    await session.execute(
        text(
            "UPDATE infrastructure_assets "
            "SET geometry = ST_SetSRID(ST_GeomFromGeoJSON(:geometry_geojson), 4326) "
            "WHERE id = :asset_id"
        ),
        {"geometry_geojson": asset.geometry_geojson, "asset_id": asset.id},
    )


async def import_payload(
    session: AsyncSession,
    source_key: str,
    payload: Any,
    *,
    fetched_at: datetime | None = None,
    endpoint: str | None = None,
    batch_size: int = 250,
) -> InfrastructureImportStats:
    if batch_size < 1 or batch_size > 5000:
        raise ValueError("batch_size must be between 1 and 5000")
    fetched_at = fetched_at or datetime.now(timezone.utc)
    source = await ensure_infrastructure_source(session, source_key, endpoint=endpoint)
    features = _feature_list(payload)
    inserted_count = updated_count = skipped_count = duplicate_count = 0
    processed = 0
    for index, feature in enumerate(features):
        try:
            normalized = normalize_feature(feature, source_key)
            digest = payload_hash(feature)
            raw = (
                await session.execute(
                    select(RawInfrastructureRecord).where(
                        RawInfrastructureRecord.source_id == source.id,
                        RawInfrastructureRecord.payload_hash == digest,
                    )
                )
            ).scalar_one_or_none()
            if raw is None:
                raw = RawInfrastructureRecord(
                    source_id=source.id,
                    source_record_id=normalized["source_asset_id"],
                    source_updated_at=normalized["source_updated_at"],
                    fetched_at=fetched_at,
                    payload=json.dumps(feature, sort_keys=True),
                    payload_hash=digest,
                    processing_state=ProcessingState.RECEIVED.value,
                    adapter_version=source.adapter_version,
                )
                session.add(raw)
                await session.flush()
            else:
                duplicate_count += 1

            asset = (
                await session.execute(
                    select(InfrastructureAsset).where(
                        InfrastructureAsset.source_id == source.id,
                        InfrastructureAsset.source_asset_id == normalized["source_asset_id"],
                    )
                )
            ).scalar_one_or_none()
            geometry_json = json.dumps(normalized["geometry"], sort_keys=True)
            provenance_json = json.dumps(
                [
                    {
                        "source_record_id": normalized["source_asset_id"],
                        "source_url": source.endpoint,
                        "source_name": source.name,
                        "attribution": source.attribution,
                        "license": source.license,
                        "fetched_at": fetched_at.isoformat(),
                        "raw_record_id": raw.id,
                        "adapter_version": source.adapter_version,
                        "payload_hash": digest,
                    }
                ],
                sort_keys=True,
            )
            values = {
                "raw_infrastructure_record_id": raw.id,
                "name": normalized["name"],
                "asset_type": normalized["asset_type"],
                "asset_subtype": normalized["asset_subtype"],
                "operator": normalized["operator"],
                "owner": normalized["owner"],
                "status": normalized["status"],
                "region": normalized["region"],
                "latitude": normalized["latitude"],
                "longitude": normalized["longitude"],
                "geometry_type": normalized["geometry_type"],
                "geometry_geojson": geometry_json,
                "metadata_json": json.dumps(normalized["metadata"], sort_keys=True),
                "provenance_json": provenance_json,
                "payload_hash": digest,
                "classification": "REFERENCE",
                "source_updated_at": normalized["source_updated_at"],
                "imported_at": fetched_at,
                "updated_at": fetched_at,
                "normalized_version": source.adapter_version,
            }
            if asset is None:
                asset = InfrastructureAsset(source_id=source.id, source_asset_id=normalized["source_asset_id"], **values)
                session.add(asset)
                inserted_count += 1
            else:
                for key, value in values.items():
                    setattr(asset, key, value)
                updated_count += 1
            raw.processing_state = ProcessingState.NORMALIZED.value
            await session.flush()
            await _sync_postgis_geometry(session, asset)
            processed += 1
            if processed % batch_size == 0:
                await session.commit()
                log.info("infrastructure_import_batch", extra={"source": source_key, "processed": processed})
        except (GeometryValidationError, KeyError, TypeError, ValueError) as exc:
            skipped_count += 1
            log.warning("infrastructure_record_skipped", extra={"source": source_key, "index": index, "error": str(exc)})

    source.last_import_at = fetched_at
    source.last_import_count = processed
    source.last_import_error = f"{skipped_count} malformed record(s) skipped" if skipped_count else None
    await session.commit()
    return InfrastructureImportStats(
        source_key=source_key,
        fetched_count=len(features),
        inserted_count=inserted_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        duplicate_count=duplicate_count,
        imported_at=fetched_at,
    )


async def import_source(
    session: AsyncSession,
    source_key: str,
    *,
    file_path: str | None = None,
    url: str | None = None,
    batch_size: int = 250,
    timeout: float = 30,
) -> InfrastructureImportStats:
    payload = await load_payload(file_path=file_path, url=url, timeout=timeout)
    return await import_payload(session, source_key, payload, endpoint=url, batch_size=batch_size)


def _cli() -> None:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Import Phase 2 infrastructure reference GeoJSON")
    parser.add_argument("--source", choices=sorted(SOURCE_DEFINITIONS), required=True)
    parser.add_argument("--file", dest="file_path")
    parser.add_argument("--url")
    parser.add_argument("--database-url")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if bool(args.file_path) == bool(args.url):
        parser.error("provide exactly one of --file or --url")

    from app.config import Settings
    from app.database import create_engine, session_factory

    async def run() -> None:
        settings = Settings(database_url=args.database_url) if args.database_url else Settings()
        engine = create_engine(settings)
        await __import__("app.database", fromlist=["init_db"]).init_db(engine)
        async with session_factory(engine)() as session:
            stats = await import_source(
                session,
                args.source,
                file_path=args.file_path,
                url=args.url,
                batch_size=args.batch_size,
                timeout=args.timeout,
            )
            print(json.dumps(stats.as_dict(), default=str, sort_keys=True))
        await engine.dispose()

    import logging as _logging

    _logging.basicConfig(level=_logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    _cli()
