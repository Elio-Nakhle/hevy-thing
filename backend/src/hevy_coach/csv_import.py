"""Load training history from a Hevy CSV export.

Hevy's developer API needs a Pro subscription; the CSV export (Settings ->
Export Data) does not, so it is what this project ingests. Drop exports into
``workouts_dir`` and the newest file there is the one that gets imported - no
renaming, no configuration per export. An export uploaded through the web UI
lands in the same folder (see ``save_upload``), so the browser and the CLI read
from one place rather than two.

Two things the CSV lacks and this module reconstructs:

* **Identity.** There are no workout or exercise-template ids, so both are
  derived deterministically (start time for a workout, a slug of the title for
  an exercise). Re-importing an export therefore updates rows rather than
  duplicating them.
* **Muscle groups.** The API serves these per exercise template and the export
  omits them entirely, so they come from ``data/muscle_map.json``. Without them
  the muscle-balance chart and the volume-balance insights have nothing to join
  against.

An export is the complete history, so anything in the database that is absent
from the file has been deleted in the app and is pruned to match.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from hevy_coach.config import DATA_DIR, Settings
from hevy_coach.db import Database
from hevy_coach.hevy.models import ExerciseTemplate, HevyExercise, HevySet, HevyWorkout

LAST_IMPORT_KEY = "last_import_at"
IMPORTED_FILE_KEY = "last_import_file"

#: Hevy writes local wall-clock time with no offset, e.g. "Sep 1, 2026, 6:55 PM".
#: The 24-hour variants cover exports made with a non-English locale setting.
TIME_FORMATS = (
    "%b %d, %Y, %I:%M %p",
    "%d %b %Y, %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)

SET_TYPES = {"normal", "warmup", "dropset", "failure"}

#: Equipment inferred from the trailing parenthetical Hevy puts on most titles.
EQUIPMENT = ("barbell", "dumbbell", "machine", "cable", "kettlebell", "smith machine",
             "resistance band", "weighted", "assisted", "bodyweight", "plate")


class ExportError(Exception):
    """The export folder is empty, or the file is not a Hevy CSV export."""


@dataclass
class ImportResult:
    file: str
    workouts: int = 0
    sets: int = 0
    exercises: int = 0
    workouts_removed: int = 0
    #: Titles that matched no rule in the muscle map, so they land in "other".
    unmapped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"Imported {self.workouts} workouts", f"{self.sets} sets"]
        if self.exercises:
            parts.append(f"{self.exercises} exercises")
        if self.workouts_removed:
            parts.append(f"{self.workouts_removed} removed")
        return f"{', '.join(parts)} from {Path(self.file).name}"


# -- locating the export ----------------------------------------------------


def latest_export(directory: Path) -> Path:
    """The most recently added CSV in ``directory``.

    Newest modification time wins; the filename breaks ties so the choice is
    stable when a batch of files shares a timestamp.
    """
    if not directory.is_dir():
        raise ExportError(f"No export folder at {directory}")

    candidates = [p for p in directory.glob("*.csv") if p.is_file()]
    if not candidates:
        raise ExportError(
            f"No CSV export in {directory}. Export from Hevy "
            "(Profile -> Settings -> Export Data) and save the file there."
        )
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


# -- accepting an upload ----------------------------------------------------


def _upload_name(filename: str) -> str:
    """A filesystem-safe name for an uploaded export.

    Only the basename survives, so a crafted ``../`` path cannot escape the
    workouts folder, and only ``[A-Za-z0-9._-]`` survives that.
    """
    name = Path(filename or "").name
    if not name.lower().endswith(".csv"):
        raise ExportError(
            f"{name or 'That file'} is not a CSV. Export from Hevy "
            "(Profile -> Settings -> Export Data) and upload the file it gives you."
        )
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name[:-4]).strip("-._")
    return f"{stem or 'export'}.csv"


def save_upload(directory: Path, filename: str, data: bytes) -> Path:
    """Store an uploaded export in ``directory`` and return where it landed.

    Written to a hidden ``.part`` file and parsed before it is moved into place,
    for two reasons: a name collision replaces a good export with a newer one
    only once the newer one is known to be readable, and a half-written or
    non-Hevy file never becomes what the next folder import picks up. The
    staging name is dot-prefixed and not ``*.csv``, so :func:`latest_export`
    would not see it even if the process died mid-write.
    """
    name = _upload_name(filename)
    directory.mkdir(parents=True, exist_ok=True)
    staged = directory / f".{name}.part"

    try:
        staged.write_bytes(data)
        workouts, _ = parse_export(staged)
        if not workouts:
            raise ExportError(f"{name} contains no workouts.")
    except ExportError as exc:
        staged.unlink(missing_ok=True)
        # parse_export names the file it was handed, which is the staging name.
        # The uploader has never heard of it, so say the name they chose.
        raise ExportError(str(exc).replace(staged.name, name)) from exc
    except Exception:
        staged.unlink(missing_ok=True)
        raise

    target = directory / name
    staged.replace(target)
    return target


# -- muscle groups ----------------------------------------------------------


@lru_cache
def load_muscle_map() -> dict[str, Any]:
    with (DATA_DIR / "muscle_map.json").open() as handle:
        return json.load(handle)


@lru_cache
def _compiled_rules() -> list[tuple[re.Pattern[str], str, tuple[str, ...]]]:
    rules = []
    for rule in load_muscle_map()["rules"]:
        pattern = re.compile("|".join(rule["match"]))
        rules.append((pattern, rule["primary"], tuple(rule.get("secondary", ()))))
    return rules


def resolve_muscles(title: str) -> tuple[str | None, list[str]]:
    """Primary and secondary muscle groups for an exercise title.

    Returns ``(None, [])`` when nothing matches, which surfaces as "other" in
    the volume breakdown rather than silently attaching to a real muscle.
    """
    normalised = title.strip().lower()

    override = load_muscle_map()["overrides"].get(normalised)
    if override is not None:
        return override.get("primary"), list(override.get("secondary", []))

    for pattern, primary, secondary in _compiled_rules():
        if pattern.search(normalised):
            return primary, list(secondary)
    return None, []


# -- parsing ----------------------------------------------------------------


def _slug(title: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.strip().lower())).strip("-")


def _parse_time(value: str) -> datetime:
    text = (value or "").strip()
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"unrecognised timestamp {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _number(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(value: str) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _equipment(title: str) -> str | None:
    lowered = title.lower()
    return next((name for name in EQUIPMENT if f"({name})" in lowered), None)


def _template(title: str) -> ExerciseTemplate:
    primary, secondary = resolve_muscles(title)
    return ExerciseTemplate(
        id=_slug(title),
        title=title,
        type="weight_reps",
        primary_muscle_group=primary,
        secondary_muscle_groups=secondary,
        equipment_category=_equipment(title),
        is_custom=False,
    )


def parse_export(path: Path) -> tuple[list[HevyWorkout], list[str]]:
    """Read an export into workouts, newest last, plus any per-row errors.

    Rows are already grouped by workout and ordered within it, so a change of
    exercise title starts a new exercise block. That keeps an exercise performed
    twice in one session as two entries instead of merging them.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "start_time" not in reader.fieldnames:
            raise ExportError(
                f"{path.name} does not look like a Hevy export "
                "(no 'start_time' column)."
            )
        rows = list(reader)

    workouts: dict[str, HevyWorkout] = {}
    errors: list[str] = []

    for line, row in enumerate(rows, start=2):
        try:
            start = _parse_time(row["start_time"])
        except ValueError as exc:
            errors.append(f"line {line}: {exc}")
            continue

        title = (row.get("title") or "").strip()
        workout_id = f"csv-{start:%Y%m%dT%H%M%S}"
        workout = workouts.get(workout_id)
        if workout is None:
            end = None
            if (row.get("end_time") or "").strip():
                try:
                    end = _parse_time(row["end_time"])
                except ValueError:
                    end = None
            workout = HevyWorkout(
                id=workout_id,
                title=title,
                description=(row.get("description") or "").strip() or None,
                start_time=start,
                end_time=end,
            )
            workouts[workout_id] = workout

        exercise_title = (row.get("exercise_title") or "").strip()
        if not exercise_title:
            errors.append(f"line {line}: no exercise_title")
            continue

        exercise = workout.exercises[-1] if workout.exercises else None
        if exercise is None or exercise.title != exercise_title:
            exercise = HevyExercise(
                index=len(workout.exercises),
                title=exercise_title,
                notes=(row.get("exercise_notes") or "").strip() or None,
                exercise_template_id=_slug(exercise_title),
                supersets_id=_int(row.get("superset_id", "")),
            )
            workout.exercises.append(exercise)

        set_type = (row.get("set_type") or "normal").strip().lower()
        distance_km = _number(row.get("distance_km", ""))
        exercise.sets.append(
            HevySet(
                index=_int(row.get("set_index", "")) or 0,
                type=set_type if set_type in SET_TYPES else "normal",
                weight_kg=_number(row.get("weight_kg", "")),
                reps=_int(row.get("reps", "")),
                distance_meters=distance_km * 1000 if distance_km is not None else None,
                duration_seconds=_number(row.get("duration_seconds", "")),
                rpe=_number(row.get("rpe", "")),
            )
        )

    ordered = sorted(workouts.values(), key=lambda w: w.start_time)
    return ordered, errors


# -- import -----------------------------------------------------------------


def _titles(workouts: Iterable[HevyWorkout]) -> Iterator[str]:
    seen: set[str] = set()
    for workout in workouts:
        for exercise in workout.exercises:
            if exercise.title not in seen:
                seen.add(exercise.title)
                yield exercise.title


def import_export(
    settings: Settings,
    db: Database,
    *,
    path: Path | None = None,
    prune: bool = True,
) -> ImportResult:
    """Import a Hevy CSV export, defaulting to the newest one in the folder."""
    source = path or latest_export(settings.workouts_dir)
    workouts, errors = parse_export(source)
    if not workouts:
        raise ExportError(f"{source.name} contains no workouts.")

    result = ImportResult(file=str(source), errors=errors)

    titles = list(_titles(workouts))
    result.exercises = db.upsert_templates([_template(title) for title in titles])
    result.unmapped = [title for title in titles if resolve_muscles(title)[0] is None]

    result.workouts = db.upsert_workouts(workouts)
    result.sets = sum(len(e.sets) for w in workouts for e in w.exercises)

    if prune:
        keep = {workout.id for workout in workouts}
        stale = [row["id"] for row in db.query("SELECT id FROM workouts") if row["id"] not in keep]
        for workout_id in stale:
            db.delete_workout(workout_id)
        result.workouts_removed = len(stale)

    db.set_meta(LAST_IMPORT_KEY, datetime.now(UTC).isoformat())
    db.set_meta(IMPORTED_FILE_KEY, source.name)
    return result
