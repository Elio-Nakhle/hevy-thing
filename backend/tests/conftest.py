"""Shared fixtures.

The synthetic training log lives in ``hevy_coach.demo`` because it serves double
duty: it backs these tests and it seeds a database for frontend development.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.demo import build_history, build_templates


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
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
