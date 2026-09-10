"""The competition total, and what it is worth for a lifter of this size.

Powerlifting has one headline number - squat plus bench plus deadlift - and one
way to compare it across bodyweights: a coefficient. This uses DOTS, which
replaced Wilks as the IPF-adjacent standard because it is a single polynomial
fitted to modern raw data rather than an equipped-era curve with separate tables.

The total here is built from estimated 1RMs, not competition attempts, so it
is a training number: an e1RM from a set of five is an estimate that flatters a
lifter who never handles heavy singles. It answers "where is my training total
now", not "what would I total on the platform".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hevy_coach.analytics import metrics
from hevy_coach.analytics.standards import resolve_lift
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.goals import profile_for

#: DOTS polynomial coefficients, by sex. Denominator is a quartic in bodyweight.
DOTS_COEFFICIENTS = {
    "male": (-0.000001093, 0.0007391293, -0.1918759221, 24.0900756, -307.75076),
    "female": (-0.0000010706, 0.0005158568, -0.1126655495, 13.6175032, -57.96288),
}

#: The fit is only meaningful across the range it was built on; outside it the
#: quartic misbehaves, so bodyweight is clamped and the report says so.
DOTS_RANGE = {"male": (40.0, 210.0), "female": (40.0, 150.0)}

#: Rough raw-lifter proportions relative to the squat. Wide tolerances - these
#: exist to catch a lift that is genuinely lagging, not to police leverages.
EXPECTED_RATIOS = {"bench-press": 0.75, "deadlift": 1.2}
RATIO_TOLERANCE = 0.15


def dots(total_kg: float, bodyweight_kg: float, sex: str) -> float | None:
    """DOTS score for a total. Higher is better; ~400 is a strong raw lifter."""
    coefficients = DOTS_COEFFICIENTS.get(sex)
    if coefficients is None or total_kg <= 0:
        return None
    low, high = DOTS_RANGE[sex]
    weight = min(max(bodyweight_kg, low), high)
    a, b, c, d, e = coefficients
    denominator = a * weight**4 + b * weight**3 + c * weight**2 + d * weight + e
    if denominator <= 0:
        return None
    return round(total_kg * 500.0 / denominator, 1)


@dataclass
class TotalEntry:
    lift: str
    title: str
    template_id: str
    e1rm_kg: float
    last_performed: str | None
    sessions: int
    #: Share of the total, as a percentage.
    share: float


@dataclass
class TotalReport:
    goal: str
    sex: str
    bodyweight_kg: float
    bodyweight_clamped: bool
    #: Sum of the best e1RM for each main lift the goal names.
    total_kg: float
    dots: float | None
    entries: list[TotalEntry] = field(default_factory=list)
    #: Main lifts the goal names that do not appear in the log at all.
    missing: list[str] = field(default_factory=list)
    #: Human-readable observations about lift proportions.
    ratios: list[dict[str, object]] = field(default_factory=list)


def total_report(db: Database, settings: Settings, *, days: int | None = 365) -> TotalReport:
    """Best e1RM per main lift, their total, and how they sit against each other."""
    profile = profile_for(settings.training_goal)
    bodyweight = db.latest_bodyweight() or settings.bodyweight_kg
    low, high = DOTS_RANGE.get(settings.sex, (0.0, 1e9))

    # Several exercises can map to one lift (barbell and dumbbell bench both map
    # to their own lifts, but a smith squat and a back squat can collide), so
    # keep the strongest per lift.
    best: dict[str, TotalEntry] = {}
    for summary in metrics.exercise_summaries(db, days=days):
        if summary.best_e1rm_kg is None:
            continue
        lift = resolve_lift(summary.title, summary.template_id)
        if lift not in profile.main_lifts:
            continue
        current = best.get(lift or "")
        if current is None or summary.best_e1rm_kg > current.e1rm_kg:
            best[lift or ""] = TotalEntry(
                lift=lift or "",
                title=summary.title,
                template_id=summary.template_id,
                e1rm_kg=summary.best_e1rm_kg,
                last_performed=summary.last_performed,
                sessions=summary.sessions,
                share=0.0,
            )

    total = round(sum(entry.e1rm_kg for entry in best.values()), 1)
    for entry in best.values():
        entry.share = round(entry.e1rm_kg / total * 100.0, 1) if total else 0.0

    entries = [best[lift] for lift in profile.main_lifts if lift in best]
    missing = [lift for lift in profile.main_lifts if lift not in best]

    return TotalReport(
        goal=profile.name,
        sex=settings.sex,
        bodyweight_kg=bodyweight,
        bodyweight_clamped=not (low <= bodyweight <= high),
        total_kg=total,
        # Only a complete total is comparable; a partial one would flatter.
        dots=dots(total, bodyweight, settings.sex) if total and not missing else None,
        entries=entries,
        missing=missing,
        ratios=_ratios(best),
    )


def _ratios(best: dict[str, TotalEntry]) -> list[dict[str, object]]:
    """How each lift sits against the squat, for goals that have one."""
    squat = best.get("squat")
    if squat is None or squat.e1rm_kg <= 0:
        return []

    out: list[dict[str, object]] = []
    for lift, expected in EXPECTED_RATIOS.items():
        entry = best.get(lift)
        if entry is None:
            continue
        ratio = entry.e1rm_kg / squat.e1rm_kg
        if ratio < expected - RATIO_TOLERANCE:
            verdict = "lagging"
        elif ratio > expected + RATIO_TOLERANCE:
            verdict = "leading"
        else:
            verdict = "typical"
        out.append(
            {
                "lift": lift,
                "title": entry.title,
                "ratio": round(ratio, 2),
                "expected": expected,
                "verdict": verdict,
            }
        )
    return out
