"""Tests for the strength-standards dataset and scoring."""

from __future__ import annotations

from typing import ClassVar

import pytest

from hevy_coach.analytics.standards import (
    LEVEL_PERCENTILES,
    LEVELS,
    PAIRED_DUMBBELL_LIFTS,
    StandardsNotAvailable,
    _interpolate,
    _level_score,
    available_lifts,
    bands_for,
    load_dataset,
    metric_for,
    per_dumbbell_load,
    resolve_lift,
    score_lift,
)


class TestDataset:
    def test_dataset_covers_the_main_lifts(self) -> None:
        lifts = available_lifts()
        assert {"bench-press", "squat", "deadlift", "pull-ups"} <= set(lifts)

    def test_every_lift_has_both_sexes_and_rising_thresholds(self) -> None:
        for lift, entry in load_dataset()["lifts"].items():
            assert {"male", "female"} <= set(entry["sexes"]), lift
            for sex, table in entry["sexes"].items():
                count = len(table["bodyweights_kg"])
                columns = [table["levels"][level] for level in LEVELS]
                assert all(len(c) == count for c in columns), f"{lift}/{sex}"
                for row in range(count):
                    values = [c[row] for c in columns]
                    assert values == sorted(values), f"{lift}/{sex} row {row}"

    def test_bodyweight_lifts_use_added_weight(self) -> None:
        # Hevy logs weighted pull-ups as added load, so the standard must match.
        assert load_dataset()["lifts"]["pull-ups"]["metric"] == "added_kg"
        assert load_dataset()["lifts"]["bench-press"]["metric"] == "kg"


    def test_every_lift_declares_a_load_metric(self) -> None:
        """A reps or time table scraped as if it were kilos would show up here."""
        for lift, entry in load_dataset()["lifts"].items():
            assert entry["metric"] in {"kg", "added_kg"}, lift

    def test_metric_for_reports_how_a_lift_is_measured(self) -> None:
        assert metric_for("bench-press") == "kg"
        assert metric_for("pull-ups") == "added_kg"
        assert metric_for("not-a-lift") is None


class TestInterpolation:
    def test_interpolates_between_rows(self) -> None:
        assert _interpolate([50, 60], [100, 120], 55) == pytest.approx(110.0)

    def test_clamps_instead_of_extrapolating(self) -> None:
        # Inventing standards outside the published range would be worse than
        # holding the endpoint.
        assert _interpolate([50, 60], [100, 120], 10) == 100.0
        assert _interpolate([50, 60], [100, 120], 999) == 120.0

    def test_bodyweight_between_table_rows_is_interpolated(self) -> None:
        at_80 = bands_for("bench-press", sex="male", bodyweight_kg=80).thresholds
        at_85 = bands_for("bench-press", sex="male", bodyweight_kg=85).thresholds
        at_82 = bands_for("bench-press", sex="male", bodyweight_kg=82.5).thresholds
        for level in LEVELS:
            assert at_80[level] < at_82[level] < at_85[level]


class TestLevelScore:
    THRESHOLDS: ClassVar[list[float]] = [50.0, 75.0, 100.0, 125.0, 150.0]

    def test_thresholds_land_on_whole_numbers(self) -> None:
        for i, value in enumerate(self.THRESHOLDS):
            assert _level_score(value, self.THRESHOLDS) == pytest.approx(float(i))

    def test_midband_is_fractional(self) -> None:
        assert _level_score(87.5, self.THRESHOLDS) == pytest.approx(1.5)

    def test_score_continues_past_both_ends(self) -> None:
        assert _level_score(25.0, self.THRESHOLDS) < 0
        assert _level_score(175.0, self.THRESHOLDS) > 4


class TestLiftResolution:
    def test_barbell_deadlift_variants_map_to_the_deadlift_standard(self) -> None:
        for title in ("Deadlift (Barbell)", "Deadlift", "Conventional Deadlift"):
            assert resolve_lift(title) == "deadlift", title

    def test_dumbbell_deadlift_is_not_scored_as_a_barbell_deadlift(self) -> None:
        """Regression: ``^deadlift`` swallowed the dumbbell variant.

        A dumbbell deadlift is a different movement with a much lower ceiling,
        and the dataset has no table for it. Scoring it against the barbell
        table gave one lift two contradictory levels in the same report.
        """
        assert resolve_lift("Deadlift (Dumbbell)") is None

    def test_the_specific_deadlift_variants_still_win(self) -> None:
        assert resolve_lift("Sumo Deadlift (Barbell)") == "sumo-deadlift"
        assert resolve_lift("Romanian Deadlift (Barbell)") == "romanian-deadlift"


class TestDumbbellLoad:
    def test_per_dumbbell_logs_are_left_alone(self) -> None:
        assert per_dumbbell_load(
            "dumbbell-bench-press", 40.0, convention="per_dumbbell"
        ) == pytest.approx(40.0)

    def test_combined_logs_are_halved_for_paired_lifts(self) -> None:
        """The tables are published per dumbbell; a pair's total scores double."""
        assert per_dumbbell_load(
            "dumbbell-bench-press", 40.0, convention="combined"
        ) == pytest.approx(20.0)

    def test_single_implement_lifts_are_never_halved(self) -> None:
        """A one-arm row and a goblet squat hold one weight - no pair to split."""
        for lift in ("dumbbell-row", "goblet-squat", "bench-press"):
            assert per_dumbbell_load(lift, 40.0, convention="combined") == pytest.approx(
                40.0
            ), lift

    def test_every_paired_lift_exists_in_the_dataset(self) -> None:
        """A typo here would silently stop halving that lift."""
        assert set(available_lifts()) >= PAIRED_DUMBBELL_LIFTS

    def test_halving_a_combined_bench_brings_it_back_beside_the_barbell(self) -> None:
        """The bug this fixes: one bench elite, the other beginner, same chest."""
        raw = score_lift("dumbbell-bench-press", 70.0, sex="male", bodyweight_kg=80.0)
        halved = score_lift(
            "dumbbell-bench-press",
            per_dumbbell_load("dumbbell-bench-press", 70.0, convention="combined"),
            sex="male",
            bodyweight_kg=80.0,
        )
        assert raw.level == "elite"
        assert halved.level_score < raw.level_score - 2


class TestScoring:
    def test_known_intermediate_bench(self) -> None:
        # 100 kg bench at 80 kg bodyweight sits just past intermediate for men.
        score = score_lift("bench-press", 100.0, sex="male", bodyweight_kg=80.0)
        assert score.level == "intermediate"
        assert 2.0 <= score.level_score < 3.0
        assert score.next_level == "advanced"
        assert score.kg_to_next_level is not None and score.kg_to_next_level > 0

    def test_ratio_and_percentile_are_reported(self) -> None:
        score = score_lift("squat", 160.0, sex="male", bodyweight_kg=80.0)
        assert score.ratio == pytest.approx(2.0)
        assert 0 <= score.percentile_estimate <= 100

    def test_percentile_matches_the_published_band_definitions(self) -> None:
        """Each level must report the percentile the source says it is.

        Regression: this was ``level_score / 4 * 100``, which called elite the
        100th percentile and novice the 25th. The bands are unevenly spaced in
        percentile terms, so the mapping has to go through the real anchors.
        """
        bands = bands_for("bench-press", sex="male", bodyweight_kg=80.0)
        for level, expected in zip(LEVELS, LEVEL_PERCENTILES, strict=True):
            score = score_lift(
                "bench-press", bands.thresholds[level], sex="male", bodyweight_kg=80.0
            )
            assert score.percentile_estimate == pytest.approx(expected, abs=0.6), level

    def test_percentile_is_held_flat_outside_the_published_bands(self) -> None:
        """Past either end the tables stop resolving, so the percentile stops too."""
        weak = score_lift("bench-press", 5.0, sex="male", bodyweight_kg=80.0)
        strong = score_lift("bench-press", 400.0, sex="male", bodyweight_kg=80.0)
        assert weak.percentile_estimate == LEVEL_PERCENTILES[0]
        assert strong.percentile_estimate == LEVEL_PERCENTILES[-1]

    def test_age_adjustment_lowers_the_bar_for_older_lifters(self) -> None:
        young = bands_for("bench-press", sex="male", bodyweight_kg=80, age=30)
        older = bands_for("bench-press", sex="male", bodyweight_kg=80, age=65)
        assert older.thresholds["intermediate"] < young.thresholds["intermediate"]
        assert older.age_factor < 1.0

    def test_added_weight_lift_carries_an_explanatory_note(self) -> None:
        score = score_lift("pull-ups", 20.0, sex="male", bodyweight_kg=80.0)
        assert score.metric == "added_kg"
        assert any("added to bodyweight" in note for note in score.notes)

    def test_unknown_lift_raises(self) -> None:
        with pytest.raises(StandardsNotAvailable):
            score_lift("not-a-lift", 100.0, sex="male", bodyweight_kg=80.0)


class TestExerciseMapping:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Bench Press (Barbell)", "bench-press"),
            ("Incline Bench Press (Barbell)", "incline-bench-press"),
            ("Bench Press (Dumbbell)", "dumbbell-bench-press"),
            ("Squat (Barbell)", "squat"),
            ("Front Squat", "front-squat"),
            ("Bulgarian Split Squat", "bulgarian-split-squat"),
            ("Deadlift (Barbell)", "deadlift"),
            ("Romanian Deadlift (Barbell)", "romanian-deadlift"),
            ("Sumo Deadlift", "sumo-deadlift"),
            ("Shoulder Press (Dumbbell)", "dumbbell-shoulder-press"),
            ("Overhead Press (Barbell)", "shoulder-press"),
            ("Bent Over Row (Barbell)", "bent-over-row"),
            ("Bent Over Row (Dumbbell)", "dumbbell-row"),
            ("Lat Pulldown (Cable)", "lat-pulldown"),
            ("Pull Up", "pull-ups"),
            ("Chin Up", "chin-ups"),
            ("Bicep Curl (Barbell)", "barbell-curl"),
            ("Bicep Curl (Dumbbell)", "dumbbell-curl"),
            ("Lateral Raise (Dumbbell)", "dumbbell-lateral-raise"),
            # Machine and cable variants have their own standards, so they must
            # not fall through to the free-weight lift.
            ("Lateral Raise (Machine)", "machine-lateral-raise"),
            ("Seated Shoulder Press (Machine)", "machine-shoulder-press"),
            ("Chest Press (Machine)", "chest-press"),
            ("Chest Fly (Machine)", "machine-chest-fly"),
            ("Rear Delt Reverse Fly (Machine)", "machine-reverse-fly"),
            ("Bicep Curl (Cable)", "cable-curl"),
            ("Preacher Curl (Barbell)", "preacher-curl"),
            ("Triceps Rope Pushdown", "tricep-rope-pushdown"),
            ("Triceps Pushdown", "tricep-pushdown"),
            ("Leg Press Horizontal (Machine)", "horizontal-leg-press"),
            ("Zercher Squat", "zercher-squat"),
            ("Back Extension (Machine)", "machine-back-extension"),
            ("Hip Abduction (Machine)", "hip-abduction"),
            ("Hip Adduction (Machine)", "hip-adduction"),
            ("Shrug (Dumbbell)", "dumbbell-shrug"),
            ("Standing Calf Raise (Dumbbell)", "dumbbell-calf-raise"),
            ("Seated Calf Raise", "seated-calf-raise"),
            ("Farmers Walk", "farmers-walk"),
            # A leg curl is not a biceps curl, and a wrist curl is not either.
            ("Lying Leg Curl (Machine)", "lying-leg-curl"),
            ("Seated Palms Up Wrist Curl", "wrist-curl"),
            ("Seated Wrist Extension (Barbell)", "reverse-wrist-curl"),
            ("Triceps Dip (Weighted)", "dips"),
        ],
    )
    def test_specific_variants_win_over_base_lifts(self, title: str, expected: str) -> None:
        assert resolve_lift(title) == expected

    def test_every_mapped_lift_exists_in_the_dataset(self) -> None:
        from hevy_coach.analytics.standards import load_exercise_map

        known = set(available_lifts())
        for rule in load_exercise_map()["rules"]:
            assert rule["lift"] in known, rule["lift"]

    @pytest.mark.parametrize(
        "title",
        [
            # Reps- and time-only movements: strengthlevel publishes no load
            # table for these, so there is nothing to benchmark against.
            "Sit Up (Weighted)",
            "Decline Crunch (Weighted)",
            "Leg Raise Parallel Bars",
            "Side Plank",
            # Cardio machines must not be mistaken for rows or presses.
            "Rowing Machine",
            "Treadmill",
        ],
    )
    def test_movements_without_a_load_standard_stay_unmapped(self, title: str) -> None:
        assert resolve_lift(title) is None

    def test_unknown_exercise_is_unmapped(self) -> None:
        assert resolve_lift("Sled Push") is None
