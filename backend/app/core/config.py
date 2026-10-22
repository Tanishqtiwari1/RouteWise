from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment configuration. Business assumptions (prices, speeds, ...) live
    in the database-backed workspace settings instead, so users can edit them."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ROUTEWISE_", extra="ignore")

    environment: str = "development"
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'routewise.db'}"
    data_dir: Path = BACKEND_DIR / "data"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    log_level: str = "INFO"

    # Optional shared secret for administrative actions (road closures, network
    # ingestion, settings). When unset, these actions are open (local dev only).
    admin_token: str | None = None

    # External providers. Public OSM endpoints have strict usage policies:
    # identify the application and keep request volume low.
    http_user_agent: str = "RouteWise/1.0 (self-hosted; set ROUTEWISE_HTTP_USER_AGENT with contact info)"
    http_timeout_s: float = 30.0
    overpass_timeout_s: float = 180.0
    geocoder_min_interval_s: float = 1.1

    # Abuse / resource protection.
    max_network_area_km2: float = 200.0
    max_snap_distance_m: float = 1500.0
    ucs_max_expansions: int = 3_000_000
    ucs_time_limit_s: float = 20.0
    multi_stop_max_stops: int = 10
    multi_stop_max_states: int = 300_000
    rate_limit_per_minute: int = 30
    max_csv_bytes: int = 2_000_000
    max_csv_rows: int = 5_000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v):
        items = [o.strip() for o in v.split(",")] if isinstance(v, str) else list(v)
        # Hosting platforms often pass bare hostnames between services.
        return [o if "://" in o else f"https://{o}" for o in items if o]

    @field_validator("database_url", mode="before")
    @classmethod
    def sqlalchemy_driver(cls, v: str) -> str:
        # Managed Postgres providers hand out postgres:// or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if isinstance(v, str) and v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def networks_dir(self) -> Path:
        return self.data_dir / "networks"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and not s.admin_token:
        raise RuntimeError("ROUTEWISE_ADMIN_TOKEN must be set when ROUTEWISE_ENVIRONMENT=production")
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.networks_dir.mkdir(parents=True, exist_ok=True)
    return s
