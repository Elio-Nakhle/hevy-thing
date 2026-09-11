"""Runtime configuration, loaded from the environment and an optional .env file."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hevy_coach.goals import Goal

#: How a log records the load on a two-dumbbell movement. Lives here rather than
#: in the analytics package, which imports this module back for DATA_DIR.
DumbbellLoad = Literal["per_dumbbell", "combined"]

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(__file__).resolve().parent / "data"

#: How the coach reaches a model: the Anthropic API, the local `claude` CLI, or
#: whichever of the two this machine can actually run.
CoachBackend = Literal["auto", "api", "cli"]

Sex = Literal["male", "female"]
Units = Literal["kg", "lb"]
#: Kilograms, bounded to catch a typo or a wrong field rather than to police a
#: plausible bodyweight - 181 lb is 82 kg and also a real 181 kg lifter, so no
#: range can tell those apart. Converting pounds to kilograms is the form's job.
#: Shared with the profile form so the API rejects what the loader would have.
BodyweightKg = Annotated[float, Field(gt=20, lt=300)]

#: The lifter-profile fields the setup form asks for and writes to .env. Order
#: is the order the form presents them in.
PROFILE_FIELDS = (
    "sex",
    "bodyweight_kg",
    "birth_date",
    "units",
    "dumbbell_load",
    "training_goal",
)


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
    # Where the coach's model runs. "api" needs a key above; "cli" needs Claude
    # Code installed and signed in, and costs no key at all. "auto" takes the
    # key when there is one and the CLI otherwise - see coach/cli_agent.py.
    coach_backend: CoachBackend = "auto"
    coach_model: str = "claude-opus-5"
    # Effort buys thinking tokens, which are output tokens, which are the
    # dearest thing in the request. "medium" answers a training question from a
    # briefing and a couple of queries; raise it for a genuinely open analysis.
    coach_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    # --- Storage ------------------------------------------------------------
    database_path: Path = REPO_ROOT / "data" / "hevy.db"

    # --- Lifter profile -----------------------------------------------------
    # Used to place your lifts on the strength-standard curves.
    sex: Sex = "male"
    # What the log is for. Changes which findings the analytics report and the
    # thresholds they use - see hevy_coach/goals.py.
    training_goal: Goal = "hypertrophy"
    bodyweight_kg: BodyweightKg = 80.0
    # How you type the load for a two-dumbbell movement. The standards are
    # published per dumbbell, which is also what Hevy asks for; set this to
    # "combined" if you enter the pair's total instead.
    dumbbell_load: DumbbellLoad = "per_dumbbell"
    birth_date: date | None = None
    units: Units = "kg"

    # --- Server -------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def unset_profile_fields(self) -> tuple[str, ...]:
        """Profile fields nothing supplied, so a class default is standing in.

        This is what lets the app tell "the lifter weighs 80 kg" apart from
        "nobody has said what the lifter weighs", which are the same value and
        very different claims.
        """
        return tuple(name for name in PROFILE_FIELDS if name not in self.model_fields_set)

    @property
    def bodyweight_is_default(self) -> bool:
        """True when nothing supplied a bodyweight and the class default stands.

        Every strength standard is indexed on bodyweight, so a defaulted number
        silently rescales the whole benchmark - at 80 kg a 60 kg bench is
        "beginner", at 55 kg it is "novice" most of the way to intermediate.
        Callers use this to say the figure is a placeholder rather than present
        it as the lifter's.
        """
        return "bodyweight_kg" in self.unset_profile_fields

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
