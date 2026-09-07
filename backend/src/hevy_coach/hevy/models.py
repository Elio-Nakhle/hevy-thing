"""The shapes a workout is stored in.

Field names follow the Hevy API's snake_case naming, which is also the shape
the CSV importer builds and the shape ``workouts.payload`` holds on disk. Every
metric is genuinely nullable - a set may record weight+reps, distance+duration,
or neither.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SetType = Literal["normal", "warmup", "dropset", "failure"]


class HevySet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    type: SetType = "normal"
    weight_kg: float | None = None
    reps: int | None = None
    distance_meters: float | None = None
    duration_seconds: float | None = None
    rpe: float | None = None
    custom_metric: float | None = None

    @property
    def is_working_set(self) -> bool:
        """Warm-ups are excluded from volume and best-set analysis."""
        return self.type != "warmup"


class HevyExercise(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    title: str = ""
    notes: str | None = None
    exercise_template_id: str = ""
    supersets_id: int | None = None
    sets: list[HevySet] = Field(default_factory=list)


class HevyWorkout(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str = ""
    routine_id: str | None = None
    description: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    exercises: list[HevyExercise] = Field(default_factory=list)

    @property
    def duration_seconds(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()


class ExerciseTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str = ""
    type: str = ""
    primary_muscle_group: str | None = None
    secondary_muscle_groups: list[str] = Field(default_factory=list)
    equipment_category: str | None = None
    is_custom: bool = False


class BodyMeasurement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str
    weight_kg: float | None = None
    lean_mass_kg: float | None = None
    fat_percent: float | None = None
