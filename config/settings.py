from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = parent of the `config/` directory that holds this file.
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    sumo_home: str | None = None
    sumo_gui: bool = False

    sim_seed: int = 42
    sim_step_length: float = 1.0
    sim_duration: int = 3600

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def sim_dir(self) -> Path:
        return PROJECT_ROOT / "sim"

    @property
    def networks_dir(self) -> Path:
        return self.sim_dir / "networks"

    @property
    def routes_dir(self) -> Path:
        return self.sim_dir / "routes"

    @property
    def scenarios_dir(self) -> Path:
        return self.sim_dir / "scenarios"

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    def resolved_sumo_home(self) -> str | None:

        explicit = self.sumo_home or os.environ.get("SUMO_HOME")
        if explicit:
            return explicit
        try:
            import sumo

            return sumo.SUMO_HOME
        except Exception:
            return None

    def ensure_dirs(self) -> None:
        """Create the runtime output directories if they don't exist."""
        for path in (self.outputs_dir, self.videos_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton accessor for the settings object."""
    return Settings()


settings = get_settings()
