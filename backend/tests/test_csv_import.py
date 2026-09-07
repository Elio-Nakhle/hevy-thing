"""Tests for the Hevy CSV export importer."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hevy_coach.analytics import metrics
from hevy_coach.config import Settings
from hevy_coach.csv_import import (
    IMPORTED_FILE_KEY,
    LAST_IMPORT_KEY,
    ExportError,
    import_export,
    latest_export,
    parse_export,
    resolve_muscles,
)
from hevy_coach.db import Database

HEADER = (
    '"title","start_time","end_time","description","exercise_title","superset_id",'
    '"exercise_notes","set_index","set_type","weight_kg","reps","distance_km",'
    '"duration_seconds","rpe"'
)


def _row(
    *,
    title: str = "Full A",
    start: str = "Sep 1, 2026, 6:55 PM",
    end: str = "Sep 1, 2026, 7:54 PM",
    exercise: str = "Squat (Barbell)",
    set_index: int = 0,
    set_type: str = "normal",
    weight: str = "100",
    reps: str = "5",
    distance_km: str = "",
    duration: str = "",
    rpe: str = "",
) -> str:
    return (
        f'"{title}","{start}","{end}","","{exercise}",,"",{set_index},"{set_type}",'
        f"{weight},{reps},{distance_km},{duration},{rpe}"
    )


def _write(path: Path, *rows: str) -> Path:
    path.write_text("\n".join([HEADER, *rows]) + "\n")
    return path


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "workouts"
    directory.mkdir()
    return directory


# -- picking the file -------------------------------------------------------


def test_latest_export_picks_newest_file(export_dir: Path) -> None:
    old = _write(export_dir / "old.csv", _row())
    new = _write(export_dir / "new.csv", _row())
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))

    assert latest_export(export_dir) == new


def test_latest_export_breaks_ties_on_name(export_dir: Path) -> None:
    """Equal timestamps must still resolve to one stable choice."""
    first = _write(export_dir / "a.csv", _row())
    second = _write(export_dir / "b.csv", _row())
    for path in (first, second):
        os.utime(path, (1_000_000, 1_000_000))

    assert latest_export(export_dir) == second


def test_latest_export_ignores_other_extensions(export_dir: Path) -> None:
    (export_dir / "notes.txt").write_text("not an export")
    wanted = _write(export_dir / "workouts.csv", _row())

    assert latest_export(export_dir) == wanted


def test_latest_export_without_any_csv(export_dir: Path) -> None:
    with pytest.raises(ExportError, match="No CSV export"):
        latest_export(export_dir)


def test_latest_export_without_folder(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="No export folder"):
        latest_export(tmp_path / "missing")


# -- parsing ----------------------------------------------------------------


def test_parses_a_single_workout(export_dir: Path) -> None:
    path = _write(
        export_dir / "e.csv",
        _row(set_index=0, weight="60", reps="8"),
        _row(set_index=1, weight="80", reps="5"),
    )
    workouts, errors = parse_export(path)

    assert errors == []
    assert len(workouts) == 1
    workout = workouts[0]
    assert workout.title == "Full A"
    assert workout.duration_seconds == 59 * 60
    assert len(workout.exercises) == 1
    assert workout.exercises[0].exercise_template_id == "squat-barbell"
    assert [(s.weight_kg, s.reps) for s in workout.exercises[0].sets] == [(60.0, 8), (80.0, 5)]


def test_workout_id_is_derived_from_start_time(export_dir: Path) -> None:
    path = _write(export_dir / "e.csv", _row())
    workouts, _ = parse_export(path)

    assert workouts[0].id == "csv-20260901T185500"


def test_rows_split_into_workouts_by_start_time(export_dir: Path) -> None:
    path = _write(
        export_dir / "e.csv",
        _row(start="Sep 1, 2026, 6:55 PM", end="Sep 1, 2026, 7:54 PM"),
        _row(title="Full B", start="Sep 3, 2026, 6:00 PM", end="Sep 3, 2026, 7:00 PM"),
    )
    workouts, _ = parse_export(path)

    assert [w.title for w in workouts] == ["Full A", "Full B"]
    assert workouts[0].start_time < workouts[1].start_time


def test_repeated_exercise_stays_two_blocks(export_dir: Path) -> None:
    """A lift performed twice in one session must not collapse into one entry."""
    path = _write(
        export_dir / "e.csv",
        _row(exercise="Squat (Barbell)"),
        _row(exercise="Bench Press (Barbell)"),
        _row(exercise="Squat (Barbell)"),
    )
    workouts, _ = parse_export(path)

    titles = [e.title for e in workouts[0].exercises]
    assert titles == ["Squat (Barbell)", "Bench Press (Barbell)", "Squat (Barbell)"]


def test_bodyweight_sets_have_no_weight(export_dir: Path) -> None:
    path = _write(export_dir / "e.csv", _row(exercise="Pull Up", weight="", reps="10"))
    workouts, _ = parse_export(path)

    set_ = workouts[0].exercises[0].sets[0]
    assert set_.weight_kg is None
    assert set_.reps == 10


def test_distance_is_converted_to_meters(export_dir: Path) -> None:
    path = _write(
        export_dir / "e.csv",
        _row(exercise="Treadmill", weight="", reps="", distance_km="2.4", duration="630"),
    )
    workouts, _ = parse_export(path)

    set_ = workouts[0].exercises[0].sets[0]
    assert set_.distance_meters == 2400.0
    assert set_.duration_seconds == 630.0


def test_warmup_sets_keep_their_type(export_dir: Path) -> None:
    path = _write(export_dir / "e.csv", _row(set_type="warmup"))
    workouts, _ = parse_export(path)

    assert workouts[0].exercises[0].sets[0].type == "warmup"
    assert workouts[0].exercises[0].sets[0].is_working_set is False


def test_unknown_set_type_falls_back_to_normal(export_dir: Path) -> None:
    path = _write(export_dir / "e.csv", _row(set_type="long_interval"))
    workouts, _ = parse_export(path)

    assert workouts[0].exercises[0].sets[0].type == "normal"


def test_missing_end_time_is_tolerated(export_dir: Path) -> None:
    path = _write(export_dir / "e.csv", _row(end=""))
    workouts, _ = parse_export(path)

    assert workouts[0].end_time is None
    assert workouts[0].duration_seconds is None


def test_unparseable_row_is_reported_not_fatal(export_dir: Path) -> None:
    path = _write(
        export_dir / "e.csv",
        _row(start="not a date"),
        _row(),
    )
    workouts, errors = parse_export(path)

    assert len(workouts) == 1
    assert len(errors) == 1
    assert "unrecognised timestamp" in errors[0]


def test_iso_timestamps_are_accepted(export_dir: Path) -> None:
    path = _write(
        export_dir / "e.csv",
        _row(start="2026-09-01 18:55:00", end="2026-09-01 19:54:00"),
    )
    workouts, errors = parse_export(path)

    assert errors == []
    assert workouts[0].id == "csv-20260901T185500"


def test_foreign_csv_is_rejected(export_dir: Path) -> None:
    path = export_dir / "other.csv"
    path.write_text("a,b,c\n1,2,3\n")

    with pytest.raises(ExportError, match="does not look like a Hevy export"):
        parse_export(path)


# -- muscle groups ----------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "primary"),
    [
        ("Squat (Barbell)", "quadriceps"),
        ("Bench Press (Barbell)", "chest"),
        ("Deadlift (Barbell)", "hamstrings"),
        ("T Bar Row", "upper_back"),
        # "grip" must not beat the row rule, and "row" must not beat cardio.
        ("Seated Cable Row - V Grip (Cable)", "upper_back"),
        ("Rowing Machine", "cardio"),
        # "leg curl" must not resolve as a biceps curl.
        ("Lying Leg Curl (Machine)", "hamstrings"),
        ("Seated Palms Up Wrist Curl", "forearms"),
        ("Bicep Curl (Dumbbell)", "biceps"),
        ("Lat Pulldown (Cable)", "lats"),
        ("Pull Up", "lats"),
        ("Triceps Pushdown", "triceps"),
        ("Seated Calf Raise", "calves"),
        ("Lateral Raise (Dumbbell)", "shoulders"),
        ("Hip Abduction (Machine)", "abductors"),
        ("Hip Adduction (Machine)", "adductors"),
        ("Sit Up (Weighted)", "abdominals"),
        ("Shrug (Dumbbell)", "traps"),
        ("Back Extension (Machine)", "lower_back"),
    ],
)
def test_resolve_muscles(title: str, primary: str) -> None:
    assert resolve_muscles(title)[0] == primary


def test_isolation_work_has_no_secondaries() -> None:
    assert resolve_muscles("Triceps Pushdown")[1] == []


def test_unknown_exercise_resolves_to_nothing() -> None:
    assert resolve_muscles("Interpretive Dance (Barbell)") == (None, [])


# -- importing --------------------------------------------------------------


@pytest.fixture
def import_settings(tmp_path: Path, export_dir: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "import.db",
        workouts_dir=export_dir,
        sex="male",
        bodyweight_kg=80.0,
    )


def test_import_writes_workouts_sets_and_templates(
    import_settings: Settings, export_dir: Path
) -> None:
    _write(
        export_dir / "workouts.csv",
        _row(exercise="Squat (Barbell)", set_index=0),
        _row(exercise="Squat (Barbell)", set_index=1),
        _row(exercise="Bench Press (Barbell)", set_index=0),
    )
    db = Database(import_settings.database_path)

    result = import_export(import_settings, db)

    assert result.workouts == 1
    assert result.sets == 3
    assert result.exercises == 2
    assert result.unmapped == []
    assert db.workout_count() == 1
    assert db.query_one("SELECT COUNT(*) AS n FROM sets")["n"] == 3
    assert "workouts.csv" in result.summary()


def test_imported_templates_carry_muscle_groups(
    import_settings: Settings, export_dir: Path
) -> None:
    """The muscle-balance chart inner-joins on this, so it cannot be empty."""
    _write(export_dir / "workouts.csv", _row(exercise="Squat (Barbell)"))
    db = Database(import_settings.database_path)
    import_export(import_settings, db)

    row = db.query_one("SELECT * FROM exercise_templates WHERE id = 'squat-barbell'")
    assert row is not None
    assert row["primary_muscle_group"] == "quadriceps"
    assert "glutes" in row["secondary_muscle_groups"]
    assert row["equipment_category"] == "barbell"


def test_import_is_idempotent(import_settings: Settings, export_dir: Path) -> None:
    _write(export_dir / "workouts.csv", _row(), _row(set_index=1))
    db = Database(import_settings.database_path)

    import_export(import_settings, db)
    import_export(import_settings, db)

    assert db.workout_count() == 1
    assert db.query_one("SELECT COUNT(*) AS n FROM sets")["n"] == 2


def test_import_picks_up_the_newest_export(
    import_settings: Settings, export_dir: Path
) -> None:
    old = _write(export_dir / "old.csv", _row())
    new = _write(
        export_dir / "new.csv",
        _row(),
        _row(title="Full B", start="Sep 3, 2026, 6:00 PM", end="Sep 3, 2026, 7:00 PM"),
    )
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    db = Database(import_settings.database_path)

    result = import_export(import_settings, db)

    assert Path(result.file).name == "new.csv"
    assert db.workout_count() == 2


def test_import_prunes_workouts_absent_from_the_export(
    import_settings: Settings, export_dir: Path
) -> None:
    """An export is the full history, so a workout deleted in the app goes here too."""
    _write(
        export_dir / "workouts.csv",
        _row(),
        _row(title="Full B", start="Sep 3, 2026, 6:00 PM", end="Sep 3, 2026, 7:00 PM"),
    )
    db = Database(import_settings.database_path)
    import_export(import_settings, db)
    assert db.workout_count() == 2

    _write(export_dir / "workouts.csv", _row())
    result = import_export(import_settings, db)

    assert result.workouts_removed == 1
    assert db.workout_count() == 1


def test_prune_can_be_turned_off(import_settings: Settings, export_dir: Path) -> None:
    _write(
        export_dir / "workouts.csv",
        _row(),
        _row(title="Full B", start="Sep 3, 2026, 6:00 PM", end="Sep 3, 2026, 7:00 PM"),
    )
    db = Database(import_settings.database_path)
    import_export(import_settings, db)

    _write(export_dir / "workouts.csv", _row())
    result = import_export(import_settings, db, prune=False)

    assert result.workouts_removed == 0
    assert db.workout_count() == 2


def test_import_records_what_it_read(import_settings: Settings, export_dir: Path) -> None:
    _write(export_dir / "workouts.csv", _row())
    db = Database(import_settings.database_path)

    import_export(import_settings, db)

    assert db.get_meta(IMPORTED_FILE_KEY) == "workouts.csv"
    assert db.get_meta(LAST_IMPORT_KEY) is not None


def test_import_reports_unmapped_exercises(
    import_settings: Settings, export_dir: Path
) -> None:
    _write(export_dir / "workouts.csv", _row(exercise="Interpretive Dance (Barbell)"))
    db = Database(import_settings.database_path)

    result = import_export(import_settings, db)

    assert result.unmapped == ["Interpretive Dance (Barbell)"]


def test_import_of_an_empty_export(import_settings: Settings, export_dir: Path) -> None:
    _write(export_dir / "workouts.csv")
    db = Database(import_settings.database_path)

    with pytest.raises(ExportError, match="no workouts"):
        import_export(import_settings, db)


def test_muscle_volume_works_off_an_import(
    import_settings: Settings, export_dir: Path
) -> None:
    """End to end: the CSV has no muscle data, but the breakdown still fills in."""
    _write(
        export_dir / "workouts.csv",
        _row(exercise="Squat (Barbell)", weight="100", reps="5"),
        _row(exercise="Bench Press (Barbell)", weight="80", reps="5"),
    )
    db = Database(import_settings.database_path)
    import_export(import_settings, db)

    breakdown = {row["muscle_group"]: row for row in metrics.muscle_group_volume(db, days=28)}

    assert breakdown["quadriceps"]["sets"] == 1.0
    assert breakdown["quadriceps"]["volume_kg"] == 500.0
    assert breakdown["chest"]["volume_kg"] == 400.0
    # Squat's secondaries count half a set each.
    assert breakdown["glutes"]["sets"] == 0.5
