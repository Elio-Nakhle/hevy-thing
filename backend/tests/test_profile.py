"""Tests for the lifter profile and the dotenv file it is written to.

The write path gets most of the attention because it edits a file the user also
edits by hand: losing their comments, or leaving a key assigned twice, would be
worse than not having a form at all.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hevy_coach import profile
from hevy_coach.config import PROFILE_FIELDS, Settings
from hevy_coach.profile import ProfileUpdate


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


# -- what counts as unset ---------------------------------------------------


def test_a_bare_profile_needs_setup() -> None:
    settings = _settings()

    assert profile.needs_setup(settings) is True
    assert set(settings.unset_profile_fields) == set(PROFILE_FIELDS)


def test_the_critical_three_are_enough_to_finish_setup() -> None:
    """Birth date, units and the dumbbell convention are refinements, not gates."""
    settings = _settings(sex="female", bodyweight_kg=62.0, training_goal="strength")

    assert profile.needs_setup(settings) is False
    assert set(settings.unset_profile_fields) == {"birth_date", "units", "dumbbell_load"}


def test_bodyweight_alone_is_not_enough() -> None:
    assert profile.needs_setup(_settings(bodyweight_kg=62.0)) is True


def test_a_logged_measurement_answers_the_bodyweight_question() -> None:
    """H1.3 will write these rows; a measured weight beats anything we can ask."""
    settings = _settings(sex="male", training_goal="strength")

    assert profile.needs_setup(settings, 84.2) is False


# -- describing -------------------------------------------------------------


def test_describe_marks_a_defaulted_bodyweight() -> None:
    described = profile.describe(_settings())

    assert described["bodyweight_kg"] == 80.0
    assert described["bodyweight_source"] == "default"
    assert described["needs_setup"] is True
    assert "bodyweight_kg" in described["unset"]


def test_describe_separates_the_measured_and_configured_bodyweight() -> None:
    """The form has to show what the user typed, not what the scale said."""
    described = profile.describe(_settings(bodyweight_kg=80.0), 86.4)

    assert described["bodyweight_kg"] == 86.4
    assert described["configured_bodyweight_kg"] == 80.0
    assert described["bodyweight_source"] == "measured"


def test_describe_carries_the_goal_in_words() -> None:
    described = profile.describe(_settings(training_goal="powerlifting"))

    assert described["training_goal"] == "powerlifting"
    assert "Squat, bench and deadlift" in described["training_goal_summary"]


# -- writing the dotenv file ------------------------------------------------


def test_writes_a_new_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    profile.write_env(env, {"BODYWEIGHT_KG": "82", "SEX": "female"})

    assert "BODYWEIGHT_KG=82" in env.read_text()
    assert "SEX=female" in env.read_text()


def test_updates_an_existing_assignment_in_place(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SEX=male\nBODYWEIGHT_KG=80\nUNITS=kg\n")

    profile.write_env(env, {"BODYWEIGHT_KG": "91.5"})

    assert env.read_text() == "SEX=male\nBODYWEIGHT_KG=91.5\nUNITS=kg\n"


def test_uncomments_a_commented_key_rather_than_duplicating_it(tmp_path: Path) -> None:
    """.env starts as a copy of .env.example, where every profile key is
    commented out. Appending below the comment would assign the key twice."""
    env = tmp_path / ".env"
    env.write_text("# --- lifter profile ---\n# BODYWEIGHT_KG=82\n# UNITS=kg\n")

    profile.write_env(env, {"BODYWEIGHT_KG": "74"})

    text = env.read_text()
    assert "BODYWEIGHT_KG=74" in text
    assert text.count("BODYWEIGHT_KG") == 1
    assert "# UNITS=kg" in text


def test_writes_to_the_assignment_that_actually_wins(tmp_path: Path) -> None:
    """The bug this ordering exists for. dotenv gives effect to the last
    assignment of a key, so writing to the first is a silent no-op whenever
    anything sits below it - which is where you land by copying .env.example,
    whose keys are all present and commented, then typing a value at the end."""
    env = tmp_path / ".env"
    env.write_text(
        "# TRAINING_GOAL=hypertrophy  # hypertrophy | strength | powerlifting\n"
        "\n"
        "TRAINING_GOAL=powerlifting\n"
    )

    profile.write_env(env, {"TRAINING_GOAL": "strength"})

    lines = env.read_text().splitlines()
    live = [line for line in lines if line.startswith("TRAINING_GOAL=")]
    assert live == ["TRAINING_GOAL=strength"]
    # The template line above it is documentation and stays commented.
    assert lines[0].startswith("# TRAINING_GOAL=")


def test_an_earlier_live_duplicate_is_commented_out(tmp_path: Path) -> None:
    """It was shadowed before the write and after it, but two live lines
    disagreeing about the same key next to a value we just wrote is a trap."""
    env = tmp_path / ".env"
    env.write_text("BODYWEIGHT_KG=70\nSEX=male\nBODYWEIGHT_KG=82\n")

    profile.write_env(env, {"BODYWEIGHT_KG": "91"})

    text = env.read_text()
    assert [line for line in text.splitlines() if line.startswith("BODYWEIGHT_KG=")] == [
        "BODYWEIGHT_KG=91"
    ]
    # Not deleted - the old value stays readable.
    assert "# BODYWEIGHT_KG=70" in text


def test_a_saved_profile_is_actually_what_loads_back(tmp_path: Path) -> None:
    """End to end over the duplicate case: the point of writing the file is
    that Settings reads back what was written."""
    env = tmp_path / ".env"
    env.write_text("# BODYWEIGHT_KG=82\nBODYWEIGHT_KG=70\n")

    profile.write_env(env, {"BODYWEIGHT_KG": "91"})

    assert Settings(_env_file=env).bodyweight_kg == 91.0  # type: ignore[call-arg]


def test_preserves_unrelated_lines_and_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# my notes\nANTHROPIC_API_KEY=sk-ant-secret\n\n# --- lifter profile ---\nSEX=male\n"
    )

    profile.write_env(env, {"SEX": "female"})

    text = env.read_text()
    assert "# my notes" in text
    assert "ANTHROPIC_API_KEY=sk-ant-secret" in text
    assert "SEX=female" in text


def test_keeps_the_trailing_comment_on_a_line_it_rewrites(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("UNITS=kg   # kg | lb - display only\n")

    profile.write_env(env, {"UNITS": "lb"})

    assert env.read_text() == "UNITS=lb  # kg | lb - display only\n"


def test_a_line_already_saying_the_right_thing_is_left_alone(tmp_path: Path) -> None:
    """No reformatting churn when the form saves a value that has not changed."""
    original = "SEX=male                  # male | female\n"
    env = tmp_path / ".env"
    env.write_text(original)

    profile.write_env(env, {"SEX": "male"})

    assert env.read_text() == original


def test_new_keys_are_appended_under_one_header(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant\n")

    profile.write_env(env, {"SEX": "male"})
    profile.write_env(env, {"UNITS": "lb"})

    text = env.read_text()
    assert text.count(profile.ENV_HEADER) == 1
    assert "SEX=male" in text
    assert "UNITS=lb" in text


def test_writes_end_with_a_newline(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SEX=male")  # no trailing newline

    profile.write_env(env, {"UNITS": "lb"})

    assert env.read_text().endswith("\n")


# -- rendering values -------------------------------------------------------


def test_update_renders_env_values() -> None:
    update = ProfileUpdate(
        sex="female",
        bodyweight_kg=61.5,
        birth_date=date(1995, 6, 1),
        units="lb",
        dumbbell_load="combined",
        training_goal="powerlifting",
    )

    assert update.env_values() == {
        "SEX": "female",
        "BODYWEIGHT_KG": "61.5",
        "BIRTH_DATE": "1995-06-01",
        "UNITS": "lb",
        "DUMBBELL_LOAD": "combined",
        "TRAINING_GOAL": "powerlifting",
    }


def test_a_whole_bodyweight_loses_its_decimal_point() -> None:
    """`80.0` in a config file a human reads should say `80`."""
    assert ProfileUpdate(bodyweight_kg=80.0).env_values() == {"BODYWEIGHT_KG": "80"}


def test_omitted_fields_are_not_written() -> None:
    assert ProfileUpdate(units="lb").env_values() == {"UNITS": "lb"}


@pytest.mark.parametrize("value", [0, 5, 20, 300, 900])
def test_an_impossible_bodyweight_is_rejected(value: float) -> None:
    """The bounds catch a typo or a value in the wrong field. They cannot catch
    pounds - 181 lb is 82 kg and also a real 181 kg lifter - so the form
    converts to kilograms before it sends anything here."""
    with pytest.raises(ValueError):
        ProfileUpdate(bodyweight_kg=value)


@pytest.mark.parametrize("value", [20.5, 55, 82.4, 180]) 
def test_a_plausible_bodyweight_is_accepted(value: float) -> None:
    assert ProfileUpdate(bodyweight_kg=value).bodyweight_kg == value


def test_an_unknown_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        ProfileUpdate(database_path="/etc/passwd")  # type: ignore[call-arg]


# -- choosing the file ------------------------------------------------------


def test_env_path_prefers_the_highest_precedence_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings applies its candidates in order, so a write to an earlier file
    would be silently shadowed by a later one."""
    low, high = tmp_path / "root.env", tmp_path / "cwd.env"
    low.write_text("SEX=male\n")
    high.write_text("SEX=female\n")
    monkeypatch.setitem(Settings.model_config, "env_file", (low, high))

    assert profile.env_path() == high


def test_env_path_falls_back_to_the_first_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "root.env"
    monkeypatch.setitem(Settings.model_config, "env_file", (first, tmp_path / "cwd.env"))

    assert profile.env_path() == first


# -- saving end to end ------------------------------------------------------


def test_save_reloads_the_settings_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("# BODYWEIGHT_KG=82\n")
    monkeypatch.setitem(Settings.model_config, "env_file", (env,))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "saved.db"))

    saved = profile.save(ProfileUpdate(bodyweight_kg=74.0, sex="female"))

    assert saved.bodyweight_kg == 74.0
    assert saved.sex == "female"
    assert saved.bodyweight_is_default is False
    assert "BODYWEIGHT_KG=74" in env.read_text()
