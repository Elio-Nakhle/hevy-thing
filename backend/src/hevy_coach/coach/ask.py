"""How a question gets answered, cheapest route first.

Three things can answer a question about the training log, and they are not
equally expensive:

1. the analytics, directly - free, instant, and exactly right for a lookup
   (`coach.answers`);
2. an answer already given about this same log - free, because the log has not
   changed since (`coach.cache`);
3. a model, with read-only tools over the log - the only one that can actually
   coach, and the only one that costs anything.

Every route returns the same shape, so a caller does not have to care which one
answered - but it is told, because an answer's provenance is the user's business.
"""

from __future__ import annotations

from typing import Any

from hevy_coach.coach import answers, cache, cli_agent
from hevy_coach.config import Settings
from hevy_coach.db import Database


def answer(
    db: Database,
    settings: Settings,
    question: str,
    *,
    history: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Answer one question. Raises `cli_agent.CoachUnavailable` if a model is
    needed and none can run.

    A follow-up - anything carrying history or a session - always goes to the
    model: the cheap routes answer a question, not a conversation, and serving a
    cached first answer to "and what about squats?" would be nonsense.
    """
    follow_up = bool(history or session_id)

    if not follow_up:
        computed = answers.answer(question, db, settings)
        if computed is not None:
            return {
                "backend": "computed",
                "cached": False,
                "answer": computed.answer,
                "tools_used": [computed.source],
                "usage": {},
                "stop_reason": "computed",
                "session_id": None,
            }

    coach = cli_agent.build_coach(db, settings)
    state = cache.fingerprint(db, settings)
    key = cache.answer_key(
        question,
        state=state,
        model=settings.coach_model,
        effort=settings.coach_effort,
        backend=coach.backend,
    )

    if not follow_up:
        hit = db.get_coach_answer(key)
        if hit is not None:
            return {
                "backend": coach.backend,
                "cached": True,
                "answer": hit["answer"],
                "tools_used": hit["tools_used"],
                "usage": {},
                "stop_reason": "cached",
                "session_id": None,
            }

    result = coach.ask(question, history, session_id)

    # Only a first-turn answer is cacheable, and only a real one: a refusal or an
    # empty reply is not worth serving twice.
    if not follow_up and result.get("answer") and result.get("stop_reason") != "refusal":
        db.put_coach_answer(
            key,
            fingerprint=state,
            question=question,
            answer=result["answer"],
            tools_used=result.get("tools_used") or [],
        )

    return {"backend": coach.backend, "cached": False, **result}
