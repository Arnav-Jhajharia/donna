from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TRACE_FILE = Path("donna_traces.jsonl")
SESSION_STORE_FILE = Path(".donna_sessions.json")
MODEL_NAME = "claude-sonnet-4-6"

TOOL_NAMESPACE = "donna"
MCP_SERVER_NAME = "donna-tools"
MCP_SERVER_VERSION = "0.1.0"

ALLOWED_TOOLS = (
    # Stage 0 baseline: terminators only. No retrieval, no profile — pure voice test.
    "mcp__donna__send_burst",
    "mcp__donna__stay_silent",
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


@dataclass(frozen=True)
class DonnaAgentConfig:
    model: str = MODEL_NAME
    max_turns: int = 3
    request_timeout_s: float = 45.0
    trace_file: Path = TRACE_FILE
    session_store_file: Path = SESSION_STORE_FILE
    tool_mode: ToolMode = "fake"
    allowed_tools: tuple[str, ...] = ALLOWED_TOOLS
    disallowed_tools: tuple[str, ...] = DISALLOWED_TOOLS
    thinking_enabled: bool = False
    system_context: str = ""
    resume_session_id: str | None = None
    user_id: str | None = None
    fork_session: bool = False
    langsmith_enabled: bool | Literal["local"] | None = None
    langsmith_project: str | None = None
    langsmith_tags: tuple[str, ...] = ("donna", "agent-sdk")
    target_phone: str | None = None
