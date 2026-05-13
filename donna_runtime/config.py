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

# ── image tool ────────────────────────────────────────────────────────────────────────
IMAGE_MODEL = "fal-ai/flux-pro/v1.1"
IMAGE_SIZE = "square_hd"
IMAGE_LOCKED_STYLE = (
    "warm hand-drawn illustration, gentle muted palette, soft edges"
)
IMAGE_COOLDOWN_HOURS = 6
IMAGE_WEEKLY_CAP = 3

ALLOWED_TOOLS = (
    "mcp__donna__recall",
    "mcp__donna__remember",
    "mcp__donna__attend",
    "mcp__donna__list_attentions",
    "mcp__donna__cancel_attention",
    "mcp__donna__snooze_attention",
    "mcp__donna__accept_attention",
    "mcp__donna__remind",
    "mcp__donna__list_reminders",
    "mcp__donna__cancel_reminder",
    "mcp__donna__image",
    "mcp__donna__send_burst",
    "WebSearch",
    "mcp__donna__update_identity",
    "mcp__donna__log_observation",
    "mcp__donna__track_open_loop",
    "mcp__donna__gather_context",
    "mcp__donna__connect_integration",
    "mcp__donna__check_integration_status",
    "mcp__donna__list_gmail_recent",
    "mcp__donna__search_gmail",
    "mcp__donna__read_gmail_thread",
    "mcp__donna__composio_search_tools",
    "mcp__donna__composio_execute_tool",
    "mcp__donna__update_dashboard",
    "mcp__donna__send_dashboard_link",
    "mcp__donna__send_login_otp",
    "mcp__donna__clear_pending_note",
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


def _cache_ttl_1h_default() -> bool:
    """Honor DONNA_CACHE_TTL_1H env var.

    When 1 (default), build_options sets ENABLE_PROMPT_CACHING_1H on the
    spawned CLI subprocess so cache writes use a 1-hour TTL instead of the
    5-minute default. Trades a higher write rate for fewer rewrites on
    gap-after-5-min turns. Set to 0 to revert to 5-minute TTL.
    """
    return os.environ.get("DONNA_CACHE_TTL_1H", "1") == "1"


@dataclass(frozen=True)
class DonnaAgentConfig:
    model: str = MODEL_NAME
    max_turns: int = 6
    proactive_max_turns: int = 12
    tier3_max_turns: int = 5
    # Bumped 45 → 120. The 45s ceiling was killing turns mid-tool-loop:
    # a chain of attend()/recall() calls (each ~6-8s) blew past it after
    # 5-7 invocations, the SDK subprocess got cancelled before any
    # terminator (send_burst) emitted, and the user saw silence — which
    # they read as "donna didn't reply" and retyped, creating a redelivery
    # loop. 120s covers a healthy 12-call chain. Pair with proactive_max_turns
    # (12) so the model can't chew this budget on a single runaway loop.
    request_timeout_s: float = 120.0
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
    # Phone exposed to hooks for deterministic channel I/O (e.g., image ack).
    # Distinct from target_phone — setting this does NOT make the runner
    # deliver. api/main.py owns delivery in the WA pipeline; only the CLI
    # sets target_phone.
    user_phone: str | None = None
    inbound_wa_message_id: str | None = None
    chat_already_persisted: bool = False
    mode: Literal["reactive", "proactive", "proactive_tier3"] = "reactive"
    voice_filter_enabled: bool = True
    stateless_sessions: bool = False
    cache_ttl_1h: bool = True
