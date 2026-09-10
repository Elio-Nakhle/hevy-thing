"""Progression analysis: is a lift actually moving, and what is holding it back?

This is the part that turns a training log into something actionable. For each
exercise we fit a trend to its e1RM history, classify it, and flag the specific
patterns worth changing - stalls, regressions, exercises you have dropped, and
whatever the lifter's goal says is the variable that matters.

Some rules are goal-specific and read their thresholds from
``hevy_coach.goals``: weekly sets per muscle group is the hypertrophy question,
exposure to heavy load and frequency on the main lifts is the strength one.
Rules that apply to any goal - stalls, regressions, abandoned lifts, volume
swings - run regardless.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from hevy_coach import units
from hevy_coach.analytics import intensity, metrics
from hevy_coach.analytics.powerlifting import total_report
from hevy_coach.analytics.standards import per_dumbbell_load, resolve_lift, score_lift
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.goals import profile_for

Trend = Literal["progressing", "maintaining", "stalling", "regressing", "insufficient_data"]

# A lift needs this many sessions before a trend line means anything.
MIN_SESSIONS_FOR_TREND = 4

# Percent change per 30 days that separates the trend classes.
PROGRESS_THRESHOLD = 1.0
REGRESS_THRESHOLD = -1.0

# How far back the goal-specific checks look. Four weeks is long enough to
# smooth out one missed session and short enough to describe current training.
GOAL_WINDOW_DAYS = 28


def linear_trend(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares slope and intercept for (x, y) points.

    Returns ``(0.0, mean_y)`` when the x values do not vary, so a set of
    same-day sessions degrades to "flat" rather than dividing by zero.
    """
    n = len(points)
    if n == 0:
        return 0.0, 0.0
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    variance = sum((x - mean_x) ** 2 for x, _ in points)
    if variance == 0:
        return 0.0, mean_y
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = covariance / variance
    return slope, mean_y - slope * mean_x


@dataclass
class ExerciseTrend:
    template_id: str
    title: str
    sessions: int
    first_date: str
    last_date: str
    days_since_last: int
    first_e1rm_kg: float
    latest_e1rm_kg: float
    best_e1rm_kg: float
    #: kg per 30 days, from the least-squares fit.
    slope_kg_per_month: float
    change_pct_per_month: float
    trend: Trend
    #: Sessions since the best e1RM was set. High numbers mean a stall.
    sessions_since_best: int
    lift: str | None = None
    level: str | None = None
    level_score: float | None = None
    kg_to_next_level: float | None = None


def exercise_trends(
    db: Database,
    settings: Settings,
    *,
    days: int = 180,
    min_sessions: int = MIN_SESSIONS_FOR_TREND,
) -> list[ExerciseTrend]:
    """Trend one entry per exercise, newest activity first."""
    bodyweight = db.latest_bodyweight() or settings.bodyweight_kg
    now = datetime.now(UTC)
    results: list[ExerciseTrend] = []

    for summary in metrics.exercise_summaries(db, days=days):
        history = [
            point
            for point in metrics.exercise_history(db, summary.template_id, days=days)
            if point.best_e1rm_kg is not None
        ]
        if len(history) < min_sessions:
            continue

        origin = datetime.fromisoformat(history[0].date)
        points = [
            ((datetime.fromisoformat(p.date) - origin).days, p.best_e1rm_kg or 0.0)
            for p in history
        ]
        slope_per_day, _ = linear_trend(points)
        slope_per_month = slope_per_day * 30.0

        first = history[0].best_e1rm_kg or 0.0
        latest = history[-1].best_e1rm_kg or 0.0
        best = max(p.best_e1rm_kg or 0.0 for p in history)
        pct_per_month = (slope_per_month / first * 100.0) if first else 0.0

        if pct_per_month >= PROGRESS_THRESHOLD:
            trend: Trend = "progressing"
        elif pct_per_month <= REGRESS_THRESHOLD:
            trend = "regressing"
        elif abs(pct_per_month) < 0.25:
            trend = "stalling"
        else:
            trend = "maintaining"

        best_index = max(
            range(len(history)), key=lambda i: history[i].best_e1rm_kg or 0.0
        )
        last_date = datetime.fromisoformat(history[-1].date)

        entry = ExerciseTrend(
            template_id=summary.template_id,
            title=summary.title,
            sessions=len(history),
            first_date=history[0].date,
            last_date=history[-1].date,
            days_since_last=(now - last_date.replace(tzinfo=last_date.tzinfo or UTC)).days,
            first_e1rm_kg=round(first, 1),
            latest_e1rm_kg=round(latest, 1),
            best_e1rm_kg=round(best, 1),
            slope_kg_per_month=round(slope_per_month, 2),
            change_pct_per_month=round(pct_per_month, 2),
            trend=trend,
            sessions_since_best=len(history) - 1 - best_index,
        )

        lift = resolve_lift(summary.title, summary.template_id)
        if lift:
            try:
                score = score_lift(
                    lift,
                    per_dumbbell_load(lift, best, convention=settings.dumbbell_load),
                    sex=settings.sex,
                    bodyweight_kg=bodyweight,
                    age=settings.age,
                )
            except LookupError:
                pass
            else:
                entry.lift = lift
                entry.level = score.level
                entry.level_score = score.level_score
                entry.kg_to_next_level = score.kg_to_next_level

        results.append(entry)

    results.sort(key=lambda e: e.last_date, reverse=True)
    return results


@dataclass
class Insight:
    """One concrete, checkable observation about the training log."""

    kind: str
    severity: Literal["info", "suggestion", "warning"]
    title: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _strength_insights(db: Database, settings: Settings) -> list[Insight]:
    """Findings that only make sense for a strength or powerlifting goal.

    Volume answers "am I doing enough work"; these answer "is any of it heavy,
    and is it on the lifts that count". A log can look busy and contain no
    maximal-strength stimulus at all, which is invisible to every other rule.
    """
    goal = profile_for(settings.training_goal)
    found: list[Insight] = []

    if goal.min_heavy_sets_per_week is not None:
        report = intensity.intensity_report(db, settings, days=GOAL_WINDOW_DAYS)
        if report.scored_sets and report.heavy_sets_per_week < goal.min_heavy_sets_per_week:
            top = max((lift.top_percent for lift in report.lifts), default=0.0)
            found.append(
                Insight(
                    kind="low_heavy_exposure",
                    severity="warning",
                    title="Little training above 85% of your maxes",
                    detail=(
                        f"{report.heavy_sets} of {report.scored_sets} working sets in the "
                        f"last 4 weeks were at or above {report.heavy_pct:.0f}% "
                        f"({report.heavy_sets_per_week}/week against a target of "
                        f"{goal.min_heavy_sets_per_week:g}). The heaviest set on any lift "
                        f"was {top:.0f}%. A {goal.name} goal needs regular exposure to "
                        "loads that a hypertrophy rep range never reaches."
                    ),
                    evidence={
                        "heavy_sets": report.heavy_sets,
                        "heavy_sets_per_week": report.heavy_sets_per_week,
                        "scored_sets": report.scored_sets,
                        "heavy_pct": report.heavy_pct,
                        "top_percent": round(top, 1),
                    },
                )
            )

    if goal.min_main_lift_frequency is not None:
        for lift in intensity.main_lift_frequency(db, settings, days=GOAL_WINDOW_DAYS):
            if lift.sessions_per_week >= goal.min_main_lift_frequency:
                continue
            if lift.sessions == 0:
                detail = (
                    f"Not trained at all in the last 4 weeks. It is one of the lifts a "
                    f"{goal.name} goal is judged on."
                )
                severity: Literal["info", "suggestion", "warning"] = "warning"
            else:
                detail = (
                    f"{lift.sessions_per_week}/week over the last 4 weeks, against "
                    f"{goal.min_main_lift_frequency:g}/week for a {goal.name} goal. "
                    "Specificity is the main driver on the competition lifts."
                )
                severity = "suggestion"
            found.append(
                Insight(
                    kind="main_lift_frequency",
                    severity=severity,
                    title=f"{lift.title} is trained too rarely",
                    detail=detail,
                    evidence=asdict(lift),
                )
            )

    if goal.tracks_total:
        for ratio in total_report(db, settings).ratios:
            if ratio["verdict"] != "lagging":
                continue
            found.append(
                Insight(
                    kind="lift_ratio",
                    severity="info",
                    title=f"{ratio['title']} is low relative to your squat",
                    detail=(
                        f"It sits at {ratio['ratio']:.2f}x your squat; raw lifters usually "
                        f"land near {ratio['expected']:.2f}x. Worth a block of extra "
                        "frequency if you want the total to move."
                    ),
                    evidence=dict(ratio),
                )
            )

    return found


def insights(db: Database, settings: Settings, *, days: int = 180) -> list[Insight]:
    """Rule-based findings. These are the coach's evidence, not its opinions."""
    found: list[Insight] = []
    goal = profile_for(settings.training_goal)
    trends = exercise_trends(db, settings, days=days)

    # 1. Stalls and regressions on lifts still being trained.
    for trend in trends:
        if trend.days_since_last > 21 or trend.sessions < MIN_SESSIONS_FOR_TREND:
            continue
        if trend.trend == "regressing":
            found.append(
                Insight(
                    kind="regression",
                    severity="warning",
                    title=f"{trend.title} is trending down",
                    detail=(
                        f"e1RM is falling about "
                        f"{units.fmt(abs(trend.slope_kg_per_month), settings.units)}/month "
                        f"({trend.change_pct_per_month:.1f}%/month) across "
                        f"{trend.sessions} sessions. Best was "
                        f"{units.fmt(trend.best_e1rm_kg, settings.units)}, "
                        f"latest {units.fmt(trend.latest_e1rm_kg, settings.units)}."
                    ),
                    evidence=asdict(trend),
                )
            )
        elif trend.trend == "stalling" and trend.sessions_since_best >= 4:
            found.append(
                Insight(
                    kind="stall",
                    severity="suggestion",
                    title=f"{trend.title} has stalled",
                    detail=(
                        f"No new e1RM best in {trend.sessions_since_best} sessions and the "
                        f"trend is flat ({trend.change_pct_per_month:+.1f}%/month). "
                        "Worth changing a variable: rep range, frequency, or a deload."
                    ),
                    evidence=asdict(trend),
                )
            )

    # 2. Exercises dropped after establishing a history.
    for trend in trends:
        if 28 <= trend.days_since_last <= 120 and trend.sessions >= MIN_SESSIONS_FOR_TREND:
            found.append(
                Insight(
                    kind="abandoned",
                    severity="info",
                    title=f"{trend.title} has not been trained in {trend.days_since_last} days",
                    detail=(
                        f"You built {trend.sessions} sessions of history on it "
                        f"(best {units.fmt(trend.best_e1rm_kg, settings.units)}) "
                        "and then stopped."
                    ),
                    evidence=asdict(trend),
                )
            )

    # 3. Undertrained muscle groups. Only for goals that judge volume this way -
    #    a powerlifter's accessory set count is not the thing to optimise, and
    #    flagging every muscle group buries the findings that matter.
    if goal.low_weekly_sets is not None:
        for group in metrics.muscle_group_volume(db, days=GOAL_WINDOW_DAYS):
            if group["sets_per_week"] < goal.low_weekly_sets and group["muscle_group"] not in {
                "cardio",
                "other",
                "full_body",
            }:
                rationale = goal.volume_rationale.format(sets=goal.low_weekly_sets)
                found.append(
                    Insight(
                        kind="low_volume",
                        severity="suggestion",
                        title=f"Low weekly volume for {group['muscle_group'].replace('_', ' ')}",
                        detail=(
                            f"{group['sets_per_week']} working sets/week over the last 4 "
                            f"weeks. {rationale}."
                        ),
                        evidence=group,
                    )
                )

    # 3b. Goal-specific: heavy exposure, main-lift frequency and lift
    #     proportions. No-ops for a hypertrophy goal, whose profile leaves
    #     those thresholds unset.
    found.extend(_strength_insights(db, settings))

    # 4. Training frequency drift.
    weekly = metrics.weekly_volume(db, weeks=12)
    if len(weekly) >= 6:
        recent = weekly[-4:]
        earlier = weekly[-12:-4] or weekly[:-4]
        recent_avg = sum(w["volume_kg"] for w in recent) / len(recent)
        earlier_avg = sum(w["volume_kg"] for w in earlier) / len(earlier) if earlier else 0.0
        if earlier_avg > 0:
            delta = (recent_avg - earlier_avg) / earlier_avg * 100.0
            if delta <= -25:
                found.append(
                    Insight(
                        kind="volume_drop",
                        severity="warning",
                        title="Training volume has dropped sharply",
                        detail=(
                            "Last 4 weeks averaged "
                            f"{units.fmt(recent_avg, settings.units, 0, thousands=True)}"
                            "/week versus "
                            f"{units.fmt(earlier_avg, settings.units, 0, thousands=True)}"
                            f"/week before that ({delta:.0f}%)."
                        ),
                        evidence={"recent_avg": recent_avg, "earlier_avg": earlier_avg},
                    )
                )
            elif delta >= 60:
                found.append(
                    Insight(
                        kind="volume_spike",
                        severity="suggestion",
                        title="Training volume has spiked",
                        detail=(
                            "Last 4 weeks averaged "
                            f"{units.fmt(recent_avg, settings.units, 0, thousands=True)}"
                            "/week versus "
                            f"{units.fmt(earlier_avg, settings.units, 0, thousands=True)}"
                            f"/week before ({delta:+.0f}%). "
                            "Large jumps are a common precursor to a stall or injury."
                        ),
                        evidence={"recent_avg": recent_avg, "earlier_avg": earlier_avg},
                    )
                )

    # 5. Imbalances between paired movements against the standards.
    scored = [t for t in trends if t.level_score is not None]
    if len(scored) >= 2:
        strongest = max(scored, key=lambda t: t.level_score or 0)
        weakest = min(scored, key=lambda t: t.level_score or 0)
        gap = (strongest.level_score or 0) - (weakest.level_score or 0)
        if gap >= 1.0:
            found.append(
                Insight(
                    kind="imbalance",
                    severity="info",
                    title=f"{weakest.title} lags {strongest.title} by a full level",
                    detail=(
                        f"{strongest.title} sits at {strongest.level} "
                        f"({strongest.level_score:.2f}) while {weakest.title} is at "
                        f"{weakest.level} ({weakest.level_score:.2f}) on the same "
                        "bodyweight-adjusted scale."
                    ),
                    evidence={"strongest": asdict(strongest), "weakest": asdict(weakest)},
                )
            )

    severity_rank = {"warning": 0, "suggestion": 1, "info": 2}
    found.sort(key=lambda i: severity_rank[i.severity])
    return found
