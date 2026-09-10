"""Tests for the competition total and DOTS.

The scoping of DOTS gets most of the attention. It is the kind of bug that
cannot be caught by looking at the output: a general-strength total run through
the coefficients produces a plausible three-figure number that is simply not a
DOTS score, and it reads about forty points high.
"""

from __future__ import annotations

import pytest

from hevy_coach.analytics.powerlifting import DOTS_LIFTS, dots, total_report
from hevy_coach.config import Settings
from hevy_coach.db import Database


def _goal(settings: Settings, goal: str) -> Settings:
    return settings.model_copy(update={"training_goal": goal})


# -- the coefficient --------------------------------------------------------


def test_dots_scores_a_total() -> None:
    """~400 is a strong raw lifter, which anchors the scale."""
    score = dots(400.0, 82.0, "male")

    assert score is not None
    assert 200 < score < 350


def test_dots_rises_with_the_total_and_falls_with_bodyweight() -> None:
    light = dots(400.0, 70.0, "male")
    heavy = dots(400.0, 110.0, "male")
    stronger = dots(500.0, 70.0, "male")

    assert light and heavy and stronger
    assert light > heavy
    assert stronger > light


@pytest.mark.parametrize("total", [0.0, -10.0])
def test_dots_refuses_a_non_total(total: float) -> None:
    assert dots(total, 82.0, "male") is None


def test_dots_needs_a_sex_it_has_coefficients_for() -> None:
    assert dots(400.0, 82.0, "other") is None


def test_bodyweight_outside_the_fitted_range_is_clamped(
    db: Database, settings: Settings
) -> None:
    """The quartic misbehaves outside the range it was fitted on, so the report
    says the number was clamped rather than quietly returning nonsense."""
    heavy = _goal(settings.model_copy(update={"bodyweight_kg": 250.0}), "powerlifting")

    report = total_report(db, heavy)

    assert report.bodyweight_clamped is True
    assert report.dots is not None


# -- what a goal totals -----------------------------------------------------


def test_hypertrophy_totals_nothing(db: Database, settings: Settings) -> None:
    report = total_report(db, _goal(settings, "hypertrophy"))

    assert report.tracks_total is False
    assert report.total_kg == 0
    assert report.entries == []


def test_powerlifting_totals_the_competition_three(
    db: Database, settings: Settings
) -> None:
    report = total_report(db, _goal(settings, "powerlifting"))

    assert report.tracks_total is True
    assert [entry.lift for entry in report.entries] == list(DOTS_LIFTS)
    assert report.total_kg == pytest.approx(
        sum(entry.e1rm_kg for entry in report.entries), abs=0.1
    )
    assert report.dots is not None
    # Nothing else is in the total, so the two agree.
    assert report.dots_total_kg == pytest.approx(report.total_kg, abs=0.1)


def test_general_strength_totals_four_lifts(db: Database, settings: Settings) -> None:
    report = total_report(db, _goal(settings, "strength"))

    assert [entry.lift for entry in report.entries] == [
        "squat",
        "bench-press",
        "deadlift",
        "shoulder-press",
    ]
    assert report.total_kg > report.dots_total_kg  # type: ignore[operator]


# -- the bug ----------------------------------------------------------------


def test_dots_ignores_lifts_it_was_not_fitted_on(db: Database, settings: Settings) -> None:
    """The regression. A general-strength total includes an overhead press; the
    coefficients were fitted to competition squat+bench+deadlift totals. Scoring
    the four-lift total inflated the same lifter by about forty points."""
    powerlifting = total_report(db, _goal(settings, "powerlifting"))
    strength = total_report(db, _goal(settings, "strength"))

    # Same lifter, same three lifts, so the same score - whatever else the goal
    # chooses to add up.
    assert strength.dots == powerlifting.dots
    assert strength.dots_total_kg == powerlifting.dots_total_kg
    assert strength.total_kg != strength.dots_total_kg


def test_a_missing_competition_lift_means_no_dots(
    empty_db: Database, settings: Settings
) -> None:
    """A partial total would flatter, so there is no score and the report says
    which lift is missing."""
    report = total_report(empty_db, _goal(settings, "powerlifting"))

    assert report.dots is None
    assert report.dots_total_kg is None
    assert sorted(report.dots_missing) == sorted(DOTS_LIFTS)


# -- the breakdown ----------------------------------------------------------


def test_shares_add_up(db: Database, settings: Settings) -> None:
    report = total_report(db, _goal(settings, "powerlifting"))

    assert sum(entry.share for entry in report.entries) == pytest.approx(100.0, abs=0.5)


def test_ratios_compare_each_lift_with_the_squat(
    db: Database, settings: Settings
) -> None:
    report = total_report(db, _goal(settings, "powerlifting"))

    lifts = {ratio["lift"] for ratio in report.ratios}
    assert lifts == {"bench-press", "deadlift"}
    assert all(ratio["verdict"] in {"lagging", "leading", "typical"} for ratio in report.ratios)


def test_no_ratios_without_a_squat(empty_db: Database, settings: Settings) -> None:
    assert total_report(empty_db, _goal(settings, "powerlifting")).ratios == []
