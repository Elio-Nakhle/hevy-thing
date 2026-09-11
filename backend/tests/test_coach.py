"""Tests for the coach's tool surface and its two backends.

No live model runs here. Everything the model depends on to answer correctly is
local and is tested: the tool definitions, what the tools return, the profile
block that rides on the first user turn, and - for the CLI backend - the choice
between backends and the parsing either side of the CLI run.
"""

from __future__ import annotations

from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from hevy_coach.coach import ask, briefing, cache, cli_agent, compact
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

    def test_every_tool_answers_with_its_defaults(self, tools: dict[str, Any]) -> None:
        for name, tool in tools.items():
            if name in {"get_exercise_history", "get_standard_thresholds", "get_workout_plan"}:
                continue  # these require an argument
            assert tool.call({}).strip(), f"{name} returned nothing"

    def test_row_payloads_name_their_columns_once(self, tools: dict[str, Any]) -> None:
        """The whole point of the table format: keys in the header, not per row.

        Reverting a tool to a JSON dump of dataclasses would repeat the key on
        every row, which is three quarters of what a question used to cost.
        """
        for name in ("list_exercises", "get_exercise_trends", "get_personal_records"):
            payload = tools[name].call({})
            header, *rows = payload.splitlines()
            columns = header.split("|")

            assert {"id", "title"} <= set(columns)
            assert len(rows) > 1
            assert all(len(row.split("|")) == len(columns) for row in rows)
            # The field names appear in the header and nowhere else.
            assert payload.count("sessions") <= 1
            assert "template_id" not in payload


class TestToolResults:
    def test_overview_reports_the_database(self, tools: dict[str, Any], db: Database) -> None:
        payload = tools["get_overview"].call({})
        assert f"workouts={db.workout_count()}" in payload
        assert "total_volume_kg=" in payload

    def test_exercise_history_returns_sessions(self, tools: dict[str, Any]) -> None:
        header, *rows = tools["get_exercise_history"].call({"template_id": "T_BENCH"}).splitlines()
        assert header.split("|")[:2] == ["date", "e1rm"]
        assert rows

    def test_unknown_exercise_reports_an_error_instead_of_raising(
        self, tools: dict[str, Any]
    ) -> None:
        """The model must be able to recover from a bad id, not crash the turn."""
        assert tools["get_exercise_history"].call({"template_id": "nope"}).startswith("error:")

    def test_workout_plan_carries_a_prescription_per_exercise(
        self, tools: dict[str, Any]
    ) -> None:
        listed = tools["list_workouts"].call({"limit": 5}).splitlines()
        assert len(listed) > 1
        first = dict(zip(listed[0].split("|"), listed[1].split("|"), strict=True))

        payload = tools["get_workout_plan"].call({"workout_id": first["id"]})

        assert f"title={first['title']}" in payload
        exercises = payload.splitlines()[2:]
        columns = exercises[0].split("|")
        assert "action" in columns and "next" in columns
        action = columns.index("action")
        rows = [row.split("|") for row in exercises[1:] if "|" in row]
        assert rows
        assert all(row[action] for row in rows), "every exercise needs a prescription"

    def test_unknown_workout_reports_an_error_instead_of_raising(
        self, tools: dict[str, Any]
    ) -> None:
        assert tools["get_workout_plan"].call({"workout_id": "nope"}).startswith("error:")

    def test_standard_thresholds_are_returned_for_a_known_lift(
        self, tools: dict[str, Any]
    ) -> None:
        payload = tools["get_standard_thresholds"].call({"lift": "bench-press"})
        bands = dict(pair.split("=", 1) for pair in payload.splitlines()[1].split(" "))
        assert float(bands["elite"]) > float(bands["beginner"])

    def test_standard_thresholds_reports_an_unknown_lift(self, tools: dict[str, Any]) -> None:
        payload = tools["get_standard_thresholds"].call({"lift": "not-a-lift"})
        assert payload.startswith("error:")
        assert "bench-press" in payload, "the model needs to see what it could have asked for"

    def test_lift_list_is_offered_so_the_model_can_pick_a_valid_one(
        self, tools: dict[str, Any]
    ) -> None:
        assert "bench-press" in tools["list_standard_lifts"].call({}).split()

    def test_benchmark_scores_each_lift_without_repeating_the_thresholds(
        self, tools: dict[str, Any]
    ) -> None:
        payload = tools["get_benchmark"].call({})

        assert "overall_level=" in payload
        header = payload.splitlines()[1]
        assert header.startswith("title|lift|e1rm|level|score")
        assert len(payload.splitlines()) > 3
        # The five thresholds and the source URL were two thirds of this payload
        # and the model can ask for them per lift.
        assert "strengthlevel.com" not in payload
        assert "beginner=" not in payload

    def test_insights_state_their_numbers_in_the_line(self, tools: dict[str, Any]) -> None:
        lines = tools["get_insights"].call({}).splitlines()

        assert lines
        assert all(line.startswith("[") for line in lines)
        # `detail` already carries every number `evidence` used to repeat.
        assert "evidence" not in tools["get_insights"].call({})

    def test_insights_are_capped_and_ranked_by_severity(self, tools: dict[str, Any]) -> None:
        lines = tools["get_insights"].call({"limit": 3}).splitlines()

        assert len(lines) <= 3
        severities = [line.split("]")[0].lstrip("[") for line in lines]
        order = ["warning", "suggestion", "info"]
        assert severities == sorted(severities, key=order.index)


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


class TestBackendChoice:
    """Which model backend the machine can run, and how that gets reported."""

    @pytest.fixture(autouse=True)
    def no_ambient_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A developer's own key must not decide what these tests assert."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    def test_a_key_takes_the_api(self, settings: Settings) -> None:
        keyed = settings.model_copy(update={"anthropic_api_key": "sk-ant-test"})
        assert cli_agent.resolve_backend(keyed) == "api"

    def test_no_key_falls_back_to_the_local_cli(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_agent, "claude_cli", lambda: "/usr/local/bin/claude")
        assert cli_agent.resolve_backend(settings) == "cli"

    def test_neither_is_reported_rather_than_guessed(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_agent, "claude_cli", lambda: None)

        described = cli_agent.describe(settings)

        assert described["backend"] is None
        assert described["ready"] is False
        assert described["detail"], "the page has nothing to tell the user otherwise"

    def test_an_explicit_backend_is_not_second_guessed(self, settings: Settings) -> None:
        """A forced backend that then fails is more useful than a silent swap."""
        forced = settings.model_copy(
            update={"coach_backend": "cli", "anthropic_api_key": "sk-ant-test"}
        )
        assert cli_agent.resolve_backend(forced) == "cli"

    def test_build_coach_refuses_when_nothing_can_run(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_agent, "claude_cli", lambda: None)
        with pytest.raises(cli_agent.CoachUnavailable):
            cli_agent.build_coach(db, settings)

    def test_each_backend_names_itself(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_agent, "claude_cli", lambda: "/usr/local/bin/claude")
        assert cli_agent.build_coach(db, settings).backend == "cli"

        keyed = settings.model_copy(update={"anthropic_api_key": "sk-ant-test"})
        assert cli_agent.build_coach(db, keyed).backend == "api"


class TestCliToolBridge:
    """The CLI backend must offer exactly the tools the API backend defines."""

    def test_every_tool_crosses_over_intact(self, db: Database, settings: Settings) -> None:
        api = build_tools(db, settings)
        bridged = cli_agent._mcp_tools(db, settings)

        assert [tool.name for tool in bridged] == [tool.name for tool in api]
        for mcp_tool, api_tool in zip(bridged, api, strict=True):
            assert mcp_tool.description == api_tool.description
            assert mcp_tool.input_schema == api_tool.input_schema

    async def test_a_bridged_tool_returns_the_same_result(
        self, db: Database, settings: Settings
    ) -> None:
        overview = next(
            tool for tool in cli_agent._mcp_tools(db, settings) if tool.name == "get_overview"
        )

        payload = await overview.handler({})

        text = payload["content"][0]["text"]
        assert f"workouts={db.workout_count()}" in text

    def test_only_the_log_is_reachable(self, db: Database, settings: Settings) -> None:
        """No Bash, no Read, no Write - and only these tools pre-approved."""
        options = cli_agent.CliCoach(db, settings)._options(None)

        assert options.tools == []
        assert options.allowed_tools == [
            f"mcp__{cli_agent.SERVER}__{tool.name}" for tool in build_tools(db, settings)
        ]
        assert options.permission_mode == "dontAsk"
        assert options.system_prompt == SYSTEM
        assert options.strict_mcp_config is True


class TestCliAsk:
    """Reading a CLI run back into the same answer shape the API backend returns.

    The model itself is not exercised; `query` is replaced, because what can
    break here is the parsing either side of it.
    """

    @staticmethod
    def _transcript(**overrides: Any) -> list[Any]:
        result = {
            "subtype": "success",
            "duration_ms": 10,
            "duration_api_ms": 8,
            "is_error": False,
            "num_turns": 2,
            "session_id": "session-1",
            "stop_reason": "end_turn",
            "result": "Add 2.5 kg to your top set.",
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }
        result.update(overrides)
        return [
            AssistantMessage(
                content=[ToolUseBlock(id="t1", name="mcp__hevy__get_overview", input={})],
                model="claude-opus-5",
            ),
            AssistantMessage(
                content=[TextBlock(text="Add 2.5 kg to your top set.")], model="claude-opus-5"
            ),
            ResultMessage(**result),
        ]

    def _patch_query(
        self, monkeypatch: pytest.MonkeyPatch, messages: list[Any]
    ) -> dict[str, Any]:
        seen: dict[str, Any] = {}

        async def fake_query(*, prompt: str, options: Any) -> Any:
            seen["prompt"] = prompt
            seen["resume"] = options.resume
            for message in messages:
                yield message

        monkeypatch.setattr(cli_agent, "query", fake_query)
        return seen

    def test_answer_tools_and_session_come_back(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._patch_query(monkeypatch, self._transcript())

        result = cli_agent.CliCoach(db, settings).ask("What should I do next?")

        assert result["answer"] == "Add 2.5 kg to your top set."
        # The MCP prefix is an artefact of the transport, not something to show.
        assert result["tools_used"] == ["get_overview"]
        assert result["session_id"] == "session-1"
        assert result["usage"] == {
            "input_tokens": 10,
            "output_tokens": 3,
            "cache_read_input_tokens": 0,
        }
        assert "<lifter_profile>" in seen["prompt"]
        assert seen["resume"] is None

    def test_a_follow_up_resumes_and_does_not_repeat_the_profile(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._patch_query(monkeypatch, self._transcript())

        cli_agent.CliCoach(db, settings).ask("And squats?", session_id="session-1")

        assert seen["resume"] == "session-1"
        assert "<lifter_profile>" not in seen["prompt"]

    def test_a_failed_run_raises_instead_of_answering(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A CLI that is installed but not signed in must not look like advice."""
        self._patch_query(
            monkeypatch,
            self._transcript(is_error=True, subtype="error_during_execution", result=None),
        )

        with pytest.raises(RuntimeError, match="claude CLI"):
            cli_agent.CliCoach(db, settings).ask("What should I do next?")


class TestCompactFormat:
    """The cell rules are where the savings actually come from."""

    def test_nothing_is_written_for_nothing(self) -> None:
        assert compact.cell(None) == ""
        assert compact.cell(False) == ""
        assert compact.cell(True) == "y"

    def test_floats_lose_their_noise(self) -> None:
        assert compact.cell(60.833333) == "60.8"
        assert compact.cell(45.0) == "45"
        assert compact.cell(0.0) == "0"

    def test_timestamps_lose_the_time_nobody_asked_for(self) -> None:
        assert compact.cell("2026-09-08T19:44:00+00:00") == "2026-09-08"
        assert compact.cell("2026-09-08") == "2026-09-08"

    def test_the_delimiter_cannot_appear_in_a_cell(self) -> None:
        """Exercise titles are user-supplied, so this is not hypothetical."""
        assert compact.cell("Row | Machine") == "Row / Machine"

    def test_a_table_names_its_columns_once(self) -> None:
        rows = [{"a": 1, "b": 2.5}, {"a": 3, "b": None}]

        out = compact.table(rows, ["a", ("bee", "b")])

        assert out == "a|bee\n1|2.5\n3|"

    def test_a_column_can_be_computed(self) -> None:
        rows = [{"inner": {"deep": 7}}]

        out = compact.table(rows, [("deep", lambda row: row["inner"]["deep"])])

        assert out == "deep\n7"

    def test_an_empty_table_is_still_readable(self) -> None:
        assert compact.table([], ["a", "b"]) == "a|b"

    def test_fields_skip_what_is_missing(self) -> None:
        assert compact.fields({"a": 1, "b": None, "c": "x"}, ("a", "b", "c", "d")) == "a=1 c=x"


class TestBriefing:
    def test_carries_the_ground_a_question_starts_from(
        self, db: Database, settings: Settings
    ) -> None:
        text = briefing.build(db, settings)

        assert "<briefing>" in text and "</briefing>" in text
        assert f"workouts={db.workout_count()}" in text
        assert "## Trends" in text and "## Findings" in text and "## Standards" in text
        assert "trend" in text and "overall_level=" in text

    def test_is_capped_so_it_cannot_grow_into_the_thing_it_replaced(
        self, db: Database, settings: Settings
    ) -> None:
        """It exists to be cheaper than the three calls it saves.

        Those returned 5,743 tokens on a real log. A briefing that drifts past a
        few hundred stops being a saving, so the budget is a test, not a hope.
        """
        text = briefing.build(db, settings)

        assert len(text) < 4000, f"briefing is {len(text)} chars"
        assert len(text.splitlines()) < 40

    def test_says_when_the_bodyweight_is_a_placeholder(self, db: Database) -> None:
        """Every level is indexed on bodyweight, so the caveat rides along."""
        unset = Settings(_env_file=None, database_path=db.path)

        assert "placeholder bodyweight" in briefing.build(db, unset)

    def test_an_empty_log_still_briefs(self, empty_db: Database, settings: Settings) -> None:
        text = briefing.build(empty_db, settings)

        assert "workouts=0" in text
        assert "## Trends" not in text


class TestCacheKeys:
    def test_the_fingerprint_follows_the_log(self, db: Database, settings: Settings) -> None:
        before = cache.fingerprint(db, settings)
        assert cache.fingerprint(db, settings) == before, "must be stable to be a key"

        db.upsert_body_measurements([BodyMeasurement(date="2026-02-02", weight_kg=84.0)])

        assert cache.fingerprint(db, settings) != before

    def test_the_fingerprint_follows_the_profile(
        self, db: Database, settings: Settings
    ) -> None:
        """A profile edit rescales every level without touching a set."""
        before = cache.fingerprint(db, settings)

        assert cache.fingerprint(db, settings.model_copy(update={"bodyweight_kg": 91.0})) != before
        assert (
            cache.fingerprint(db, settings.model_copy(update={"training_goal": "strength"}))
            != before
        )
        assert cache.fingerprint(db, settings.model_copy(update={"units": "lb"})) != before

    def test_the_briefing_is_built_once_per_state(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        builds = []
        monkeypatch.setattr(
            cache.briefing_module, "build", lambda *a: builds.append(1) or "briefed"
        )
        cache._BRIEFINGS.clear()

        assert cache.briefing(db, settings) == "briefed"
        assert cache.briefing(db, settings) == "briefed"
        assert len(builds) == 1

        db.upsert_body_measurements([BodyMeasurement(date="2026-03-03", weight_kg=77.0)])
        cache.briefing(db, settings)

        assert len(builds) == 2, "a new import or profile has to rebuild it"

    def test_a_question_is_keyed_on_what_would_change_the_answer(self) -> None:
        base = {"state": "s1", "model": "m", "effort": "medium", "backend": "cli"}
        key = cache.answer_key("Is my volume balanced?", **base)

        # Wording that does not change the question shares the answer.
        assert cache.answer_key("  is my   VOLUME balanced? ", **base) == key
        # Anything that changes it does not.
        assert cache.answer_key("is my volume balanced", **base) != key
        assert cache.answer_key("Is my volume balanced?", **{**base, "state": "s2"}) != key
        assert cache.answer_key("Is my volume balanced?", **{**base, "model": "n"}) != key
        assert cache.answer_key("Is my volume balanced?", **{**base, "effort": "max"}) != key
        assert cache.answer_key("Is my volume balanced?", **{**base, "backend": "api"}) != key


class TestAnswerStore:
    def test_an_answer_reads_back(self, db: Database) -> None:
        db.put_coach_answer(
            "k1", fingerprint="f1", question="q", answer="a", tools_used=["get_overview"]
        )

        hit = db.get_coach_answer("k1")

        assert hit is not None
        assert hit["answer"] == "a"
        assert hit["tools_used"] == ["get_overview"]
        assert hit["created_at"]

    def test_a_miss_is_a_miss(self, db: Database) -> None:
        assert db.get_coach_answer("nope") is None

    def test_answers_about_an_older_log_are_dropped(self, db: Database) -> None:
        """Otherwise the table grows forever holding answers nothing can serve."""
        db.put_coach_answer("old", fingerprint="f1", question="q", answer="a", tools_used=[])

        db.put_coach_answer("new", fingerprint="f2", question="q", answer="b", tools_used=[])

        assert db.get_coach_answer("old") is None
        assert db.get_coach_answer("new") is not None


class TestAnswerPolicy:
    """Cheapest route first, and only the model can answer a conversation."""

    @pytest.fixture
    def model(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any, Any]]:
        """A stand-in backend that records what it was asked."""
        calls: list[tuple[str, Any, Any]] = []

        class Stub:
            backend = "cli"

            def ask(
                self, question: str, history: Any = None, session_id: Any = None
            ) -> dict[str, Any]:
                calls.append((question, history, session_id))
                return {
                    "answer": "the model's answer",
                    "tools_used": ["get_overview"],
                    "usage": {"input_tokens": 1},
                    "stop_reason": "end_turn",
                    "session_id": "s-1",
                }

        monkeypatch.setattr(ask.cli_agent, "build_coach", lambda db, settings: Stub())
        return calls

    def test_a_lookup_never_reaches_a_model(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unreachable(*_: Any) -> Any:
            raise AssertionError("a computed answer must not build a backend")

        monkeypatch.setattr(ask.cli_agent, "build_coach", unreachable)

        result = ask.answer(db, settings, "Is my volume distribution balanced?")

        assert result["backend"] == "computed"
        assert result["cached"] is False
        assert "sets/week" in result["answer"]
        assert result["usage"] == {}

    def test_a_coaching_question_goes_to_the_model_and_is_remembered(
        self, db: Database, settings: Settings, model: list[Any]
    ) -> None:
        first = ask.answer(db, settings, "What should I change this month?")

        assert first["backend"] == "cli"
        assert first["cached"] is False
        assert first["answer"] == "the model's answer"
        assert len(model) == 1

        second = ask.answer(db, settings, "What should I change this month?")

        assert second["cached"] is True
        assert second["answer"] == "the model's answer"
        assert second["tools_used"] == ["get_overview"]
        assert len(model) == 1, "the log has not changed, so neither has the answer"

    def test_a_changed_log_is_a_different_question(
        self, db: Database, settings: Settings, model: list[Any]
    ) -> None:
        ask.answer(db, settings, "What should I change this month?")

        db.upsert_body_measurements([BodyMeasurement(date="2026-04-04", weight_kg=88.0)])
        ask.answer(db, settings, "What should I change this month?")

        assert len(model) == 2

    def test_a_follow_up_always_reaches_the_model(
        self, db: Database, settings: Settings, model: list[Any]
    ) -> None:
        """Cheap routes answer a question, not a conversation."""
        ask.answer(db, settings, "Is my volume distribution balanced?", session_id="s-1")
        ask.answer(db, settings, "What should I change this month?", history=[{"role": "user"}])

        assert len(model) == 2
        assert model[0][2] == "s-1"

    def test_a_follow_up_is_not_remembered(
        self, db: Database, settings: Settings, model: list[Any]
    ) -> None:
        """Its answer depends on turns the key knows nothing about."""
        ask.answer(db, settings, "and squats?", session_id="s-1")

        assert ask.answer(db, settings, "and squats?", session_id="s-1")["cached"] is False
        assert len(model) == 2

    def test_a_refusal_is_not_worth_serving_twice(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Refusing:
            backend = "cli"

            def ask(self, *_: Any) -> dict[str, Any]:
                return {
                    "answer": "The request was declined: no",
                    "tools_used": [],
                    "usage": {},
                    "stop_reason": "refusal",
                    "session_id": None,
                }

        monkeypatch.setattr(ask.cli_agent, "build_coach", lambda db, settings: Refusing())

        ask.answer(db, settings, "What should I change this month?")

        assert ask.answer(db, settings, "What should I change this month?")["cached"] is False

    def test_no_backend_still_raises_for_a_question_needing_one(
        self, db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_agent, "claude_cli", lambda: None)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

        with pytest.raises(cli_agent.CoachUnavailable):
            ask.answer(db, settings, "What should I change this month?")
