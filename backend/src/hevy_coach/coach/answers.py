"""Questions this project can answer without a model.

Some of what people ask the coach is not a judgement call, it is a lookup the
analytics already do: whether the volume is spread across the muscle groups the
goal cares about, whether one lift is moving, which lift is furthest behind the
standards and what to do with it next session. Every number in those answers
comes from the same functions that serve `/api/volume/muscle-groups`,
`progression.exercise_trends` and `session.recommend` - the pages have shown
them for months. Paying a model to read them back is the most expensive way to
get an answer that was already computed.

So these run first, cost nothing, and decline the moment a question wants more
than a lookup. Declining is the normal case and the model handles it: a matcher
that fires on "should I change my split" would be worse than no matcher at all.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from hevy_coach import units
from hevy_coach.analytics import metrics, progression, session
from hevy_coach.analytics.benchmark import benchmark
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.goals import PROFILES

#: Words that mean the question has outgrown a lookup. A question carrying any
#: of these goes to the model even when it also matches a pattern below - a
#: half-answer to "is my volume balanced and should I change my split" is worse
#: than no answer, because the user cannot see which half was ignored.
OPEN_ENDED = (
    "split",
    "programme",
    "program",
    "instead",
    "swap",
    "replace",
    "deload",
    "why",
    "plan",
    "month",
    "week plan",
    "periodi",
    "diet",
    "nutrition",
    "sleep",
    "injur",
    "pain",
    "form",
    "technique",
)


@dataclass(frozen=True)
class Computed:
    """An answer produced from the log, with no model involved."""

    answer: str
    #: The analytics that produced it, shown to the user in place of the tool
    #: list, so a computed answer is never passed off as the coach's reasoning.
    source: str


Matcher = Callable[[str, Database, Settings], Computed | None]


def answer(question: str, db: Database, settings: Settings) -> Computed | None:
    """A computed answer to this question, or None to let the model have it."""
    text = question.strip().lower()
    if not text or any(word in text for word in OPEN_ENDED):
        return None
    for matcher in MATCHERS:
        found = matcher(text, db, settings)
        if found is not None:
            return found
    return None


def _has(text: str, *words: str) -> bool:
    return any(word in text for word in words)


# -- volume balance ---------------------------------------------------------


def _volume_balance(text: str, db: Database, settings: Settings) -> Computed | None:
    """Sets per week per muscle group against the goal's own floor."""
    if not _has(text, "volume", "sets"):
        return None
    if not _has(text, "balanc", "distribut", "spread", "even", "per muscle", "muscle group"):
        return None

    rows = metrics.muscle_group_volume(db, days=28)
    if not rows:
        return None

    goal = PROFILES[settings.training_goal]
    floor = goal.low_weekly_sets
    ranked = sorted(rows, key=lambda r: r["sets_per_week"], reverse=True)
    lines = [
        "Working sets per week by muscle group, last 28 days "
        "(secondary muscles count as half a set):",
        "",
    ]
    lines += [
        f"- **{row['muscle_group'].replace('_', ' ')}** - {row['sets_per_week']:.1f} sets/week"
        + (" *(below target)*" if floor is not None and row["sets_per_week"] < floor else "")
        for row in ranked
    ]

    if floor is None:
        lines += [
            "",
            f"Your goal is {goal.name}, which does not set a volume floor per muscle "
            "group - heavy exposure on the main lifts is the variable that matters, "
            "so accessory volume is not scored here.",
        ]
    else:
        under = [row for row in ranked if row["sets_per_week"] < floor]
        top, bottom = ranked[0], ranked[-1]
        lines += ["", f"Target for {goal.name} is {floor} sets/week per group."]
        if under:
            named = ", ".join(row["muscle_group"].replace("_", " ") for row in under)
            lines.append(f"Below it: **{named}**.")
        else:
            lines.append("Every group that appears in the log clears it.")
        lines.append(
            f"The spread runs from {top['sets_per_week']:.1f} sets/week "
            f"({top['muscle_group'].replace('_', ' ')}) down to {bottom['sets_per_week']:.1f} "
            f"({bottom['muscle_group'].replace('_', ' ')})."
        )
        lines.append(
            "A group with no sets at all does not appear above - check the list for "
            "anything missing entirely."
        )

    return Computed("\n".join(lines), "muscle-group volume vs your goal's threshold")


# -- progression on one lift ------------------------------------------------


def _named_exercise(text: str, db: Database) -> tuple[str, str] | None:
    """(template_id, title) for the exercise named in the question, if one is.

    Titles are matched with their equipment suffix stripped, so "bench press"
    finds "Bench Press (Barbell)". When several match - barbell and dumbbell
    bench both reduce to "bench press" - the most trained one wins, which is
    what someone naming a lift without qualifying it almost always means.
    """
    matches = []
    for summary in metrics.exercise_summaries(db, days=None):
        bare = re.sub(r"\s*\(.*?\)", "", summary.title).strip().lower()
        if len(bare) >= 4 and bare in text:
            matches.append((len(bare), summary.sessions, summary.template_id, summary.title))
    if not matches:
        return None
    # Longest name first so "leg press" beats "press"; then most trained.
    best = max(matches)
    return best[2], best[3]


def _equipment(db: Database, template_id: str) -> str | None:
    """The exercise's equipment category, which sets the fallback load step."""
    row = db.query_one(
        "SELECT equipment_category FROM exercise_templates WHERE id = ?", (template_id,)
    )
    return row["equipment_category"] if row else None


def _progression(text: str, db: Database, settings: Settings) -> Computed | None:
    """Is this lift moving, and what the app prescribes for it next."""
    if not _has(text, "progress", "improv", "moving", "stall", "going up", "getting stronger"):
        return None
    named = _named_exercise(text, db)
    if named is None:
        return None
    template_id, title = named

    trend = next(
        (
            t
            for t in progression.exercise_trends(db, settings, days=180)
            if t.template_id == template_id
        ),
        None,
    )
    history = session.exercise_sessions(db, template_id)
    if trend is None or not history:
        return None

    unit = settings.units
    verdict = {
        "progressing": "Yes - it is going up.",
        "maintaining": "It is holding, not climbing.",
        "stalling": "No - it has stalled.",
        "regressing": "No - it is going backwards.",
    }.get(trend.trend, trend.trend)

    lines = [
        f"**{title}** - {verdict}",
        "",
        f"- e1RM {units.fmt(trend.latest_e1rm_kg, unit)} now, best "
        f"{units.fmt(trend.best_e1rm_kg, unit)}, across {trend.sessions} sessions in the "
        f"last 180 days",
        f"- Trend {trend.slope_kg_per_month:+.1f} kg/month "
        f"({trend.change_pct_per_month:+.1f}%/month)",
        f"- Last trained {trend.days_since_last} days ago",
    ]
    if trend.level:
        lines.append(
            f"- Standards: {trend.level} at your bodyweight "
            f"(level score {trend.level_score})"
        )

    plan = session.recommend(history, equipment=_equipment(db, template_id), unit=unit)
    lines += [
        "",
        f"**Next session: {plan.headline}**",
        "",
        plan.detail,
    ]
    return Computed("\n".join(lines), f"trend fit and next-session prescription for {title}")


# -- furthest behind the standards ------------------------------------------


def _furthest_behind(text: str, db: Database, settings: Settings) -> Computed | None:
    """The lowest-scoring lift on the standards, and its next prescription."""
    if not _has(text, "behind", "weakest", "worst", "lagging", "furthest"):
        return None
    if not _has(text, "standard", "level", "benchmark", "lift"):
        return None

    report = benchmark(db, settings, days=365)
    if not report.entries:
        return None
    # `BenchmarkEntry.score` is a dict, not a dataclass - the standards module
    # builds it from the tables rather than declaring a type per lift.
    worst = min(report.entries, key=lambda e: e.score["level_score"])
    score = worst.score
    unit = settings.units

    lines = [
        f"**{worst.title}** is furthest behind - {score['level']} "
        f"(level score {score['level_score']} of 4).",
        "",
        f"- Best e1RM in the last year: {units.fmt(score['e1rm_kg'], unit)}",
    ]
    if score.get("next_level") and score.get("kg_to_next_level"):
        lines.append(
            f"- {units.fmt(score['kg_to_next_level'], unit)} short of {score['next_level']}"
        )
    lines.append(f"- {worst.sessions} sessions on record")

    history = session.exercise_sessions(db, worst.template_id)
    if history:
        plan = session.recommend(
            history, equipment=_equipment(db, worst.template_id), unit=unit
        )
        lines += ["", f"**Next session: {plan.headline}**", "", plan.detail]
    for caveat in report.caveats:
        lines += ["", caveat]
    return Computed("\n".join(lines), "strength standards and the next-session prescription")


#: Order matters only where two could fire; the specific ones come first.
MATCHERS: tuple[Matcher, ...] = (_progression, _furthest_behind, _volume_balance)
