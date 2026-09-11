"""Compact wire formats for the coach's tool results.

Every token a tool returns is written into the conversation and re-read on each
later turn, so a fat payload is charged many times over. Measured on a
29-workout log, one question cost 36,875 cache-write tokens - about three
quarters of the bill - and almost all of it was tool output spending its bytes
on key names repeated per row, timezone suffixes nobody reads, and float noise.

So rows that are all the same shape ship as a pipe-delimited table with the keys
once in a header. Payloads that are nested or one-of-a-kind stay JSON, which is
cheap when there is only one of them. The model is told the format in the system
prompt and in each tool's own description.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

#: A value in a cell can be pulled by key or computed from the whole row.
Extract = str | Callable[[Mapping[str, Any]], Any]
#: A column is a header plus how to fill it. A bare string is both.
Column = str | tuple[str, Extract]

_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T")

#: Order findings are reported in, most actionable first.
SEVERITY = {"warning": 0, "suggestion": 1, "info": 2}


def json_dump(payload: Any) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)


def cell(value: Any) -> str:
    """One value, as short as it can be written without losing meaning.

    Nulls become empty rather than "null" (four tokens to say nothing), dates
    lose the time nobody asks about, and floats lose the trailing zero.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "y" if value else ""
    if isinstance(value, float):
        rounded = round(value, 1)
        return str(int(rounded)) if rounded == int(rounded) else str(rounded)
    if isinstance(value, str):
        if _TIMESTAMP.match(value):
            return value[:10]
        # The delimiter cannot appear inside a cell; exercise titles are
        # user-supplied, so this is not hypothetical.
        return value.replace("|", "/")
    return str(value)


def table(rows: Sequence[Mapping[str, Any]], columns: Sequence[Column]) -> str:
    """Rows as `a|b|c`, keys once in the header. Empty rows give the header alone."""
    headers: list[str] = []
    extractors: list[Extract] = []
    for column in columns:
        if isinstance(column, str):
            headers.append(column)
            extractors.append(column)
        else:
            headers.append(column[0])
            extractors.append(column[1])

    lines = ["|".join(headers)]
    for row in rows:
        lines.append(
            "|".join(
                cell(extract(row) if callable(extract) else row.get(extract))
                for extract in extractors
            )
        )
    return "\n".join(lines)


def fields(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    """A single record as `key=value` pairs, skipping what is empty."""
    parts = [f"{key}={cell(payload.get(key))}" for key in keys if payload.get(key) is not None]
    return " ".join(parts)


# -- the payloads themselves ------------------------------------


def insight_lines(found: list[Any]) -> str:
    """Findings as one line each, the numbers in the prose rather than a dict.

    `Insight.detail` already states every number `Insight.evidence` carries, so
    shipping both spends the same tokens twice. The template_id is the one thing
    only the evidence has, and the model needs it to drill in.
    """
    lines = []
    for item in found:
        evidence = getattr(item, "evidence", None) or {}
        template_id = evidence.get("template_id")
        subject = f"{item.title} ({template_id})" if template_id else item.title
        lines.append(f"[{item.severity}] {subject}: {item.detail}")
    return "\n".join(lines)


def trend_table(trends: list[dict[str, Any]]) -> str:
    return table(
        trends,
        [
            "title",
            ("id", "template_id"),
            "sessions",
            ("last", "last_date"),
            ("days_ago", "days_since_last"),
            ("e1rm", "latest_e1rm_kg"),
            ("best", "best_e1rm_kg"),
            ("kg_per_mo", "slope_kg_per_month"),
            ("pct_per_mo", "change_pct_per_month"),
            "trend",
            "level",
            ("score", "level_score"),
        ],
    )


def benchmark_report(report: dict[str, Any]) -> str:
    """The benchmark as a header line, a row per lift, and the caveats."""
    head = fields(
        report, ("sex", "bodyweight_kg", "bodyweight_source", "age", "overall_level")
    )
    head += f" overall_score={cell(report.get('overall_level_score'))}"
    rows = table(
        report["entries"],
        [
            "title",
            ("lift", lambda row: row["score"]["lift"]),
            ("e1rm", lambda row: row["score"]["e1rm_kg"]),
            ("level", lambda row: row["score"]["level"]),
            ("score", lambda row: row["score"]["level_score"]),
            ("to_next", lambda row: row["score"]["kg_to_next_level"]),
            ("next", lambda row: row["score"]["next_level"]),
            ("last", "last_performed"),
            "sessions",
        ],
    )
    parts = [head, rows]
    if report.get("unmapped"):
        # Titles only: the lifts with no standard are named so the model does not
        # claim a level for them, not analysed here.
        parts.append(
            "no standard for: " + ", ".join(item["title"] for item in report["unmapped"])
        )
    parts.extend(report.get("caveats") or [])
    return "\n".join(parts)


def workout_plan(detail: dict[str, Any]) -> str:
    """One session and its prescriptions, without the per-set JSON.

    The sets survive as a `kg x reps` list because they are the evidence behind
    the prescription; the array of one object per set does not.
    """
    head = fields(
        detail, ("title", "start_time", "duration_minutes", "sets", "volume_kg", "total_reps")
    )
    routine = fields(
        detail.get("routine") or {},
        ("title", "runs", "run_index", "previous_date", "previous_volume_kg", "volume_delta_pct"),
    )

    rows = []
    for block in detail["exercises"]:
        done = ",".join(
            f"{cell(s['weight_kg'])}x{cell(s['reps'])}" for s in block["sets"]
        )
        rows.append({**block, "done": done})

    exercises = table(
        rows,
        [
            "title",
            ("id", "template_id"),
            ("sets_done", "done"),
            ("top_kg", "top_weight_kg"),
            ("top_reps", "top_reps"),
            ("e1rm", "best_e1rm_kg"),
            ("e1rm_delta", "e1rm_delta_kg"),
            ("pr", "is_pr"),
            ("action", lambda row: row["recommendation"]["action"]),
            ("next", lambda row: row["recommendation"]["headline"]),
            ("why", lambda row: row["recommendation"]["detail"]),
        ],
    )

    parts = [head, f"routine: {routine}", exercises]
    parts.extend(detail.get("notes") or [])
    return "\n".join(parts)
