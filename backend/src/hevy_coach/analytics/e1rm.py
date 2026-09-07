"""Estimated one-rep max.

Everything downstream - strength standards, progression trends, PR detection -
needs a single number per set that is comparable across rep ranges. That number
is the estimated 1RM (e1RM).

Formula choice matters more than people assume. Epley is optimistic at high
reps, Brzycki breaks down past ~12 reps (its denominator approaches zero at 37
reps). We default to Epley but clamp the rep range we trust, and expose Brzycki
and an RPE-based estimate for comparison.
"""

from __future__ import annotations

from typing import Literal

Formula = Literal["epley", "brzycki", "rpe"]

# Beyond this, a 1RM estimate says more about work capacity than maximal strength.
MAX_TRUSTED_REPS = 12

# Reps-in-reserve -> fraction of 1RM, for a given number of reps performed.
# Derived from the standard RPE/RIR load chart used in RTS-style programming.
_RIR_TABLE: dict[int, dict[int, float]] = {
    # reps: {rir: %1RM}
    1: {0: 1.000, 1: 0.955, 2: 0.922, 3: 0.892, 4: 0.863},
    2: {0: 0.955, 1: 0.922, 2: 0.892, 3: 0.863, 4: 0.837},
    3: {0: 0.922, 1: 0.892, 2: 0.863, 3: 0.837, 4: 0.811},
    4: {0: 0.892, 1: 0.863, 2: 0.837, 3: 0.811, 4: 0.786},
    5: {0: 0.863, 1: 0.837, 2: 0.811, 3: 0.786, 4: 0.762},
    6: {0: 0.837, 1: 0.811, 2: 0.786, 3: 0.762, 4: 0.739},
    7: {0: 0.811, 1: 0.786, 2: 0.762, 3: 0.739, 4: 0.707},
    8: {0: 0.786, 1: 0.762, 2: 0.739, 3: 0.707, 4: 0.680},
    9: {0: 0.762, 1: 0.739, 2: 0.707, 3: 0.680, 4: 0.653},
    10: {0: 0.739, 1: 0.707, 2: 0.680, 3: 0.653, 4: 0.626},
    11: {0: 0.707, 1: 0.680, 2: 0.653, 3: 0.626, 4: 0.599},
    12: {0: 0.680, 1: 0.653, 2: 0.626, 3: 0.599, 4: 0.572},
}


def epley(weight: float, reps: int) -> float:
    """Epley: ``w * (1 + reps/30)``. The most common gym-calculator default."""
    return weight * (1.0 + reps / 30.0)


def brzycki(weight: float, reps: int) -> float:
    """Brzycki: ``w * 36 / (37 - reps)``. Undefined at 37 reps, so it is clamped."""
    return weight * 36.0 / (37.0 - min(reps, 36))


def from_rpe(weight: float, reps: int, rpe: float) -> float | None:
    """Estimate 1RM from load, reps and RPE.

    RPE 10 means zero reps in reserve, RPE 9 means one, and so on. This is the
    most accurate of the three when RPE is logged honestly, because it uses the
    lifter's own report of proximity to failure instead of assuming every set
    was taken to failure.
    """
    rir = round(10.0 - rpe)
    if reps < 1 or reps > 12 or not 0 <= rir <= 4:
        return None
    fraction = _RIR_TABLE[reps][rir]
    return weight / fraction


def estimate(
    weight: float | None,
    reps: int | None,
    rpe: float | None = None,
    *,
    formula: Formula = "epley",
) -> float | None:
    """Best-effort e1RM for one set, or None when the set cannot be scored.

    Returns None for warm-up-shaped data (no reps), bodyweight-only sets that
    carry no load, and rep counts too high to extrapolate from. Note that a
    ``weight`` of exactly 0 is meaningful for assisted/bodyweight movements, so
    only ``None`` is rejected.
    """
    if weight is None or reps is None or reps < 1:
        return None
    if reps > MAX_TRUSTED_REPS:
        return None

    if formula == "rpe" and rpe is not None:
        rpe_estimate = from_rpe(weight, reps, rpe)
        if rpe_estimate is not None:
            return rpe_estimate
        # Fall through to Epley when the RPE is out of table range.
    if formula == "brzycki":
        return brzycki(weight, reps)
    return epley(weight, reps)


def added_load(
    added_kg: float | None,
    reps: int | None,
    bodyweight_kg: float,
    rpe: float | None = None,
    *,
    formula: Formula = "epley",
) -> float | None:
    """e1RM for a bodyweight movement, expressed as load *added* to bodyweight.

    Hevy records ``weight_kg`` on pull-ups, chin-ups and dips as load added to
    bodyweight - negative when assisted, and empty for an unweighted rep, which
    means +0 kg rather than missing data. The strength standards for these lifts
    are published the same way.

    Estimating a 1RM has to work on the total load actually being moved, so
    bodyweight goes into the formula and comes back out of the result. Eight dips
    at +20 kg for an 80 kg lifter is a 1RM of roughly +27 kg, not the +25 kg you
    get by feeding the added weight to Epley on its own - and ten unweighted
    pull-ups score +27 kg instead of dropping out of the benchmark entirely.
    """
    if reps is None or bodyweight_kg <= 0:
        return None
    total = estimate(bodyweight_kg + (added_kg or 0.0), reps, rpe, formula=formula)
    return None if total is None else total - bodyweight_kg


def best_of(
    sets: list[tuple[float | None, int | None, float | None]],
    *,
    formula: Formula = "epley",
) -> float | None:
    """Highest e1RM across ``(weight, reps, rpe)`` triples."""
    values = [e for s in sets if (e := estimate(s[0], s[1], s[2], formula=formula)) is not None]
    return max(values) if values else None
