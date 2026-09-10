"""Tests for e1RM, storage, metrics and progression."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hevy_coach import units
from hevy_coach.analytics import e1rm, metrics, progression
from hevy_coach.analytics.benchmark import benchmark
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.demo import build_history
from hevy_coach.hevy.models import HevyExercise, HevySet, HevyWorkout


class TestE1RM:
    def test_single_rep_returns_the_load(self) -> None:
        assert e1rm.epley(100, 1) == pytest.approx(103.33, abs=0.01)
        assert e1rm.brzycki(100, 1) == pytest.approx(100.0, abs=0.01)

    def test_epley_matches_the_formula(self) -> None:
        assert e1rm.estimate(100, 5) == pytest.approx(100 * (1 + 5 / 30))

    def test_high_reps_are_not_extrapolated(self) -> None:
        assert e1rm.estimate(60, e1rm.MAX_TRUSTED_REPS) is not None
        assert e1rm.estimate(60, e1rm.MAX_TRUSTED_REPS + 1) is None

    def test_missing_data_returns_none(self) -> None:
        assert e1rm.estimate(None, 5) is None
        assert e1rm.estimate(100, None) is None
        assert e1rm.estimate(100, 0) is None

    def test_zero_load_is_valid_for_bodyweight_work(self) -> None:
        # An unweighted pull-up is a real set; it must not be dropped like a null.
        assert e1rm.estimate(0.0, 8) == 0.0

    def test_rpe_estimate_beats_epley_for_submaximal_sets(self) -> None:
        # 5 reps at RPE 8 means 2 in reserve, so the true 1RM is well above the
        # naive "as if taken to failure" Epley number.
        rpe_based = e1rm.estimate(100, 5, 8.0, formula="rpe")
        assert rpe_based is not None
        assert rpe_based > e1rm.estimate(100, 5)  # type: ignore[operator]

    def test_rpe_out_of_range_falls_back(self) -> None:
        assert e1rm.estimate(100, 5, 4.0, formula="rpe") == pytest.approx(e1rm.epley(100, 5))

    def test_added_load_puts_bodyweight_in_and_takes_it_back_out(self) -> None:
        """Ten unweighted pull-ups at 80 kg is a 1RM of about +27 kg added."""
        assert e1rm.added_load(None, 10, 80.0) == pytest.approx(26.667, abs=0.01)

    def test_added_load_beats_scoring_the_added_weight_alone(self) -> None:
        """Eight dips at +20 kg move 100 kg, so the 1RM is well above +20 kg."""
        assert e1rm.added_load(20.0, 8, 80.0) == pytest.approx(46.667, abs=0.01)
        # Feeding Epley the added weight on its own understates it badly.
        assert e1rm.estimate(20.0, 8) == pytest.approx(25.333, abs=0.01)

    def test_added_load_rises_with_added_weight_and_with_reps(self) -> None:
        assert e1rm.added_load(20.0, 5, 80.0) > e1rm.added_load(10.0, 5, 80.0)
        assert e1rm.added_load(10.0, 8, 80.0) > e1rm.added_load(10.0, 5, 80.0)

    def test_added_load_is_lower_for_a_heavier_lifter(self) -> None:
        """The same set is less impressive when there is less bodyweight to move."""
        assert e1rm.added_load(None, 10, 60.0) < e1rm.added_load(None, 10, 90.0)

    def test_added_load_handles_assisted_reps(self) -> None:
        """Assistance is negative load, and stays negative after the estimate."""
        assert e1rm.added_load(-20.0, 5, 80.0) < 0

    def test_added_load_needs_reps_and_a_bodyweight(self) -> None:
        assert e1rm.added_load(10.0, None, 80.0) is None
        assert e1rm.added_load(10.0, 5, 0.0) is None
        assert e1rm.added_load(10.0, 20, 80.0) is None

    def test_best_of_picks_the_maximum(self) -> None:
        assert e1rm.best_of([(100, 5, None), (120, 1, None), (80, 10, None)]) == pytest.approx(
            e1rm.epley(120, 1)
        )


class TestDatabase:
    def test_workouts_and_sets_are_stored(self, db: Database) -> None:
        assert db.workout_count() == 60  # 20 weeks x 3 sessions
        rows = db.query("SELECT COUNT(*) AS n FROM sets")
        assert rows[0]["n"] == 60 * 2 * 4  # 2 exercises x (1 warmup + 3 working)

    def test_upsert_is_idempotent(self, db: Database) -> None:
        before = db.query("SELECT COUNT(*) AS n FROM sets")[0]["n"]
        db.upsert_workouts(build_history())
        assert db.query("SELECT COUNT(*) AS n FROM sets")[0]["n"] == before
        assert db.workout_count() == 60

    def test_delete_cascades_to_sets(self, db: Database) -> None:
        db.delete_workout("w00-0")
        assert db.query("SELECT COUNT(*) AS n FROM sets WHERE workout_id='w00-0'")[0]["n"] == 0


class TestMetrics:
    def test_overview_excludes_warmups_from_volume(self, db: Database) -> None:
        stats = metrics.overview(db)
        assert stats.workouts == 60
        assert stats.total_sets == 60 * 2 * 3  # warm-ups excluded
        assert stats.total_volume_kg > 0
        assert stats.avg_workouts_per_week == pytest.approx(3.0, abs=0.5)

    def test_weekly_volume_is_chronological(self, db: Database) -> None:
        weekly = metrics.weekly_volume(db, weeks=52)
        assert len(weekly) >= 19
        assert [w["week"] for w in weekly] == sorted(w["week"] for w in weekly)
        assert all(w["volume_kg"] > 0 for w in weekly)

    def test_secondary_muscles_count_as_half_a_set(self, db: Database) -> None:
        groups = {g["muscle_group"]: g for g in metrics.muscle_group_volume(db, days=365)}
        # Each exercise contributes 20 sessions x 3 working sets = 60 sets.
        # Chest is primary on the bench and nothing else, so it gets all 60.
        assert groups["chest"]["sets"] == pytest.approx(60.0)
        # Forearms are secondary on the curl only, so exactly half of its 60.
        assert groups["forearms"]["sets"] == pytest.approx(30.0)
        # Biceps are primary on the curl (60) and secondary on the row (30).
        assert groups["biceps"]["sets"] == pytest.approx(90.0)

    def test_exercise_history_is_one_point_per_session(self, db: Database) -> None:
        history = metrics.exercise_history(db, "T_BENCH", days=None)
        assert len(history) == 20  # bench appears once a week
        assert all(p.best_e1rm_kg is not None for p in history)
        assert history[0].date < history[-1].date

    def test_personal_records_only_records_improvements(self, db: Database) -> None:
        records = metrics.personal_records(db, days=None, limit=100)
        assert records
        by_exercise: dict[str, list[float]] = {}
        for record in sorted(records, key=lambda r: r.date):
            by_exercise.setdefault(record.template_id, []).append(record.e1rm_kg)
        for values in by_exercise.values():
            assert values == sorted(values), "a PR must beat every PR before it"


class TestProgression:
    def test_linear_trend_recovers_a_known_slope(self) -> None:
        slope, intercept = progression.linear_trend([(0, 10), (1, 12), (2, 14), (3, 16)])
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(10.0)

    def test_linear_trend_handles_constant_x(self) -> None:
        slope, intercept = progression.linear_trend([(5, 10), (5, 20)])
        assert slope == 0.0
        assert intercept == pytest.approx(15.0)

    def test_progressing_lifts_are_detected(self, db: Database, settings: Settings) -> None:
        trends = {t.template_id: t for t in progression.exercise_trends(db, settings, days=365)}
        assert trends["T_SQUAT"].trend == "progressing"
        assert trends["T_SQUAT"].slope_kg_per_month > 0

    def test_stalled_lift_is_flagged(self, db: Database, settings: Settings) -> None:
        trends = {t.template_id: t for t in progression.exercise_trends(db, settings, days=365)}
        # The curl is generated with zero weekly gain.
        assert trends["T_CURL"].trend in {"stalling", "maintaining"}
        assert abs(trends["T_CURL"].slope_kg_per_month) < 1.0

    def test_insights_are_produced_and_ordered(self, db: Database, settings: Settings) -> None:
        found = progression.insights(db, settings, days=365)
        assert found
        rank = {"warning": 0, "suggestion": 1, "info": 2}
        severities = [rank[i.severity] for i in found]
        assert severities == sorted(severities)

    def test_empty_database_yields_no_insights(
        self, empty_db: Database, settings: Settings
    ) -> None:
        assert progression.insights(empty_db, settings) == []


class TestUnits:
    def test_kilograms_pass_through(self) -> None:
        assert units.convert(100.0, "kg") == 100.0
        assert units.fmt(82.5, "kg") == "82.5 kg"

    def test_pounds_are_converted_and_labelled(self) -> None:
        assert units.convert(100.0, "lb") == pytest.approx(220.462, abs=0.01)
        assert units.fmt(80.0, "lb") == "176.4 lb"

    def test_thousands_separator_is_opt_in(self) -> None:
        assert units.fmt(8810.0, "kg", 0, thousands=True) == "8,810 kg"
        assert units.fmt(8810.0, "kg", 0) == "8810 kg"


class TestInsightProse:
    """Insight text is generated server-side, so it has to honour the unit itself."""

    @staticmethod
    def _regressing_db(path: Path) -> Database:
        """A lift whose e1RM falls week over week, so the prose quotes loads."""
        database = Database(path)
        start = datetime.now(UTC) - timedelta(weeks=10)
        database.upsert_workouts(
            [
                HevyWorkout(
                    id=f"w{week}",
                    title="Session",
                    start_time=start + timedelta(weeks=week),
                    exercises=[
                        HevyExercise(
                            title="Bench Press (Barbell)",
                            exercise_template_id="T_BENCH",
                            sets=[HevySet(weight_kg=100.0 - week * 3, reps=5)],
                        )
                    ],
                )
                for week in range(10)
            ]
        )
        return database

    def test_details_are_written_in_kilograms_by_default(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        database = self._regressing_db(tmp_path / "kg.db")

        details = " ".join(i.detail for i in progression.insights(database, settings, days=180))

        assert " kg" in details
        assert " lb" not in details

    def test_details_are_written_in_pounds_when_configured(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        database = self._regressing_db(tmp_path / "lb.db")
        in_pounds = settings.model_copy(update={"units": "lb"})

        details = " ".join(i.detail for i in progression.insights(database, in_pounds, days=180))

        assert " lb" in details
        assert " kg" not in details


class TestBenchmark:
    def test_main_lifts_are_mapped_and_scored(self, db: Database, settings: Settings) -> None:
        report = benchmark(db, settings, days=None)
        mapped = {entry.lift for entry in report.entries}
        assert {"bench-press", "squat", "deadlift", "bent-over-row"} <= mapped
        assert report.overall_level_score is not None

    def test_one_row_per_standard_even_with_several_logged_variants(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        """Regression: two cable-row variants meant two levels for one standard.

        Both grips score against ``seated-cable-row``. Emitting a row each put
        two contradictory levels in the report and let the weaker variant drag
        the overall mean down, so only the strongest survives - and it names
        the one it shadowed.
        """
        database = Database(tmp_path / "variants.db")
        database.upsert_workouts(
            [
                HevyWorkout(
                    id="w1",
                    title="Pull",
                    start_time=datetime.now(UTC) - timedelta(days=2),
                    exercises=[
                        HevyExercise(
                            title="Seated Cable Row - V Grip (Cable)",
                            exercise_template_id="row-v",
                            sets=[HevySet(weight_kg=80.0, reps=5)],
                        ),
                        HevyExercise(
                            title="Seated Cable Row - Bar Grip",
                            exercise_template_id="row-bar",
                            sets=[HevySet(weight_kg=40.0, reps=5)],
                        ),
                    ],
                )
            ]
        )

        report = benchmark(database, settings, days=None)
        rows = [entry for entry in report.entries if entry.lift == "seated-cable-row"]

        assert len(rows) == 1
        assert rows[0].title == "Seated Cable Row - V Grip (Cable)"
        assert rows[0].also_logged == ["Seated Cable Row - Bar Grip"]

    def test_a_defaulted_bodyweight_is_flagged_not_presented_as_the_lifters(
        self, tmp_path: Path
    ) -> None:
        """Every band is indexed on bodyweight, so a guessed one has to say so."""
        defaulted = Settings(
            _env_file=None, database_path=tmp_path / "d.db", workouts_dir=tmp_path / "w"
        )
        database = Database(defaulted.database_path)
        database.upsert_workouts(build_history())

        report = benchmark(database, defaulted, days=None)

        assert report.bodyweight_source == "default"
        assert any("placeholder bodyweight" in caveat for caveat in report.caveats)

    def test_a_configured_bodyweight_carries_no_caveat(
        self, db: Database, settings: Settings
    ) -> None:
        report = benchmark(db, settings, days=None)
        assert report.bodyweight_source == "configured"
        assert report.caveats == []

    def test_a_combined_dumbbell_log_is_scored_per_dumbbell(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        """Regression: a combined-weight dumbbell bench read elite next to a
        beginner barbell bench, because the published table is per dumbbell."""
        database = Database(tmp_path / "db.db")
        database.upsert_workouts(
            [
                HevyWorkout(
                    id="w1",
                    title="Push",
                    start_time=datetime.now(UTC) - timedelta(days=1),
                    exercises=[
                        HevyExercise(
                            title="Bench Press (Dumbbell)",
                            exercise_template_id="db-bench",
                            sets=[HevySet(weight_kg=50.0, reps=5)],
                        )
                    ],
                )
            ]
        )

        def bench(config: Settings) -> dict[str, object]:
            entry = next(
                e
                for e in benchmark(database, config, days=None).entries
                if e.lift == "dumbbell-bench-press"
            )
            return entry.score

        as_logged = bench(settings)
        halved = bench(settings.model_copy(update={"dumbbell_load": "combined"}))

        assert halved["e1rm_kg"] == pytest.approx(as_logged["e1rm_kg"] / 2, abs=0.1)
        assert halved["level_score"] < as_logged["level_score"]
        assert as_logged["notes"] == []
        assert any("Halved to one dumbbell" in note for note in halved["notes"])

    def test_a_single_implement_dumbbell_lift_is_never_halved(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        """A one-arm row holds one dumbbell, so a combined log cannot apply."""
        database = Database(tmp_path / "db2.db")
        database.upsert_workouts(
            [
                HevyWorkout(
                    id="w1",
                    title="Pull",
                    start_time=datetime.now(UTC) - timedelta(days=1),
                    exercises=[
                        HevyExercise(
                            title="Dumbbell Row",
                            exercise_template_id="db-row",
                            sets=[HevySet(weight_kg=30.0, reps=5)],
                        )
                    ],
                )
            ]
        )

        combined = settings.model_copy(update={"dumbbell_load": "combined"})
        rows = [
            (e.score["e1rm_kg"], e.score["notes"])
            for config in (settings, combined)
            for e in benchmark(database, config, days=None).entries
            if e.lift == "dumbbell-row"
        ]

        assert len(rows) == 2
        assert rows[0][0] == rows[1][0]
        assert rows[0][1] == rows[1][1] == []

    def test_scores_are_ordered_strongest_first(self, db: Database, settings: Settings) -> None:
        report = benchmark(db, settings, days=None)
        scores = [entry.score["level_score"] for entry in report.entries]
        assert scores == sorted(scores, reverse=True)

    def test_bodyweight_lifts_are_scored_not_dropped(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        """Regression: pull-ups log no weight, and used to vanish from the report."""
        database = Database(tmp_path / "bw.db")
        database.upsert_workouts(
            [
                HevyWorkout(
                    id="w1",
                    title="Pull day",
                    start_time=datetime.now(UTC) - timedelta(days=3),
                    exercises=[
                        HevyExercise(
                            title="Pull Up",
                            exercise_template_id="pull-up",
                            sets=[HevySet(reps=10), HevySet(reps=8)],
                        )
                    ],
                )
            ]
        )

        report = benchmark(database, settings, days=365)

        entry = next(e for e in report.entries if e.title == "Pull Up")
        assert entry.lift == "pull-ups"
        assert entry.score["metric"] == "added_kg"
        # 10 reps at bodyweight, not the 0 kg that Epley alone would give.
        assert entry.score["e1rm_kg"] == pytest.approx(26.7, abs=0.1)

    def test_thresholds_are_monotonic(self, db: Database, settings: Settings) -> None:
        report = benchmark(db, settings, days=None)
        for entry in report.entries:
            values = list(entry.score["thresholds"].values())
            assert values == sorted(values), entry.title
