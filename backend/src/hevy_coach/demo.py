"""Synthetic training history.

Two uses: it backs the test suite, and it lets the frontend be developed against
a populated database without a CSV export to hand. The generated log is shaped like
a real one - three sessions a week, linear progression with noise, a deload every
sixth week, and one accessory lift that goes nowhere so the stall detection has
something to find.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from hevy_coach.db import Database
from hevy_coach.hevy.models import ExerciseTemplate, HevyExercise, HevySet, HevyWorkout

# (template_id, title, primary muscle, starting top-set kg, weekly gain kg, deloads)
PROGRAM = [
    ("T_BENCH", "Bench Press (Barbell)", "chest", 70.0, 0.55, True),
    ("T_SQUAT", "Squat (Barbell)", "quadriceps", 90.0, 0.8, True),
    ("T_DEADL", "Deadlift (Barbell)", "hamstrings", 110.0, 0.9, True),
    ("T_OHP", "Shoulder Press (Barbell)", "shoulders", 45.0, 0.25, True),
    ("T_ROW", "Bent Over Row (Barbell)", "upper_back", 60.0, 0.4, True),
    # Deliberately flat and undeloaded, so there is a genuinely stalled lift.
    ("T_CURL", "Bicep Curl (Barbell)", "biceps", 30.0, 0.0, False),
]

SECONDARIES = {
    "T_BENCH": ["triceps", "shoulders"],
    "T_SQUAT": ["glutes", "lower_back"],
    "T_DEADL": ["lower_back", "traps"],
    "T_OHP": ["triceps"],
    "T_ROW": ["biceps", "lats"],
    "T_CURL": ["forearms"],
}

# Each session pairs one main lift with one accessory.
SESSIONS = ([0, 4], [1, 3], [2, 5])


def build_history(weeks: int = 20, seed: int = 7) -> list[HevyWorkout]:
    rng = random.Random(seed)
    start = datetime.now(UTC) - timedelta(weeks=weeks)
    workouts: list[HevyWorkout] = []

    for week in range(weeks):
        for day, session in enumerate(SESSIONS):
            when = start + timedelta(weeks=week, days=day * 2, hours=18)
            exercises = []
            for order, index in enumerate(session):
                template_id, title, _, base, gain, deloads = PROGRAM[index]
                deload = 0.88 if (deloads and week % 6 == 5) else 1.0
                top = (base + gain * week) * deload + rng.uniform(-1.5, 1.5)
                top = round(top / 2.5) * 2.5

                sets = [HevySet(index=0, type="warmup", weight_kg=round(top * 0.5), reps=8)]
                for s in range(3):
                    sets.append(
                        HevySet(
                            index=s + 1,
                            type="normal",
                            weight_kg=max(20.0, top - 2.5 * s),
                            reps=rng.choice([5, 5, 6, 8]),
                            rpe=rng.choice([7.0, 8.0, 8.5, 9.0]),
                        )
                    )
                exercises.append(
                    HevyExercise(
                        index=order,
                        title=title,
                        exercise_template_id=template_id,
                        sets=sets,
                    )
                )

            workouts.append(
                HevyWorkout(
                    id=f"w{week:02d}-{day}",
                    title=f"Session {day + 1}",
                    start_time=when,
                    end_time=when + timedelta(minutes=rng.randint(55, 80)),
                    updated_at=when,
                    exercises=exercises,
                )
            )
    return workouts


def build_templates() -> list[ExerciseTemplate]:
    return [
        ExerciseTemplate(
            id=template_id,
            title=title,
            type="weight_reps",
            primary_muscle_group=primary,
            secondary_muscle_groups=SECONDARIES[template_id],
            equipment_category="barbell",
        )
        for template_id, title, primary, *_ in PROGRAM
    ]


def seed(db: Database, *, weeks: int = 20, seed_value: int = 7) -> int:
    """Populate a database with synthetic history. Returns the workout count."""
    count = db.upsert_workouts(build_history(weeks=weeks, seed=seed_value))
    db.upsert_templates(build_templates())
    return count
