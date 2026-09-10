"""One sentence for the top of the dashboard: are you getting stronger?

Every interview in the roadmap's research asked this question, and the dashboard
answered it with four stat tiles, two charts and a findings list - all true,
none of them the answer. "Am I getting stronger? Everything else is you showing
your working."

Two decisions shape what comes out of here.

**Framed against the lifter's own past self, not a percentile.** A percentile is
a comparison with strangers, and it lands worst in exactly the case where
encouragement matters most: the same research recorded someone reading
"intermediate" on their bench, scrolling to "beginner" on eight other lifts, and
feeling worse than before they opened the app. The percentile still exists - it
is what the strength page is for - it just does not go first.

**The thresholds are the ones already used for a single lift.** ``progression``
calls one lift progressing above +1% a month and regressing below -1%; the same
numbers applied across lifts mean "your lifts are progressing" cannot quietly
disagree with "this lift is progressing".

**The middle lift, not the average one.** Percentage change per month is wildly
skewed by where a lift started: an accessory taken from 12 kg to 73 kg reads as
+82% a month and is not wrong, it is just not news about the lifter's strength.
Averaged in, it put the headline on the log this was built against at "up 21.6%
a month" - a claim of tripling inside half a year. The median of the same eleven
lifts is 13.9%, which is what the lifter would say if you asked them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Literal

from hevy_coach.analytics import progression, session
from hevy_coach.config import Settings
from hevy_coach.db import Database

Verdict = Literal["progressing", "holding", "slipping", "insufficient_data"]

#: "Currently" is a season, not a career. Long enough that a fitted trend is not
#: reading noise, short enough that last winter's block cannot carry the answer.
DEFAULT_WINDOW_DAYS = 90


@dataclass
class NextUp:
    """The other half of the answer: what changes when you next train."""

    title: str
    workout_id: str
    days_since: int
    exercises: int
    changes: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class Headline:
    verdict: Verdict
    #: The answer to "am I getting stronger", in one sentence, no jargon.
    answer: str
    lifts_tracked: int
    lifts_up: int
    lifts_flat: int
    lifts_down: int
    lifts_up_names: list[str]
    lifts_flat_names: list[str]
    lifts_down_names: list[str]
    #: Median of the per-lift trends, in percent per month. Median, not mean -
    #: see the module docstring.
    median_change_pct_per_month: float | None
    window_days: int
    next_up: NextUp | None = None


def _spread(up: int, flat: int, down: int) -> str:
    """"5 of 8 climbing, 1 sliding" - the mean alone would hide four lifts
    climbing while four others slide."""
    tracked = up + flat + down
    if not up and not down:
        return f"none of {tracked} clearly either way"
    if not down:
        return f"{up} of {tracked} climbing"
    if not up:
        return f"{down} of {tracked} sliding"
    return f"{up} of {tracked} climbing, {down} sliding"


def _answer(verdict: Verdict, up: int, flat: int, down: int, middle: float) -> str:
    spread = _spread(up, flat, down)
    if verdict == "progressing":
        return f"Yes. Your typical lift is up {middle:.1f}% a month - {spread}."
    if verdict == "slipping":
        return f"Not right now. Your typical lift is down {abs(middle):.1f}% a month - {spread}."
    return f"Holding. Your typical lift moves {middle:+.1f}% a month - {spread}."


def headline(
    db: Database, settings: Settings, *, days: int = DEFAULT_WINDOW_DAYS
) -> Headline:
    """Answer "am I getting stronger", and say what changes next session."""
    trends = progression.exercise_trends(db, settings, days=days)
    up = sum(1 for trend in trends if trend.trend == "progressing")
    down = sum(1 for trend in trends if trend.trend == "regressing")
    flat = len(trends) - up - down
    up_names = [trend.title for trend in trends if trend.trend == "progressing"]
    down_names = [trend.title for trend in trends if trend.trend == "regressing"]
    flat_names = [
        trend.title
        for trend in trends
        if trend.trend not in ("progressing", "regressing")
    ]

    if not trends:
        answer = _nothing_to_say(db, days)
        verdict: Verdict = "insufficient_data"
        middle = None
    else:
        middle = round(median(t.change_pct_per_month for t in trends), 1)
        if middle >= progression.PROGRESS_THRESHOLD:
            verdict = "progressing"
        elif middle <= progression.REGRESS_THRESHOLD:
            verdict = "slipping"
        else:
            verdict = "holding"
        answer = _answer(verdict, up, flat, down, middle)

    return Headline(
        verdict=verdict,
        answer=answer,
        lifts_tracked=len(trends),
        lifts_up=up,
        lifts_flat=flat,
        lifts_down=down,
        lifts_up_names=up_names,
        lifts_flat_names=flat_names,
        lifts_down_names=down_names,
        median_change_pct_per_month=middle,
        window_days=days,
        next_up=_next_up(db, settings),
    )


def _nothing_to_say(db: Database, days: int) -> str:
    """Why there is no answer yet, and what would produce one."""
    if db.workout_count() == 0:
        return "Nothing imported yet. Drop a Hevy CSV export on this page and it fills in."
    return (
        f"Not enough history yet. A lift needs "
        f"{progression.MIN_SESSIONS_FOR_TREND} sessions in the last {days // 7} weeks "
        f"before a trend through it means anything, and none of yours have that so far."
    )


def _next_up(db: Database, settings: Settings) -> NextUp | None:
    try:
        upcoming = session.next_session(db, settings)
    except LookupError:
        return None
    return NextUp(
        title=upcoming.routine.title,
        workout_id=upcoming.routine.workout_id,
        days_since=upcoming.routine.days_since,
        exercises=len(upcoming.exercises),
        changes=upcoming.changes,
        summary=upcoming.summary,
    )
