"""Tests for per-session analysis and the next-session prescription."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hevy_coach.analytics import session
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.hevy.models import ExerciseTemplate, HevyExercise, HevySet, HevyWorkout

TEMPLATE = "T_BENCH"
OTHER = "T_SQUAT"


def _workout(
    index: int,
    sets: list[tuple[float | None, int]],
    *,
    title: str = "Push",
    days_ago: int = 0,
    template: str = TEMPLATE,
) -> HevyWorkout:
    start = datetime.now(UTC) - timedelta(days=days_ago)
    return HevyWorkout(
        id=f"w{index}",
        title=title,
        start_time=start,
        end_time=start + timedelta(minutes=50),
        exercises=[
            HevyExercise(
                index=0,
                title="Bench Press (Barbell)" if template == TEMPLATE else "Squat (Barbell)",
                exercise_template_id=template,
                sets=[
                    HevySet(index=i, type="normal", weight_kg=w, reps=r)
                    for i, (w, r) in enumerate(sets)
                ],
            )
        ],
    )


def _sessions(db: Database) -> list[session.ExerciseSession]:
    return session.exercise_sessions(db, TEMPLATE)


@pytest.fixture
def log(tmp_path) -> Database:
    return Database(tmp_path / "session.db")


class TestRepBand:
    def test_reads_the_scheme_from_every_set_not_the_heaviest(self) -> None:
        # A ramp finishing on a heavy triple is still a session of fives.
        assert session.rep_band([5, 5, 3, 10]) == (4, 6)

    def test_a_genuine_singles_session_lands_in_the_low_band(self) -> None:
        assert session.rep_band([3, 2, 1]) == (1, 3)

    def test_high_rep_work_stays_high_rep(self) -> None:
        assert session.rep_band([20, 20, 20]) == (15, 20)
        # Past the top band, the top band is still the answer.
        assert session.rep_band([30, 30]) == (15, 20)

    def test_no_reps_falls_back_to_a_middle_band(self) -> None:
        assert session.rep_band([]) == (6, 10)


class TestLoadStep:
    def test_reads_the_increment_off_the_lifters_own_history(self) -> None:
        # A stack that moves in sevens should be progressed in sevens, not 2.5s.
        assert session.load_step([40, 45, 50, 55], "barbell") == 5.0
        assert session.load_step([12, 16, 20, 24], None) == 4.0

    def test_falls_back_to_equipment_when_there_is_no_history(self) -> None:
        assert session.load_step([], "dumbbell") == 2.0
        assert session.load_step([60], "barbell") == 2.5
        assert session.load_step([], None) == session.DEFAULT_STEP

    def test_odd_increments_snap_to_a_loadable_step(self) -> None:
        assert session.load_step([50, 52.3, 54.4], "machine") in session.LOAD_STEPS


class TestProgression:
    def test_one_session_only_establishes_a_baseline(self, log: Database) -> None:
        log.upsert_workouts([_workout(0, [(60, 5), (60, 5)], days_ago=7)])
        rec = session.recommend(_sessions(log))
        assert rec.action == "establish"
        assert rec.target_weight_kg == 60

    def test_top_of_the_range_on_every_set_earns_load(self, log: Database) -> None:
        log.upsert_workouts(
            [
                _workout(0, [(60, 6), (60, 6)], days_ago=14),
                _workout(1, [(60, 6), (60, 6)], days_ago=7),
            ]
        )
        rec = session.recommend(_sessions(log), equipment="barbell")
        assert rec.action == "add_load"
        assert rec.rep_range == (4, 6)
        # Load goes up, reps reset to the bottom of the range.
        assert rec.target_weight_kg == 62.5
        assert rec.target_reps == 4

    def test_a_short_set_keeps_the_load_and_adds_reps(self, log: Database) -> None:
        log.upsert_workouts(
            [
                _workout(0, [(60, 4), (60, 4)], days_ago=14),
                _workout(1, [(60, 5), (60, 4)], days_ago=7),
            ]
        )
        rec = session.recommend(_sessions(log), equipment="barbell")
        assert rec.action == "add_reps"
        assert rec.target_weight_kg == 60
        assert rec.target_reps == 5

    def test_a_stall_at_a_fixed_load_deloads_instead_of_pushing(self, log: Database) -> None:
        # Same load, same reps, no new best - the case where "add weight" is wrong.
        log.upsert_workouts(
            [
                _workout(i, [(100, 5), (100, 5)], days_ago=28 - i * 7)
                for i in range(4)
            ]
        )
        rec = session.recommend(_sessions(log), equipment="barbell")
        assert rec.action == "deload"
        assert rec.target_weight_kg == pytest.approx(90.0)
        assert "stall" in rec.detail.lower() or "fatigue" in rec.detail.lower()

    def test_a_down_session_holds_rather_than_progressing(self, log: Database) -> None:
        log.upsert_workouts(
            [
                _workout(0, [(100, 5)], days_ago=21),
                _workout(1, [(105, 5)], days_ago=14),
                _workout(2, [(80, 5)], days_ago=7),
            ]
        )
        rec = session.recommend(_sessions(log), equipment="barbell")
        assert rec.action == "hold"
        assert rec.target_weight_kg == 80

    def test_bodyweight_work_progresses_on_reps_then_added_load(self, log: Database) -> None:
        log.upsert_workouts(
            [
                _workout(0, [(None, 10), (None, 10)], days_ago=14),
                _workout(1, [(None, 10), (None, 10)], days_ago=7),
            ]
        )
        rec = session.recommend(_sessions(log), equipment="weighted")
        assert rec.action == "add_load"
        assert rec.target_weight_kg == 2.5

    def test_cardio_gets_no_prescription(self, log: Database) -> None:
        log.upsert_workouts([_workout(0, [], days_ago=7)])
        assert session.recommend(_sessions(log)).action == "no_basis"

    def test_ramp_up_sets_are_excluded_from_the_prescription(self, log: Database) -> None:
        # 60 and 80 are a ramp; only the two sets at 100 are the working sets.
        log.upsert_workouts(
            [
                _workout(0, [(60, 5), (80, 5), (100, 5), (100, 5)], days_ago=14),
                _workout(1, [(60, 5), (80, 5), (100, 6), (100, 6)], days_ago=7),
            ]
        )
        rec = session.recommend(_sessions(log), equipment="barbell")
        assert rec.target_sets == 2
        assert rec.action == "add_load"


class TestWorkoutDetail:
    @pytest.fixture
    def populated(self, tmp_path) -> tuple[Database, Settings]:
        settings = Settings(database_path=tmp_path / "detail.db", workouts_dir=tmp_path)
        db = Database(settings.database_path)
        db.upsert_workouts(
            [
                _workout(0, [(60, 5), (60, 5)], days_ago=21),
                _workout(1, [(65, 5), (65, 5)], days_ago=14),
                # A different routine in between must not affect Push's numbering.
                _workout(2, [(40, 8)], title="Pull", days_ago=10, template=OTHER),
                _workout(3, [(70, 5), (70, 5)], days_ago=7),
            ]
        )
        db.upsert_templates(
            [
                ExerciseTemplate(
                    id=TEMPLATE,
                    title="Bench Press (Barbell)",
                    primary_muscle_group="chest",
                    secondary_muscle_groups=["triceps"],
                    equipment_category="barbell",
                )
            ]
        )
        return db, settings

    def test_unknown_id_raises(self, populated) -> None:
        db, settings = populated
        with pytest.raises(LookupError):
            session.workout_detail(db, settings, "nope")

    def test_routine_position_counts_only_the_same_routine(self, populated) -> None:
        db, settings = populated
        detail = session.workout_detail(db, settings, "w3")
        assert detail.routine.title == "Push"
        assert (detail.routine.run_index, detail.routine.runs) == (3, 3)
        assert detail.routine.previous_id == "w1"

    def test_session_totals_and_comparison(self, populated) -> None:
        db, settings = populated
        detail = session.workout_detail(db, settings, "w3")
        assert detail.sets == 2
        assert detail.volume_kg == pytest.approx(700.0)
        assert detail.duration_minutes == pytest.approx(50.0)
        # 700 against 650 the run before.
        assert detail.routine.volume_delta_pct == pytest.approx(7.7, abs=0.1)

    def test_exercise_block_compares_against_the_previous_occurrence(self, populated) -> None:
        db, settings = populated
        block = session.workout_detail(db, settings, "w3").exercises[0]
        assert block.previous is not None
        assert block.previous.workout_id == "w1"
        assert block.previous.top_weight_kg == 65
        assert block.e1rm_delta_kg == pytest.approx(5.9, abs=0.1)
        assert block.is_pr is True
        assert block.muscle_group == "chest"

    def test_exercise_comparison_crosses_routines(self, tmp_path) -> None:
        # The baseline is the last time you did *the exercise*, wherever it was.
        # Rotating a lift between two routines must not reset its history.
        settings = Settings(database_path=tmp_path / "cross.db", workouts_dir=tmp_path)
        db = Database(settings.database_path)
        db.upsert_workouts(
            [
                _workout(0, [(60, 5)], title="Push", days_ago=14),
                _workout(1, [(65, 5)], title="Full Body", days_ago=7),
                _workout(2, [(70, 5)], title="Push", days_ago=1),
            ]
        )
        detail = session.workout_detail(db, settings, "w2")
        assert detail.routine.previous_id == "w0"
        assert detail.exercises[0].previous is not None
        assert detail.exercises[0].previous.workout_id == "w1"

    def test_history_is_truncated_at_the_session_being_viewed(self, populated) -> None:
        # Viewing an old session must not use sets that had not happened yet.
        db, settings = populated
        block = session.workout_detail(db, settings, "w1").exercises[0]
        assert block.sessions == 2
        assert block.is_pr is True
        assert block.recommendation.target_weight_kg == 65

    def test_muscle_breakdown_and_notes(self, populated) -> None:
        db, settings = populated
        detail = session.workout_detail(db, settings, "w3")
        assert detail.muscle_groups == [
            {"muscle_group": "chest", "sets": 2, "volume_kg": 700.0}
        ]
        assert any("Bench Press" in note for note in detail.notes)

    def test_listing_tags_each_session_with_its_routine_position(self, populated) -> None:
        db, _ = populated
        listed = session.list_workouts(db)
        assert [w.id for w in listed] == ["w3", "w2", "w1", "w0"]
        assert (listed[0].routine_index, listed[0].routine_runs) == (3, 3)
        assert (listed[1].routine_index, listed[1].routine_runs) == (1, 1)
