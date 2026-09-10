"""Tests for the dashboard's one-sentence answer.

The sentence is the product here, so these assert on wording more than usual:
the whole point of H0.3 is that a lifter can read it without help, and a mean
that contradicts the counts beside it would be worse than no headline at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hevy_coach.analytics import headline as headline_module
from hevy_coach.analytics.headline import headline
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.hevy.models import ExerciseTemplate, HevyExercise, HevySet, HevyWorkout


def _log(db: Database, lifts: dict[str, list[float]], *, title: str = "Push") -> None:
    """One workout per week; each lift's list is its top-set weight per week."""
    weeks = max(len(loads) for loads in lifts.values())
    db.upsert_templates(
        [
            ExerciseTemplate(id=name, title=name, equipment_category="barbell")
            for name in lifts
        ]
    )
    workouts = []
    for week in range(weeks):
        start = datetime.now(UTC) - timedelta(days=(weeks - week) * 7)
        workouts.append(
            HevyWorkout(
                id=f"w{week}",
                title=title,
                start_time=start,
                end_time=start + timedelta(minutes=50),
                exercises=[
                    HevyExercise(
                        index=index,
                        title=name,
                        exercise_template_id=name,
                        sets=[
                            HevySet(index=s, type="normal", weight_kg=loads[week], reps=5)
                            for s in range(3)
                        ],
                    )
                    for index, (name, loads) in enumerate(lifts.items())
                    if week < len(loads)
                ],
            )
        )
    db.upsert_workouts(workouts)


def _settings(tmp_path: object) -> Settings:
    return Settings(_env_file=None, database_path=tmp_path / "h.db", bodyweight_kg=80.0)  # type: ignore[operator]


RISING = [100.0, 102.5, 105.0, 107.5, 110.0, 112.5, 115.0, 117.5]
FALLING = list(reversed(RISING))
FLAT = [100.0] * 8


# -- the verdict ------------------------------------------------------------


def test_a_rising_log_answers_yes(tmp_path) -> None:
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": RISING, "Bench": RISING})

    result = headline(db, _settings(tmp_path))

    assert result.verdict == "progressing"
    assert result.answer.startswith("Yes. Your typical lift is up")
    assert "2 of 2 climbing" in result.answer
    assert result.lifts_up == 2
    assert result.lifts_down == 0


def test_a_falling_log_says_not_right_now(tmp_path) -> None:
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": FALLING, "Bench": FALLING})

    result = headline(db, _settings(tmp_path))

    assert result.verdict == "slipping"
    assert result.answer.startswith("Not right now.")
    assert "2 of 2 sliding" in result.answer
    assert result.median_change_pct_per_month is not None
    assert result.median_change_pct_per_month < 0


def test_a_flat_log_says_holding(tmp_path) -> None:
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": FLAT, "Bench": FLAT})

    result = headline(db, _settings(tmp_path))

    assert result.verdict == "holding"
    assert result.answer.startswith("Holding.")
    assert "none of 2 clearly either way" in result.answer


def test_a_mixed_log_reports_both_directions(tmp_path) -> None:
    """A mean of zero across one climbing and one sliding lift is true and
    useless on its own, so the sentence has to carry the spread."""
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": RISING, "Bench": FALLING})

    result = headline(db, _settings(tmp_path))

    assert result.lifts_up == 1
    assert result.lifts_down == 1
    assert "1 of 2 climbing, 1 sliding" in result.answer


def test_the_verdict_uses_the_same_thresholds_as_a_single_lift(tmp_path) -> None:
    """"Your lifts are progressing" must not be able to disagree with
    "this lift is progressing"."""
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": RISING, "Bench": RISING})

    result = headline(db, _settings(tmp_path))

    assert result.median_change_pct_per_month is not None
    assert result.median_change_pct_per_month >= headline_module.progression.PROGRESS_THRESHOLD


def test_one_runaway_lift_does_not_carry_the_headline(tmp_path) -> None:
    """An accessory taken from 12 kg to 73 kg reads as +80% a month. True, and
    not news about the lifter - a mean would let it speak for everything."""
    db = Database(tmp_path / "h.db")
    _log(
        db,
        {
            "Curl": [12.0, 22.0, 34.0, 46.0, 58.0, 66.0, 70.0, 73.0],
            "Squat": FLAT,
            "Bench": FLAT,
        },
    )

    result = headline(db, _settings(tmp_path))

    middle = result.median_change_pct_per_month
    assert middle is not None
    # The two flat lifts are the middle of three, so they decide the verdict.
    assert middle < 1.0
    assert result.verdict == "holding"
    assert result.lifts_up == 1


# -- when there is no answer ------------------------------------------------


def test_an_empty_log_asks_for_an_import(tmp_path) -> None:
    db = Database(tmp_path / "h.db")

    result = headline(db, _settings(tmp_path))

    assert result.verdict == "insufficient_data"
    assert "Nothing imported yet" in result.answer
    assert result.next_up is None
    assert result.median_change_pct_per_month is None


def test_too_little_history_says_what_is_missing(tmp_path) -> None:
    """Not "no data" - the number of sessions a trend needs."""
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": [100.0, 102.5]})

    result = headline(db, _settings(tmp_path))

    assert result.verdict == "insufficient_data"
    assert "4 sessions" in result.answer
    assert "12 weeks" in result.answer
    assert result.lifts_tracked == 0


def test_the_window_is_reported_so_the_ui_can_name_it(tmp_path) -> None:
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": RISING})

    assert headline(db, _settings(tmp_path)).window_days == 90
    assert headline(db, _settings(tmp_path), days=180).window_days == 180


# -- what changes next session ----------------------------------------------


def test_the_headline_carries_the_next_session(tmp_path) -> None:
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": RISING, "Bench": RISING})

    result = headline(db, _settings(tmp_path))

    assert result.next_up is not None
    assert result.next_up.title == "Push"
    assert result.next_up.exercises == 2
    assert result.next_up.summary.startswith("Push is up next -")


def test_the_next_session_is_the_overdue_routine(tmp_path) -> None:
    db = Database(tmp_path / "h.db")
    _log(db, {"Squat": RISING}, title="Legs")
    # A newer routine, so Legs is the one waiting.
    start = datetime.now(UTC) - timedelta(days=1)
    db.upsert_templates([ExerciseTemplate(id="Bench", title="Bench", equipment_category="barbell")])
    db.upsert_workouts(
        [
            HevyWorkout(
                id="upper",
                title="Upper",
                start_time=start,
                end_time=start + timedelta(minutes=40),
                exercises=[
                    HevyExercise(
                        index=0,
                        title="Bench",
                        exercise_template_id="Bench",
                        sets=[HevySet(index=0, type="normal", weight_kg=80.0, reps=5)],
                    )
                ],
            )
        ]
    )

    result = headline(db, _settings(tmp_path))

    assert result.next_up is not None
    assert result.next_up.title == "Legs"
