"""The AI coach.

Claude gets read-only tools over the local training database and answers from
what it finds there. The tools are defined per-request with the database bound
via a closure, which keeps them pure functions of the request rather than
reaching for global state.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import anthropic
from anthropic import beta_tool

from hevy_coach.analytics import metrics, progression, session
from hevy_coach.analytics.benchmark import benchmark
from hevy_coach.analytics.standards import available_lifts, bands_for
from hevy_coach.coach.prompts import SYSTEM
from hevy_coach.config import Settings
from hevy_coach.db import Database

# Enough for a long analysis with several tool round-trips, without letting one
# question run away.
MAX_TOKENS = 16000
MAX_TURNS = 24


def _json(payload: Any) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)


def build_tools(db: Database, settings: Settings) -> list[Any]:
    """Read-only tools over the training log, bound to this request's database."""

    @beta_tool
    def get_overview(days: int | None = None) -> str:
        """Headline training stats: workout count, tonnage, sets, frequency, bodyweight.

        Call this first to get oriented.

        Args:
            days: Only consider the last N days. Omit for the full history.
        """
        return _json(asdict(metrics.overview(db, days=days)))

    @beta_tool
    def get_insights(days: int = 180) -> str:
        """Rule-based findings: stalls, regressions, dropped exercises, low volume.

        These are computed from the log, not opinions. Use them to decide where to
        look next.

        Args:
            days: Analysis window in days.
        """
        return _json([asdict(i) for i in progression.insights(db, settings, days=days)])

    @beta_tool
    def list_exercises(days: int | None = 365, limit: int = 40) -> str:
        """List trained exercises with session counts, best e1RM, and last performed date.

        Use this to find the exact template_id for an exercise before calling
        get_exercise_history.

        Args:
            days: Only consider the last N days. Omit for the full history.
            limit: Maximum exercises to return, most-trained first.
        """
        summaries = metrics.exercise_summaries(db, days=days)[:limit]
        return _json([asdict(s) for s in summaries])

    @beta_tool
    def get_exercise_history(template_id: str, days: int | None = 365) -> str:
        """Per-session history for one exercise: best e1RM, top set, sets, volume.

        Args:
            template_id: Hevy exercise template id, from list_exercises.
            days: Only consider the last N days. Omit for the full history.
        """
        history = metrics.exercise_history(db, template_id, days=days)
        if not history:
            return _json({"error": f"no sets logged for template_id {template_id!r}"})
        return _json([asdict(p) for p in history])

    @beta_tool
    def get_exercise_trends(days: int = 180) -> str:
        """Trend classification per exercise: slope of e1RM, stall detection, level.

        Args:
            days: Analysis window in days.
        """
        trends = progression.exercise_trends(db, settings, days=days)
        return _json([asdict(t) for t in trends])

    @beta_tool
    def get_benchmark(days: int | None = 365) -> str:
        """Compare every mappable lift against bodyweight-adjusted strength standards.

        Returns a level (beginner..elite), a continuous 0-4 level score, the five
        thresholds in kg, and how far the lift is from the next level.

        The level names are percentiles of lifts logged on strengthlevel.com -
        beginner is the 5th, novice the 20th, intermediate the 50th, advanced the
        80th, elite the 95th - so they rank the user against people who track
        their training, not the general population. Say so rather than reading
        the names as training age, and read `caveats` before trusting any level:
        it lists reasons the inputs are unreliable, such as a placeholder
        bodyweight.

        Args:
            days: Use each exercise's best e1RM within the last N days.
        """
        report = benchmark(db, settings, days=days)
        return _json(asdict(report))

    @beta_tool
    def get_standard_thresholds(lift: str, bodyweight_kg: float | None = None) -> str:
        """Look up the five strength-standard thresholds for one lift.

        Args:
            lift: Lift id, e.g. "bench-press". Call list_standard_lifts for the set.
            bodyweight_kg: Bodyweight to score at. Defaults to the user's own.
        """
        weight = bodyweight_kg or db.latest_bodyweight() or settings.bodyweight_kg
        try:
            bands = bands_for(lift, sex=settings.sex, bodyweight_kg=weight, age=settings.age)
        except LookupError as exc:
            return _json({"error": str(exc), "available": sorted(available_lifts())})
        return _json(asdict(bands))

    @beta_tool
    def list_standard_lifts() -> str:
        """List every lift id that has strength-standard tables available."""
        return _json(available_lifts())

    @beta_tool
    def get_muscle_group_volume(days: int = 28) -> str:
        """Working sets and tonnage per muscle group, with sets per week.

        Secondary muscles count as half a set.

        Args:
            days: Analysis window in days.
        """
        return _json(metrics.muscle_group_volume(db, days=days))

    @beta_tool
    def get_weekly_volume(weeks: int = 26) -> str:
        """Tonnage, working sets, reps and session count per week.

        Args:
            weeks: Number of recent weeks to return.
        """
        return _json(metrics.weekly_volume(db, weeks=weeks))

    @beta_tool
    def get_personal_records(days: int | None = 365, limit: int = 25) -> str:
        """Sessions where an exercise's e1RM beat everything before it.

        Args:
            days: Only return PRs set within the last N days.
            limit: Maximum records to return, newest first.
        """
        records = metrics.personal_records(db, days=days, limit=limit)
        return _json([asdict(r) for r in records])

    @beta_tool
    def list_workouts(limit: int = 20) -> str:
        """Recent sessions, newest first, each with its position in its routine.

        Use this to find the workout_id for get_workout_plan.

        Args:
            limit: Maximum sessions to return.
        """
        return _json([asdict(w) for w in session.list_workouts(db, limit=limit)])

    @beta_tool
    def get_workout_plan(workout_id: str) -> str:
        """One session's sets, its comparison to the previous time each exercise
        was trained, and a next-session prescription per exercise.

        The prescription is double progression: hold the load until every working
        set reaches the top of its rep range, then add the smallest increment the
        lifter's own history shows they use. Deload and hold branches override it
        on a stalled or regressing lift. Ramp-up sets are excluded from the
        decision - only sets at the exercise's top load count.

        Args:
            workout_id: Id from list_workouts.
        """
        try:
            return _json(asdict(session.workout_detail(db, settings, workout_id)))
        except LookupError as exc:
            return _json({"error": str(exc)})

    return [
        get_overview,
        get_insights,
        list_workouts,
        get_workout_plan,
        list_exercises,
        get_exercise_history,
        get_exercise_trends,
        get_benchmark,
        get_standard_thresholds,
        list_standard_lifts,
        get_muscle_group_volume,
        get_weekly_volume,
        get_personal_records,
    ]


def _profile_block(db: Database, settings: Settings) -> str:
    measured = db.latest_bodyweight()
    lines = [
        "<lifter_profile>",
        f"date: {datetime.now(UTC).date().isoformat()}",
        f"sex: {settings.sex}",
        f"bodyweight_kg: {measured or settings.bodyweight_kg}"
        f"{' (from Hevy measurements)' if measured else ' (configured)'}",
    ]
    if settings.age:
        lines.append(f"age: {settings.age:.0f}")
    lines.append(f"preferred_units: {settings.units}")
    lines.append(f"workouts_logged: {db.workout_count()}")
    lines.append("</lifter_profile>")
    return "\n".join(lines)


class Coach:
    """Multi-turn coaching conversation backed by the local training database."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.tools = build_tools(db, settings)

    def ask(
        self,
        question: str,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Answer one question, running tool calls until Claude is done.

        Returns the answer text, the tools that were called, and token usage.
        """
        messages: list[Any] = list(history or [])
        if not messages:
            # The profile rides on the first user turn so the cached system
            # prefix stays byte-identical across requests.
            question = f"{_profile_block(self.db, self.settings)}\n\n{question}"
        messages.append({"role": "user", "content": question})

        runner = self.client.beta.messages.tool_runner(
            model=self.settings.coach_model,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            thinking={"type": "adaptive"},
            output_config={"effort": self.settings.coach_effort},
            tools=self.tools,
            messages=messages,
            max_iterations=MAX_TURNS,
        )

        tools_used: list[str] = []
        answer_parts: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        final: Any = None

        for message in runner:
            final = message
            messages.append({"role": "assistant", "content": message.content})
            for block in message.content:
                if block.type == "tool_use":
                    tools_used.append(block.name)
                elif block.type == "text" and block.text.strip():
                    answer_parts.append(block.text)
            if message.usage:
                usage["input_tokens"] += message.usage.input_tokens or 0
                usage["output_tokens"] += message.usage.output_tokens or 0
                usage["cache_read_input_tokens"] += (
                    getattr(message.usage, "cache_read_input_tokens", 0) or 0
                )
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                messages.append(tool_response)

        if final is not None and final.stop_reason == "refusal":
            detail = getattr(final.stop_details, "explanation", None) or "no explanation given"
            return {
                "answer": f"The request was declined: {detail}",
                "tools_used": tools_used,
                "usage": usage,
                "stop_reason": "refusal",
                "messages": messages,
            }

        # Only the last assistant turn is the answer; earlier text blocks are
        # narration around tool calls.
        answer = answer_parts[-1] if answer_parts else ""
        return {
            "answer": answer.strip(),
            "tools_used": tools_used,
            "usage": usage,
            "stop_reason": final.stop_reason if final else None,
            "messages": messages,
        }
