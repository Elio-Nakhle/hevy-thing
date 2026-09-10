"""One session at a time: what happened, and what to load next time.

Every other analytic in this project aggregates *across* sessions - weekly
tonnage, e1RM trends, standings against the standards. Useful for steering a
training block, useless when you are standing in front of a rack trying to
remember what you did last Tuesday. This module answers the other question:
for this workout, exercise by exercise, what should the next run of the same
routine look like?

Three things shape the design, all of them forced by what a Hevy CSV export
actually contains:

* **No RPE.** The export carries the field but almost no lifter fills it in, so
  anything RPE-gated (velocity-loss autoregulation, RIR-targeted load drops)
  would silently do nothing. Progression here is driven by load, reps and their
  history alone.
* **No warm-up marking.** Hevy's CSV types every set ``normal``, so a ramp to a
  top single looks identical to three straight sets. Rather than guess, the
  *top weight* of the exercise is found and only the sets at that weight are
  treated as the working prescription; everything lighter is reported as ramp-up
  and left out of the progression decision.
* **No routine id.** CSV exports drop it, so a routine is identified by its
  workout title. "Full A" run nine times is nine occurrences of one routine.

Two entry points come out of this. :func:`workout_detail` reads one session
that already happened; :func:`next_session` looks forward - it works out which
routine is due, and hands back that routine's prescriptions with nothing else
attached, which is all you want on a phone at the rack.

The progression model is **double progression**, the scheme with the least
ceremony and the most evidence behind it: hold the load until the top of a rep
range is reached on every working set, then add the smallest useful increment
and drop back to the bottom of the range. It needs no RPE, no percentages and
no configured 1RM, which is exactly the data situation above. Deloads and holds
are layered on top for the cases where pushing is the wrong call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from statistics import median
from typing import Any, Literal

from hevy_coach import units
from hevy_coach.analytics import e1rm
from hevy_coach.analytics.metrics import WORKING_SETS
from hevy_coach.config import Settings
from hevy_coach.db import Database

# -- progression constants --------------------------------------------------

#: Canonical rep ranges. An exercise is assigned the first band its recent
#: top-set reps fit into, so the prescription stays in the rep neighbourhood the
#: lifter already trains rather than dragging a 20-rep carry towards triples.
REP_BANDS: tuple[tuple[int, int], ...] = ((1, 3), (4, 6), (6, 10), (10, 15), (15, 20))

#: Load steps we are willing to prescribe, in kg. Real plate and stack jumps
#: cluster here; anything else is noise from a machine with odd stack labelling.
LOAD_STEPS: tuple[float, ...] = (1.0, 2.0, 2.5, 4.0, 5.0, 10.0)

#: Fallback increment per equipment category, used until an exercise has enough
#: distinct loads in its history to reveal its own smallest usable jump.
EQUIPMENT_STEP: dict[str, float] = {
    "barbell": 2.5,
    "dumbbell": 2.0,
    "machine": 5.0,
    "cable": 2.5,
    "weighted": 2.5,
    "kettlebell": 4.0,
}
DEFAULT_STEP = 2.5

#: Sessions without a new e1RM best, at an unchanged load, before the lift is
#: called stalled and offered a deload. Three is late enough that one bad night
#: does not trigger it and early enough to save a month of grinding.
STALL_SESSIONS = 3

#: A deload drops to this fraction of the stalled load. 10% off is the standard
#: light-week magnitude - enough to shed fatigue, small enough to climb back in
#: two sessions.
DELOAD_FACTOR = 0.9

#: How far below the exercise's best e1RM a session has to fall before it counts
#: as a genuine regression rather than day-to-day variation.
REGRESSION_MARGIN = 0.95

#: Sessions of history used to infer an exercise's load increment. A lifter who
#: started in 10 kg jumps and now moves in 5s is programming 5s; averaging over
#: the whole log would keep prescribing the jumps they have already outgrown.
STEP_WINDOW = 8

Action = Literal[
    "add_load",
    "add_reps",
    "hold",
    "deload",
    "establish",
    "no_basis",
]


# -- performed work ---------------------------------------------------------


@dataclass
class PerformedSet:
    set_index: int
    set_type: str
    weight_kg: float | None
    reps: int | None
    rpe: float | None
    e1rm_kg: float | None
    volume_kg: float
    #: True for sets at the heaviest load of the exercise - the working sets the
    #: prescription is built from. Lighter sets are ramp-up.
    is_top: bool


@dataclass
class ExerciseSession:
    """One exercise's work inside one workout."""

    workout_id: str
    date: str
    template_id: str
    title: str
    sets: list[PerformedSet]
    volume_kg: float
    top_weight_kg: float | None
    top_reps: int | None
    #: Sets performed at ``top_weight_kg``.
    top_set_count: int
    best_e1rm_kg: float | None

    @property
    def top_set_reps(self) -> list[int]:
        return [s.reps for s in self.sets if s.is_top and s.reps is not None]


def _exercise_session(rows: list[Any]) -> ExerciseSession | None:
    """Fold one workout's rows for a single exercise into a session record."""
    if not rows:
        return None

    loaded = [float(r["weight_kg"]) for r in rows if r["weight_kg"] is not None]
    top_weight = max(loaded) if loaded else None

    sets: list[PerformedSet] = []
    volume = 0.0
    best = None
    top_reps = None
    top_count = 0

    for row in rows:
        weight, reps = row["weight_kg"], row["reps"]
        estimate = e1rm.estimate(weight, reps, row["rpe"])
        set_volume = float(weight or 0.0) * float(reps or 0)
        volume += set_volume

        # With no weight logged anywhere - a bodyweight movement - every set is
        # a working set, since there is no load to rank them by.
        is_top = weight is not None and top_weight is not None and weight >= top_weight
        if top_weight is None:
            is_top = True
        if is_top:
            top_count += 1
            if reps is not None and (top_reps is None or reps > top_reps):
                top_reps = int(reps)

        if estimate is not None and (best is None or estimate > best):
            best = estimate

        sets.append(
            PerformedSet(
                set_index=int(row["set_index"]),
                set_type=row["set_type"],
                weight_kg=weight,
                reps=int(reps) if reps is not None else None,
                rpe=row["rpe"],
                e1rm_kg=round(estimate, 1) if estimate is not None else None,
                volume_kg=round(set_volume, 1),
                is_top=is_top,
            )
        )

    return ExerciseSession(
        workout_id=rows[0]["workout_id"],
        date=rows[0]["start_time"],
        template_id=rows[0]["template_id"],
        title=rows[0]["exercise_title"],
        sets=sets,
        volume_kg=round(volume, 1),
        top_weight_kg=top_weight,
        top_reps=top_reps,
        top_set_count=top_count,
        best_e1rm_kg=round(best, 1) if best is not None else None,
    )


def exercise_sessions(
    db: Database, template_id: str, *, until: str | None = None
) -> list[ExerciseSession]:
    """Every session containing one exercise, oldest first.

    ``until`` caps the range inclusively, so a session can be analysed against
    only the history that preceded it rather than against its own future.
    """
    clause = " AND start_time <= ?" if until else ""
    params: tuple[Any, ...] = (template_id, until) if until else (template_id,)
    rows = db.query(
        f"""
        SELECT workout_id, start_time, template_id, exercise_title, set_index,
               set_type, weight_kg, reps, rpe
        FROM sets
        WHERE template_id = ? AND {WORKING_SETS}{clause}
        ORDER BY start_time, set_index
        """,
        params,
    )

    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row["workout_id"], []).append(row)

    sessions = [s for rows_ in grouped.values() if (s := _exercise_session(rows_))]
    sessions.sort(key=lambda s: s.date)
    return sessions


# -- progression ------------------------------------------------------------


@dataclass
class Recommendation:
    """What to do with one exercise the next time this routine comes round."""

    action: Action
    #: Prescription in one line: "3 x 8 @ 62.5 kg". Weight is kilograms; the
    #: frontend converts for display like everywhere else.
    headline: str
    #: Why this and not something else, in the lifter's own numbers.
    detail: str
    target_sets: int | None = None
    target_reps: int | None = None
    target_weight_kg: float | None = None
    rep_range: tuple[int, int] | None = None
    load_step_kg: float | None = None


def rep_band(reps: list[int]) -> tuple[int, int]:
    """The canonical rep range a session's rep scheme sits in.

    Two choices here, both learned from real logs:

    *Only this session, not an average of recent ones.* Programmes change, and
    an average lags them - a lifter who moved deadlifts from eights to fives
    keeps getting told to chase ten reps for a month afterwards.

    *Every set, at the median - not the top set.* A ramp that finishes on a
    heavy triple is still a session of fives, and the ramp and back-off sets are
    what say so. Reading the band off the heaviest set alone turns
    ``40x5 44x5 48x3 40x10`` into a prescription for singles, which is not what
    anyone lifting that way is doing.
    """
    if not reps:
        return REP_BANDS[2]
    anchor = median(reps)
    for low, high in REP_BANDS:
        if anchor <= high:
            return low, high
    return REP_BANDS[-1]


def load_step(weights: list[float], equipment: str | None) -> float:
    """The smallest load jump this exercise actually moves in.

    Read from the lifter's own history where there is enough of it - a machine
    whose stack goes up in sevens should be progressed in sevens, and no
    configuration file will ever say so. The equipment category is the fallback
    for an exercise with too few distinct loads to infer from.
    """
    distinct = sorted({round(w, 2) for w in weights if w > 0})
    diffs = [b - a for a, b in pairwise(distinct) if b > a]
    if diffs:
        return min(LOAD_STEPS, key=lambda step: abs(step - median(diffs)))
    return EQUIPMENT_STEP.get(equipment or "", DEFAULT_STEP)


def _snap(weight: float, step: float) -> float:
    """Round a target load to something you can actually load on the bar."""
    return round(round(weight / step) * step, 2)


def _fmt_kg(value: float, unit: units.Units = "kg") -> str:
    """Prose weight. Numeric fields stay in kilograms; only the wording converts."""
    return units.fmt(value, unit, 1 if unit == "lb" or value % 1 else 0)


def _fmt_reps(count: int) -> str:
    return f"{count} rep" if count == 1 else f"{count} reps"


def _sets_phrase(count: int) -> str:
    """"that set" / "both sets" / "all 4 sets" - "all 1 set" reads like a bug."""
    if count == 1:
        return "that set"
    if count == 2:
        return "both sets"
    return f"all {count} sets"


def _prescription(sets: int, reps: int, weight: float | None, unit: units.Units) -> str:
    load = _fmt_kg(weight, unit) if weight else "bodyweight"
    return f"{sets} x {reps} @ {load}"


def recommend(
    history: list[ExerciseSession],
    *,
    equipment: str | None = None,
    unit: units.Units = "kg",
) -> Recommendation:
    """Next-session prescription for one exercise.

    ``history`` runs oldest to newest and ends with the session being analysed.
    The decision order matters: fatigue and regression are checked before
    progression, because the whole point of the deload branch is that it fires
    instead of "add load" on a lift that has stopped responding to load.
    """
    if not history:
        return Recommendation(
            action="no_basis",
            headline="No prescription",
            detail="No working sets logged for this exercise.",
        )

    current = history[-1]
    top_reps = current.top_set_reps

    # Cardio and duration-only work have no load/rep pair to progress.
    if not top_reps:
        return Recommendation(
            action="no_basis",
            headline="Not progressed",
            detail=(
                "No reps logged, so there is nothing to apply a progression "
                "scheme to. Distance and duration work is tracked, not prescribed."
            ),
        )

    sets_count = max(current.top_set_count, 1)
    weights = [
        s.weight_kg
        for h in history[-STEP_WINDOW:]
        for s in h.sets
        if s.weight_kg is not None and s.weight_kg > 0
    ]
    step = load_step(weights, equipment)
    top_weight = current.top_weight_kg
    low, high = rep_band([s.reps for s in current.sets if s.reps is not None])

    if len(history) < 2:
        return Recommendation(
            action="establish",
            headline=_prescription(sets_count, max(top_reps), top_weight, unit),
            detail=(
                "First session on record for this exercise. Repeat it to "
                "establish a baseline - one session is not a trend, and a "
                "progression step off a single data point is a guess."
            ),
            target_sets=sets_count,
            target_reps=max(top_reps),
            target_weight_kg=top_weight,
            rep_range=(low, high),
            load_step_kg=step,
        )

    scored = [h.best_e1rm_kg for h in history if h.best_e1rm_kg is not None]
    best = max(scored) if scored else None

    # Sessions since the best was *first* reached, not since it was last tied.
    # Repeating a number is not beating it: a lifter who has hit exactly 100x5
    # for four sessions running has stalled, and counting from the most recent
    # tie would score that as "new best this session" and prescribe more weight.
    sessions_since_best = 0
    if best is not None:
        for index, past in enumerate(history):
            if past.best_e1rm_kg is not None and past.best_e1rm_kg >= best - 1e-9:
                sessions_since_best = len(history) - 1 - index
                break

    # How long the top load has sat unchanged, current session included.
    same_load = 0
    if top_weight is not None:
        for past in reversed(history):
            if past.top_weight_kg is None or abs(past.top_weight_kg - top_weight) > 1e-9:
                break
            same_load += 1

    # 1. Stalled: same load, no new best, several sessions running. Adding
    #    weight here is how a plateau turns into a month of grinding; back off
    #    and rebuild into it instead.
    if (
        top_weight
        and sessions_since_best >= STALL_SESSIONS
        and same_load >= STALL_SESSIONS
    ):
        target = _snap(top_weight * DELOAD_FACTOR, step)
        return Recommendation(
            action="deload",
            headline=_prescription(sets_count, high, target, unit),
            detail=(
                f"{_fmt_kg(top_weight, unit)} for {same_load} sessions with no new e1RM "
                f"best in {sessions_since_best}. Drop to {_fmt_kg(target, unit)} "
                f"(-{100 - DELOAD_FACTOR * 100:g}%) for one session, hit {high} reps "
                "on every set, then climb back. A stall at a fixed load is a "
                "fatigue signal, not a reason to push harder into it."
            ),
            target_sets=sets_count,
            target_reps=high,
            target_weight_kg=target,
            rep_range=(low, high),
            load_step_kg=step,
        )

    # 2. Regression: this session came in meaningfully under the exercise's
    #    best. Repeat rather than progress off a bad day.
    previous = history[-2]
    if (
        best is not None
        and current.best_e1rm_kg is not None
        and current.best_e1rm_kg < best * REGRESSION_MARGIN
        and previous.best_e1rm_kg is not None
        and current.best_e1rm_kg < previous.best_e1rm_kg
    ):
        return Recommendation(
            action="hold",
            headline=_prescription(sets_count, high, top_weight, unit),
            detail=(
                f"This session's best e1RM ({_fmt_kg(current.best_e1rm_kg, unit)}) came in "
                f"under both your best ({_fmt_kg(best, unit)}) and the session before it. "
                "Repeat the same load and target the top of the range before "
                "adding anything - one down session is sleep, food or stress far "
                "more often than lost strength."
            ),
            target_sets=sets_count,
            target_reps=high,
            target_weight_kg=top_weight,
            rep_range=(low, high),
            load_step_kg=step,
        )

    # 3. Double progression: top of the range on every working set earns load.
    if min(top_reps) >= high:
        if top_weight:
            target = _snap(top_weight + step, step)
            detail = (
                f"You hit {high}+ reps on {_sets_phrase(sets_count)} at "
                f"{_fmt_kg(top_weight, unit)}, the top of the {low}-{high} range. "
                f"Add {_fmt_kg(step, unit)} and restart at {_fmt_reps(low)}."
            )
        else:
            # Unloaded bodyweight work: adding external load is the progression.
            target = step
            detail = (
                f"You are at {min(top_reps)} reps on every set unweighted, the top of "
                f"the {low}-{high} range. Add {_fmt_kg(step, unit)} of external load and "
                f"restart at {_fmt_reps(low)}."
            )
        return Recommendation(
            action="add_load",
            headline=_prescription(sets_count, low, target, unit),
            detail=detail,
            target_sets=sets_count,
            target_reps=low,
            target_weight_kg=target,
            rep_range=(low, high),
            load_step_kg=step,
        )

    # 4. Otherwise the load stays and the reps climb.
    lagging = min(top_reps)
    return Recommendation(
        action="add_reps",
        headline=_prescription(sets_count, min(lagging + 1, high), top_weight, unit),
        detail=(
            f"Your worst set at {_fmt_kg(top_weight, unit) if top_weight else 'bodyweight'} "
            f"was {lagging} reps, short of the {high} that earns more load. Keep the "
            f"load and add a rep where you can; once {_sets_phrase(sets_count)} "
            f"{'reaches' if sets_count == 1 else 'reach'} {high}, the weight goes up."
        ),
        target_sets=sets_count,
        target_reps=min(lagging + 1, high),
        target_weight_kg=top_weight,
        rep_range=(low, high),
        load_step_kg=step,
    )


# -- workout assembly -------------------------------------------------------


@dataclass
class ExercisePrevious:
    """The last time this exercise was trained before the session in question."""

    workout_id: str
    date: str
    top_weight_kg: float | None
    top_reps: int | None
    top_set_count: int
    volume_kg: float
    best_e1rm_kg: float | None


@dataclass
class ExerciseBlock:
    template_id: str
    title: str
    muscle_group: str | None
    equipment: str | None
    order: int
    sets: list[PerformedSet]
    working_sets: int
    volume_kg: float
    top_weight_kg: float | None
    top_reps: int | None
    best_e1rm_kg: float | None
    #: Sessions on this exercise up to and including this one.
    sessions: int
    previous: ExercisePrevious | None
    e1rm_delta_kg: float | None
    volume_delta_pct: float | None
    #: This session set the exercise's best e1RM in the whole log.
    is_pr: bool
    recommendation: Recommendation


@dataclass
class RoutineContext:
    """Where this session sits among the other runs of the same routine."""

    title: str
    #: Total runs of this routine, this one included.
    runs: int
    #: 1-based position of this session among them, oldest first.
    run_index: int
    previous_id: str | None
    previous_date: str | None
    previous_volume_kg: float | None
    volume_delta_pct: float | None
    median_volume_kg: float | None


@dataclass
class WorkoutSummary:
    id: str
    title: str
    start_time: str
    end_time: str | None
    duration_minutes: float | None
    exercises: int
    sets: int
    volume_kg: float
    #: Runs of this routine, so the list page can show "Full B - run 10 of 10".
    routine_runs: int
    routine_index: int


@dataclass
class WorkoutDetail:
    id: str
    title: str
    start_time: str
    end_time: str | None
    duration_minutes: float | None
    sets: int
    volume_kg: float
    total_reps: int
    routine: RoutineContext
    exercises: list[ExerciseBlock] = field(default_factory=list)
    muscle_groups: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _duration(start: str, end: str | None) -> float | None:
    if not end:
        return None
    minutes = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60.0
    return round(minutes, 1) if minutes > 0 else None


def _routine_runs(db: Database) -> dict[str, list[tuple[str, str]]]:
    """Workout ids grouped by routine title, oldest first within each title."""
    rows = db.query("SELECT id, title, start_time FROM workouts ORDER BY start_time")
    runs: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        runs.setdefault(row["title"], []).append((row["id"], row["start_time"]))
    return runs


def list_workouts(db: Database, *, limit: int = 50, offset: int = 0) -> list[WorkoutSummary]:
    """Sessions newest first, each tagged with its place in its routine."""
    runs = _routine_runs(db)
    position = {
        workout_id: (index + 1, len(entries))
        for entries in runs.values()
        for index, (workout_id, _) in enumerate(entries)
    }

    rows = db.query(
        f"""
        SELECT w.id, w.title, w.start_time, w.end_time,
               COUNT(s.rowid)                    AS sets,
               COUNT(DISTINCT s.template_id)     AS exercises,
               COALESCE(SUM(COALESCE(s.weight_kg,0) * COALESCE(s.reps,0)), 0) AS volume
        FROM workouts w
        LEFT JOIN sets s
          ON s.workout_id = w.id AND {WORKING_SETS.replace('set_type', 's.set_type')}
        GROUP BY w.id
        ORDER BY w.start_time DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )

    summaries = []
    for row in rows:
        index, total = position.get(row["id"], (1, 1))
        summaries.append(
            WorkoutSummary(
                id=row["id"],
                title=row["title"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                duration_minutes=_duration(row["start_time"], row["end_time"]),
                exercises=int(row["exercises"]),
                sets=int(row["sets"]),
                volume_kg=round(float(row["volume"]), 1),
                routine_runs=total,
                routine_index=index,
            )
        )
    return summaries


def _muscle_breakdown(db: Database, workout_id: str) -> list[dict[str, Any]]:
    """Working sets per primary muscle group for one session.

    Primary only. The half-set secondary convention used for weekly volume is
    meaningful over a month; inside a single session it turns six honest sets
    into fractional noise.
    """
    rows = db.query(
        f"""
        SELECT COALESCE(t.primary_muscle_group, 'other') AS muscle_group,
               COUNT(*) AS sets,
               COALESCE(SUM(COALESCE(s.weight_kg,0) * COALESCE(s.reps,0)), 0) AS volume
        FROM sets s
        LEFT JOIN exercise_templates t ON t.id = s.template_id
        WHERE s.workout_id = ? AND {WORKING_SETS.replace('set_type', 's.set_type')}
        GROUP BY muscle_group
        ORDER BY sets DESC
        """,
        (workout_id,),
    )
    return [
        {
            "muscle_group": row["muscle_group"],
            "sets": int(row["sets"]),
            "volume_kg": round(float(row["volume"]), 1),
        }
        for row in rows
    ]


def _session_notes(detail_exercises: list[ExerciseBlock], routine: RoutineContext) -> list[str]:
    """Plain-language flags worth reading before the next run."""
    notes: list[str] = []

    prs = [e.title for e in detail_exercises if e.is_pr]
    if prs:
        listed = ", ".join(prs[:3])
        more = f" and {len(prs) - 3} more" if len(prs) > 3 else ""
        notes.append(f"Best-ever estimated 1RM on {listed}{more}.")

    stalled = [e.title for e in detail_exercises if e.recommendation.action == "deload"]
    if stalled:
        notes.append(
            f"{', '.join(stalled)} {'has' if len(stalled) == 1 else 'have'} stalled at "
            "a fixed load - the prescription backs off rather than pushing."
        )

    down = [
        e.title
        for e in detail_exercises
        if e.e1rm_delta_kg is not None and e.e1rm_delta_kg < -2.5
    ]
    if down:
        notes.append(
            f"Down against the previous session on {', '.join(down[:3])}. "
            "One session is noise; two in a row is a pattern."
        )

    if routine.volume_delta_pct is not None and abs(routine.volume_delta_pct) >= 25:
        direction = "above" if routine.volume_delta_pct > 0 else "below"
        notes.append(
            f"Session tonnage was {abs(routine.volume_delta_pct):.0f}% {direction} the "
            f"previous run of {routine.title}."
        )

    return notes


def workout_detail(db: Database, settings: Settings, workout_id: str) -> WorkoutDetail:
    """Full analysis of one session, with a prescription per exercise.

    Raises ``LookupError`` when the id is unknown.
    """
    workout = db.query_one(
        "SELECT id, title, start_time, end_time FROM workouts WHERE id = ?", (workout_id,)
    )
    if workout is None:
        raise LookupError(f"no workout with id {workout_id}")

    rows = db.query(
        f"""
        SELECT s.workout_id, s.start_time, s.exercise_index, s.set_index, s.template_id,
               s.exercise_title, s.set_type, s.weight_kg, s.reps, s.rpe,
               t.primary_muscle_group, t.equipment_category
        FROM sets s
        LEFT JOIN exercise_templates t ON t.id = s.template_id
        WHERE s.workout_id = ? AND {WORKING_SETS.replace('set_type', 's.set_type')}
        ORDER BY s.exercise_index, s.set_index
        """,
        (workout_id,),
    )

    by_exercise: dict[int, list[Any]] = {}
    for row in rows:
        by_exercise.setdefault(int(row["exercise_index"]), []).append(row)

    blocks: list[ExerciseBlock] = []
    for order, exercise_rows in sorted(by_exercise.items()):
        session = _exercise_session(exercise_rows)
        if session is None:
            continue

        # History up to and including this session, so a workout viewed months
        # later reads exactly as it did on the day.
        history = exercise_sessions(db, session.template_id, until=session.date)
        prior = [h for h in history if h.workout_id != workout_id]
        equipment = exercise_rows[0]["equipment_category"]

        previous = None
        e1rm_delta = None
        volume_delta = None
        if prior:
            last = prior[-1]
            previous = ExercisePrevious(
                workout_id=last.workout_id,
                date=last.date,
                top_weight_kg=last.top_weight_kg,
                top_reps=last.top_reps,
                top_set_count=last.top_set_count,
                volume_kg=last.volume_kg,
                best_e1rm_kg=last.best_e1rm_kg,
            )
            if session.best_e1rm_kg is not None and last.best_e1rm_kg is not None:
                e1rm_delta = round(session.best_e1rm_kg - last.best_e1rm_kg, 1)
            if last.volume_kg > 0:
                volume_delta = round(
                    (session.volume_kg - last.volume_kg) / last.volume_kg * 100.0, 1
                )

        earlier_best = [h.best_e1rm_kg for h in prior if h.best_e1rm_kg is not None]
        is_pr = bool(
            session.best_e1rm_kg is not None
            and (not earlier_best or session.best_e1rm_kg > max(earlier_best))
        )

        blocks.append(
            ExerciseBlock(
                template_id=session.template_id,
                title=session.title,
                muscle_group=exercise_rows[0]["primary_muscle_group"],
                equipment=equipment,
                order=order,
                sets=session.sets,
                working_sets=len(session.sets),
                volume_kg=session.volume_kg,
                top_weight_kg=session.top_weight_kg,
                top_reps=session.top_reps,
                best_e1rm_kg=session.best_e1rm_kg,
                sessions=len(history),
                previous=previous,
                e1rm_delta_kg=e1rm_delta,
                volume_delta_pct=volume_delta,
                is_pr=is_pr,
                recommendation=recommend(history, equipment=equipment, unit=settings.units),
            )
        )

    volume = round(sum(b.volume_kg for b in blocks), 1)
    total_sets = sum(b.working_sets for b in blocks)
    total_reps = sum(s.reps or 0 for b in blocks for s in b.sets)

    # Routine context: the same title is the only routine identity a CSV export
    # leaves us with.
    runs = _routine_runs(db).get(workout["title"], [])
    ids = [wid for wid, _ in runs]
    index = ids.index(workout_id) + 1 if workout_id in ids else 1

    previous_id = ids[index - 2] if index >= 2 else None
    previous_volume = None
    volume_delta_pct = None
    if previous_id:
        row = db.query_one(
            f"""
            SELECT COALESCE(SUM(COALESCE(weight_kg,0) * COALESCE(reps,0)), 0) AS volume
            FROM sets WHERE workout_id = ? AND {WORKING_SETS}
            """,
            (previous_id,),
        )
        previous_volume = round(float(row["volume"]), 1) if row else None
        if previous_volume:
            volume_delta_pct = round((volume - previous_volume) / previous_volume * 100.0, 1)

    other_volumes = [
        float(r["volume"])
        for r in db.query(
            f"""
            SELECT COALESCE(SUM(COALESCE(s.weight_kg,0) * COALESCE(s.reps,0)), 0) AS volume
            FROM workouts w JOIN sets s ON s.workout_id = w.id
            WHERE w.title = ? AND {WORKING_SETS.replace('set_type', 's.set_type')}
            GROUP BY w.id
            """,
            (workout["title"],),
        )
    ]

    routine = RoutineContext(
        title=workout["title"],
        runs=len(ids) or 1,
        run_index=index,
        previous_id=previous_id,
        previous_date=next((d for wid, d in runs if wid == previous_id), None),
        previous_volume_kg=previous_volume,
        volume_delta_pct=volume_delta_pct,
        median_volume_kg=round(median(other_volumes), 1) if other_volumes else None,
    )

    return WorkoutDetail(
        id=workout["id"],
        title=workout["title"],
        start_time=workout["start_time"],
        end_time=workout["end_time"],
        duration_minutes=_duration(workout["start_time"], workout["end_time"]),
        sets=total_sets,
        volume_kg=volume,
        total_reps=total_reps,
        routine=routine,
        exercises=blocks,
        muscle_groups=_muscle_breakdown(db, workout_id),
        notes=_session_notes(blocks, routine),
    )


# -- what to do next --------------------------------------------------------

#: Runs of a title before it counts as a routine rather than a one-off session.
#: The bar is deliberately low - two is a rotation slot, one is a holiday hotel
#: gym - but it has to exist, see :func:`_due_next`.
MIN_RUNS_FOR_ROUTINE = 2

#: How recently a routine must have been trained to count as part of the current
#: programme. Same four weeks, for the same reason, as the goal checks in
#: ``progression``: long enough to survive one missed session, short enough to
#: describe what the lifter is doing now rather than what they used to do.
ACTIVE_WINDOW_DAYS = 28

#: Names listed before a prescription summary says "and N more".
SUMMARY_NAMES = 2


@dataclass
class RoutineDue:
    """A routine, and how long it has been waiting."""

    title: str
    #: Most recent run, which the prescriptions are computed from.
    workout_id: str
    last_performed: str
    days_since: int
    runs: int


@dataclass
class NextSessionExercise:
    """One exercise's prescription, plus just enough of last time to trust it."""

    template_id: str
    title: str
    muscle_group: str | None
    equipment: str | None
    order: int
    last_top_weight_kg: float | None
    #: Best set at that load. Kept for continuity with the workout pages.
    last_top_reps: int | None
    last_top_set_count: int
    #: Every set at the top load, in the order performed. The prescription
    #: progresses the *worst* of these, so showing only the best one made a
    #: target of 11 look like a downgrade from a 12 that was really a 12 and a 10.
    last_top_set_reps: list[int]
    sessions: int
    recommendation: Recommendation


@dataclass
class NextSession:
    routine: RoutineDue
    exercises: list[NextSessionExercise]
    #: Every routine, most overdue first, so the view can switch between them.
    alternatives: list[RoutineDue]
    #: The prescriptions that change something, as one line each.
    changes: list[str] = field(default_factory=list)
    #: "Full B is up next - add weight on Squat and Bench Press."
    summary: str = ""


def routines_due(db: Database) -> list[RoutineDue]:
    """Every routine in the log, longest-unused first."""
    now = datetime.now(UTC)
    due = [
        RoutineDue(
            title=title,
            workout_id=entries[-1][0],
            last_performed=entries[-1][1],
            days_since=max(0, (now - datetime.fromisoformat(entries[-1][1])).days),
            runs=len(entries),
        )
        for title, entries in _routine_runs(db).items()
    ]
    return sorted(due, key=lambda routine: routine.last_performed)


def _due_next(ranked: list[RoutineDue]) -> RoutineDue:
    """The routine most overdue *within the current programme*.

    "Most overdue" on its own is wrong on a real log, and wrong in a way that
    looks plausible until you check it. A Hevy log accumulates titles: sessions
    Hevy auto-named "Afternoon workout", a week of hotel-gym improvising, a
    routine dropped three months ago. Every one of those is more overdue than
    anything you actually train, so the oldest entry is reliably the least
    relevant one. On the log this was built against it chose a twice-run title
    last trained 104 days ago, over the Full A / Full B pair the lifter was
    plainly alternating that week.

    So a candidate has to be both a routine (it repeats) and current (trained
    inside :data:`ACTIVE_WINDOW_DAYS`). Failing that there is no rotation to
    infer, and the most recently trained routine is the better guess: after a
    layoff you resume where you left off, and with one routine you repeat it.
    """
    current = [
        routine
        for routine in ranked
        if routine.runs >= MIN_RUNS_FOR_ROUTINE and routine.days_since <= ACTIVE_WINDOW_DAYS
    ]
    # `ranked` is oldest-first, so the most overdue current routine is first and
    # the most recently trained of anything is last.
    return current[0] if current else ranked[-1]


def _name_list(names: list[str]) -> str:
    """"Squat", "Squat and Bench", "Squat, Bench and 3 more"."""
    if len(names) <= SUMMARY_NAMES:
        return " and ".join(names)
    return f"{', '.join(names[:SUMMARY_NAMES])} and {len(names) - SUMMARY_NAMES} more"


def _summarise(title: str, exercises: list[NextSessionExercise]) -> str:
    """One line for the top of a dashboard: what actually changes next time."""
    by_action: dict[str, list[str]] = {}
    for exercise in exercises:
        by_action.setdefault(exercise.recommendation.action, []).append(exercise.title)

    parts = []
    if adds := by_action.get("add_load"):
        parts.append(f"add weight on {_name_list(adds)}")
    if reps := by_action.get("add_reps"):
        parts.append(f"chase reps on {_name_list(reps)}")
    if backs := by_action.get("deload"):
        parts.append(f"back off on {_name_list(backs)}")
    if not parts:
        parts.append("same weights as last time")

    label = title or "Your next session"
    return f"{label} is up next - {', and '.join(parts)}."


def next_session(
    db: Database, settings: Settings, *, title: str | None = None
) -> NextSession:
    """The prescriptions for the routine that is due, or for a named one.

    Raises ``LookupError`` when the log is empty or the title is unknown.
    """
    ranked = routines_due(db)
    if not ranked:
        raise LookupError("no workouts imported yet")

    if title is None:
        chosen = _due_next(ranked)
    else:
        found = next((routine for routine in ranked if routine.title == title), None)
        if found is None:
            raise LookupError(f"no routine titled {title!r}")
        chosen = found

    # The prescriptions already exist: a routine's next run is prescribed from
    # its last one, which is exactly what workout_detail computes.
    detail = workout_detail(db, settings, chosen.workout_id)
    exercises = [
        NextSessionExercise(
            template_id=block.template_id,
            title=block.title,
            muscle_group=block.muscle_group,
            equipment=block.equipment,
            order=block.order,
            last_top_weight_kg=block.top_weight_kg,
            last_top_reps=block.top_reps,
            last_top_set_count=sum(1 for s in block.sets if s.is_top),
            last_top_set_reps=[
                s.reps for s in block.sets if s.is_top and s.reps is not None
            ],
            sessions=block.sessions,
            recommendation=block.recommendation,
        )
        for block in detail.exercises
    ]

    changed = {"add_load", "add_reps", "deload"}
    return NextSession(
        routine=chosen,
        exercises=exercises,
        alternatives=ranked,
        changes=[
            f"{exercise.title}: {exercise.recommendation.headline}"
            for exercise in exercises
            if exercise.recommendation.action in changed
        ],
        summary=_summarise(chosen.title, exercises),
    )
