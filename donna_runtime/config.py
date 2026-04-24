from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TRACE_FILE = Path("donna_traces.jsonl")
SESSION_STORE_FILE = Path(".donna_sessions.json")
MODEL_NAME = "claude-sonnet-4-6"
PROACTIVE_MODEL_NAME = "claude-sonnet-4-6"
UPGRADE_MODEL_NAME = "claude-sonnet-4-6"

TOOL_NAMESPACE = "donna"
MCP_SERVER_NAME = "donna-tools"
MCP_SERVER_VERSION = "0.1.0"

ALLOWED_TOOLS = (
    "mcp__donna__recall_episodic",
    "mcp__donna__recall_graph",
    "mcp__donna__smart_recall",
    "mcp__donna__read_tracker",
    "mcp__donna__list_open_loops",
    "mcp__donna__list_calendar",
    "mcp__donna__log_observation",
    "mcp__donna__track_open_loop",
    "mcp__donna__close_open_loop",
    "mcp__donna__set_timezone",
    "mcp__donna__schedule_reminder",
    "mcp__donna__resolve_time_expression",
    "mcp__donna__read_situation_brief",
    "mcp__donna__send_burst",
)

DISALLOWED_TOOLS = (
    "ToolSearch",
    "Task",
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "TodoWrite",
    "NotebookEdit",
    "ExitPlanMode",
    "EnterPlanMode",
)

EXERCISE_MESSAGES = (
    "haha same",
    "I'm literally dying. Antler is in 16 hours and my deck still feels flat",
    "how much did I spend this week",
    "bro",
    "was I nervous before the last pitch too or is this new",
    "k",
    "should I lead with HARP or with the market size slide",
    "remind me to text luca tomorrow",
    "I think I want to quit. this is too much",
    "forgot to tell you, coffee was 6 bucks",
)

DEFAULT_TEST_MESSAGES = (
    "forgot to tell you, coffee was 6 bucks",
    "how much did i spend on coffee this week",
)


ToolMode = Literal["stage0", "fake", "real"]


def _stateless_sessions_default() -> bool:
    """Honor DONNA_STATELESS_SESSIONS env var.

    When 1, brain.donna_turn skips SDK session resume/save entirely. The
    SDK runs as a pure tool-use loop; conversation history lives in the
    chat_messages table and is rendered into the per-turn user message
    via context_builder.render_turn_context.
    """
    return os.environ.get("DONNA_STATELESS_SESSIONS") == "1"


@dataclass(frozen=True)
class DonnaAgentConfig:
    model: str = MODEL_NAME
    max_turns: int = 6
    proactive_max_turns: int = 12
    request_timeout_s: float = 45.0
    trace_file: Path = TRACE_FILE
    session_store_file: Path = SESSION_STORE_FILE
    tool_mode: ToolMode = "real"
    allowed_tools: tuple[str, ...] = ALLOWED_TOOLS
    disallowed_tools: tuple[str, ...] = DISALLOWED_TOOLS
    thinking_enabled: bool = False
    system_context: str = ""
    user_model_block: str = ""
    resume_session_id: str | None = None
    user_id: str | None = None
    fork_session: bool = False
    langsmith_enabled: bool | Literal["local"] | None = None
    langsmith_project: str | None = None
    langsmith_tags: tuple[str, ...] = ("donna", "agent-sdk")
    target_phone: str | None = None
    chat_already_persisted: bool = False
    mode: Literal["reactive", "proactive"] = "reactive"
    voice_filter_enabled: bool = True
    stateless_sessions: bool = False
