"""Runtime configuration, loaded from the environment and an optional .env file."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hevy_coach.goals import Goal

#: How a log records the load on a two-dumbbell movement. Lives here rather than
#: in the analytics package, which imports this module back for DATA_DIR.
DumbbellLoad = Literal["per_dumbbell", "combined"]

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
    # What the log is for. Changes which findings the analytics report and the
    # thresholds they use - see hevy_coach/goals.py.
    training_goal: Goal = "hypertrophy"
    bodyweight_kg: float = Field(default=80.0, gt=20, lt=300)
    # How you type the load for a two-dumbbell movement. The standards are
    # published per dumbbell, which is also what Hevy asks for; set this to
    # "combined" if you enter the pair's total instead.
    dumbbell_load: DumbbellLoad = "per_dumbbell"
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
    def bodyweight_is_default(self) -> bool:
        """True when nothing supplied a bodyweight and the class default stands.

        Every strength standard is indexed on bodyweight, so a defaulted number
        silently rescales the whole benchmark - at 80 kg a 60 kg bench is
        "beginner", at 55 kg it is "novice" most of the way to intermediate.
        Callers use this to say the figure is a placeholder rather than present
        it as the lifter's.
        """
        return "bodyweight_kg" not in self.model_fields_set

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
