"""Score lifts against published strength standards.

The bundled dataset (``data/standards.json``, built by
``scripts/fetch_standards.py`` from strengthlevel.com) gives, per lift and sex,
the load at five levels - beginner, novice, intermediate, advanced, elite - across
a grid of bodyweights, plus an age curve.

Two things this module does that a plain table lookup does not:

* **Interpolates between bodyweight rows.** The tables step in 5 kg increments;
  an 82 kg lifter should not be scored as if they were 80.
* **Produces a continuous score**, not just a bucket. Landing at "intermediate"
  tells you little when the band spans 25 kg; "intermediate +0.6" tells you where
  in the band you are and makes progress visible between level changes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from hevy_coach.config import DATA_DIR, DumbbellLoad

LEVELS = ("beginner", "novice", "intermediate", "advanced", "elite")
LEVEL_INDEX = {name: i for i, name in enumerate(LEVELS)}

#: What the five level names mean at the source: the percentile of logged lifts
#: each one sits at ("beginner - stronger than 5% of lifters", and so on up).
#:
#: Worth keeping in view when reading a level, because the names oversell the
#: percentiles. The population is people who log lifts in a strength app, not
#: the general public, so the bottom band is *not* an untrained lifter - it is
#: the 5th percentile of an already self-selected group. A "beginner" bench of
#: 56 kg at 80 kg bodyweight is the bar to clear the weakest 5% of app users,
#: which is why standards built on other populations put the same lift a band
#: or two higher.
LEVEL_PERCENTILES = (5.0, 20.0, 50.0, 80.0, 95.0)

#: Lifts the source publishes as the weight of ONE dumbbell ("Dumbbell weights
#: are for one dumbbell"), for movements held with a pair - one in each hand.
#:
#: Hevy asks for the same thing, but a log that records the pair's combined
#: weight instead scores at double, which is enough to read "elite" on a
#: dumbbell bench sitting next to a "beginner" barbell bench.
#: ``Settings.dumbbell_load`` says which convention a log follows.
#:
#: Single-implement lifts are deliberately absent: a one-arm dumbbell row and a
#: goblet squat hold one weight, so there is no pair to halve. So is the farmers
#: walk - it is usually loaded with a trap bar or handles rather than dumbbells,
#: and the published basis was not confirmed.
PAIRED_DUMBBELL_LIFTS = frozenset(
    {
        "dumbbell-bench-press",
        "dumbbell-calf-raise",
        "dumbbell-curl",
        "dumbbell-fly",
        "dumbbell-lateral-raise",
        "dumbbell-lunge",
        "dumbbell-reverse-fly",
        "dumbbell-shoulder-press",
        "dumbbell-shrug",
        "hammer-curl",
        "incline-curl",
    }
)

Sex = Literal["male", "female"]


@dataclass(frozen=True)
class LevelBands:
    """The five level thresholds for one lifter at one lift, in kg."""

    lift: str
    name: str
    metric: str  # "kg" (load) or "added_kg" (load added to bodyweight)
    thresholds: dict[str, float]
    bodyweight_kg: float
    age_factor: float = 1.0

    def as_list(self) -> list[float]:
        return [self.thresholds[level] for level in LEVELS]


@dataclass
class LiftScore:
    """Where one lift sits against the standards."""

    lift: str
    name: str
    metric: str
    e1rm_kg: float
    bodyweight_kg: float
    level: str
    #: Position on a 0-4 scale: 0.0 = beginner, 2.0 = intermediate, 4.0 = elite.
    #: Below beginner is negative; above elite exceeds 4.
    level_score: float
    #: Percentile of logged lifts this load sits at, read off the source's own
    #: definition of the bands. Held flat outside beginner..elite, where the
    #: published tables stop resolving.
    percentile_estimate: float
    thresholds: dict[str, float]
    next_level: str | None
    kg_to_next_level: float | None
    #: e1RM divided by bodyweight - the classic ratio, kept for familiarity.
    ratio: float
    source: str
    notes: list[str] = field(default_factory=list)


class StandardsNotAvailable(LookupError):
    """No standards table covers this lift/sex combination."""


@lru_cache(maxsize=1)
def load_dataset() -> dict[str, Any]:
    path = DATA_DIR / "standards.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Build it with: uv run python scripts/fetch_standards.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_exercise_map() -> dict[str, Any]:
    return json.loads((DATA_DIR / "exercise_map.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _compiled_rules() -> list[tuple[str, list[re.Pattern[str]]]]:
    rules = []
    for rule in load_exercise_map()["rules"]:
        patterns = [re.compile(p, re.IGNORECASE) for p in rule["match"]]
        rules.append((rule["lift"], patterns))
    return rules


def resolve_lift(title: str, template_id: str | None = None) -> str | None:
    """Map a Hevy exercise onto a standards lift id, or None if unmapped."""
    overrides = load_exercise_map().get("overrides", {})
    if template_id and template_id in overrides:
        return overrides[template_id]  # may be null, meaning "never benchmark this"

    normalised = title.strip().lower()
    for lift, patterns in _compiled_rules():
        if any(p.search(normalised) for p in patterns):
            return lift
    return None


def metric_for(lift: str) -> str | None:
    """How a lift's thresholds are expressed: kg, added_kg, or None if unknown."""
    entry = load_dataset()["lifts"].get(lift)
    return entry["metric"] if entry else None


def available_lifts() -> dict[str, str]:
    """Lift id -> display name for everything in the dataset."""
    return {lift: entry["name"] for lift, entry in load_dataset()["lifts"].items()}


def per_dumbbell_load(lift: str, logged_kg: float, *, convention: DumbbellLoad) -> float:
    """Restate a logged load as the one-dumbbell figure the standards are in.

    A no-op unless the log records combined pair weight and the lift is held
    with a pair. e1RM formulas are linear in load, so halving the estimate is
    the same as halving every set that fed it.
    """
    if convention == "combined" and lift in PAIRED_DUMBBELL_LIFTS:
        return logged_kg / 2.0
    return logged_kg


def _interpolate(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation with flat extrapolation past either end.

    Extrapolating strength standards beyond the published bodyweight range would
    invent numbers, so the end rows are held constant instead.
    """
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            span = xs[i + 1] - xs[i]
            if span == 0:
                return ys[i]
            t = (x - xs[i]) / span
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def _age_factor(age_factors: dict[str, float], age: float | None) -> float:
    if not age_factors or age is None:
        return 1.0
    ages = sorted(float(a) for a in age_factors)
    values = [age_factors[str(int(a))] for a in ages]
    return _interpolate(ages, values, age)


def bands_for(
    lift: str,
    *,
    sex: Sex,
    bodyweight_kg: float,
    age: float | None = None,
) -> LevelBands:
    """Level thresholds for a given lifter, interpolated to their bodyweight."""
    dataset = load_dataset()
    entry = dataset["lifts"].get(lift)
    if entry is None:
        raise StandardsNotAvailable(f"no standards for lift {lift!r}")
    table = entry["sexes"].get(sex)
    if table is None:
        raise StandardsNotAvailable(f"no {sex} standards for lift {lift!r}")

    xs = table["bodyweights_kg"]
    factor = _age_factor(table.get("age_factors") or {}, age)

    thresholds = {
        level: round(_interpolate(xs, table["levels"][level], bodyweight_kg) * factor, 1)
        for level in LEVELS
    }
    return LevelBands(
        lift=lift,
        name=entry["name"],
        metric=entry.get("metric", "kg"),
        thresholds=thresholds,
        bodyweight_kg=bodyweight_kg,
        age_factor=round(factor, 4),
    )


def _level_score(value: float, thresholds: list[float]) -> float:
    """Map a load onto a continuous 0-4 scale across the five thresholds.

    Within a band the position is linear. Below beginner and above elite the
    slope of the nearest band is reused, so the score keeps moving instead of
    saturating - useful when you are just starting out or already very strong.
    """
    if value <= thresholds[0]:
        span = thresholds[1] - thresholds[0]
        return -((thresholds[0] - value) / span) if span > 0 else 0.0
    for i in range(len(thresholds) - 1):
        low, high = thresholds[i], thresholds[i + 1]
        if low <= value <= high:
            span = high - low
            return i + ((value - low) / span if span > 0 else 0.0)
    span = thresholds[-1] - thresholds[-2]
    return 4.0 + ((value - thresholds[-1]) / span if span > 0 else 0.0)


def _percentile(score: float) -> float:
    """Turn a 0-4 band position into the percentile the source itself publishes.

    The bands are not evenly spaced in percentile terms - 0 to 1 spans 15
    percentiles, 1 to 2 spans 30 - so rescaling the band index (``score / 4``)
    understates the middle of the distribution and overstates the top, which
    reported elite as the 100th percentile. Held flat past either end, because
    the tables stop resolving there.
    """
    return round(_interpolate([0.0, 1.0, 2.0, 3.0, 4.0], list(LEVEL_PERCENTILES), score), 1)


def score_lift(
    lift: str,
    e1rm_kg: float,
    *,
    sex: Sex,
    bodyweight_kg: float,
    age: float | None = None,
) -> LiftScore:
    """Place an estimated 1RM on the standards curve for this lifter."""
    bands = bands_for(lift, sex=sex, bodyweight_kg=bodyweight_kg, age=age)
    thresholds = bands.as_list()
    score = _level_score(e1rm_kg, thresholds)

    index = max(0, min(4, int(score)))
    level = LEVELS[index] if score >= 0 else "untrained"

    next_level: str | None = None
    kg_to_next: float | None = None
    if score < 4:
        next_index = max(0, index + 1 if score >= 0 else 0)
        next_level = LEVELS[min(next_index, 4)]
        kg_to_next = round(thresholds[LEVEL_INDEX[next_level]] - e1rm_kg, 1)

    notes: list[str] = []
    if bands.metric == "added_kg":
        notes.append(
            "Standards for this lift are expressed as weight added to bodyweight "
            "(negative means assisted), matching how Hevy logs it."
        )
    if bodyweight_kg <= min(load_dataset()["lifts"][lift]["sexes"][sex]["bodyweights_kg"]) or (
        bodyweight_kg >= max(load_dataset()["lifts"][lift]["sexes"][sex]["bodyweights_kg"])
    ):
        notes.append(
            f"Bodyweight {bodyweight_kg:g} kg is at or outside the published table range; "
            "the nearest row was used without extrapolating."
        )
    if bands.age_factor != 1.0:
        notes.append(f"Age adjustment applied (x{bands.age_factor:g}).")

    return LiftScore(
        lift=lift,
        name=bands.name,
        metric=bands.metric,
        e1rm_kg=round(e1rm_kg, 1),
        bodyweight_kg=bodyweight_kg,
        level=level,
        level_score=round(score, 2),
        percentile_estimate=_percentile(score),
        thresholds=bands.thresholds,
        next_level=next_level,
        kg_to_next_level=kg_to_next,
        ratio=round(e1rm_kg / bodyweight_kg, 2) if bodyweight_kg else 0.0,
        source=load_dataset()["lifts"][lift]["source"],
        notes=notes,
    )
