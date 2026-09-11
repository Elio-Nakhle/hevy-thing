"""What the coach does not have to compute, or ask a model, twice.

The training log is immutable between imports, so everything derived from it -
the briefing, and the answer to a question about it - stays valid until the next
import. That makes the state of the log a natural cache key.

Two caches sit on it. The briefing is rebuilt once per import rather than once
per question, in memory, because it is pure computation. Answers are kept in
SQLite so they survive a restart: the four suggestion chips on the coach page
are fixed strings, and the second click on one should not cost anything.
"""

from __future__ import annotations

import hashlib
import re

from hevy_coach import csv_import
from hevy_coach.coach import briefing as briefing_module
from hevy_coach.config import Settings
from hevy_coach.db import Database

_WHITESPACE = re.compile(r"\s+")

#: Briefings by (database, fingerprint). One entry in practice - the previous
#: log's briefing is worthless the moment an import lands.
_BRIEFINGS: dict[tuple[str, str], str] = {}


def fingerprint(db: Database, settings: Settings) -> str:
    """Identity of everything an answer depends on besides the question itself.

    The import stamp alone is not enough: a profile edit changes which band each
    lift lands in and which volume thresholds apply, without touching a single
    set. Bodyweight is read from the log as well as the profile because a logged
    measurement outranks the configured number.
    """
    parts = (
        db.get_meta(csv_import.LAST_IMPORT_KEY) or "",
        str(db.workout_count()),
        db.latest_workout_time() or "",
        settings.sex,
        str(settings.bodyweight_kg),
        str(db.latest_bodyweight()),
        settings.training_goal,
        str(settings.birth_date),
        settings.dumbbell_load,
        settings.units,
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def briefing(db: Database, settings: Settings) -> str:
    """The briefing for the log as it stands, built at most once per import."""
    key = (str(db.path), fingerprint(db, settings))
    hit = _BRIEFINGS.get(key)
    if hit is None:
        # Only the current state is worth holding; a stale briefing is never
        # served, so keeping it would just be memory.
        _BRIEFINGS.clear()
        hit = _BRIEFINGS[key] = briefing_module.build(db, settings)
    return hit



def answer_key(question: str, *, state: str, model: str, effort: str, backend: str) -> str:
    """Cache key for one question about one state of the log.

    The model, the effort and the backend are in the key because the same
    question answered by a different model is a different answer, and serving
    yesterday's haiku reply as today's opus one would be a lie about provenance.
    """
    normalized = _WHITESPACE.sub(" ", question.strip().lower())
    return hashlib.sha256(
        "|".join((normalized, state, model, effort, backend)).encode()
    ).hexdigest()[:32]
