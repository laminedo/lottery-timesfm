"""Runtime settings, read from the environment (or backend/.env)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Postgres connection string (Supabase, Neon, ...). Unset: an embedded Postgres under `pgdata_dir`.
    database_url: str | None = None
    pgdata_dir: Path = BACKEND_DIR / "data" / "pgdata"
    seed_dir: Path = BACKEND_DIR / "data" / "seed"

    # auto: TimesFM when installed, otherwise exponential smoothing. Or force "timesfm" / "smoothing".
    forecast_backend: str = "auto"
    # Set to run TimesFM in a separate inference service (see app/inference_service.py).
    inference_url: str | None = None
    timesfm_model: str = "google/timesfm-2.5-200m-pytorch"
    timesfm_device: str = "auto"  # auto | cpu | mps | cuda
    timesfm_batch_size: int = 128
    timesfm_context: int = 512
    timesfm_flip_invariance: bool = False  # doubles inference time when on

    # Pull new draws from the official sources on startup and then every `refresh_hours`.
    auto_refresh: bool = True
    refresh_hours: float = 6.0

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
