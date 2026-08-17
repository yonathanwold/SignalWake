from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./signalwake.db"
    ingest_on_startup: bool = True
    use_demo_data: bool = True
    nws_alerts_url: str = "https://api.weather.gov/alerts/active?status=actual"
    usgs_earthquake_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    )
    source_user_agent: str = "signalwake-portfolio/0.1 (contact@example.com)"
    request_timeout_seconds: float = 15.0
    adapter_version: str = "1.0.0"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
