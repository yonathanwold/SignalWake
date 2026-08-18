from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./signalwake.db"
    ingest_on_startup: bool = True
    use_demo_data: bool = True
    nws_alerts_url: str = "https://api.weather.gov/alerts/active?status=actual"
    nws_observations_url: str = "https://api.weather.gov/observations?limit=500"
    usgs_earthquake_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    )
    usgs_water_url: str = (
        "https://waterservices.usgs.gov/nwis/iv/?format=json&parameterCd=00060&siteStatus=active"
    )
    usgs_water_states: str = "VA,CA,TX,WA,FL,NY,PA,OH,IL,CO,AZ,NC"
    nhc_url: str = "https://www.nhc.noaa.gov/CurrentStorms.json"
    firms_map_key: str | None = None
    firms_area: str = "USA"
    firms_product: str = "VIIRS_SNPP_NRT"
    firms_days: int = 2
    firms_url: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    airnow_api_key: str | None = None
    airnow_bbox: str = "-130,20,-60,55"
    airnow_parameters: str = "PM25,OZONE"
    airnow_url: str = "https://www.airnowapi.org/aq/data/"
    noaa_coops_station_ids: str = ""
    noaa_coops_station_limit: int = 10
    noaa_coops_metadata_url: str = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels&units=metric"
    noaa_coops_data_url: str = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    source_user_agent: str = "signalwake-portfolio/0.1 (contact@example.com)"
    request_timeout_seconds: float = 15.0
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_allow_credentials: bool = True
    adapter_version: str = "1.0.0"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def cors_origin_list(self) -> list[str]:
        """Return normalized CORS origins from a comma-separated setting."""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_cors(self) -> "Settings":
        origins = self.cors_origin_list
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        if "*" in origins and self.cors_allow_credentials:
            raise ValueError("CORS wildcard cannot be combined with credentials")
        if self.request_timeout_seconds <= 0 or self.request_timeout_seconds > 120:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be greater than 0 and at most 120")
        if self.firms_days < 1 or self.firms_days > 2:
            raise ValueError("FIRMS_DAYS must be between 1 and 2 for the operational window")
        if self.noaa_coops_station_limit < 1 or self.noaa_coops_station_limit > 25:
            raise ValueError("NOAA_COOPS_STATION_LIMIT must be between 1 and 25")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
