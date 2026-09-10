"""Benchmark the whole training log against the strength standards."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hevy_coach.analytics import e1rm, metrics
from hevy_coach.analytics.standards import (
    LEVELS,
    PAIRED_DUMBBELL_LIFTS,
    LiftScore,
    StandardsNotAvailable,
    metric_for,
    per_dumbbell_load,
    resolve_lift,
    score_lift,
)
from hevy_coach.config import Settings
from hevy_coach.db import Database


@dataclass
class BenchmarkEntry:
    template_id: str
    title: str
    lift: str
    last_performed: str | None
    sessions: int
    score: dict[str, Any]
    #: Other logged exercises that map to the same standard and scored lower.
    #: Kept visible so a shadowed variant is explained rather than just missing.
    also_logged: list[str] = field(default_factory=list)


@dataclass
class BenchmarkReport:
    sex: str
    bodyweight_kg: float
    age: float | None
    bodyweight_source: str
    entries: list[BenchmarkEntry]
    unmapped: list[dict[str, Any]]
    #: Mean level score across benchmarked lifts - a single "how strong am I" number.
    overall_level_score: float | None
    overall_level: str | None
    #: Reasons to distrust the levels below, worst first. Empty when the inputs
    #: are all real.
    caveats: list[str] = field(default_factory=list)


def _best_e1rm(
    db: Database,
    summary: metrics.ExerciseSummary,
    lift: str,
    *,
    bodyweight: float,
    days: int | None,
) -> float | None:
    """The e1RM to score, in whatever unit this lift's standard is published in.

    Bodyweight movements need their own pass. Their standards are in load *added*
    to bodyweight, and Hevy leaves the weight empty for an unweighted rep - which
    :func:`metrics.exercise_summaries` reads as an unscoreable set, so pull-ups
    and dips would silently vanish from the benchmark.
    """
    if metric_for(lift) != "added_kg":
        return summary.best_e1rm_kg

    scores = [
        value
        for weight, reps, rpe in metrics.exercise_sets(db, summary.template_id, days=days)
        if (value := e1rm.added_load(weight, reps, bodyweight, rpe)) is not None
    ]
    return round(max(scores), 1) if scores else None


def benchmark(
    db: Database,
    settings: Settings,
    *,
    days: int | None = 365,
    min_sessions: int = 1,
) -> BenchmarkReport:
    """Score every mappable exercise, using each one's best e1RM in the window."""
    measured = db.latest_bodyweight()
    bodyweight = measured or settings.bodyweight_kg
    if measured:
        source = "measured"
    elif settings.bodyweight_is_default:
        source = "default"
    else:
        source = "configured"

    caveats: list[str] = []
    if source == "default":
        caveats.append(
            f"Every level below was scored at the placeholder bodyweight of "
            f"{bodyweight:g} kg - nobody has said what the lifter weighs and no body "
            f"measurement is logged. The standards are indexed on bodyweight, so this "
            f"is the single biggest thing skewing the classifications: fill in the "
            f"lifter profile (Settings, or BODYWEIGHT_KG in .env) and re-read the report."
        )

    # One standard, potentially several logged exercises: a V-grip and a bar-grip
    # cable row both score against `seated-cable-row`. Emitting a row each gave
    # one lift two contradictory levels and skewed the overall mean toward
    # whichever variant was logged more often, so only the strongest is kept.
    strongest: dict[str, BenchmarkEntry] = {}
    unmapped: list[dict[str, Any]] = []

    for summary in metrics.exercise_summaries(db, days=days):
        if summary.sessions < min_sessions:
            continue

        lift = resolve_lift(summary.title, summary.template_id)
        if not lift:
            if summary.best_e1rm_kg is None:
                continue
            unmapped.append(
                {
                    "template_id": summary.template_id,
                    "title": summary.title,
                    "sessions": summary.sessions,
                    "best_e1rm_kg": summary.best_e1rm_kg,
                }
            )
            continue

        best = _best_e1rm(db, summary, lift, bodyweight=bodyweight, days=days)
        if best is None:
            continue
        best = per_dumbbell_load(lift, best, convention=settings.dumbbell_load)

        try:
            score: LiftScore = score_lift(
                lift,
                best,
                sex=settings.sex,
                bodyweight_kg=bodyweight,
                age=settings.age,
            )
        except StandardsNotAvailable:
            unmapped.append(
                {
                    "template_id": summary.template_id,
                    "title": summary.title,
                    "sessions": summary.sessions,
                    "reason": f"no standards table for {lift}/{settings.sex}",
                }
            )
            continue

        scored = asdict(score)
        if settings.dumbbell_load == "combined" and lift in PAIRED_DUMBBELL_LIFTS:
            scored["notes"].append(
                "Halved to one dumbbell, which is what the standard is published in, "
                "because DUMBBELL_LOAD=combined says this log records the pair's total."
            )

        entry = BenchmarkEntry(
            template_id=summary.template_id,
            title=summary.title,
            lift=lift,
            last_performed=summary.last_performed,
            sessions=summary.sessions,
            score=scored,
        )
        incumbent = strongest.get(lift)
        if incumbent is None:
            strongest[lift] = entry
        elif entry.score["level_score"] > incumbent.score["level_score"]:
            entry.also_logged = [*incumbent.also_logged, incumbent.title]
            strongest[lift] = entry
        else:
            incumbent.also_logged.append(entry.title)

    entries = sorted(strongest.values(), key=lambda e: e.score["level_score"], reverse=True)
    unmapped.sort(key=lambda item: item.get("sessions", 0), reverse=True)

    overall = (
        sum(e.score["level_score"] for e in entries) / len(entries) if entries else None
    )
    overall_level = (
        LEVELS[max(0, min(4, int(overall)))] if overall is not None and overall >= 0 else None
    )

    return BenchmarkReport(
        sex=settings.sex,
        bodyweight_kg=bodyweight,
        age=round(settings.age, 1) if settings.age else None,
        bodyweight_source=source,
        entries=entries,
        unmapped=unmapped[:25],
        overall_level_score=round(overall, 2) if overall is not None else None,
        overall_level=overall_level,
        caveats=caveats,
    )
