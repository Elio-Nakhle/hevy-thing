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


# -- which routine is due ---------------------------------------------------


def _settings(tmp_path: object) -> Settings:
    return Settings(  # type: ignore[operator]
        _env_file=None, database_path=tmp_path / "next.db", bodyweight_kg=80.0
    )


def _rotation(db: Database) -> None:
    """Push/Pull alternating, Pull run most recently - so Push is due."""
    db.upsert_templates(
        [
            ExerciseTemplate(
                id=TEMPLATE, title="Bench Press (Barbell)", equipment_category="barbell"
            ),
            ExerciseTemplate(id=OTHER, title="Squat (Barbell)", equipment_category="barbell"),
        ]
    )
    db.upsert_workouts(
        [
            _workout(1, [(60.0, 8), (60.0, 8)], title="Push", days_ago=14),
            _workout(2, [(80.0, 8), (80.0, 8)], title="Pull", days_ago=11, template=OTHER),
            _workout(3, [(60.0, 10), (60.0, 10)], title="Push", days_ago=7),
            _workout(4, [(80.0, 10), (80.0, 10)], title="Pull", days_ago=4, template=OTHER),
        ]
    )


def test_routines_due_lists_longest_unused_first(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    _rotation(db)

    due = session.routines_due(db)

    assert [routine.title for routine in due] == ["Push", "Pull"]
    assert due[0].runs == 2
    assert due[0].days_since == 7


def test_the_routine_you_did_least_recently_is_due(tmp_path) -> None:
    """After Pull, Push is next - not a repeat of what you just did."""
    db = Database(tmp_path / "next.db")
    _rotation(db)

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Push"
    assert upcoming.routine.workout_id == "w3"


def test_prescriptions_come_from_that_routine_last_run(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    _rotation(db)

    upcoming = session.next_session(db, _settings(tmp_path))

    assert [exercise.title for exercise in upcoming.exercises] == ["Bench Press (Barbell)"]
    exercise = upcoming.exercises[0]
    assert exercise.last_top_weight_kg == 60.0
    assert exercise.last_top_reps == 10
    assert exercise.last_top_set_count == 2
    assert exercise.last_top_set_reps == [10, 10]
    # Top of the 6-10 band on both sets, so the next run adds load.
    assert exercise.recommendation.action == "add_load"
    assert exercise.recommendation.target_weight_kg is not None


def test_a_named_routine_overrides_what_is_due(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    _rotation(db)

    upcoming = session.next_session(db, _settings(tmp_path), title="Pull")

    assert upcoming.routine.title == "Pull"
    assert [exercise.title for exercise in upcoming.exercises] == ["Squat (Barbell)"]


def test_every_routine_is_offered_as_an_alternative(tmp_path) -> None:
    """The rack view needs them: what is due is a guess, not a plan."""
    db = Database(tmp_path / "next.db")
    _rotation(db)

    upcoming = session.next_session(db, _settings(tmp_path))

    assert [routine.title for routine in upcoming.alternatives] == ["Push", "Pull"]


def test_an_unknown_routine_is_a_lookup_error(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    _rotation(db)

    with pytest.raises(LookupError, match="Legs"):
        session.next_session(db, _settings(tmp_path), title="Legs")


def test_an_empty_log_has_no_next_session(tmp_path) -> None:
    db = Database(tmp_path / "next.db")

    with pytest.raises(LookupError, match="no workouts"):
        session.next_session(db, _settings(tmp_path))


def test_a_stale_one_off_is_selectable_but_never_predicted(tmp_path) -> None:
    """It stays in `alternatives` - the lifter may want it - but is not a guess."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.upsert_workouts([_workout(9, [(40.0, 10)], title="Hotel gym", days_ago=90)])

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Push"
    # Still selectable, just not predicted.
    assert "Hotel gym" in [routine.title for routine in upcoming.alternatives]


def test_an_abandoned_routine_does_not_stay_due_forever(tmp_path) -> None:
    """The bug this rule exists for. A real Hevy log accumulates titles - Hevy's
    own "Afternoon workout", a dropped routine, a week of improvising - and every
    one of them is more overdue than what the lifter actually trains, so "most
    overdue" alone reliably picks the least relevant thing in the log."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.upsert_workouts(
        [
            _workout(7, [(50.0, 8)], title="Afternoon workout", days_ago=104),
            _workout(8, [(50.0, 8)], title="Afternoon workout", days_ago=110),
        ]
    )

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Push"


def test_after_a_layoff_you_resume_the_last_thing_you_did(tmp_path) -> None:
    """Nothing is inside the active window, so there is no rotation to infer."""
    db = Database(tmp_path / "next.db")
    db.upsert_templates(
        [
            ExerciseTemplate(
                id=TEMPLATE, title="Bench Press (Barbell)", equipment_category="barbell"
            )
        ]
    )
    db.upsert_workouts(
        [
            _workout(1, [(60.0, 8)], title="Old A", days_ago=200),
            _workout(2, [(60.0, 8)], title="Old A", days_ago=190),
            _workout(3, [(60.0, 8)], title="Old B", days_ago=180),
            _workout(4, [(60.0, 8)], title="Old B", days_ago=170),
        ]
    )

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Old B"


def test_a_single_active_routine_is_simply_repeated(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    db.upsert_templates(
        [
            ExerciseTemplate(
                id=TEMPLATE, title="Bench Press (Barbell)", equipment_category="barbell"
            )
        ]
    )
    db.upsert_workouts(
        [
            _workout(1, [(60.0, 8)], title="Full body", days_ago=7),
            _workout(2, [(60.0, 8)], title="Full body", days_ago=3),
        ]
    )

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Full body"


def test_a_recent_one_off_does_not_outrank_the_programme(tmp_path) -> None:
    """"Baku hotel gym", logged once nine days ago, is recent but not a routine."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.upsert_workouts([_workout(7, [(40.0, 10)], title="Baku hotel gym", days_ago=9)])

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Push"


def test_a_log_with_no_repeats_still_gets_a_prescription(tmp_path) -> None:
    """Nothing repeats, so there is no rotation to infer - answer anyway."""
    db = Database(tmp_path / "next.db")
    db.upsert_templates(
        [
            ExerciseTemplate(
                id=TEMPLATE, title="Bench Press (Barbell)", equipment_category="barbell"
            )
        ]
    )
    db.upsert_workouts([_workout(1, [(60.0, 8)], title="Only one", days_ago=3)])

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Only one"
    assert upcoming.exercises


# -- the one-line summary ---------------------------------------------------


def test_summary_names_what_changes(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    _rotation(db)

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.summary.startswith("Push is up next -")
    assert "add weight on Bench Press (Barbell)" in upcoming.summary
    prescribed = upcoming.exercises[0].recommendation.headline
    assert upcoming.changes == [f"Bench Press (Barbell): {prescribed}"]


def _one_lift(db: Database, *sessions: tuple[list[tuple[float | None, int]], int]) -> None:
    db.upsert_templates(
        [
            ExerciseTemplate(
                id=TEMPLATE, title="Bench Press (Barbell)", equipment_category="barbell"
            )
        ]
    )
    db.upsert_workouts(
        [
            _workout(index, sets, title="Push", days_ago=days_ago)
            for index, (sets, days_ago) in enumerate(sessions, start=1)
        ]
    )


def test_summary_says_chase_reps_mid_range(tmp_path) -> None:
    """8 reps sits inside the 6-10 band, so the load holds and the reps go up."""
    db = Database(tmp_path / "next.db")
    _one_lift(db, ([(60.0, 8), (60.0, 8)], 10), ([(60.0, 8), (60.0, 8)], 3))

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.exercises[0].recommendation.action == "add_reps"
    assert upcoming.summary == "Push is up next - chase reps on Bench Press (Barbell)."


def test_summary_says_back_off_on_a_stalled_lift(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    _one_lift(db, *[([(60.0, 8), (60.0, 8)], 20 - i * 4) for i in range(1, 5)])

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.exercises[0].recommendation.action == "deload"
    assert upcoming.summary == "Push is up next - back off on Bench Press (Barbell)."


def test_summary_says_so_when_nothing_changes(tmp_path) -> None:
    """A first session establishes a baseline; there is nothing to change yet."""
    db = Database(tmp_path / "next.db")
    _one_lift(db, ([(60.0, 8), (60.0, 8)], 3))

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.exercises[0].recommendation.action == "establish"
    assert upcoming.summary == "Push is up next - same weights as last time."
    assert upcoming.changes == []


def test_name_list_caps_how_many_it_names() -> None:
    assert session._name_list(["A"]) == "A"
    assert session._name_list(["A", "B"]) == "A and B"
    assert session._name_list(["A", "B", "C"]) == "A, B and 1 more"
    assert session._name_list(["A", "B", "C", "D"]) == "A, B and 2 more"


def test_the_last_session_reports_every_top_set(tmp_path) -> None:
    """A 12 and a 10 at the same load must not read as "2 x 12": the
    prescription progresses the worst set, so a target of 11 would look like a
    step backwards from a number the lifter only hit once."""
    db = Database(tmp_path / "next.db")
    _one_lift(db, ([(32.0, 12), (32.0, 10)], 8), ([(32.0, 12), (32.0, 10)], 2))

    exercise = session.next_session(db, _settings(tmp_path)).exercises[0]

    assert exercise.last_top_reps == 12
    assert exercise.last_top_set_reps == [12, 10]
    assert exercise.recommendation.target_reps == 11


# -- putting a routine away -------------------------------------------------


def test_a_dismissed_routine_is_not_offered_or_predicted(tmp_path) -> None:
    """Trying a routine is not committing to it."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.set_routine_dismissed("Push", True)

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Pull"
    put_away = next(r for r in upcoming.alternatives if r.title == "Push")
    assert put_away.dismissed is True
    assert put_away.active is False


def test_dismissal_survives_training_it_again(tmp_path) -> None:
    """Sticky on purpose. A routine reappearing on its own would be the
    surprising behaviour, and a log has plenty of reasons to contain one more
    session of something the lifter is finished with."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.set_routine_dismissed("Push", True)
    db.upsert_workouts([_workout(9, [(60.0, 10), (60.0, 10)], title="Push", days_ago=0)])

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title == "Pull"


def test_asking_for_a_dismissed_routine_by_name_still_works(tmp_path) -> None:
    """Naming it is a stronger signal than having put it away."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.set_routine_dismissed("Push", True)

    upcoming = session.next_session(db, _settings(tmp_path), title="Push")

    assert upcoming.routine.title == "Push"
    assert upcoming.exercises


def test_restoring_a_routine_brings_it_back(tmp_path) -> None:
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.set_routine_dismissed("Push", True)
    db.set_routine_dismissed("Push", False)

    assert session.next_session(db, _settings(tmp_path)).routine.title == "Push"


def test_dismissing_everything_still_answers(tmp_path) -> None:
    """A blank page would be worse than a guess the lifter can switch away from."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.set_routine_dismissed("Push", True)
    db.set_routine_dismissed("Pull", True)

    upcoming = session.next_session(db, _settings(tmp_path))

    assert upcoming.routine.title in {"Push", "Pull"}
    assert upcoming.exercises


def test_only_the_current_rotation_is_active(tmp_path) -> None:
    """`active` is what the switcher shows without being asked. On a real log
    this is the difference between two chips and seven."""
    db = Database(tmp_path / "next.db")
    _rotation(db)
    db.upsert_workouts(
        [
            _workout(7, [(40.0, 10)], title="Baku hotel gym", days_ago=9),
            _workout(8, [(50.0, 8)], title="Afternoon workout", days_ago=104),
            _workout(9, [(50.0, 8)], title="Afternoon workout", days_ago=110),
        ]
    )

    upcoming = session.next_session(db, _settings(tmp_path))

    active = {r.title for r in upcoming.alternatives if r.active}
    assert active == {"Push", "Pull"}
    # Everything else is still reachable, just not offered up front.
    assert {r.title for r in upcoming.alternatives} == {
        "Push",
        "Pull",
        "Baku hotel gym",
        "Afternoon workout",
    }
