"""Tests for the HTTP layer.

Import and the profile get most of the attention: they are where the API adds
behaviour of its own - accepting an upload and choosing between it and the
workouts folder, and writing the lifter profile back to a dotenv file. The rest
of the routes are thin ``asdict`` wrappers over functions the other modules test
directly, so they are only checked for shape and for their error codes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevy_coach.api import app as api
from hevy_coach.config import PROFILE_FIELDS, Settings, get_settings
from tests.conftest import export_row, export_text, write_export


@pytest.fixture
def env_file(tmp_path: Path, export_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the real settings loader at this test's tmp_path.

    Deliberately not a `get_settings` dependency override returning a fixed
    object: saving a profile drops the settings cache so the *next* request
    rereads the file, and an override would hide exactly that. Nothing here may
    touch the developer's own .env or database.
    """
    path = tmp_path / ".env"
    monkeypatch.setitem(Settings.model_config, "env_file", (path,))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("WORKOUTS_DIR", str(export_dir))
    # A profile key exported in the developer's shell would outrank the .env and
    # make these tests pass or fail depending on whose machine they ran on.
    for field in PROFILE_FIELDS:
        monkeypatch.delenv(field.upper(), raising=False)

    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def client(env_file: Path) -> Iterator[TestClient]:
    yield TestClient(api.app)


def _upload(*rows: str) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("workouts.csv", export_text(*rows).encode(), "text/csv")}


# -- uploading --------------------------------------------------------------


def test_uploaded_export_is_imported(client: TestClient) -> None:
    response = client.post("/api/import", files=_upload(export_row(), export_row(set_index=1)))

    assert response.status_code == 200
    body = response.json()
    assert body["workouts"] == 1
    assert body["sets"] == 2
    assert "workouts.csv" in body["summary"]


def test_upload_is_kept_for_the_cli_to_find(client: TestClient, export_dir: Path) -> None:
    """The browser and the CLI have to read one history, not two."""
    client.post("/api/import", files=_upload(export_row()))

    assert [p.name for p in export_dir.glob("*.csv")] == ["workouts.csv"]


def test_upload_shows_up_in_health(client: TestClient) -> None:
    client.post("/api/import", files=_upload(export_row()))
    body = client.get("/api/health").json()

    assert body["workouts"] == 1
    assert body["imported_file"] == "workouts.csv"
    assert body["available_export"] == "workouts.csv"


def test_uploading_a_non_csv_is_rejected(client: TestClient, export_dir: Path) -> None:
    files = {"file": ("history.pdf", b"%PDF-1.4", "application/pdf")}
    response = client.post("/api/import", files=files)

    assert response.status_code == 422
    assert "not a CSV" in response.json()["detail"]
    assert list(export_dir.iterdir()) == []


def test_uploading_a_foreign_csv_is_rejected(client: TestClient) -> None:
    files = {"file": ("budget.csv", b"a,b,c\n1,2,3\n", "text/csv")}
    response = client.post("/api/import", files=files)

    # A 404 here would read as "no export to import", which is the opposite of
    # the truth: an export arrived and it was the wrong file.

    assert response.status_code == 422
    assert "does not look like a Hevy export" in response.json()["detail"]


def test_uploading_binary_gets_a_readable_error(client: TestClient) -> None:
    """A zip renamed to .csv must not surface as a raw UnicodeDecodeError."""
    files = {"file": ("export.csv", b"PK\x03\x04\xff\xfe\x00\x01", "text/csv")}
    response = client.post("/api/import", files=files)

    assert response.status_code == 422
    assert "not text" in response.json()["detail"]


def test_oversized_upload_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 16)
    response = client.post("/api/import", files=_upload(export_row()))

    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


# -- the folder path -------------------------------------------------------


def test_import_without_a_file_reads_the_folder(client: TestClient, export_dir: Path) -> None:
    write_export(export_dir / "workouts.csv", export_row())

    response = client.post("/api/import")

    assert response.status_code == 200
    assert response.json()["workouts"] == 1


def test_import_with_an_empty_folder_is_a_404(client: TestClient) -> None:
    response = client.post("/api/import")

    assert response.status_code == 404
    assert "No CSV export" in response.json()["detail"]


# -- the lifter profile -----------------------------------------------------


def test_a_bare_profile_reports_that_it_needs_setup(client: TestClient) -> None:
    body = client.get("/api/profile").json()

    assert body["needs_setup"] is True
    assert body["bodyweight_source"] == "default"
    assert body["bodyweight_kg"] == 80.0
    assert "bodyweight_kg" in body["unset"]


def test_saving_a_profile_writes_the_env_file(client: TestClient, env_file: Path) -> None:
    response = client.put(
        "/api/profile",
        json={
            "sex": "female",
            "bodyweight_kg": 61.5,
            "birth_date": "1995-06-01",
            "units": "lb",
            "dumbbell_load": "combined",
            "training_goal": "powerlifting",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["needs_setup"] is False
    assert body["bodyweight_source"] == "configured"
    assert body["bodyweight_kg"] == 61.5
    assert body["training_goal"] == "powerlifting"
    assert body["age"] is not None

    text = env_file.read_text()
    assert "BODYWEIGHT_KG=61.5" in text
    assert "TRAINING_GOAL=powerlifting" in text


def test_a_partial_save_leaves_the_rest_alone(client: TestClient) -> None:
    """The form saves one answer at a time; the others must not reset."""
    client.put("/api/profile", json={"sex": "female", "bodyweight_kg": 61.5})
    body = client.put("/api/profile", json={"units": "lb"}).json()

    assert body["units"] == "lb"
    assert body["sex"] == "female"
    assert body["configured_bodyweight_kg"] == 61.5


def test_a_saved_profile_reads_back(client: TestClient) -> None:
    client.put("/api/profile", json={"sex": "female", "bodyweight_kg": 61.5,
                                     "training_goal": "strength"})

    body = client.get("/api/profile").json()

    assert body["sex"] == "female"
    assert body["needs_setup"] is False


def test_an_empty_save_is_rejected(client: TestClient) -> None:
    response = client.put("/api/profile", json={})

    assert response.status_code == 422
    assert response.json()["detail"] == "Nothing to save."


def test_an_out_of_range_bodyweight_is_rejected(client: TestClient, env_file: Path) -> None:
    response = client.put("/api/profile", json={"bodyweight_kg": 5})

    assert response.status_code == 422
    assert not env_file.exists()


def test_an_unknown_sex_is_rejected(client: TestClient) -> None:
    response = client.put("/api/profile", json={"sex": "other"})

    assert response.status_code == 422


def test_the_profile_cannot_rewrite_unrelated_settings(
    client: TestClient, env_file: Path
) -> None:
    """`extra="forbid"` keeps the form from repointing the database or the API key."""
    response = client.put("/api/profile", json={"database_path": "/tmp/elsewhere.db"})

    assert response.status_code == 422


# -- the next session --------------------------------------------------------


def test_next_session_needs_a_log(client: TestClient) -> None:
    response = client.post("/api/import")  # nothing to import
    assert response.status_code == 404

    response = client.get("/api/next-session")

    assert response.status_code == 404
    assert "no workouts" in response.json()["detail"]


def test_next_session_prescribes_the_overdue_routine(client: TestClient) -> None:
    client.post("/api/import", files=_upload(*_history()))

    body = client.get("/api/next-session").json()

    assert body["routine"]["title"] == "Push"
    assert body["exercises"]
    assert body["exercises"][0]["recommendation"]["action"]
    assert body["summary"].startswith("Push is up next -")


def test_next_session_accepts_a_named_routine(client: TestClient) -> None:
    client.post("/api/import", files=_upload(*_history()))

    body = client.get("/api/next-session", params={"routine": "Pull"}).json()

    assert body["routine"]["title"] == "Pull"


def test_an_unknown_routine_is_a_404(client: TestClient) -> None:
    client.post("/api/import", files=_upload(*_history()))

    response = client.get("/api/next-session", params={"routine": "Legs"})

    assert response.status_code == 404


def _history() -> tuple[str, ...]:
    """Push/Pull alternating over six weeks, Pull most recently - so Push is due."""
    plan = (("Push", "Bench Press (Barbell)", 60.0), ("Pull", "Squat (Barbell)", 90.0))
    rows: list[str] = []
    for week in range(6):
        for offset, (title, exercise, base) in enumerate(plan):
            # Relative to today, so these stay inside the headline's 90-day
            # window however long the suite lives. Pull sits three days after
            # that week's Push, which makes Push the routine left waiting.
            start = datetime.now(UTC) - timedelta(days=(5 - week) * 7 + 3 - offset * 3)
            end = start + timedelta(hours=1)
            rows.extend(
                export_row(
                    title=title,
                    start=start.strftime("%Y-%m-%d %H:%M:%S"),
                    end=end.strftime("%Y-%m-%d %H:%M:%S"),
                    exercise=exercise,
                    set_index=index,
                    weight=f"{base + week * 2.5:g}",
                    reps="8",
                )
                for index in range(3)
            )
    return tuple(rows)
