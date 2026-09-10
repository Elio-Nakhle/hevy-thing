"""Training goals.

The same log means different things depending on what it is for. Eight working
sets a week for a muscle group is thin for hypertrophy and beside the point for
a powerlifter, whose limiting variable is exposure to heavy load rather than
accumulated sets. Rather than scatter `if goal ==` through the analytics, each
goal is one profile of thresholds, and the rules read from it.

Thresholds are deliberately conservative: they exist to catch a log that has
drifted away from what the lifter says they are training for, not to prescribe a
programme.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Goal = Literal["hypertrophy", "strength", "powerlifting"]

#: Fraction of a lift's estimated 1RM at or above which a set trains maximal
#: strength rather than work capacity. 85% is the usual floor for "heavy".
HEAVY_PCT = 85.0


@dataclass(frozen=True)
class GoalProfile:
    name: str
    #: One line for the UI and the coach's profile block.
    summary: str

    #: Working sets per muscle group per week below which volume is flagged.
    #: None disables the check - a powerlifter's accessory volume is not the
    #: thing to optimise, and flagging it buries the findings that matter.
    low_weekly_sets: int | None
    #: Why that number, in the insight's own words.
    volume_rationale: str

    #: Sets at or above HEAVY_PCT per week, across all lifts, below which the
    #: log is not actually training maximal strength. None disables the check.
    min_heavy_sets_per_week: float | None
    #: Sessions per week for each main lift, below which it is being neglected.
    min_main_lift_frequency: float | None
    #: The lifts a goal is judged on, as lift ids from the standards dataset.
    main_lifts: tuple[str, ...]
    #: Whether the total of the main lifts is a headline number for this goal.
    tracks_total: bool


HYPERTROPHY = GoalProfile(
    name="hypertrophy",
    summary="Muscle growth: weekly volume per muscle group is the variable to watch.",
    low_weekly_sets=8,
    volume_rationale="Most hypertrophy guidance puts the productive range above {sets}",
    min_heavy_sets_per_week=None,
    min_main_lift_frequency=None,
    main_lifts=(),
    tracks_total=False,
)

STRENGTH = GoalProfile(
    name="strength",
    summary="General strength: heavy exposure on the main lifts, volume as support.",
    # Still worth flagging a muscle group that has fallen off entirely, but at a
    # floor that does not fire on every accessory.
    low_weekly_sets=4,
    volume_rationale="Even as support work, {sets} sets/week is thin",
    min_heavy_sets_per_week=3.0,
    min_main_lift_frequency=0.75,
    main_lifts=("squat", "bench-press", "deadlift", "shoulder-press"),
    tracks_total=True,
)

POWERLIFTING = GoalProfile(
    name="powerlifting",
    summary="Squat, bench and deadlift: total, heavy exposure and specificity.",
    low_weekly_sets=None,
    volume_rationale="",
    min_heavy_sets_per_week=4.0,
    min_main_lift_frequency=1.5,
    main_lifts=("squat", "bench-press", "deadlift"),
    tracks_total=True,
)

PROFILES: dict[str, GoalProfile] = {
    profile.name: profile for profile in (HYPERTROPHY, STRENGTH, POWERLIFTING)
}


def profile_for(goal: Goal) -> GoalProfile:
    return PROFILES[goal]
