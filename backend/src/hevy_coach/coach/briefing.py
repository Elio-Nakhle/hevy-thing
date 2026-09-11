"""The state of the log, handed over on the first message.

A question used to spend three or four calls just getting oriented -
`get_overview`, then `get_insights`, then `get_exercise_trends`, each one a
round trip that re-sends everything before it. Measured on a 29-workout log
those three returned 5,743 tokens between them; this digest covers the same
ground in about 600 and costs one pass over SQLite, so a question starts
oriented and drills in only where it actually needs to.

It is a summary and says so. The tools still hold the detail, and the system
prompt tells the model to reach for them when the briefing is not enough.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from hevy_coach.analytics import metrics, progression
from hevy_coach.analytics.benchmark import benchmark
from hevy_coach.coach import compact
from hevy_coach.coach.compact import SEVERITY, insight_lines, trend_table
from hevy_coach.config import Settings
from hevy_coach.db import Database

#: Trend rows, most-trained lifts first. Past a dozen the tail is noise the
#: model can fetch if it wants it.
LIFTS = 12
#: Findings, most severe first.
FINDINGS = 6
#: Lifts furthest behind the standards. "Where am I weakest" is a common
#: question and the full benchmark table is thirty rows.
BEHIND = 4
#: Window for the trend fits and the findings, in days.
WINDOW = 180


def build(db: Database, settings: Settings) -> str:
    """The briefing, as the model sees it."""
    sections = [
        "<briefing>",
        "A summary of the log as it stands. Weights are kilograms. Use the tools "
        "for anything not here - per-session history, a specific workout's "
        "prescriptions, the full standards table.",
        "",
        "## Totals",
        compact.fields(
            asdict(metrics.overview(db)),
            (
                "workouts",
                "first_workout",
                "last_workout",
                "total_sets",
                "total_volume_kg",
                "avg_workouts_per_week",
                "avg_duration_minutes",
                "distinct_exercises",
            ),
        ),
    ]

    trends = [asdict(t) for t in progression.exercise_trends(db, settings, days=WINDOW)]
    if trends:
        top = sorted(trends, key=lambda t: t.get("sessions") or 0, reverse=True)[:LIFTS]
        sections += ["", f"## Trends, {LIFTS} most trained lifts ({WINDOW}d)", trend_table(top)]

    found = progression.insights(db, settings, days=WINDOW)
    if found:
        ranked = sorted(found, key=lambda i: SEVERITY.get(i.severity, 9))[:FINDINGS]
        sections += ["", "## Findings", insight_lines(ranked)]

    sections += ["", "## Standards", _standards(db, settings)]
    sections.append("</briefing>")
    return "\n".join(sections)


def _standards(db: Database, settings: Settings) -> str:
    """Overall level plus the lifts furthest behind, not the whole table."""
    report = asdict(benchmark(db, settings, days=365))
    head = compact.fields(report, ("bodyweight_kg", "bodyweight_source", "overall_level"))
    head += f" overall_score={compact.cell(report.get('overall_level_score'))}"
    lines = [head]

    entries: list[dict[str, Any]] = sorted(
        report["entries"], key=lambda e: e["score"]["level_score"]
    )[:BEHIND]
    if entries:
        lines.append(f"furthest behind ({BEHIND} of {len(report['entries'])} scored):")
        lines.append(
            compact.table(
                entries,
                [
                    "title",
                    ("lift", lambda row: row["score"]["lift"]),
                    ("e1rm", lambda row: row["score"]["e1rm_kg"]),
                    ("level", lambda row: row["score"]["level"]),
                    ("score", lambda row: row["score"]["level_score"]),
                    ("to_next", lambda row: row["score"]["kg_to_next_level"]),
                ],
            )
        )
    # A placeholder bodyweight rescales every level, so the caveat travels with
    # the numbers rather than waiting for the model to call get_benchmark.
    lines.extend(report.get("caveats") or [])
    return "\n".join(lines)
