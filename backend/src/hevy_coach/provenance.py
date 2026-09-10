"""Where each number on screen comes from, and what to call it in plain English.

Two problems, one table. The README is honest about this project's limits in a
way most training apps are not - e1RM inflation on high-rep sets, ramp-up sets
that cannot be told from working sets, percentile bands drawn from people who
log their training rather than the general population - and all of that honesty
was in the README, where nobody reading a dashboard will find it. Meanwhile the
surface talks in jargon: a lifter who knows perfectly well what a bench press is
should not have to look up "e1RM", "tonnage" or "DOTS" to read their own log.

So every derived number gets one entry here carrying both: the plain-language
name to show instead of the jargon, and a one-line account of where the number
came from, close enough to the reasoning in the analytics modules' own
docstrings that the two cannot drift far. The frontend uses ``plain`` to rename
the surface and ``detail`` as the hover text, so the glossary and the tooltips
can never disagree.

Keep ``detail`` to one sentence a lifter would actually read, and say the
limitation rather than the mechanism where there is a choice: "estimates past 12
reps are not trusted" beats a restatement of Epley's formula.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Term:
    #: Stable id the frontend references, e.g. ``<Term id="e1rm" />``.
    key: str
    #: The technical name, shown when plain-language mode is off.
    term: str
    #: What to call it when plain-language mode is on.
    plain: str
    #: One line: where this number comes from, and what not to trust about it.
    detail: str
    #: Attribution, where the number is not ours.
    source: str | None = None


TERMS: tuple[Term, ...] = (
    Term(
        key="e1rm",
        term="e1RM",
        plain="estimated best single",
        detail=(
            "Your best working set, converted to a one-rep max with Epley "
            "(weight x (1 + reps/30)). It is an estimate, not a lift you did: sets "
            "above 12 reps are not trusted, and rep-max estimates flatter lifters "
            "who train in higher reps."
        ),
    ),
    Term(
        key="volume",
        term="volume",
        plain="total weight lifted",
        detail=(
            "Weight x reps added up across working sets. Warm-ups are excluded. It "
            "counts a heavy single and a set of ten by the weight moved, so it "
            "describes work done rather than how hard the session was."
        ),
    ),
    Term(
        key="working_set",
        term="working set",
        plain="real set",
        detail=(
            "Every set except a warm-up. Hevy's CSV types almost everything "
            "'normal', so this is as fine a distinction as the export supports."
        ),
    ),
    Term(
        key="ramp_up",
        term="ramp-up set",
        plain="lighter set",
        detail=(
            "A set below the exercise's heaviest load that day. Hevy's export "
            "marks no warm-ups, so a ramp cannot be told from straight sets - only "
            "the sets at the top weight drive the prescription."
        ),
    ),
    Term(
        key="sets_per_week",
        term="sets/week",
        plain="sets a week",
        detail=(
            "Working sets for the muscle group over the window, divided by its "
            "weeks. An exercise's secondary muscles count as half a set each, "
            "because they take real but lesser load."
        ),
    ),
    Term(
        key="sessions_per_week",
        term="sessions/week",
        plain="workouts a week",
        detail="Workouts divided by the weeks between your first and your last one.",
    ),
    Term(
        key="trend",
        term="trend",
        plain="direction",
        detail=(
            "A straight line fitted through this lift's estimated best single, "
            "session by session. Better than +1% a month is progressing, worse "
            "than -1% regressing, in between maintaining. Needs four sessions."
        ),
    ),
    Term(
        key="pr",
        term="PR",
        plain="personal best",
        detail=(
            "A session whose estimated best single beat every session before it. "
            "Because it is an estimate, a rep PR at a lighter load can register "
            "as one."
        ),
    ),
    Term(
        key="level",
        term="level",
        plain="rank",
        detail=(
            "Where this lift sits on published standards for your bodyweight, sex "
            "and age: beginner, novice, intermediate, advanced, elite."
        ),
        source="strengthlevel.com",
    ),
    Term(
        key="level_score",
        term="level score",
        plain="rank score",
        detail=(
            "The level as a continuous 0-4 number - 0 beginner, 2 intermediate, "
            "4 elite - so a lift near the top of its band is not filed with one at "
            "the bottom."
        ),
    ),
    Term(
        key="percentile",
        term="percentile",
        plain="how you compare",
        detail=(
            "Your rank among lifts logged on strengthlevel.com. Those are people "
            "who track their training, not the general population, so this reads "
            "lower than standards built on everybody."
        ),
        source="strengthlevel.com",
    ),
    Term(
        key="prescription",
        term="prescription",
        plain="what to do next",
        detail=(
            "Double progression: hold the weight until you reach the top of the rep "
            "range on every working set, then add the smallest useful jump and drop "
            "back to the bottom of the range. No RPE or configured max needed."
        ),
    ),
    Term(
        key="load_step",
        term="load step",
        plain="weight jump",
        detail=(
            "The smallest jump this exercise actually moves in, read from your own "
            "history - so a machine whose stack goes up in sevens gets sevens. The "
            "equipment type is the fallback until there is enough history."
        ),
    ),
    Term(
        key="rep_range",
        term="rep range",
        plain="rep range",
        detail=(
            "The band your median top-set reps fall into, so a prescription stays "
            "in the rep neighbourhood you already train instead of dragging a "
            "20-rep carry towards triples."
        ),
    ),
    Term(
        key="stall",
        term="stall",
        plain="stuck",
        detail=(
            "Three sessions at an unchanged weight without a new estimated best. "
            "Late enough that one bad night does not trigger it, early enough to "
            "save a month of grinding."
        ),
    ),
    Term(
        key="deload",
        term="deload",
        plain="back-off week",
        detail=(
            "10% off a weight that has stopped producing bests - enough to shed "
            "fatigue, small enough to climb back in two sessions."
        ),
    ),
    Term(
        key="bodyweight_source",
        term="bodyweight source",
        plain="where your weight came from",
        detail=(
            "Whether the bodyweight behind these numbers was measured in your log, "
            "entered in your profile, or is still a placeholder. Every standard is "
            "indexed on it, so a placeholder shifts levels by whole bands."
        ),
    ),
)

BY_KEY: dict[str, Term] = {term.key: term for term in TERMS}


def glossary() -> dict[str, dict[str, Any]]:
    """The whole table, keyed by id, for the frontend to look terms up in."""
    return {term.key: asdict(term) for term in TERMS}


def plain(key: str) -> str:
    """The plain-language name for a term, or the key itself if unknown."""
    entry = BY_KEY.get(key)
    return entry.plain if entry else key
