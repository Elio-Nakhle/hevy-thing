"""Tests for the coach's tool surface.

``Coach.ask`` needs a live model, so it is not exercised here. Everything the
model depends on to answer correctly is local and is: the tool definitions, what
the tools return, and the profile block that rides on the first user turn.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hevy_coach.coach.agent import _profile_block, build_tools
from hevy_coach.coach.prompts import SYSTEM
from hevy_coach.config import Settings
from hevy_coach.db import Database
from hevy_coach.hevy.models import BodyMeasurement


@pytest.fixture
def tools(db: Database, settings: Settings) -> dict[str, Any]:
    return {tool.name: tool for tool in build_tools(db, settings)}


class TestToolDefinitions:
    def test_every_tool_is_callable_and_described(self, tools: dict[str, Any]) -> None:
        assert tools
        for name, tool in tools.items():
            assert tool.description, f"{name} has no description for the model to read"
            assert tool.input_schema["type"] == "object"

    def test_tool_names_are_unique(self, db: Database, settings: Settings) -> None:
        """A duplicate name would make one of the pair unreachable."""
        names = [tool.name for tool in build_tools(db, settings)]
        assert len(names) == len(set(names))

    def test_every_tool_returns_json_with_its_defaults(self, tools: dict[str, Any]) -> None:
        for name, tool in tools.items():
            if name in {"get_exercise_history", "get_standard_thresholds"}:
                continue  # these two require an argument
            json.loads(tool.call({}))


class TestToolResults:
    def test_overview_reports_the_database(self, tools: dict[str, Any], db: Database) -> None:
        payload = json.loads(tools["get_overview"].call({}))
        assert payload["workouts"] == db.workout_count()
        assert payload["total_volume_kg"] > 0

    def test_exercise_history_returns_sessions(self, tools: dict[str, Any]) -> None:
        payload = json.loads(tools["get_exercise_history"].call({"template_id": "T_BENCH"}))
        assert payload
        assert "best_e1rm_kg" in payload[0]

    def test_unknown_exercise_reports_an_error_instead_of_raising(
        self, tools: dict[str, Any]
    ) -> None:
        """The model must be able to recover from a bad id, not crash the turn."""
        payload = json.loads(tools["get_exercise_history"].call({"template_id": "nope"}))
        assert "error" in payload

    def test_standard_thresholds_are_returned_for_a_known_lift(
        self, tools: dict[str, Any]
    ) -> None:
        payload = json.loads(tools["get_standard_thresholds"].call({"lift": "bench-press"}))
        assert payload["thresholds"]["elite"] > payload["thresholds"]["beginner"]

    def test_standard_thresholds_reports_an_unknown_lift(self, tools: dict[str, Any]) -> None:
        payload = json.loads(tools["get_standard_thresholds"].call({"lift": "not-a-lift"}))
        assert "error" in payload

    def test_lift_list_is_offered_so_the_model_can_pick_a_valid_one(
        self, tools: dict[str, Any]
    ) -> None:
        payload = json.loads(tools["list_standard_lifts"].call({}))
        assert "bench-press" in payload

    def test_benchmark_and_insights_are_available(self, tools: dict[str, Any]) -> None:
        assert json.loads(tools["get_benchmark"].call({}))["entries"]
        assert isinstance(json.loads(tools["get_insights"].call({})), list)


class TestProfileBlock:
    def test_carries_what_the_standards_need(self, db: Database, settings: Settings) -> None:
        block = _profile_block(db, settings)
        assert "sex: male" in block
        assert "bodyweight_kg: 80.0" in block
        assert "preferred_units: kg" in block
        assert f"workouts_logged: {db.workout_count()}" in block

    def test_prefers_a_logged_bodyweight_over_the_configured_one(
        self, db: Database, settings: Settings
    ) -> None:
        db.upsert_body_measurements([BodyMeasurement(date="2026-01-01", weight_kg=91.5)])

        block = _profile_block(db, settings)

        assert "bodyweight_kg: 91.5" in block
        assert "(from Hevy measurements)" in block

    def test_reports_the_configured_unit(self, db: Database, tmp_path: Any) -> None:
        settings = Settings(database_path=tmp_path / "u.db", units="lb")
        assert "preferred_units: lb" in _profile_block(db, settings)


class TestSystemPrompt:
    def test_is_a_static_cache_prefix(self) -> None:
        """Anything per-request must go in the user turn, or caching breaks."""
        assert SYSTEM
        assert "{" not in SYSTEM and "}" not in SYSTEM

    def test_tells_the_model_the_tools_speak_kilograms(self) -> None:
        assert "preferred_units" in SYSTEM
