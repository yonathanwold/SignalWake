"""Authoritative source/layer registry.

The registry is deliberately metadata-first. A row can describe a useful
reference or credentialed dataset without implying that SIGNALWAKE downloaded
it or has current records. Only adapters with persisted source state are
reported as LIVE/ERROR; unavailable layers return an empty data response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import InfrastructureAsset, InfrastructureSource, Source
from app.schemas import LayerCatalogItem
from app.temporal import TemporalWindow

CATALOG_VERSION = "1.0.0"


@dataclass(frozen=True)
class CatalogSpec:
    key: str
    name: str
    category: str
    geometry_kind: str
    data_kind: str
    temporal_semantics: str
    applies_to_48h_window: bool
    endpoint: str
    status: str
    adapter_version: str = CATALOG_VERSION
    source_key: str | None = None
    provenance: dict[str, object] | None = None
    coverage: dict[str, Any] | None = None


def _spec(
    key: str,
    name: str,
    category: str,
    geometry_kind: str,
    data_kind: str,
    temporal_semantics: str,
    applies: bool,
    endpoint: str,
    status: str,
    *,
    source_key: str | None = None,
    adapter_version: str = CATALOG_VERSION,
    coverage: dict[str, Any] | None = None,
) -> CatalogSpec:
    return CatalogSpec(
        key,
        name,
        category,
        geometry_kind,
        data_kind,
        temporal_semantics,
        applies,
        endpoint,
        status,
        adapter_version,
        source_key,
        {"registry_version": CATALOG_VERSION, "authority": name},
        coverage,
    )


CATALOG: tuple[CatalogSpec, ...] = (
    _spec("nws_alerts", "NWS active alerts", "weather", "Point/Polygon", "operational events", "effective, expires, updated", True, "https://api.weather.gov/alerts/active?status=actual", "LIVE", source_key="nws"),
    _spec("nws_forecasts", "NWS forecasts", "weather", "Point/Polygon", "forecast observations", "issued and valid forecast periods", True, "https://api.weather.gov/points", "NOT_CONNECTED"),
    _spec("nws_observations", "NWS observations", "weather", "Point", "station observations", "observation time", True, "https://api.weather.gov/observations?limit=500", "LIVE", source_key="nws_observations"),
    _spec("nws_storm_reports", "NWS storm reports", "weather", "Point", "storm reports", "report time", True, "https://www.spc.noaa.gov/climo/reports/", "NOT_CONNECTED"),
    _spec("usgs_earthquakes", "USGS earthquakes", "seismic", "Point", "observed events", "event time and updated time", True, "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson", "LIVE", source_key="usgs"),
    _spec("usgs_water", "USGS water services", "hydrology", "Point", "near-real-time gauge observations", "observation time", True, "https://waterservices.usgs.gov/nwis/iv/?format=json&parameterCd=00060&siteStatus=active", "NEAR_REAL_TIME", source_key="usgs_water", coverage={"mode": "bounded state fan-out", "max_states": 25, "max_features": 1000}),
    _spec("nasa_firms", "NASA FIRMS active fire", "fire", "Point", "near-real-time detections", "acquisition time", True, "https://firms.modaps.eosdis.nasa.gov/api/area/csv", "REQUIRES_CREDENTIALS", source_key="nasa_firms", coverage={"requires": "FIRMS_MAP_KEY", "days_max": 2, "max_features": 1000}),
    _spec("airnow", "AirNow air quality", "air_quality", "Point", "near-real-time observations", "observation time", True, "https://www.airnowapi.org/aq/data/", "REQUIRES_CREDENTIALS", source_key="airnow", coverage={"requires": "AIRNOW_API_KEY", "max_features": 1000}),
    _spec("nhc_systems", "NHC current tropical systems", "tropical_weather", "Point/Polygon", "current systems", "advisory and valid times", True, "https://www.nhc.noaa.gov/CurrentStorms.json", "NEAR_REAL_TIME", source_key="nhc"),
    _spec("noaa_coops", "NOAA CO-OPS water levels", "coastal", "Point", "station observations", "observation time", True, "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter", "NEAR_REAL_TIME", source_key="noaa_coops", coverage={"mode": "bounded station set", "max_stations": 25, "max_features": 25}),
    _spec("bts", "BTS transportation assets", "transportation", "Point/Line/Polygon", "reference assets", "source publication/update time", False, "https://data-usdot.opendata.arcgis.com/", "REFERENCE", source_key="bts_ports"),
    _spec("fra", "FRA rail network", "transportation", "Line", "reference assets", "source publication/update time", False, "https://data-usdot.opendata.arcgis.com/", "REFERENCE", source_key="fra_rail"),
    _spec("faa", "FAA facilities and advisories", "aviation", "Point/Polygon", "reference and operational data", "source timestamp", True, "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/", "NOT_CONNECTED"),
    _spec("energy", "Energy infrastructure", "energy", "Point/Line/Polygon", "reference assets", "source publication/update time", False, "https://atlas.eia.gov/", "NOT_CONNECTED"),
    _spec("dams", "National dam inventory", "water_infrastructure", "Point", "reference assets", "source publication/update time", False, "https://nid.sec.usace.army.mil/", "REFERENCE"),
    _spec("hospitals", "Hospitals", "public_safety", "Point", "reference assets", "source publication/update time", False, "https://data.cms.gov/", "REFERENCE"),
    _spec("shelters", "Emergency shelters", "public_safety", "Point", "local operational data", "publisher timestamp", True, "https://www.fema.gov/openfema-data-page", "NOT_CONNECTED"),
    _spec("public_safety", "Public safety facilities", "public_safety", "Point/Polygon", "reference assets", "source publication/update time", False, "https://data.gov/", "NOT_CONNECTED"),
    _spec("mrms", "NOAA MRMS precipitation", "weather", "Raster/Tile", "near-real-time raster", "scan/valid time", True, "https://www.nssl.noaa.gov/projects/mrms/", "NOT_CONNECTED"),
    _spec("lightning", "NOAA lightning", "weather", "Point/Tile", "near-real-time observations", "detection time", True, "https://www.ncei.noaa.gov/", "NOT_CONNECTED"),
    _spec("snow_temperature", "NOAA snow and temperature", "weather", "Raster/Point", "observations and grids", "observation/valid time", True, "https://www.ncei.noaa.gov/", "NOT_CONNECTED"),
    _spec("drought_soil", "Drought and soil moisture", "environment", "Raster/Polygon", "indices and observations", "observation/valid time", True, "https://droughtmonitor.unl.edu/", "REFERENCE"),
    _spec("land_elevation", "USGS elevation", "terrain", "Raster/Tile", "reference raster", "static publication", False, "https://www.usgs.gov/3d-elevation-program", "REFERENCE"),
    _spec("watersheds_hydrography", "USGS watersheds and hydrography", "hydrology", "Line/Polygon/Tile", "reference geography", "static publication", False, "https://www.usgs.gov/national-hydrography", "REFERENCE"),
    _spec("census", "U.S. Census geography", "demographics", "Polygon", "reference geography", "vintage/publication", False, "https://www.census.gov/geographies/mapping-files.html", "REFERENCE"),
    _spec("fema_nri", "FEMA National Risk Index", "risk", "Polygon", "reference risk indices", "vintage/publication", False, "https://hazards.fema.gov/nri/", "REFERENCE"),
    _spec("fema_declarations", "FEMA declarations", "emergency_management", "Point/Polygon", "declarations", "declaration and incident dates", True, "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries", "NOT_CONNECTED"),
    _spec("social_vulnerability", "CDC/ATSDR social vulnerability", "vulnerability", "Polygon", "reference index", "vintage/publication", False, "https://www.atsdr.cdc.gov/placeandhealth/svi/", "REFERENCE"),
    _spec("cdc_wastewater", "CDC wastewater surveillance", "public_health", "Point/Polygon", "near-real-time observations", "sample/report time", True, "https://www.cdc.gov/nwss/rv/COVID19-nationalData.html", "NOT_CONNECTED"),
)


def specs_by_key() -> dict[str, CatalogSpec]:
    return {item.key: item for item in CATALOG}


def _coverage(spec: CatalogSpec) -> dict[str, Any]:
    settings = get_settings()
    coverage = dict(spec.coverage or {})
    if spec.key == "usgs_water":
        coverage.update(
            {
                "states": [state.strip().upper() for state in settings.usgs_water_states.split(",") if state.strip()][:25],
                "parameter": "00060",
                "max_features": 1000,
            }
        )
    elif spec.key == "nasa_firms":
        coverage.update({"area": settings.firms_area, "product": settings.firms_product, "days": settings.firms_days})
    elif spec.key == "airnow":
        coverage.update({"bbox": settings.airnow_bbox, "parameters": settings.airnow_parameters, "hours": 48})
    elif spec.key == "noaa_coops":
        coverage.update(
            {
                "station_ids": [station.strip() for station in settings.noaa_coops_station_ids.split(",") if station.strip()],
                "station_limit": settings.noaa_coops_station_limit,
            }
        )
    return coverage


async def catalog_items(
    session: AsyncSession,
    window: TemporalWindow,
    *,
    generated_at: datetime,
) -> list[LayerCatalogItem]:
    """Project static registry rows onto current persisted source state."""

    sources = {source.key: source for source in (await session.execute(select(Source))).scalars().all()}
    infrastructure_sources = {
        source.key: source
        for source in (await session.execute(select(InfrastructureSource))).scalars().all()
    }
    result: list[LayerCatalogItem] = []
    for spec in CATALOG:
        source = sources.get(spec.source_key or "")
        infra = infrastructure_sources.get(spec.source_key or "")
        status = spec.status
        last_refresh = None
        counts: dict[str, int] = {}
        error = None
        adapter_version = spec.adapter_version
        endpoint = spec.endpoint
        if source is not None:
            if spec.status == "REQUIRES_CREDENTIALS" and source.last_attempt_at is None:
                status = spec.status
            else:
                status = (
                    "ERROR"
                    if source.last_error and source.last_success_at is None
                    else "DEGRADED"
                    if source.last_error
                    else "LIVE"
                    if source.last_success_at
                    else "NOT_CONNECTED"
                )
            last_refresh = source.last_success_at or source.last_attempt_at
            counts = {
                "retrieved": int(source.last_records_retrieved or 0),
                "accepted": int(source.last_records_accepted or 0),
                "rejected": int(source.last_records_rejected or 0),
            }
            adapter_version = source.adapter_version
            endpoint = source.endpoint
            error = source.last_error
        elif infra is not None:
            status = "REFERENCE"
            last_refresh = infra.last_success_at
            asset_count = int(
                (
                    await session.execute(
                        select(func.count(InfrastructureAsset.id)).where(
                            InfrastructureAsset.source_id == infra.id
                        )
                    )
                ).scalar_one()
            )
            counts = {"assets": asset_count}
            adapter_version = infra.adapter_version
            endpoint = infra.endpoint
        result.append(
            LayerCatalogItem(
                key=spec.key,
                name=spec.name,
                category=spec.category,
                geometry_kind=spec.geometry_kind,
                data_kind=spec.data_kind,
                temporal_semantics=spec.temporal_semantics,
                applies_to_48h_window=spec.applies_to_48h_window,
                endpoint=endpoint,
                status=status,
                adapter_version=adapter_version,
                last_refresh=last_refresh,
                counts=counts,
                source_key=spec.source_key,
                error=error,
                coverage=_coverage(spec),
                provenance={**(spec.provenance or {}), "window_start": window.start.isoformat(), "window_end": window.end.isoformat()},
            )
        )
    return result
