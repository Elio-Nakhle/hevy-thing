"""Shared fixtures and the Hevy CSV export builders.

The synthetic training log lives in ``hevy_coach.demo`` because it serves double
duty: it backs these tests and it seeds a database for frontend development.

The export builders below are here rather than in one test module because both
the importer tests and the API tests need to construct exports, and the column
list is the kind of thing that has to change in one place when it changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.demo import build_history, build_templates


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # ``_env_file=None`` keeps the developer's own .env out of the fixture. It
    # would otherwise supply a real bodyweight and dumbbell convention, and the
    # tests would pass or fail depending on whose machine they ran on.
    return Settings(
        _env_file=None,
        database_path=tmp_path / "test.db",
        sex="male",
        bodyweight_kg=80.0,
        workouts_dir=tmp_path / "workouts",
    )


@pytest.fixture
def db(settings: Settings) -> Database:
    database = Database(settings.database_path)
    database.upsert_workouts(build_history())
    database.upsert_templates(build_templates())
    return database


@pytest.fixture
def empty_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "empty.db")


# -- building a Hevy CSV export ----------------------------------------------

#: The column list Hevy writes, in order.
HEADER = (
    '"title","start_time","end_time","description","exercise_title","superset_id",'
    '"exercise_notes","set_index","set_type","weight_kg","reps","distance_km",'
    '"duration_seconds","rpe"'
)


def export_row(
    *,
    title: str = "Full A",
    start: str = "Sep 1, 2026, 6:55 PM",
    end: str = "Sep 1, 2026, 7:54 PM",
    exercise: str = "Squat (Barbell)",
    set_index: int = 0,
    set_type: str = "normal",
    weight: str = "100",
    reps: str = "5",
    distance_km: str = "",
    duration: str = "",
    rpe: str = "",
) -> str:
    """One CSV row: a single set of a single exercise in a single workout."""
    return (
        f'"{title}","{start}","{end}","","{exercise}",,"",{set_index},"{set_type}",'
        f"{weight},{reps},{distance_km},{duration},{rpe}"
    )


def export_text(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def write_export(path: Path, *rows: str) -> Path:
    path.write_text(export_text(*rows))
    return path


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    """An empty workouts folder to drop exports into."""
    directory = tmp_path / "workouts"
    directory.mkdir()
    return directory
