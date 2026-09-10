"""FastAPI application serving analytics and the coach to the Nuxt frontend."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hevy_coach import csv_import, provenance
from hevy_coach import profile as profile_module
from hevy_coach.analytics import headline as headline_module
from hevy_coach.analytics import metrics, progression, session
from hevy_coach.analytics.benchmark import benchmark
from hevy_coach.analytics.powerlifting import total_report
from hevy_coach.analytics.standards import available_lifts, bands_for
from hevy_coach.coach.agent import Coach
from hevy_coach.config import Settings, get_settings
from hevy_coach.db import Database
from hevy_coach.goals import PROFILES

app = FastAPI(
    title="Hevy Coach API",
    version="0.1.0",
    description="Training analytics, strength-standard benchmarking, and an AI coach.",
)


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Database:
    return Database(settings.database_path)


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Database, Depends(get_db)]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- health & profile -------------------------------------------------------


@app.get("/api/health")
def health(db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "workouts": db.workout_count(),
        "last_workout": db.latest_workout_time(),
        "last_import": db.get_meta(csv_import.LAST_IMPORT_KEY),
        "imported_file": db.get_meta(csv_import.IMPORTED_FILE_KEY),
        "available_export": _available_export(settings),
    }


def _available_export(settings: Settings) -> str | None:
    """Name of the export the next import would pick up, if there is one."""
    try:
        return csv_import.latest_export(settings.workouts_dir).name
    except csv_import.ExportError:
        return None


@app.get("/api/profile")
def get_profile(db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    return profile_module.describe(settings, db.latest_bodyweight())


@app.put("/api/profile")
def put_profile(
    update: profile_module.ProfileUpdate, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    """Save the lifter profile to the .env file the CLI reads too.

    Omitted fields are left as they are, so the form can save one answer at a
    time without resetting the rest.
    """
    if not update.model_dump(exclude_none=True):
        raise HTTPException(status_code=422, detail="Nothing to save.")
    try:
        saved = profile_module.save(update)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not write {profile_module.env_path()}: {exc}",
        ) from exc
    return profile_module.describe(saved, db.latest_bodyweight())


@app.get("/api/goals")
def get_goals() -> list[dict[str, Any]]:
    """The training goals and what choosing each one changes.

    Served rather than restated in the frontend: these thresholds are training
    doctrine with reasons attached (see goals.py), and a second copy in the UI
    would drift from the one the analytics actually use.
    """
    return [
        {
            "name": goal.name,
            "summary": goal.summary,
            "low_weekly_sets": goal.low_weekly_sets,
            "min_heavy_sets_per_week": goal.min_heavy_sets_per_week,
            "min_main_lift_frequency": goal.min_main_lift_frequency,
            "main_lifts": list(goal.main_lifts),
            "tracks_total": goal.tracks_total,
        }
        for goal in PROFILES.values()
    ]


# -- import -----------------------------------------------------------------


#: An upload larger than this is refused before it is read into memory. A CSV
#: export of a decade of daily training is single-digit megabytes; anything at
#: this size is not a Hevy export.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


@app.post("/api/import")
async def run_import(
    db: DbDep,
    settings: SettingsDep,
    file: Annotated[
        UploadFile | None, File(description="A Hevy CSV export to upload and import")
    ] = None,
    prune: Annotated[
        bool, Query(description="Drop workouts the export no longer contains")
    ] = True,
) -> dict[str, Any]:
    """Import a Hevy CSV export.

    With a file, the upload is stored in the workouts folder and imported from
    there, so the browser and the CLI stay pointed at the same history. Without
    one, the newest export already in that folder is imported.
    """
    if file is not None and (file.size or 0) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB, "
            "which is far bigger than any Hevy export.",
        )
    data = await file.read() if file is not None else None

    try:
        # Parsing and the insert loop are both blocking, so keep them off the
        # event loop.
        result = await asyncio.to_thread(
            _import, settings, db, prune, None if data is None else (file.filename or "", data)
        )
    except csv_import.ExportError as exc:
        # An ExportError means two different things here: with an upload it is a
        # bad file the caller sent, without one it is an empty workouts folder.
        raise HTTPException(status_code=422 if data is not None else 404, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="That file is not text. Upload the CSV Hevy exports, not a zip or a PDF.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"import failed: {exc}") from exc
    return asdict(result) | {"summary": result.summary()}


def _import(
    settings: Settings,
    db: Database,
    prune: bool,
    upload: tuple[str, bytes] | None,
) -> csv_import.ImportResult:
    """Blocking half of :func:`run_import`, so one thread hop covers both steps."""
    path = csv_import.save_upload(settings.workouts_dir, *upload) if upload else None
    return csv_import.import_export(settings, db, path=path, prune=prune)


# -- analytics --------------------------------------------------------------


@app.get("/api/overview")
def get_overview(db: DbDep, days: int | None = None) -> dict[str, Any]:
    return asdict(metrics.overview(db, days=days))


@app.get("/api/volume/weekly")
def get_weekly_volume(db: DbDep, weeks: int = 52) -> list[dict[str, Any]]:
    return metrics.weekly_volume(db, weeks=weeks)


@app.get("/api/volume/muscle-groups")
def get_muscle_volume(db: DbDep, days: int = 28) -> list[dict[str, Any]]:
    return metrics.muscle_group_volume(db, days=days)


@app.get("/api/exercises")
def get_exercises(db: DbDep, days: int | None = 365) -> list[dict[str, Any]]:
    return [asdict(s) for s in metrics.exercise_summaries(db, days=days)]


@app.get("/api/exercises/{template_id}/history")
def get_exercise_history(
    db: DbDep, template_id: str, days: int | None = 365
) -> list[dict[str, Any]]:
    history = metrics.exercise_history(db, template_id, days=days)
    if not history:
        raise HTTPException(status_code=404, detail=f"no sets logged for {template_id}")
    return [asdict(p) for p in history]


@app.get("/api/records")
def get_records(db: DbDep, days: int | None = 365, limit: int = 25) -> list[dict[str, Any]]:
    return [asdict(r) for r in metrics.personal_records(db, days=days, limit=limit)]


@app.get("/api/trends")
def get_trends(db: DbDep, settings: SettingsDep, days: int = 180) -> list[dict[str, Any]]:
    return [asdict(t) for t in progression.exercise_trends(db, settings, days=days)]


@app.get("/api/insights")
def get_insights(db: DbDep, settings: SettingsDep, days: int = 180) -> list[dict[str, Any]]:
    return [asdict(i) for i in progression.insights(db, settings, days=days)]


@app.get("/api/headline")
def get_headline(
    db: DbDep, settings: SettingsDep, days: int = headline_module.DEFAULT_WINDOW_DAYS
) -> dict[str, Any]:
    """"Am I getting stronger, and what changes next session" in one sentence."""
    return asdict(headline_module.headline(db, settings, days=days))


@app.get("/api/glossary")
def get_glossary() -> dict[str, dict[str, Any]]:
    """Where every derived number comes from, and its plain-language name.

    One table serves both: the frontend renames the surface with ``plain`` and
    uses ``detail`` as the hover text, so a term's tooltip cannot describe
    something other than what the label says.
    """
    return provenance.glossary()


# -- sessions ---------------------------------------------------------------


@app.get("/api/workouts")
def get_workouts(db: DbDep, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    return [asdict(w) for w in session.list_workouts(db, limit=limit, offset=offset)]


@app.get("/api/workouts/{workout_id}")
def get_workout(db: DbDep, settings: SettingsDep, workout_id: str) -> dict[str, Any]:
    """One session with a per-exercise prescription for its next run."""
    try:
        return asdict(session.workout_detail(db, settings, workout_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/next-session")
def get_next_session(
    db: DbDep,
    settings: SettingsDep,
    routine: Annotated[
        str | None, Query(description="Prescribe this routine instead of the one due")
    ] = None,
) -> dict[str, Any]:
    """Prescriptions for the routine that is due - the phone-at-the-rack view."""
    try:
        return asdict(session.next_session(db, settings, title=routine))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class RoutineDismissal(BaseModel):
    # The title carries spaces, emoji and anything else Hevy allowed, so it goes
    # in the body rather than the path where it would need escaping both ways.
    title: str = Field(min_length=0, max_length=200)
    dismissed: bool = True


@app.put("/api/routines/dismissed")
def set_routine_dismissed(
    payload: RoutineDismissal, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    """Put a routine away, or bring it back.

    Trying a routine once is not a decision to keep it in the rotation, and the
    date heuristics cannot tell "I am done with this" from "I have not got to it
    yet". Returns the refreshed next session, since dismissing what is currently
    due changes what is due.
    """
    known = {routine.title for routine in session.routines_due(db)}
    if payload.title not in known:
        raise HTTPException(
            status_code=404, detail=f"no routine titled {payload.title!r} in the log"
        )

    db.set_routine_dismissed(payload.title, payload.dismissed)
    return asdict(session.next_session(db, settings))


# -- strength standards -----------------------------------------------------


@app.get("/api/standards")
def get_standards() -> dict[str, str]:
    return available_lifts()


@app.get("/api/standards/{lift}")
def get_standard(
    lift: str, settings: SettingsDep, db: DbDep, bodyweight_kg: float | None = None
) -> dict[str, Any]:
    weight = bodyweight_kg or db.latest_bodyweight() or settings.bodyweight_kg
    try:
        bands = bands_for(lift, sex=settings.sex, bodyweight_kg=weight, age=settings.age)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(bands)


@app.get("/api/total")
def get_total(db: DbDep, settings: SettingsDep, days: int | None = 365) -> dict[str, Any]:
    """The total of the goal's main lifts, and DOTS on the competition three.

    A *training* total: it sums estimated 1RMs, which flatter a lifter who never
    handles heavy singles, so it answers "where is my training total now" rather
    than "what would I total on the platform".
    """
    return asdict(total_report(db, settings, days=days))


@app.get("/api/benchmark")
def get_benchmark(db: DbDep, settings: SettingsDep, days: int | None = 365) -> dict[str, Any]:
    return asdict(benchmark(db, settings, days=days))


# -- coach ------------------------------------------------------------------


class CoachRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, Any]] | None = None


@app.post("/api/coach")
async def ask_coach(
    payload: CoachRequest, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    if db.workout_count() == 0:
        raise HTTPException(
            status_code=409,
            detail="No workouts imported yet. Run POST /api/import first.",
        )
    coach = Coach(db, settings)
    try:
        # The SDK client is synchronous and the tool loop is I/O-bound, so run it
        # off the event loop rather than blocking every other request.
        result = await asyncio.to_thread(coach.ask, payload.question, payload.history)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"coach failed: {exc}") from exc

    # `messages` carries raw SDK content blocks; the frontend only needs the answer.
    return {k: v for k, v in result.items() if k != "messages"}
