"""Training metrics computed over the flattened ``sets`` table."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hevy_coach.analytics import e1rm
from hevy_coach.db import Database

# Warm-ups inflate set counts and tonnage without driving adaptation.
WORKING_SETS = "set_type != 'warmup'"


def _cutoff(days: int | None) -> str:
    if days is None:
        return "0000-01-01"
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


@dataclass
class Overview:
    workouts: int
    first_workout: str | None
    last_workout: str | None
    total_sets: int
    total_reps: int
    total_volume_kg: float
    avg_workouts_per_week: float
    avg_duration_minutes: float | None
    distinct_exercises: int
    bodyweight_kg: float | None


def overview(db: Database, *, days: int | None = None) -> Overview:
    since = _cutoff(days)
    row = db.query_one(
        """
        SELECT COUNT(DISTINCT w.id) AS workouts,
               MIN(w.start_time)    AS first_workout,
               MAX(w.start_time)    AS last_workout,
               AVG(CASE WHEN w.end_time IS NOT NULL
                        THEN (julianday(w.end_time) - julianday(w.start_time)) * 1440 END)
                                    AS avg_minutes
        FROM workouts w
        WHERE w.start_time >= ?
        """,
        (since,),
    )
    set_row = db.query_one(
        f"""
        SELECT COUNT(*)                                    AS total_sets,
               COALESCE(SUM(reps), 0)                      AS total_reps,
               COALESCE(SUM(COALESCE(weight_kg, 0) * COALESCE(reps, 0)), 0) AS volume,
               COUNT(DISTINCT template_id)                 AS exercises
        FROM sets
        WHERE start_time >= ? AND {WORKING_SETS}
        """,
        (since,),
    )

    workouts = int(row["workouts"]) if row else 0
    weeks = 1.0
    if row and row["first_workout"] and row["last_workout"]:
        first = datetime.fromisoformat(row["first_workout"])
        last = datetime.fromisoformat(row["last_workout"])
        weeks = max((last - first).days / 7.0, 1.0)

    return Overview(
        workouts=workouts,
        first_workout=row["first_workout"] if row else None,
        last_workout=row["last_workout"] if row else None,
        total_sets=int(set_row["total_sets"]) if set_row else 0,
        total_reps=int(set_row["total_reps"]) if set_row else 0,
        total_volume_kg=round(float(set_row["volume"]), 1) if set_row else 0.0,
        avg_workouts_per_week=round(workouts / weeks, 2),
        avg_duration_minutes=(
            round(float(row["avg_minutes"]), 1) if row and row["avg_minutes"] else None
        ),
        distinct_exercises=int(set_row["exercises"]) if set_row else 0,
        bodyweight_kg=db.latest_bodyweight(),
    )


def weekly_volume(db: Database, *, weeks: int = 52) -> list[dict[str, Any]]:
    """Tonnage, working sets and session count per ISO week."""
    since = _cutoff(weeks * 7)
    rows = db.query(
        f"""
        SELECT strftime('%Y-%W', start_time)                AS week,
               MIN(date(start_time))                        AS week_start,
               COUNT(*)                                     AS sets,
               COALESCE(SUM(COALESCE(weight_kg,0) * COALESCE(reps,0)), 0) AS volume,
               COALESCE(SUM(reps), 0)                       AS reps,
               COUNT(DISTINCT workout_id)                   AS workouts
        FROM sets
        WHERE start_time >= ? AND {WORKING_SETS}
        GROUP BY week
        ORDER BY week
        """,
        (since,),
    )
    return [
        {
            "week": r["week"],
            "week_start": r["week_start"],
            "sets": int(r["sets"]),
            "reps": int(r["reps"]),
            "volume_kg": round(float(r["volume"]), 1),
            "workouts": int(r["workouts"]),
        }
        for r in rows
    ]


def muscle_group_volume(db: Database, *, days: int = 28) -> list[dict[str, Any]]:
    """Working sets per muscle group, the unit most hypertrophy guidance uses.

    Secondary muscles are counted at half a set, which is the common convention
    for indirect work.
    """
    since = _cutoff(days)
    rows = db.query(
        f"""
        SELECT t.primary_muscle_group    AS primary_group,
               t.secondary_muscle_groups AS secondary_groups,
               COUNT(*)                  AS sets,
               COALESCE(SUM(COALESCE(s.weight_kg,0) * COALESCE(s.reps,0)), 0) AS volume
        FROM sets s
        JOIN exercise_templates t ON t.id = s.template_id
        WHERE s.start_time >= ? AND {WORKING_SETS.replace('set_type', 's.set_type')}
        GROUP BY t.primary_muscle_group, t.secondary_muscle_groups
        """,
        (since,),
    )

    totals: dict[str, dict[str, float]] = {}
    for row in rows:
        primary = row["primary_group"] or "other"
        entry = totals.setdefault(primary, {"sets": 0.0, "volume_kg": 0.0})
        entry["sets"] += float(row["sets"])
        entry["volume_kg"] += float(row["volume"])

        try:
            secondaries = json.loads(row["secondary_groups"] or "[]")
        except (TypeError, ValueError):
            secondaries = []
        for muscle in secondaries:
            entry = totals.setdefault(muscle, {"sets": 0.0, "volume_kg": 0.0})
            entry["sets"] += float(row["sets"]) * 0.5
            entry["volume_kg"] += float(row["volume"]) * 0.5

    weeks = max(days / 7.0, 1.0)
    return sorted(
        (
            {
                "muscle_group": muscle,
                "sets": round(values["sets"], 1),
                "sets_per_week": round(values["sets"] / weeks, 1),
                "volume_kg": round(values["volume_kg"], 1),
            }
            for muscle, values in totals.items()
        ),
        key=lambda item: item["sets_per_week"],
        reverse=True,
    )


@dataclass
class ExerciseSummary:
    template_id: str
    title: str
    sessions: int
    sets: int
    last_performed: str | None
    best_e1rm_kg: float | None
    best_weight_kg: float | None
    total_volume_kg: float


def exercise_summaries(db: Database, *, days: int | None = None) -> list[ExerciseSummary]:
    since = _cutoff(days)
    rows = db.query(
        f"""
        SELECT template_id,
               exercise_title,
               COUNT(DISTINCT workout_id) AS sessions,
               COUNT(*)                   AS sets,
               MAX(start_time)            AS last_performed,
               MAX(weight_kg)             AS best_weight,
               COALESCE(SUM(COALESCE(weight_kg,0) * COALESCE(reps,0)), 0) AS volume
        FROM sets
        WHERE start_time >= ? AND {WORKING_SETS}
        GROUP BY template_id, exercise_title
        ORDER BY sets DESC
        """,
        (since,),
    )

    summaries = []
    for row in rows:
        best = db.query_one(
            f"""
            SELECT weight_kg, reps, rpe FROM sets
            WHERE template_id = ? AND start_time >= ? AND {WORKING_SETS}
              AND weight_kg IS NOT NULL AND reps IS NOT NULL AND reps <= ?
            ORDER BY weight_kg * (1 + reps / 30.0) DESC LIMIT 1
            """,
            (row["template_id"], since, e1rm.MAX_TRUSTED_REPS),
        )
        best_e1rm = (
            e1rm.estimate(best["weight_kg"], best["reps"], best["rpe"]) if best else None
        )
        summaries.append(
            ExerciseSummary(
                template_id=row["template_id"],
                title=row["exercise_title"],
                sessions=int(row["sessions"]),
                sets=int(row["sets"]),
                last_performed=row["last_performed"],
                best_e1rm_kg=round(best_e1rm, 1) if best_e1rm else None,
                best_weight_kg=(
                    round(float(row["best_weight"]), 1) if row["best_weight"] is not None else None
                ),
                total_volume_kg=round(float(row["volume"]), 1),
            )
        )
    return summaries


def exercise_sets(
    db: Database, template_id: str, *, days: int | None = None
) -> list[tuple[float | None, int | None, float | None]]:
    """Every working set for one exercise as ``(weight, reps, rpe)``.

    Unlike :func:`exercise_summaries`, sets with no logged weight are kept: for
    a bodyweight movement that is a real data point, and the caller decides how
    to score it.
    """
    since = _cutoff(days)
    rows = db.query(
        f"""
        SELECT weight_kg, reps, rpe FROM sets
        WHERE template_id = ? AND start_time >= ? AND {WORKING_SETS}
              AND reps IS NOT NULL
        """,
        (template_id, since),
    )
    return [(row["weight_kg"], row["reps"], row["rpe"]) for row in rows]


@dataclass
class SessionPoint:
    date: str
    workout_id: str
    best_e1rm_kg: float | None
    best_weight_kg: float | None
    top_set_reps: int | None
    sets: int
    volume_kg: float


def exercise_history(
    db: Database, template_id: str, *, days: int | None = None
) -> list[SessionPoint]:
    """Per-session best set for one exercise - the series the charts plot."""
    since = _cutoff(days)
    rows = db.query(
        f"""
        SELECT workout_id, start_time, weight_kg, reps, rpe
        FROM sets
        WHERE template_id = ? AND start_time >= ? AND {WORKING_SETS}
        ORDER BY start_time
        """,
        (template_id, since),
    )

    sessions: dict[str, dict[str, Any]] = {}
    for row in rows:
        session = sessions.setdefault(
            row["workout_id"],
            {
                "date": row["start_time"],
                "sets": 0,
                "volume": 0.0,
                "best_e1rm": None,
                "best_weight": None,
                "top_reps": None,
            },
        )
        session["sets"] += 1
        session["volume"] += float(row["weight_kg"] or 0) * float(row["reps"] or 0)

        estimate = e1rm.estimate(row["weight_kg"], row["reps"], row["rpe"])
        if estimate is not None and (
            session["best_e1rm"] is None or estimate > session["best_e1rm"]
        ):
            session["best_e1rm"] = estimate
            session["best_weight"] = row["weight_kg"]
            session["top_reps"] = row["reps"]

    return [
        SessionPoint(
            date=data["date"],
            workout_id=workout_id,
            best_e1rm_kg=round(data["best_e1rm"], 1) if data["best_e1rm"] else None,
            best_weight_kg=data["best_weight"],
            top_set_reps=data["top_reps"],
            sets=data["sets"],
            volume_kg=round(data["volume"], 1),
        )
        for workout_id, data in sorted(sessions.items(), key=lambda kv: kv[1]["date"])
    ]


@dataclass
class PersonalRecord:
    template_id: str
    title: str
    date: str
    weight_kg: float
    reps: int
    e1rm_kg: float
    is_current_best: bool = False


def personal_records(
    db: Database, *, days: int | None = None, limit: int = 25
) -> list[PersonalRecord]:
    """Sessions where an exercise's e1RM exceeded everything before it."""
    since = _cutoff(days)
    rows = db.query(
        f"""
        SELECT template_id, exercise_title, start_time, weight_kg, reps, rpe
        FROM sets
        WHERE {WORKING_SETS} AND weight_kg IS NOT NULL AND reps IS NOT NULL
        ORDER BY start_time
        """
    )

    running_best: dict[str, float] = {}
    records: list[PersonalRecord] = []
    for row in rows:
        estimate = e1rm.estimate(row["weight_kg"], row["reps"], row["rpe"])
        if estimate is None:
            continue
        template_id = row["template_id"]
        if estimate > running_best.get(template_id, 0.0) + 1e-9:
            running_best[template_id] = estimate
            records.append(
                PersonalRecord(
                    template_id=template_id,
                    title=row["exercise_title"],
                    date=row["start_time"],
                    weight_kg=float(row["weight_kg"]),
                    reps=int(row["reps"]),
                    e1rm_kg=round(estimate, 1),
                )
            )

    for record in records:
        best = round(running_best[record.template_id], 1)
        record.is_current_best = abs(record.e1rm_kg - best) < 1e-9

    recent = [r for r in records if r.date >= since]
    recent.sort(key=lambda r: r.date, reverse=True)
    return recent[:limit]


def to_dicts(items: list[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]
