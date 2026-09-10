"""The lifter profile: what we know about the athlete, and how to write it down.

Every strength standard is indexed on bodyweight and sex, and every volume and
frequency threshold comes from the training goal - so these few values decide
what most of the analysis *says*. Left unset they fall back to class defaults,
and a defaulted bodyweight silently rescales the whole benchmark: at 80 kg a
60 kg bench is "beginner", at 55 kg it is nearly "intermediate". The point of
this module is that the app can ask for them instead of hoping.

They are written back to the same ``.env`` the README documents rather than to a
settings table, so there is exactly one place a value can come from and the
form, the CLI and a hand edit can never disagree.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from hevy_coach.config import (
    REPO_ROOT,
    BodyweightKg,
    DumbbellLoad,
    Settings,
    Sex,
    Units,
    get_settings,
)
from hevy_coach.goals import Goal, profile_for

#: Unset fields that make the analysis *wrong* rather than merely
#: un-personalised, and so are what "the profile needs setting up" means.
#: Bodyweight rescales every standard; the goal drives every threshold in
#: goals.py. Birth date, units and the dumbbell convention all have defaults
#: that are either cosmetic or defensibly the common case.
SETUP_CRITICAL = ("sex", "bodyweight_kg", "training_goal")

ENV_HEADER = "# --- lifter profile ---"

#: An assignment in a dotenv file, live or commented out.
_ASSIGNMENT = re.compile(r"^\s*(?:#\s*)?(?P<key>[A-Z_][A-Z0-9_]*)\s*=(?P<rest>.*)$")


class ProfileUpdate(BaseModel):
    """The writable half of the profile. Every field is optional: the form can
    save one answer at a time, and omitting a field leaves it alone rather than
    resetting it to a default."""

    model_config = ConfigDict(extra="forbid")

    sex: Sex | None = None
    bodyweight_kg: BodyweightKg | None = None
    birth_date: date | None = None
    units: Units | None = None
    dumbbell_load: DumbbellLoad | None = None
    training_goal: Goal | None = None

    def env_values(self) -> dict[str, str]:
        """The update as ``ENV_KEY -> rendered value`` pairs."""
        return {
            field.upper(): _render(value)
            for field, value in self.model_dump(exclude_none=True).items()
        }


# -- reading ----------------------------------------------------------------


def describe(settings: Settings, measured_bodyweight: float | None = None) -> dict[str, Any]:
    """The profile as the API and the setup form need it.

    ``bodyweight_kg`` is the number the analysis actually uses, which a logged
    body measurement outranks. The form needs the configured value too, or
    editing it would show a figure the user never typed.
    """
    unset = settings.unset_profile_fields
    goal = profile_for(settings.training_goal)
    return {
        "sex": settings.sex,
        "bodyweight_kg": measured_bodyweight or settings.bodyweight_kg,
        "bodyweight_source": _bodyweight_source(settings, measured_bodyweight),
        "configured_bodyweight_kg": settings.bodyweight_kg,
        "birth_date": settings.birth_date.isoformat() if settings.birth_date else None,
        "age": round(settings.age, 1) if settings.age else None,
        "units": settings.units,
        "dumbbell_load": settings.dumbbell_load,
        "training_goal": settings.training_goal,
        "training_goal_summary": goal.summary,
        # Drives whether the app offers the total page at all, so it travels
        # with the profile rather than needing a second request to /api/goals.
        "tracks_total": goal.tracks_total,
        "coach_model": settings.coach_model,
        "unset": list(unset),
        "needs_setup": needs_setup(settings, measured_bodyweight),
        "env_file": str(env_path()),
    }


def needs_setup(settings: Settings, measured_bodyweight: float | None = None) -> bool:
    """Whether anything the analysis leans on is still a stand-in."""
    unset = set(settings.unset_profile_fields)
    if measured_bodyweight:
        # A logged measurement is a better answer than anything we could ask for.
        unset.discard("bodyweight_kg")
    return bool(unset.intersection(SETUP_CRITICAL))


def _bodyweight_source(settings: Settings, measured: float | None) -> str:
    if measured:
        return "measured"
    return "default" if settings.bodyweight_is_default else "configured"


# -- writing ----------------------------------------------------------------


def env_path() -> Path:
    """The dotenv file a profile write should land in.

    ``Settings`` reads a tuple of candidates in increasing precedence, so
    writing to anything but the last existing one could be silently shadowed by
    a file further down. When none exist, the repo-root file is created - that
    is the one the README and ``inv setup`` talk about.
    """
    configured = Settings.model_config.get("env_file") or (REPO_ROOT / ".env",)
    if isinstance(configured, str | Path):
        configured = (configured,)
    candidates = [Path(candidate) for candidate in configured]

    existing = [candidate for candidate in candidates if candidate.is_file()]
    return existing[-1] if existing else candidates[0]


def save(update: ProfileUpdate, path: Path | None = None) -> Settings:
    """Persist a profile update and return the settings it produces.

    The settings cache is dropped so the next request reads the new file, and
    the returned object is built fresh - the caller's injected ``Settings`` was
    loaded before the write and is now stale.
    """
    write_env(path or env_path(), update.env_values())
    get_settings.cache_clear()
    return get_settings()


def write_env(path: Path, values: Mapping[str, str]) -> None:
    """Set ``KEY=value`` in a dotenv file, preserving everything else in it.

    An existing assignment is edited in place, and so is a *commented-out* one:
    ``.env`` starts life as a copy of ``.env.example``, where every profile key
    is present but commented, and appending a duplicate below the comment would
    leave the file saying two different things about the same key. A trailing
    comment on the line is documentation, so it survives the edit, and a line
    whose value is already correct is not rewritten at all.

    The file is walked **backwards**, because dotenv gives effect to the *last*
    assignment of a key and that is therefore the only one worth writing to.
    Editing the first match instead is a silent no-op whenever anything sits
    below it, which is a state a user reaches by the obvious route: copy
    ``.env.example``, whose keys are all present and commented, then type a
    value at the end of the file. The form then wrote the commented line near
    the top while the hand-typed one below went on winning.
    """
    lines = path.read_text().splitlines() if path.is_file() else []
    remaining = dict(values)

    for index in reversed(range(len(lines))):
        match = _ASSIGNMENT.match(lines[index])
        if match is None:
            continue
        key = match["key"]
        commented = lines[index].lstrip().startswith("#")

        if key in remaining:
            value = remaining.pop(key)
            rest = match["rest"]
            if not commented and rest.partition("#")[0].strip() == value:
                continue  # already says exactly this; leave the formatting alone
            lines[index] = f"{key}={value}{_trailing_comment(rest)}"
        elif key in values and not commented:
            # An earlier live assignment of a key already written further down.
            # It was shadowed before this write and is shadowed after it, but
            # leaving two live lines contradicting each other is a trap, and
            # commenting it out keeps the old value visible.
            lines[index] = f"# {lines[index].lstrip()}"

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        if ENV_HEADER not in lines:
            lines.append(ENV_HEADER)
        lines.extend(f"{key}={value}" for key, value in remaining.items())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _trailing_comment(rest: str) -> str:
    """The ``# ...`` half of an assignment's value, if it has one."""
    _, marker, comment = rest.partition("#")
    return f"  #{comment}" if marker else ""


def _render(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
