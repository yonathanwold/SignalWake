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
    nasa_eonet_url: str = "https://eonet.gsfc.nasa.gov/api/v3/events/geojson?status=all&days=2&bbox=-130,55,-60,20&limit=500"
    nasa_eonet_bbox: str = "-130,55,-60,20"
    nasa_eonet_days: int = 2
    nasa_eonet_limit: int = 500
    aviation_weather_url: str = "https://aviationweather.gov/api/data/pirep?age=48&format=geojson"
    aviation_weather_bbox: str = ""
    aviation_weather_age_hours: int = 48
    aviation_weather_limit: int = 400
    opensky_url: str = "https://opensky-network.org/api/states/all"
    opensky_bbox: str = "24,-125,50,-66"
    opensky_limit: int = 8000
    opensky_refresh_seconds: int = 90
    fema_declarations_url: str = "https://gis.fema.gov/arcgis/rest/services/FEMA/DECS_ALL/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson"
    fema_declarations_limit: int = 2000
    road511_url: str = "https://api.road511.com/api/v1/events"
    road511_api_key: str | None = None
    road511_bbox: str = "-130,20,-60,55"
    road511_jurisdiction: str = "WA"
    road511_limit: int = 200
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_coordinates: str = "25,-125;25,-115;25,-105;25,-95;25,-85;25,-75;35,-125;35,-115;35,-105;35,-95;35,-85;35,-75;45,-125;45,-115;45,-105;45,-95;45,-85;45,-75"
    open_meteo_past_hours: int = 6
    open_meteo_limit: int = 108
    rainviewer_url: str = "https://api.rainviewer.com/public/weather-maps.json"
    nppes_url: str = "https://npiregistry.cms.hhs.gov/api/?version=2.1&state=VA&enumeration_type=NPI-2&address_purpose=LOCATION"
    nppes_state: str = "VA"
    nppes_limit: int = 200
    census_states_url: str = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State/MapServer/0/query?where=1%3D1&outFields=NAME,GEOID&returnGeometry=true&outSR=4326&f=geojson"
    census_states_limit: int = 60
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
        if self.nasa_eonet_days < 1 or self.nasa_eonet_days > 2:
            raise ValueError("NASA_EONET_DAYS must be between 1 and 2")
        if self.nasa_eonet_limit < 1 or self.nasa_eonet_limit > 500:
            raise ValueError("NASA_EONET_LIMIT must be between 1 and 500")
        if self.aviation_weather_age_hours < 1 or self.aviation_weather_age_hours > 48:
            raise ValueError("AVIATION_WEATHER_AGE_HOURS must be between 1 and 48")
        if self.aviation_weather_limit < 1 or self.aviation_weather_limit > 400:
            raise ValueError("AVIATION_WEATHER_LIMIT must be between 1 and 400")
        if self.opensky_limit < 1 or self.opensky_limit > 10000:
            raise ValueError("OPENSKY_LIMIT must be between 1 and 10000")
        if self.opensky_refresh_seconds < 15 or self.opensky_refresh_seconds > 900:
            raise ValueError("OPENSKY_REFRESH_SECONDS must be between 15 and 900")
        if self.fema_declarations_limit < 1 or self.fema_declarations_limit > 2000:
            raise ValueError("FEMA_DECLARATIONS_LIMIT must be between 1 and 2000")
        if self.road511_limit < 1 or self.road511_limit > 500:
            raise ValueError("ROAD511_LIMIT must be between 1 and 500")
        if self.open_meteo_past_hours < 1 or self.open_meteo_past_hours > 24:
            raise ValueError("OPEN_METEO_PAST_HOURS must be between 1 and 24")
        if self.open_meteo_limit < 1 or self.open_meteo_limit > 200:
            raise ValueError("OPEN_METEO_LIMIT must be between 1 and 200")
        if self.nppes_limit < 1 or self.nppes_limit > 200:
            raise ValueError("NPPES_LIMIT must be between 1 and 200")
        if self.census_states_limit < 1 or self.census_states_limit > 60:
            raise ValueError("CENSUS_STATES_LIMIT must be between 1 and 60")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
