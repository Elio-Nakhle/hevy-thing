"""The coach, run through the local `claude` CLI instead of an API key.

Same tools, same system prompt as `agent.Coach` - the only difference is where
the model runs. The Claude Agent SDK spawns the `claude` binary on this machine
and the conversation authenticates as that CLI's own login, so no
ANTHROPIC_API_KEY is involved. The read-only training-log tools are handed over
as an in-process MCP server and every built-in Claude Code tool is switched
off, so the model can reach the log and nothing else - no shell, no files.

This module also owns the choice between the two backends, because it is the
one that knows what the machine can actually run.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
from pathlib import Path
from typing import Any, Literal

import claude_agent_sdk
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    McpToolAnnotations,
    ResultMessage,
    SdkMcpTool,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
)

from hevy_coach.coach.agent import MAX_TURNS, Coach, build_tools, first_turn_context
from hevy_coach.coach.prompts import SYSTEM
from hevy_coach.config import Settings
from hevy_coach.db import Database

Backend = Literal["api", "cli"]

#: Name of the in-process MCP server. The CLI presents each of its tools as
#: `mcp__<server>__<tool>`, and that prefixed name is what gets allow-listed.
SERVER = "hevy"

UNAVAILABLE = (
    "The coach needs either an Anthropic API key or the Claude Code CLI. "
    "Install Claude Code and run `claude` once to sign in, or set "
    "ANTHROPIC_API_KEY in .env."
)


class CoachUnavailable(RuntimeError):
    """Neither backend is usable on this machine, so there is nothing to ask."""


# -- which backend ----------------------------------------------------------


def claude_cli() -> str | None:
    """Path to a `claude` binary, in the order the SDK's transport tries them.

    The SDK ships a bundled binary, so this normally resolves even when nothing
    is on PATH - which is why "is the CLI there" is a question about the
    executable and not about the dependency being installed.
    """
    name = "claude.exe" if platform.system() == "Windows" else "claude"
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / name
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name)


def has_api_credential(settings: Settings) -> bool:
    """Whether the Anthropic SDK has a credential to authenticate with.

    `Settings.anthropic_api_key` already reads ANTHROPIC_API_KEY from the
    environment as well as from .env; ANTHROPIC_AUTH_TOKEN is the other key the
    SDK's own chain accepts.
    """
    return bool(settings.anthropic_api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def resolve_backend(settings: Settings) -> Backend | None:
    """The backend to run, or None when the machine can run neither.

    An explicit COACH_BACKEND is taken at its word - if it names a backend that
    then fails, the error is more useful than a silent fallback.
    """
    if settings.coach_backend != "auto":
        return settings.coach_backend
    if has_api_credential(settings):
        return "api"
    return "cli" if claude_cli() else None


def describe(settings: Settings) -> dict[str, Any]:
    """What the coach can run right now, for the UI to explain itself with."""
    backend = resolve_backend(settings)
    return {
        "backend": backend,
        "ready": backend is not None,
        "model": settings.coach_model,
        "effort": settings.coach_effort,
        "api_key_configured": has_api_credential(settings),
        "claude_cli_available": claude_cli() is not None,
        "detail": None if backend else UNAVAILABLE,
    }


def build_coach(db: Database, settings: Settings) -> Coach | CliCoach:
    """The coach this machine can run. Both share an `ask` signature."""
    backend = resolve_backend(settings)
    if backend == "api":
        return Coach(db, settings)
    if backend == "cli":
        return CliCoach(db, settings)
    raise CoachUnavailable(UNAVAILABLE)


# -- the CLI backend --------------------------------------------------------


def _mcp_tools(db: Database, settings: Settings) -> list[SdkMcpTool[Any]]:
    """The API backend's tools, republished as in-process MCP tools.

    `build_tools` returns Anthropic SDK function tools, which already carry a
    name, a description and a JSON schema inferred from the signature. Handing
    those straight over keeps one definition of each tool rather than a second
    one that can drift.
    """
    read_only = McpToolAnnotations(readOnlyHint=True)

    def adapt(fn: Any) -> SdkMcpTool[Any]:
        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            # The tools query SQLite synchronously; keep the event loop free.
            text = await asyncio.to_thread(fn.call, args)
            return {"content": [{"type": "text", "text": text}]}

        return SdkMcpTool(
            name=fn.name,
            description=fn.description,
            input_schema=fn.input_schema,
            handler=handler,
            annotations=read_only,
        )

    return [adapt(fn) for fn in build_tools(db, settings)]


def _usage(result: ResultMessage | None) -> dict[str, int]:
    """Token counts in the same three keys the API backend reports."""
    raw = (result.usage if result else None) or {}
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens")
    return {key: int(raw.get(key) or 0) for key in keys}


class CliCoach:
    """Coaching conversation backed by the local training database and CLI."""

    backend: Backend = "cli"

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        tools = _mcp_tools(db, settings)
        self.tool_names = [f"mcp__{SERVER}__{tool.name}" for tool in tools]
        self.server = create_sdk_mcp_server(name=SERVER, version="0.1.0", tools=tools)

    def _options(self, session_id: str | None) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=SYSTEM,
            mcp_servers={SERVER: self.server},
            # Ignore any .mcp.json or user-level server config: the training log
            # is the only thing this conversation gets to see.
            strict_mcp_config=True,
            tools=[],  # no Bash, no Read, no Write - just the log
            allowed_tools=self.tool_names,
            # Nothing outside `allowed_tools` exists, so "deny anything not
            # pre-approved" costs nothing and never blocks on a prompt that a
            # web request has no way to answer.
            permission_mode="dontAsk",
            model=self.settings.coach_model,
            effort=self.settings.coach_effort,
            max_turns=MAX_TURNS,
            resume=session_id,
        )

    def ask(
        self,
        question: str,
        history: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Answer one question, running tool calls until the model is done.

        `history` is the API backend's way of carrying a conversation and is
        ignored here: the CLI keeps its own transcript, so a follow-up passes
        back the `session_id` from the previous answer instead.

        Synchronous to match `Coach.ask`. Both callers already run the coach off
        the event loop, so the SDK's async query gets a loop of its own here.
        """
        return asyncio.run(self._ask(question, session_id))

    async def _ask(self, question: str, session_id: str | None) -> dict[str, Any]:
        if not session_id:
            # As in the API backend: the profile and briefing ride on the first
            # user turn, keeping the system prompt a byte-identical cache prefix.
            question = f"{first_turn_context(self.db, self.settings)}\n\n{question}"

        tools_used: list[str] = []
        texts: list[str] = []
        result: ResultMessage | None = None

        async for message in query(prompt=question, options=self._options(session_id)):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        tools_used.append(block.name.removeprefix(f"mcp__{SERVER}__"))
                    elif isinstance(block, TextBlock) and block.text.strip():
                        texts.append(block.text)
            elif isinstance(message, ResultMessage):
                result = message

        if result is not None and result.is_error:
            # A CLI that is installed but not signed in lands here, so say which
            # binary spoke rather than leaving a bare subtype.
            detail = result.result or result.subtype
            raise RuntimeError(f"the claude CLI could not answer: {detail}")

        # The result message carries the last assistant turn; earlier text is
        # narration around tool calls.
        answer = (result.result if result and result.result else None) or (
            texts[-1] if texts else ""
        )
        return {
            "answer": answer.strip(),
            "tools_used": tools_used,
            "usage": _usage(result),
            "stop_reason": result.stop_reason if result else None,
            "session_id": result.session_id if result else None,
        }
