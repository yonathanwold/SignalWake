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
    usgs_earthquake_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    )
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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
