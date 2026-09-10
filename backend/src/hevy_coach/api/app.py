"""FastAPI application serving analytics and the coach to the Nuxt frontend."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hevy_coach import csv_import
from hevy_coach.analytics import metrics, progression, session
from hevy_coach.analytics.benchmark import benchmark
from hevy_coach.analytics.standards import available_lifts, bands_for
from hevy_coach.coach.agent import Coach
from hevy_coach.config import Settings, get_settings
from hevy_coach.db import Database

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
def profile(db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    measured = db.latest_bodyweight()
    return {
        "sex": settings.sex,
        "bodyweight_kg": measured or settings.bodyweight_kg,
        "bodyweight_source": "measured" if measured else "configured",
        "age": round(settings.age, 1) if settings.age else None,
        "units": settings.units,
        "coach_model": settings.coach_model,
    }


# -- import -----------------------------------------------------------------


@app.post("/api/import")
async def run_import(
    db: DbDep,
    settings: SettingsDep,
    prune: Annotated[
        bool, Query(description="Drop workouts the export no longer contains")
    ] = True,
) -> dict[str, Any]:
    """Import the newest CSV export in the workouts folder."""
    try:
        # Parsing and the insert loop are both blocking, so keep them off the
        # event loop.
        result = await asyncio.to_thread(csv_import.import_export, settings, db, prune=prune)
    except csv_import.ExportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"import failed: {exc}") from exc
    return asdict(result) | {"summary": result.summary()}


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
