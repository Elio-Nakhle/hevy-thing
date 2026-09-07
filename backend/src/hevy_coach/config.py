"""Runtime configuration, loaded from the environment and an optional .env file."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(__file__).resolve().parent / "data"

Sex = Literal["male", "female"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Hevy CSV export ----------------------------------------------------
    # Drop exports here (Hevy -> Settings -> Export Data); the newest CSV in the
    # folder is the one that gets imported.
    workouts_dir: Path = REPO_ROOT / "workouts"

    # --- Anthropic ----------------------------------------------------------
    # Left unset by default so the SDK's own credential chain applies
    # (ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile).
    anthropic_api_key: str | None = None
    coach_model: str = "claude-opus-5"
    coach_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"

    # --- Storage ------------------------------------------------------------
    database_path: Path = REPO_ROOT / "data" / "hevy.db"

    # --- Lifter profile -----------------------------------------------------
    # Used to place your lifts on the strength-standard curves.
    sex: Sex = "male"
    bodyweight_kg: float = Field(default=80.0, gt=20, lt=300)
    birth_date: date | None = None
    units: Literal["kg", "lb"] = "kg"

    # --- Server -------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def age(self) -> float | None:
        """Age in years, or None when no birth date is configured."""
        if self.birth_date is None:
            return None
        return (date.today() - self.birth_date).days / 365.2425


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
