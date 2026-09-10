"""How heavy the training actually is.

Every other metric in this project measures *how much* - sets, reps, tonnage.
None of them can tell a set of five at 90% from a set of five at 60%, which is
the difference between training maximal strength and training work capacity. A
powerlifter's log looks thin by volume and a bodybuilder's looks light by
intensity; neither is a problem, but you cannot see which is which without this.

Load is expressed as a percentage of the exercise's own best estimated 1RM in
the window, so it is self-calibrating: no configured maxes to keep up to date,
and a lift that gets stronger raises its own bar.

Bodyweight movements are excluded. Hevy logs their weight as load *added* to
bodyweight, so a percentage of it is meaningless - +5 kg on a dip is not 5% of
anything.

A set counts as heavy only if it is both above the threshold *and* inside the
trusted rep range. Both halves are load-bearing: a set of twenty is not maximal
strength work whatever the bar says, and when a lift's heaviest sets are all
high-rep the reference e1RM comes from lighter sets and the percentage can read
above 100 - which is a sign the estimate is understated, not that the lifter is
grinding singles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hevy_coach.analytics import e1rm, metrics
from hevy_coach.analytics.standards import metric_for, resolve_lift
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.goals import HEAVY_PCT, profile_for

#: Lower bound (inclusive) and label for each intensity band.
BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "90%+"),
    (80.0, "80-90%"),
    (70.0, "70-80%"),
    (60.0, "60-70%"),
    (0.0, "<60%"),
)

#: Lower bound (inclusive) and label for each rep band.
REP_BANDS: tuple[tuple[int, str], ...] = (
    (13, "13+"),
    (7, "7-12"),
    (4, "4-6"),
    (1, "1-3"),
)


@dataclass
class Band:
    band: str
    sets: int
    percent: float


@dataclass
class LiftIntensity:
    """One exercise's heaviest work in the window."""

    template_id: str
    title: str
    lift: str | None
    sets: int
    heavy_sets: int
    heavy_sets_per_week: float
    #: Heaviest set as a percentage of the reference, over trusted-rep sets only.
    top_percent: float
    best_e1rm_kg: float
    sessions_per_week: float


@dataclass
class IntensityReport:
    days: int
    weeks: float
    #: Working sets that could be placed on an intensity scale.
    scored_sets: int
    #: Working sets excluded for having no load, or load that is not absolute.
    unscored_sets: int
    heavy_pct: float
    heavy_sets: int
    heavy_sets_per_week: float
    #: Share of scored sets at or above `heavy_pct`.
    heavy_share: float
    bands: list[Band] = field(default_factory=list)
    rep_bands: list[Band] = field(default_factory=list)
    lifts: list[LiftIntensity] = field(default_factory=list)


def _band(value: float, bands: tuple[tuple[Any, str], ...]) -> str:
    for lower, label in bands:
        if value >= lower:
            return label
    return bands[-1][1]


def intensity_report(
    db: Database,
    settings: Settings,
    *,
    days: int = 56,
    heavy_pct: float = HEAVY_PCT,
) -> IntensityReport:
    """Distribution of working sets by load and by reps, plus per-lift heavy work."""
    weeks = max(days / 7.0, 1.0)
    summaries = {s.template_id: s for s in metrics.exercise_summaries(db, days=days)}

    band_counts: dict[str, int] = {label: 0 for _, label in BANDS}
    rep_counts: dict[str, int] = {label: 0 for _, label in REP_BANDS}
    per_lift: dict[str, dict[str, Any]] = {}
    scored = 0
    unscored = 0
    heavy = 0

    for template_id, summary in summaries.items():
        reference = summary.best_e1rm_kg
        # A bodyweight lift's load is added weight, so it has no percentage.
        lift = resolve_lift(summary.title, template_id)
        if not reference or (lift and metric_for(lift) == "added_kg"):
            unscored += summary.sets
            continue

        entry = per_lift.setdefault(
            template_id,
            {
                "title": summary.title,
                "lift": lift,
                "sets": 0,
                "heavy": 0,
                "top": 0.0,
                "best": reference,
                "sessions": summary.sessions,
            },
        )

        for weight, reps, _ in metrics.exercise_sets(db, template_id, days=days):
            if weight is None or not reps:
                unscored += 1
                continue
            percent = weight / reference * 100.0
            band_counts[_band(percent, BANDS)] += 1
            rep_counts[_band(reps, REP_BANDS)] += 1
            scored += 1
            entry["sets"] += 1

            # Above the trusted rep range the percentage says more about the
            # reference being understated than about how heavy the set was.
            if reps > e1rm.MAX_TRUSTED_REPS:
                continue
            entry["top"] = max(entry["top"], percent)
            if percent >= heavy_pct:
                heavy += 1
                entry["heavy"] += 1

    lifts = sorted(
        (
            LiftIntensity(
                template_id=template_id,
                title=entry["title"],
                lift=entry["lift"],
                sets=entry["sets"],
                heavy_sets=entry["heavy"],
                heavy_sets_per_week=round(entry["heavy"] / weeks, 2),
                top_percent=round(entry["top"], 1),
                best_e1rm_kg=round(entry["best"], 1),
                sessions_per_week=round(entry["sessions"] / weeks, 2),
            )
            for template_id, entry in per_lift.items()
            if entry["sets"]
        ),
        key=lambda item: (item.heavy_sets, item.top_percent),
        reverse=True,
    )

    return IntensityReport(
        days=days,
        weeks=round(weeks, 1),
        scored_sets=scored,
        unscored_sets=unscored,
        heavy_pct=heavy_pct,
        heavy_sets=heavy,
        heavy_sets_per_week=round(heavy / weeks, 2),
        heavy_share=round(heavy / scored * 100.0, 1) if scored else 0.0,
        bands=[
            Band(label, band_counts[label], round(band_counts[label] / scored * 100, 1))
            for _, label in BANDS
        ]
        if scored
        else [],
        rep_bands=[
            Band(label, rep_counts[label], round(rep_counts[label] / scored * 100, 1))
            for _, label in REP_BANDS
        ]
        if scored
        else [],
        lifts=lifts,
    )


@dataclass
class MainLiftFrequency:
    lift: str
    title: str
    template_id: str | None
    sessions: int
    sessions_per_week: float
    best_e1rm_kg: float | None
    heavy_sets_per_week: float


def main_lift_frequency(
    db: Database, settings: Settings, *, days: int = 56
) -> list[MainLiftFrequency]:
    """How often each of the goal's main lifts is actually trained.

    A lift the goal names but that never appears in the log is returned with
    zero sessions - the absence is the finding.
    """
    profile = profile_for(settings.training_goal)
    if not profile.main_lifts:
        return []

    weeks = max(days / 7.0, 1.0)
    report = {
        item.lift: item
        for item in intensity_report(db, settings, days=days).lifts
        if item.lift
    }

    results = []
    for lift in profile.main_lifts:
        found = report.get(lift)
        results.append(
            MainLiftFrequency(
                lift=lift,
                title=found.title if found else lift.replace("-", " ").title(),
                template_id=found.template_id if found else None,
                sessions=round(found.sessions_per_week * weeks) if found else 0,
                sessions_per_week=found.sessions_per_week if found else 0.0,
                best_e1rm_kg=found.best_e1rm_kg if found else None,
                heavy_sets_per_week=found.heavy_sets_per_week if found else 0.0,
            )
        )
    return results
