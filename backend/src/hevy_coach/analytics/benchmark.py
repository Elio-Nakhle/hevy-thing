"""Benchmark the whole training log against the strength standards."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hevy_coach.analytics import e1rm, metrics
from hevy_coach.analytics.standards import (
    LEVELS,
    LiftScore,
    StandardsNotAvailable,
    metric_for,
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
    source = "measured" if measured else "configured"

    entries: list[BenchmarkEntry] = []
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

        entries.append(
            BenchmarkEntry(
                template_id=summary.template_id,
                title=summary.title,
                lift=lift,
                last_performed=summary.last_performed,
                sessions=summary.sessions,
                score=asdict(score),
            )
        )

    entries.sort(key=lambda e: e.score["level_score"], reverse=True)
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
    )
