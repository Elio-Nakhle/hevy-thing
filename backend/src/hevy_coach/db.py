"""SQLite storage.

Two representations are kept side by side:

* ``workouts`` holds the raw API payload, so a schema change here never means
  re-downloading your training history.
* ``sets`` is a flattened row-per-set table. Every analytic in this project is an
  aggregate over sets, so this is the shape that actually gets queried.

The schema is small enough that a version counter plus full rebuild of ``sets``
from ``workouts`` beats a migration framework.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevy_coach.hevy.models import HevyWorkout

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS workouts (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    start_time   TEXT NOT NULL,
    end_time     TEXT,
    updated_at   TEXT,
    routine_id   TEXT,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workouts_start ON workouts(start_time);

CREATE TABLE IF NOT EXISTS sets (
    workout_id       TEXT NOT NULL,
    exercise_index   INTEGER NOT NULL,
    set_index        INTEGER NOT NULL,
    start_time       TEXT NOT NULL,
    template_id      TEXT NOT NULL,
    exercise_title   TEXT NOT NULL,
    set_type         TEXT NOT NULL,
    weight_kg        REAL,
    reps             INTEGER,
    distance_meters  REAL,
    duration_seconds REAL,
    rpe              REAL,
    PRIMARY KEY (workout_id, exercise_index, set_index),
    FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sets_template ON sets(template_id, start_time);
CREATE INDEX IF NOT EXISTS idx_sets_start ON sets(start_time);

CREATE TABLE IF NOT EXISTS exercise_templates (
    id                      TEXT PRIMARY KEY,
    title                   TEXT NOT NULL,
    type                    TEXT,
    primary_muscle_group    TEXT,
    secondary_muscle_groups TEXT,
    equipment_category      TEXT,
    is_custom               INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS body_measurements (
    date         TEXT PRIMARY KEY,
    weight_kg    REAL,
    lean_mass_kg REAL,
    fat_percent  REAL
);

-- Routines the lifter has put away. Trying a routine once is not a decision to
-- keep it in the rotation, and a log accumulates titles faster than it
-- accumulates programmes, so "which of these am I actually doing" needs an
-- answer the lifter can give directly rather than one only inferred from dates.
CREATE TABLE IF NOT EXISTS dismissed_routines (
    title        TEXT PRIMARY KEY,
    dismissed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # -- connections -------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            yield cur
            cur.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        conn = self.connect()
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        finally:
            conn.close()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def _init_schema(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
        finally:
            conn.close()

    # -- meta --------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.query_one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # -- writes ------------------------------------------------------------

    def upsert_workouts(self, workouts: Iterable[HevyWorkout]) -> int:
        """Insert or replace workouts and rebuild their flattened sets."""
        count = 0
        with self.cursor() as cur:
            for workout in workouts:
                cur.execute(
                    """
                    INSERT INTO workouts(id, title, start_time, end_time, updated_at,
                                         routine_id, payload)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, start_time=excluded.start_time,
                        end_time=excluded.end_time, updated_at=excluded.updated_at,
                        routine_id=excluded.routine_id, payload=excluded.payload
                    """,
                    (
                        workout.id,
                        workout.title,
                        workout.start_time.isoformat(),
                        workout.end_time.isoformat() if workout.end_time else None,
                        workout.updated_at.isoformat() if workout.updated_at else None,
                        workout.routine_id,
                        workout.model_dump_json(),
                    ),
                )
                cur.execute("DELETE FROM sets WHERE workout_id = ?", (workout.id,))
                cur.executemany(
                    """
                    INSERT INTO sets(workout_id, exercise_index, set_index, start_time,
                                     template_id, exercise_title, set_type, weight_kg,
                                     reps, distance_meters, duration_seconds, rpe)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    list(_flatten_sets(workout)),
                )
                count += 1
        return count

    def delete_workout(self, workout_id: str) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM sets WHERE workout_id = ?", (workout_id,))
            cur.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))

    def upsert_templates(self, templates: Iterable[Any]) -> int:
        count = 0
        with self.cursor() as cur:
            for tpl in templates:
                cur.execute(
                    """
                    INSERT INTO exercise_templates(id, title, type, primary_muscle_group,
                                                   secondary_muscle_groups,
                                                   equipment_category, is_custom)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, type=excluded.type,
                        primary_muscle_group=excluded.primary_muscle_group,
                        secondary_muscle_groups=excluded.secondary_muscle_groups,
                        equipment_category=excluded.equipment_category,
                        is_custom=excluded.is_custom
                    """,
                    (
                        tpl.id,
                        tpl.title,
                        tpl.type,
                        tpl.primary_muscle_group,
                        json.dumps(tpl.secondary_muscle_groups),
                        tpl.equipment_category,
                        int(tpl.is_custom),
                    ),
                )
                count += 1
        return count

    def set_routine_dismissed(self, title: str, dismissed: bool) -> None:
        """Put a routine away, or bring it back.

        Sticky either way: nothing un-dismisses a routine because it was trained
        again. Coming back on its own would be the surprising behaviour - the
        lifter said to put it away, and a log has plenty of reasons to contain
        one more session of something they are finished with.
        """
        with self.cursor() as cur:
            if dismissed:
                cur.execute(
                    "INSERT INTO dismissed_routines(title, dismissed_at) VALUES(?, ?) "
                    "ON CONFLICT(title) DO UPDATE SET dismissed_at=excluded.dismissed_at",
                    (title, datetime.now(UTC).isoformat()),
                )
            else:
                cur.execute("DELETE FROM dismissed_routines WHERE title = ?", (title,))

    def dismissed_routines(self) -> set[str]:
        """Titles the lifter has put away. Empty for a log nobody has curated."""
        return {row["title"] for row in self.query("SELECT title FROM dismissed_routines")}

    def upsert_body_measurements(self, measurements: Iterable[Any]) -> int:
        count = 0
        with self.cursor() as cur:
            for m in measurements:
                cur.execute(
                    """
                    INSERT INTO body_measurements(date, weight_kg, lean_mass_kg, fat_percent)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        weight_kg=excluded.weight_kg,
                        lean_mass_kg=excluded.lean_mass_kg,
                        fat_percent=excluded.fat_percent
                    """,
                    (m.date, m.weight_kg, m.lean_mass_kg, m.fat_percent),
                )
                count += 1
        return count

    # -- reads -------------------------------------------------------------

    def workout_count(self) -> int:
        row = self.query_one("SELECT COUNT(*) AS n FROM workouts")
        return int(row["n"]) if row else 0

    def latest_workout_time(self) -> str | None:
        row = self.query_one("SELECT MAX(start_time) AS t FROM workouts")
        return row["t"] if row and row["t"] else None

    def latest_bodyweight(self) -> float | None:
        row = self.query_one(
            "SELECT weight_kg FROM body_measurements "
            "WHERE weight_kg IS NOT NULL ORDER BY date DESC LIMIT 1"
        )
        return float(row["weight_kg"]) if row else None


def _flatten_sets(workout: HevyWorkout) -> Iterator[tuple[Any, ...]]:
    """Expand a workout into one row per set.

    Positions come from list order rather than the API's ``index`` fields: those
    are display hints and repeat across supersets, which would collide with the
    (workout, exercise, set) primary key.
    """
    start = workout.start_time.isoformat()
    for exercise_pos, exercise in enumerate(workout.exercises):
        for set_pos, set_ in enumerate(exercise.sets):
            yield (
                workout.id,
                exercise_pos,
                set_pos,
                start,
                exercise.exercise_template_id,
                exercise.title,
                set_.type,
                set_.weight_kg,
                set_.reps,
                set_.distance_meters,
                set_.duration_seconds,
                set_.rpe,
            )
