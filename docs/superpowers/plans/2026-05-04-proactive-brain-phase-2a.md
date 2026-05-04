# Proactive Brain Phase 2A — Tier 3 LLM Fires For Real

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Tier 3 brain to actually call Sonnet via the SDK with the Tier 3 system prompt, the Tier 3 tool palette, and a real (not placeholder) input contract. After this lands, every escalation runs both the legacy thin-directive path AND the new fat-contract Tier 3 turn — telemetry captures real drafts, real skip reasons, real ship/reshape/kill decisions. Mirror-mode discipline preserved: legacy is still what reaches the user.

**Architecture:** Phase 1 built the types, the tool functions (pure), the context builder (pure), the system prompt, and the dispatcher counterfactual block (which today builds the input and stops). Phase 2A closes the loop: SDK-decorated tool wrappers, mode-aware tool selection in `options.py`, real DB-backed block builders for the Tier 3 input contract, and the actual `donna_turn(mode="proactive_tier3")` call replacing today's discarded `_ = build_tier3_user_message(...)`.

**Tech Stack:** Python 3.11+, Claude Agent SDK (`claude_agent_sdk.tool`), SQLAlchemy 2, pytest, Anthropic Sonnet 4.6 + prompt caching.

**Spec:** [`2026-05-04-proactive-brain-redesign.md`](../specs/2026-05-04-proactive-brain-redesign.md). **Predecessor:** [`2026-05-04-proactive-brain-phase-1.md`](./2026-05-04-proactive-brain-phase-1.md).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `donna_runtime/tools_tier3_sdk.py` | create | 6 `@tool`-decorated MCP wrappers around the typed functions in `tools_tier3.py`. Each wrapper has name + description + JSON Schema + body that delegates to the typed function and returns an SDK-compatible result. |
| `donna_runtime/options.py` | modify | `_tools_for_mode` and `build_options` branch on `cfg.mode == "proactive_tier3"` — pick `TIER3_SDK_TOOLS`, `TIER3_SYSTEM_PROMPT`, `cfg.tier3_max_turns`. |
| `donna_runtime/context_builder_tier3.py` | modify | Add async helpers that fetch real block contents from the DB. Each helper degrades gracefully (returns a placeholder string on failure). |
| `proactive/dispatcher.py` | modify | Replace the placeholder-string call to `build_tier3_user_message` in `_escalate_to_brain` with a call that uses real block builders. Replace `_ = build_tier3_user_message(...)` with a real `donna_turn(state, cfg)` call. Capture the actual outcome (ship/skip/reshape/kill) into telemetry. |
| `scripts/proactive_counterfactual_eval.py` | modify | Recognize the new `counterfactual_fat_contract_outcome` values (`ship` / `skip` / `reshape` / `kill` / `error`) instead of just `input_built` / `input_failed`. |

**Tests:**

| File | Action |
|---|---|
| `backend/tests/runtime/test_tools_tier3_sdk.py` | create |
| `backend/tests/runtime/test_options_tier3_mode.py` | create |
| `backend/tests/runtime/test_context_builder_tier3_blocks.py` | create |
| `backend/tests/proactive/test_dispatcher_tier3_real_call.py` | create |

---

## Task 1: SDK `@tool` wrappers around the 6 typed Tier 3 functions

**Files:**
- Create: `donna_runtime/tools_tier3_sdk.py`
- Test: `backend/tests/runtime/test_tools_tier3_sdk.py`

**Why:** The existing `donna_runtime/tools_tier3.py` functions are pure Python (typed args, return outcome dicts). The Claude Agent SDK expects `@tool`-decorated MCP-registered functions with name + description + JSON Schema. We add a SEPARATE file of SDK-wrappers that delegate to the typed core. This keeps the typed core pure and testable while exposing it to the SDK runtime.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/runtime/test_tools_tier3_sdk.py`:

```python
"""SDK @tool wrappers around the typed tools_tier3 functions."""
from __future__ import annotations

import pytest

from donna_runtime.tools_tier3_sdk import (
    skip_tool,
    kill_attention_tool,
    reshape_attention_tool,
    send_burst_tool,
    quick_check_tool,
    read_external_tool,
    TIER3_SDK_TOOLS,
)


def test_tier3_sdk_tools_includes_all_six():
    names = {t.name for t in TIER3_SDK_TOOLS}
    assert names == {
        "skip",
        "kill_attention",
        "reshape_attention",
        "send_burst",
        "quick_check",
        "read_external",
    }


@pytest.mark.asyncio
async def test_skip_tool_delegates_to_typed_function():
    result = await skip_tool.handler({"reason": "moment is dead"})
    # SDK tool result shape: {"content": [...], "isError": False (optional)}
    # The typed function returns {"action": "skip", "reason": ...}; the
    # wrapper packages it for the SDK.
    assert result["content"]
    text = result["content"][0]["text"]
    assert "skip" in text
    assert "moment is dead" in text


@pytest.mark.asyncio
async def test_skip_tool_validation_error_returned_as_error():
    """Empty reason → typed function raises ValueError → wrapper packages
    as SDK error result, not a Python exception."""
    result = await skip_tool.handler({"reason": ""})
    assert result.get("isError") is True


@pytest.mark.asyncio
async def test_send_burst_tool_supports_quadrant_matrix():
    result = await send_burst_tool.handler({
        "messages": [{"type": "text", "body": "hi"}],
        "push": False,
        "surface_at": "morning_brief",
    })
    text = result["content"][0]["text"]
    assert "morning_brief" in text
    assert '"push": false' in text or "'push': False" in text


@pytest.mark.asyncio
async def test_kill_attention_tool_returns_outcome():
    result = await kill_attention_tool.handler({
        "attention_id": "att_1",
        "reason": "user already did the thing",
    })
    assert result["content"]
    text = result["content"][0]["text"]
    assert "kill" in text
    assert "att_1" in text


@pytest.mark.asyncio
async def test_quick_check_tool_validates_question():
    result = await quick_check_tool.handler({"question": "", "max_results": 3})
    assert result.get("isError") is True


@pytest.mark.asyncio
async def test_read_external_tool_validates_source():
    result = await read_external_tool.handler({
        "source": "bogus",
        "ref": "x",
    })
    assert result.get("isError") is True
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_tools_tier3_sdk.py -v
```
Expected: ImportError on `donna_runtime.tools_tier3_sdk`.

- [ ] **Step 3: Create `donna_runtime/tools_tier3_sdk.py`**

```python
"""SDK @tool wrappers around the typed Tier 3 tool functions.

The typed functions in donna_runtime/tools_tier3.py are pure Python with
proper type annotations and defensive validations. This module wraps each
one as a Claude Agent SDK MCP tool so the brain runtime can invoke them.

Why split: testing the typed functions doesn't require the SDK's MCP
machinery; testing the wrappers verifies SDK packaging and error
handling. Each wrapper:
  - Declares the @tool metadata (name, description, JSON Schema)
  - Pulls args out of the SDK's dict payload
  - Calls the typed function
  - Packages the result as SDK content blocks, or returns isError=True
    on validation failure
"""
from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from donna_runtime.tools_tier3 import (
    kill_attention,
    quick_check,
    read_external,
    reshape_attention,
    send_burst,
    skip,
)


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    """Package a typed-function outcome dict as an SDK tool result."""
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, default=str)}
        ]
    }


def _err(message: str) -> dict[str, Any]:
    """Package a validation error as an SDK tool result with isError=True."""
    return {
        "content": [{"type": "text", "text": f"validation_error: {message}"}],
        "isError": True,
    }


# ---- skip ------------------------------------------------------------------

_SKIP_DESCRIPTION = (
    "Explicit silence. First-class outcome — silence is correct when "
    "fresh signal shows the moment is dead, the topic is already covered, "
    "or your editorial read is that this fire would degrade trust. Do not "
    "use when you'd rather hold the message — use send_burst with "
    "push=false and surface_at instead."
)

_SKIP_INPUT_SCHEMA = {
    "type": "object",
    "required": ["reason"],
    "properties": {
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": "One short sentence explaining why this fire is being silenced.",
        },
    },
}


@tool("skip", _SKIP_DESCRIPTION, _SKIP_INPUT_SCHEMA)
async def skip_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await skip(reason=str(args.get("reason") or ""))
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- kill_attention --------------------------------------------------------

_KILL_DESCRIPTION = (
    "Terminate a live attention. Sets status=killed, cancels future "
    "schedule rows. Permanent. Use when fresh signal shows the user "
    "already did the thing, the moment is permanently gone, or the spec "
    "was wrong from the start. Do not use for transient stale (use "
    "reshape_attention with next_fire_at instead)."
)

_KILL_INPUT_SCHEMA = {
    "type": "object",
    "required": ["attention_id", "reason"],
    "properties": {
        "attention_id": {
            "type": "string",
            "minLength": 1,
            "description": "The attention id to terminate.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": "One short sentence for the audit log.",
        },
    },
}


@tool("kill_attention", _KILL_DESCRIPTION, _KILL_INPUT_SCHEMA)
async def kill_attention_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await kill_attention(
            attention_id=str(args.get("attention_id") or ""),
            reason=str(args.get("reason") or ""),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- reshape_attention -----------------------------------------------------

_RESHAPE_DESCRIPTION = (
    "Modify the live attention spec without firing. Use when world "
    "changed but the spec is still useful (push to tomorrow, downgrade "
    "urgency, fold cadence). Do not use when the right action is to fire "
    "now (use send_burst), or when the spec is permanently moot (use "
    "kill_attention). Must include at least one of: next_fire_at, "
    "surface_level, cadence_change."
)

_RESHAPE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["attention_id"],
    "properties": {
        "attention_id": {"type": "string", "minLength": 1},
        "next_fire_at": {
            "type": ["string", "null"],
            "description": "ISO-8601 datetime for the next fire. Null to leave unchanged.",
        },
        "surface_level": {
            "type": ["string", "null"],
            "enum": ["silent", "digest", "notify", "urgent", None],
        },
        "cadence_change": {
            "type": ["object", "null"],
            "description": "Narrow cadence params override (advanced).",
        },
    },
}


@tool("reshape_attention", _RESHAPE_DESCRIPTION, _RESHAPE_INPUT_SCHEMA)
async def reshape_attention_tool(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime

    next_fire_at = args.get("next_fire_at")
    parsed_dt = None
    if next_fire_at:
        try:
            parsed_dt = datetime.fromisoformat(str(next_fire_at))
        except ValueError as exc:
            return _err(f"next_fire_at not iso-8601: {exc}")

    try:
        result = await reshape_attention(
            attention_id=str(args.get("attention_id") or ""),
            next_fire_at=parsed_dt,
            surface_level=args.get("surface_level"),
            cadence_change=args.get("cadence_change"),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- send_burst ------------------------------------------------------------

_SEND_BURST_DESCRIPTION = (
    "Ship the proactive message. Channel is inline. Quadrants: "
    "push=true → WhatsApp ping; push=false → ambient (chat_messages "
    "only); push=false + surface_at='next_user_touch' → pending note "
    "surfaces in next reactive turn; push=false + surface_at='morning_brief' "
    "→ pending note tagged for tomorrow's morning brief. push=true with "
    "surface_at set is a contract violation."
)

_SEND_BURST_INPUT_SCHEMA = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "object",
                "required": ["type"],
            },
        },
        "push": {"type": "boolean", "default": True},
        "surface_at": {
            "type": ["string", "null"],
            "enum": ["next_user_touch", "morning_brief", None],
        },
    },
}


@tool("send_burst", _SEND_BURST_DESCRIPTION, _SEND_BURST_INPUT_SCHEMA)
async def send_burst_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await send_burst(
            messages=list(args.get("messages") or []),
            push=bool(args.get("push", True)),
            surface_at=args.get("surface_at"),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- quick_check -----------------------------------------------------------

_QUICK_CHECK_DESCRIPTION = (
    "One-shot web search to verify a specific factual claim or fetch a "
    "focused fact. Use when the event makes a claim that needs "
    "verification, or thought_youd_want needs a freshness check. Do not "
    "use for general research or exploration. HARD LIMIT: one call per "
    "turn. Cost: ~$0.005, ~1-2s."
)

_QUICK_CHECK_INPUT_SCHEMA = {
    "type": "object",
    "required": ["question"],
    "properties": {
        "question": {"type": "string", "minLength": 1, "maxLength": 500},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
    },
}


@tool("quick_check", _QUICK_CHECK_DESCRIPTION, _QUICK_CHECK_INPUT_SCHEMA)
async def quick_check_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await quick_check(
            question=str(args.get("question") or ""),
            max_results=int(args.get("max_results") or 3),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- read_external ---------------------------------------------------------

_READ_EXTERNAL_DESCRIPTION = (
    "Fresh state of one specific external resource by identifier. Use "
    "when you need fresh state of something specifically referenced by "
    "id, and that exact resource isn't in the pre-fetched fresh_signal "
    "block. Do not use when fresh_signal already has what you need. "
    "Cost: source-specific, ~0.5-2s."
)

_READ_EXTERNAL_INPUT_SCHEMA = {
    "type": "object",
    "required": ["source", "ref"],
    "properties": {
        "source": {
            "type": "string",
            "enum": [
                "gmail_thread",
                "calendar_event",
                "exa_url",
                "person_recent_chat",
            ],
        },
        "ref": {"type": "string", "minLength": 1},
    },
}


@tool("read_external", _READ_EXTERNAL_DESCRIPTION, _READ_EXTERNAL_INPUT_SCHEMA)
async def read_external_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await read_external(
            source=args.get("source"),  # type: ignore[arg-type]
            ref=str(args.get("ref") or ""),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- registry --------------------------------------------------------------

TIER3_SDK_TOOLS = (
    skip_tool,
    kill_attention_tool,
    reshape_attention_tool,
    send_burst_tool,
    quick_check_tool,
    read_external_tool,
)
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/runtime/test_tools_tier3_sdk.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/tools_tier3_sdk.py backend/tests/runtime/test_tools_tier3_sdk.py
git commit -m "feat(tools): SDK @tool wrappers for the 6 Tier 3 tools

Wraps the typed functions in tools_tier3.py as MCP-registered SDK
tools. Each wrapper carries its own JSON Schema and packages the
typed function's outcome dict as an SDK content block. Validation
errors come back as isError=True instead of raised exceptions.

TIER3_SDK_TOOLS tuple is the registry the brain options will pick up
when mode='proactive_tier3'.

Phase 2A of proactive brain redesign."
```

---

## Task 2: `options.py` mode-aware tool registration

**Files:**
- Modify: `donna_runtime/options.py`
- Test: `backend/tests/runtime/test_options_tier3_mode.py`

**Why:** Today `build_options` ignores `cfg.mode` for tool selection. Without this, calling `donna_turn(state, cfg)` with `mode="proactive_tier3"` registers the *reactive* tool palette — Tier 3 mode is wired in name only.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/runtime/test_options_tier3_mode.py`:

```python
"""build_options mode-aware tool registration for Tier 3."""
from __future__ import annotations

import pytest

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.options import _tools_for_mode, build_options


def test_tools_for_mode_returns_tier3_tools_for_proactive_tier3():
    """When cfg.mode == 'proactive_tier3', the tool palette is the Tier 3 set."""
    from donna_runtime.tools_tier3_sdk import TIER3_SDK_TOOLS

    cfg = DonnaAgentConfig(mode="proactive_tier3")
    tools = _tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode)
    tool_names = {t.name for t in tools}
    expected_names = {t.name for t in TIER3_SDK_TOOLS}
    assert tool_names == expected_names


def test_tools_for_mode_returns_donna_tools_for_reactive():
    """Default reactive mode still returns the full DONNA_TOOLS palette."""
    from donna_runtime.tools import DONNA_TOOLS

    cfg = DonnaAgentConfig(mode="reactive")
    tools = _tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode)
    assert len(tools) == len(DONNA_TOOLS)


def test_tools_for_mode_returns_donna_tools_for_proactive():
    """Legacy proactive mode also gets the reactive tool palette today."""
    from donna_runtime.tools import DONNA_TOOLS

    cfg = DonnaAgentConfig(mode="proactive")
    tools = _tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode)
    assert len(tools) == len(DONNA_TOOLS)


def test_tools_for_mode_back_compat_signature_without_runtime_mode():
    """Calling _tools_for_mode without the new runtime_mode kwarg must
    still work (defaults to reactive). Existing call sites unchanged."""
    from donna_runtime.tools import DONNA_TOOLS

    tools = _tools_for_mode("real")
    assert len(tools) == len(DONNA_TOOLS)


def test_build_options_uses_tier3_max_turns_for_tier3_mode():
    cfg = DonnaAgentConfig(
        mode="proactive_tier3",
        tier3_max_turns=3,
    )
    options = build_options(cfg)
    # SDK options expose max_turns; verify it's the tier3 value, not the
    # default 6.
    max_turns = getattr(options, "max_turns", None)
    assert max_turns == 3


def test_build_options_uses_default_max_turns_for_reactive_mode():
    cfg = DonnaAgentConfig(mode="reactive")
    options = build_options(cfg)
    max_turns = getattr(options, "max_turns", None)
    assert max_turns == 6


def test_build_options_uses_tier3_system_prompt_for_tier3_mode():
    from donna_runtime.prompt_tier3 import TIER3_SYSTEM_PROMPT

    cfg = DonnaAgentConfig(mode="proactive_tier3")
    options = build_options(cfg)
    system_prompt = str(getattr(options, "system_prompt", "") or "")
    # Tier 3 system prompt is distinctive — has 'editorial mode' on line 1.
    assert "editorial mode" in system_prompt.lower()
    assert system_prompt.strip().startswith(TIER3_SYSTEM_PROMPT.strip()[:50])
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_options_tier3_mode.py -v
```
Expected: failures on `runtime_mode` kwarg + tier3_max_turns + tier3 prompt.

- [ ] **Step 3: Modify `donna_runtime/options.py`**

Find `_tools_for_mode` (line 14). Replace with:

```python
def _tools_for_mode(mode: str, *, runtime_mode: str | None = None):
    """Pick the tool palette.

    ``mode`` is the legacy ``tool_mode`` (fake vs real). ``runtime_mode``
    is the new ``DonnaAgentConfig.mode`` (reactive / proactive /
    proactive_tier3). Tier 3 mode gets a narrow palette of 6 tools
    instead of the full reactive set.
    """
    if mode == "fake":
        return list(FAKE_DONNA_TOOLS)
    if runtime_mode == "proactive_tier3":
        from donna_runtime.tools_tier3_sdk import TIER3_SDK_TOOLS
        return list(TIER3_SDK_TOOLS)
    return list(DONNA_TOOLS)
```

Find `build_mcp_server` (line 26). Update to pass `runtime_mode`:

```python
def build_mcp_server(config: DonnaAgentConfig | None = None):
    cfg = config or DonnaAgentConfig()
    return create_sdk_mcp_server(
        name=MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
        tools=_tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode),
    )
```

Find `build_options` (line 35). Find the `kwargs = {...}` dict. Modify:

```python
def build_options(config: DonnaAgentConfig | None = None) -> ClaudeAgentOptions:
    config = config or DonnaAgentConfig()
    env: dict[str, str] = {}
    if config.cache_ttl_1h:
        env["ENABLE_PROMPT_CACHING_1H"] = "1"

    # Phase 2A: Tier 3 mode picks its own system prompt + max_turns.
    if config.mode == "proactive_tier3":
        from donna_runtime.prompt_tier3 import TIER3_SYSTEM_PROMPT
        system_prompt = TIER3_SYSTEM_PROMPT
        max_turns = config.tier3_max_turns
    else:
        system_prompt = build_system_prompt(tool_mode=config.tool_mode)
        max_turns = config.max_turns

    kwargs = {
        "model": config.model,
        "system_prompt": system_prompt,
        "mcp_servers": {TOOL_NAMESPACE: build_mcp_server(config)},
        "extra_args": {
            "thinking": "enabled" if config.thinking_enabled else "disabled",
            "bare": None,
            "strict-mcp-config": None,
            "tools": "",
            "disable-slash-commands": None,
            "exclude-dynamic-system-prompt-sections": None,
        },
        "env": env,
        "allowed_tools": _allowed_for_mode(config.tool_mode, config),
        "disallowed_tools": list(config.disallowed_tools),
        "setting_sources": [],
        "hooks": {
            "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
        },
        "max_turns": max_turns,
        "resume": config.resume_session_id,
        "fork_session": config.fork_session,
        "skills": [],
        "tools": [],
    }
    return ClaudeAgentOptions(**_filter_supported_options(kwargs))
```

Don't change `_allowed_for_mode` — Tier 3's 6 tools are inside the same MCP namespace, so allowed_tools list still works.

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/runtime/test_options_tier3_mode.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Smoke-run existing tests for regressions**

```
pytest backend/tests/runtime/ -v 2>&1 | tail -10
```
Expected: same pass count as before this commit, plus 7 new.

- [ ] **Step 6: Commit**

```bash
git add donna_runtime/options.py backend/tests/runtime/test_options_tier3_mode.py
git commit -m "feat(runtime): build_options mode-aware tool registration for Tier 3

When cfg.mode == 'proactive_tier3', build_options now picks:
  - TIER3_SDK_TOOLS (6 tools) instead of DONNA_TOOLS
  - TIER3_SYSTEM_PROMPT instead of build_system_prompt()
  - cfg.tier3_max_turns (3) instead of cfg.max_turns (6)

Reactive and legacy proactive modes unchanged. _tools_for_mode keeps
its old signature backward-compatible via the new optional runtime_mode
kwarg.

Phase 2A of proactive brain redesign."
```

---

## Task 3: USER MODEL + Pending notes block builders (lean — reuse existing)

**Files:**
- Modify: `donna_runtime/context_builder_tier3.py` (add async block builders)
- Test: `backend/tests/runtime/test_context_builder_tier3_blocks.py`

**Why:** Phase 1 passes placeholder strings into `build_tier3_user_message`. Replace two of them — USER MODEL (existing helper) and PENDING NOTES (new, simple) — first because they're the easiest.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/runtime/test_context_builder_tier3_blocks.py`:

```python
"""Real block builders for the Tier 3 input contract."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from db.models import PendingProactiveNote, generate_uuid, utcnow_naive
from donna_runtime.context_builder_tier3 import (
    load_user_model_block_for_tier3,
    load_pending_notes_block,
)


@pytest.mark.asyncio
async def test_load_user_model_block_for_tier3_unknown_user_returns_placeholder(db):
    """Unknown user → degraded placeholder string, never raises."""
    block = await load_user_model_block_for_tier3(user_id="nonexistent_xyz")
    assert isinstance(block, str)
    assert len(block) > 0


@pytest.mark.asyncio
async def test_load_user_model_block_for_tier3_returns_string_for_known_user(db):
    """The conftest fixture seeds u1; should return a non-empty string."""
    block = await load_user_model_block_for_tier3(user_id="u1")
    assert isinstance(block, str)
    assert len(block) > 0


@pytest.mark.asyncio
async def test_load_pending_notes_block_no_notes_returns_placeholder(db):
    block = await load_pending_notes_block(user_id="u1")
    assert "no pending notes" in block.lower() or block.strip() == ""


@pytest.mark.asyncio
async def test_load_pending_notes_block_returns_active_notes(db):
    """Active rows in pending_proactive_notes should appear in the block."""
    async with db() as session:
        note = PendingProactiveNote(
            id=generate_uuid(),
            user_id="u1",
            topic_key="thread_test",
            draft_text="hey, anthropic just shipped a new agent SDK feature",
            status="pending",
            source="email",
            created_at=utcnow_naive(),
        )
        session.add(note)
        await session.commit()

    block = await load_pending_notes_block(user_id="u1")
    assert "anthropic" in block
    assert "thread_test" in block
```

> **Note**: Adjust `PendingProactiveNote(...)` fields to match your actual model. If the model has different required columns, omit / adjust to satisfy the schema. The test must still demonstrate that an active row surfaces in the block.

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_context_builder_tier3_blocks.py -v
```
Expected: ImportError on `load_user_model_block_for_tier3` and `load_pending_notes_block`.

- [ ] **Step 3: Modify `donna_runtime/context_builder_tier3.py`**

Append to the bottom (keep existing `build_tier3_user_message` and `EscalationReason` import unchanged):

```python
import logging

logger = logging.getLogger(__name__)


_PLACEHOLDER_PREFIX = "(phase 2a — degraded fallback)"


async def load_user_model_block_for_tier3(*, user_id: str) -> str:
    """Render the USER MODEL block for the Tier 3 input contract.

    Reuses the existing reactive helper. On any failure, returns a
    placeholder so the dispatcher never blocks.
    """
    try:
        from donna_runtime.context_builder import load_user_model_block

        block = await load_user_model_block(user_id) or ""
        if not block.strip():
            return f"{_PLACEHOLDER_PREFIX} no user model loaded"
        return block.strip()
    except Exception:
        logger.exception(
            "tier3 block: USER MODEL load failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} user model unavailable"


async def load_pending_notes_block(*, user_id: str) -> str:
    """Render the PENDING NOTES block from active pending_proactive_notes."""
    try:
        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import PendingProactiveNote
    except Exception:
        logger.exception("tier3 block: pending_notes imports failed")
        return f"{_PLACEHOLDER_PREFIX} pending notes unavailable"

    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(PendingProactiveNote)
                    .where(PendingProactiveNote.user_id == user_id)
                    .where(PendingProactiveNote.status == "pending")
                    .order_by(PendingProactiveNote.created_at.desc())
                    .limit(20)
                )
            ).scalars().all()
    except Exception:
        logger.exception(
            "tier3 block: pending_notes query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} pending notes query failed"

    if not rows:
        return "no pending notes."

    lines = []
    for row in rows:
        # Compact one-line per note. Truncate long drafts to keep prompt tight.
        draft = (getattr(row, "draft_text", None) or "")[:160]
        topic = getattr(row, "topic_key", None) or "(no topic)"
        lines.append(f"- {topic} — {draft}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```
pytest backend/tests/runtime/test_context_builder_tier3_blocks.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/context_builder_tier3.py backend/tests/runtime/test_context_builder_tier3_blocks.py
git commit -m "feat(runtime): real USER MODEL + PENDING NOTES block builders

Two of the seven block builders the Tier 3 input contract needs.
Both fail gracefully — on any DB or import error they return a
placeholder string so the dispatcher never blocks.

USER MODEL block reuses load_user_model_block from the reactive
context builder. PENDING NOTES queries active pending_proactive_notes
rows and renders one line per note.

Phase 2A of proactive brain redesign."
```

---

## Task 4: DAY view block builder

**Files:**
- Modify: `donna_runtime/context_builder_tier3.py`
- Modify: `backend/tests/runtime/test_context_builder_tier3_blocks.py` (append)

**Why:** The DAY view tells the Tier 3 brain what's already happened today — what messages it sent, what the user replied with, prior proactive fires today vs. the daily cap. This is the most important block for editorial decisions.

- [ ] **Step 1: Write the failing test (append to existing file)**

Append to `backend/tests/runtime/test_context_builder_tier3_blocks.py`:

```python
from datetime import datetime, timedelta, timezone

from db.models import ChatMessage, ProactiveDispatchTelemetry
from donna_runtime.context_builder_tier3 import load_day_view_block


@pytest.mark.asyncio
async def test_load_day_view_block_no_activity_returns_compact_summary(db):
    block = await load_day_view_block(user_id="u1")
    assert isinstance(block, str)
    assert len(block) > 0
    # Empty day still has a header.
    assert "today" in block.lower() or "day" in block.lower()


@pytest.mark.asyncio
async def test_load_day_view_block_includes_proactive_fires(db):
    """Telemetry rows from today should appear in the block."""
    async with db() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id="u1",
            source="email",
            speech_act="heads_up",
            topic_key="thread_xyz",
            tier3_invoked=True,
            tier3_outcome="legacy_thin_directive",
            channel="whatsapp",
            counterfactual_legacy_outbound_count=1,
            counterfactual_fat_contract_outcome="input_built",
            event_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()

    block = await load_day_view_block(user_id="u1")
    assert "thread_xyz" in block or "heads_up" in block
    # The block should hint at fires_today count
    assert "fire" in block.lower() or "ping" in block.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_context_builder_tier3_blocks.py::test_load_day_view_block_no_activity_returns_compact_summary -v
```
Expected: ImportError on `load_day_view_block`.

- [ ] **Step 3: Append to `donna_runtime/context_builder_tier3.py`**

```python
async def load_day_view_block(*, user_id: str) -> str:
    """Render the DAY VIEW block.

    Compact, fits in a few hundred tokens. Pulls from:
      - chat_messages today (Donna's outbound + user's inbound, with
        timestamps and short snippets)
      - proactive_dispatch_telemetry today (proactive fires this user
        already received, with topic_key + speech_act + draft)
      - schedule_fires today via DonnaSchedule.fired_at

    Degrades gracefully on any failure.
    """
    try:
        from sqlalchemy import and_, or_, select

        from backend.db.session import async_session
        from db.models import (
            ChatMessage,
            DonnaSchedule,
            ProactiveDispatchTelemetry,
        )
    except Exception:
        logger.exception("tier3 block: day_view imports failed")
        return f"{_PLACEHOLDER_PREFIX} day view unavailable"

    from datetime import datetime, timedelta

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    chat_lines: list[str] = []
    fires_today: list[str] = []
    schedule_fires: list[str] = []

    try:
        async with async_session() as session:
            # Chat messages today
            chat_rows = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .where(ChatMessage.created_at >= today_start)
                    .order_by(ChatMessage.created_at.asc())
                    .limit(40)
                )
            ).scalars().all()

            for cm in chat_rows:
                role = getattr(cm, "role", "") or ""
                ts = getattr(cm, "created_at", None)
                ts_str = ts.strftime("%H:%M") if ts else "??:??"
                content = (getattr(cm, "content", None) or "")[:60]
                chat_lines.append(f"  {ts_str} [{role}] {content}")

            # Proactive fires today
            fire_rows = (
                await session.execute(
                    select(ProactiveDispatchTelemetry)
                    .where(ProactiveDispatchTelemetry.user_id == user_id)
                    .where(ProactiveDispatchTelemetry.event_at >= today_start)
                    .order_by(ProactiveDispatchTelemetry.event_at.asc())
                )
            ).scalars().all()

            for fr in fire_rows:
                draft = (getattr(fr, "tier2_draft", None) or "")[:60]
                fires_today.append(
                    f"  {fr.speech_act} on {fr.topic_key} → {draft}"
                )

            # Schedule fires today
            sched_rows = (
                await session.execute(
                    select(DonnaSchedule)
                    .where(DonnaSchedule.user_id == user_id)
                    .where(DonnaSchedule.fired_at >= today_start)
                    .order_by(DonnaSchedule.fired_at.asc())
                    .limit(20)
                )
            ).scalars().all()

            for sr in sched_rows:
                ts = getattr(sr, "fired_at", None)
                ts_str = ts.strftime("%H:%M") if ts else "??:??"
                schedule_fires.append(f"  {ts_str} fired sched {sr.id[:8]}")
    except Exception:
        logger.exception(
            "tier3 block: day_view query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} day view query failed"

    parts: list[str] = []
    parts.append(f"today (UTC): {today_start.date().isoformat()}")
    parts.append(f"proactive fires today: {len(fires_today)}")
    if fires_today:
        parts.extend(fires_today)
    parts.append(f"schedule fires today: {len(schedule_fires)}")
    if schedule_fires:
        parts.extend(schedule_fires)
    parts.append(f"chat messages today: {len(chat_lines)}")
    if chat_lines:
        parts.extend(chat_lines[-10:])  # last 10 messages only
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests**

```
pytest backend/tests/runtime/test_context_builder_tier3_blocks.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/context_builder_tier3.py backend/tests/runtime/test_context_builder_tier3_blocks.py
git commit -m "feat(runtime): DAY view block builder for Tier 3 input contract

Pulls today's chat messages (capped to last 10), proactive fires from
proactive_dispatch_telemetry, and DonnaSchedule fires. Renders compact,
~150 tokens for an active day. Degrades to placeholder on DB error.

Phase 2A of proactive brain redesign."
```

---

## Task 5: Prior touches + User state now block builders

**Files:**
- Modify: `donna_runtime/context_builder_tier3.py`
- Modify: `backend/tests/runtime/test_context_builder_tier3_blocks.py` (append)

**Why:** Prior touches lets Tier 3 avoid double-tapping (was this topic pinged in the last 7 days? what was the user's response?). User state now tells Tier 3 the user's right-this-second mood/focus signal so soft-register fires (`i_noticed`) can be timed appropriately.

- [ ] **Step 1: Write the failing tests (append)**

Append to `backend/tests/runtime/test_context_builder_tier3_blocks.py`:

```python
from donna_runtime.context_builder_tier3 import (
    load_prior_touches_block,
    load_user_state_now_block,
)


@pytest.mark.asyncio
async def test_load_prior_touches_block_no_history_returns_compact_string(db):
    block = await load_prior_touches_block(
        user_id="u1", topic_key="never_touched_topic"
    )
    assert isinstance(block, str)
    assert "no prior" in block.lower() or "never" in block.lower() or block.strip() == ""


@pytest.mark.asyncio
async def test_load_prior_touches_block_finds_recent_telemetry(db):
    async with db() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id="u1",
            source="email",
            speech_act="heads_up",
            topic_key="thread_recurring",
            tier3_invoked=True,
            tier2_draft="luca replied",
            counterfactual_legacy_outbound_count=1,
            event_at=datetime.utcnow() - timedelta(days=2),
        )
        session.add(row)
        await session.commit()

    block = await load_prior_touches_block(
        user_id="u1", topic_key="thread_recurring"
    )
    assert "thread_recurring" in block or "luca" in block


@pytest.mark.asyncio
async def test_load_user_state_now_block_returns_compact_summary(db):
    block = await load_user_state_now_block(user_id="u1")
    assert isinstance(block, str)
    # Even with no observations / chat, returns at least time-of-day signal.
    assert len(block) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_context_builder_tier3_blocks.py::test_load_prior_touches_block_no_history_returns_compact_string -v
```

- [ ] **Step 3: Append to `donna_runtime/context_builder_tier3.py`**

```python
async def load_prior_touches_block(
    *,
    user_id: str,
    topic_key: str,
    lookback_days: int = 7,
) -> str:
    """Render the PRIOR TOUCHES block.

    Surfaces:
      - Most recent proactive fire on this topic_key (or any topic if
        none specifically) within lookback_days.
      - The user's response within 1h, if available (Phase 2: today
        we don't have a join from telemetry to chat replies; fallback
        to 'no response captured').

    Tells the brain whether to double-tap. Degrades gracefully.
    """
    try:
        from datetime import datetime, timedelta

        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import ProactiveDispatchTelemetry
    except Exception:
        logger.exception("tier3 block: prior_touches imports failed")
        return f"{_PLACEHOLDER_PREFIX} prior touches unavailable"

    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    try:
        async with async_session() as session:
            # Most recent fire on this topic
            on_topic = (
                await session.execute(
                    select(ProactiveDispatchTelemetry)
                    .where(ProactiveDispatchTelemetry.user_id == user_id)
                    .where(ProactiveDispatchTelemetry.topic_key == topic_key)
                    .where(ProactiveDispatchTelemetry.event_at >= cutoff)
                    .order_by(ProactiveDispatchTelemetry.event_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            # Most recent fire any topic (for double-tap risk)
            any_topic = (
                await session.execute(
                    select(ProactiveDispatchTelemetry)
                    .where(ProactiveDispatchTelemetry.user_id == user_id)
                    .where(ProactiveDispatchTelemetry.event_at >= cutoff)
                    .order_by(ProactiveDispatchTelemetry.event_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
    except Exception:
        logger.exception(
            "tier3 block: prior_touches query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} prior touches query failed"

    parts: list[str] = []
    if on_topic:
        delta = datetime.utcnow() - on_topic.event_at
        hours = int(delta.total_seconds() / 3600)
        draft = (on_topic.tier2_draft or "")[:80]
        parts.append(
            f"on this topic ({topic_key}): last fire {hours}h ago — '{draft}'"
        )
    else:
        parts.append(f"on this topic ({topic_key}): no prior fires in {lookback_days}d")

    if any_topic and (not on_topic or any_topic.id != on_topic.id):
        delta = datetime.utcnow() - any_topic.event_at
        mins = int(delta.total_seconds() / 60)
        parts.append(
            f"most recent fire (any topic): {mins} min ago, "
            f"speech_act={any_topic.speech_act}, topic={any_topic.topic_key}"
        )
    elif not any_topic:
        parts.append(f"no proactive fires in {lookback_days}d at all")

    return "\n".join(parts)


async def load_user_state_now_block(*, user_id: str) -> str:
    """Render the USER STATE NOW block.

    Phase 2A keeps this lean — no Haiku tone read yet (that's Phase 2.5).
    Surfaces:
      - Time-of-day in user's tz (or UTC fallback)
      - Last user message (from chat_messages, if any in last 30 min)
      - Latest observation (from observations table, if any in last 36h)

    Real mood/focus inference lands later when the synthesis worker
    populates a richer state cache.
    """
    try:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import ChatMessage, Observation, User
    except Exception:
        logger.exception("tier3 block: user_state imports failed")
        return f"{_PLACEHOLDER_PREFIX} user state unavailable"

    parts: list[str] = []

    try:
        async with async_session() as session:
            user_row = (
                await session.execute(
                    select(User).where(User.id == user_id)
                )
            ).scalar_one_or_none()
            tz_name = getattr(user_row, "timezone", None) or "UTC"

            try:
                from zoneinfo import ZoneInfo
                now_local = datetime.now(ZoneInfo(tz_name))
            except Exception:
                now_local = datetime.utcnow()
            parts.append(f"local time: {now_local.strftime('%Y-%m-%d %H:%M %Z')}")

            # Last user message in last 30 min
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            last_user_msg = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .where(ChatMessage.role == "user")
                    .where(ChatMessage.created_at >= cutoff)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if last_user_msg:
                content = (getattr(last_user_msg, "content", None) or "")[:80]
                age = datetime.utcnow() - last_user_msg.created_at
                mins = int(age.total_seconds() / 60)
                parts.append(f"last user msg: {mins}min ago — '{content}'")
            else:
                parts.append("no user messages in last 30 min")

            # Latest observation in last 36h
            obs_cutoff = datetime.utcnow() - timedelta(hours=36)
            last_obs = (
                await session.execute(
                    select(Observation)
                    .where(Observation.user_id == user_id)
                    .where(Observation.event_time >= obs_cutoff)
                    .order_by(Observation.event_time.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_obs:
                kind = getattr(last_obs, "kind", None) or "obs"
                age = datetime.utcnow() - last_obs.event_time
                hours = int(age.total_seconds() / 3600)
                parts.append(f"last observation: {kind}, {hours}h ago")
            else:
                parts.append("no observations in last 36h")
    except Exception:
        logger.exception(
            "tier3 block: user_state query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} user state query failed"

    return "\n".join(parts)
```

- [ ] **Step 4: Run tests**

```
pytest backend/tests/runtime/test_context_builder_tier3_blocks.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/context_builder_tier3.py backend/tests/runtime/test_context_builder_tier3_blocks.py
git commit -m "feat(runtime): PRIOR TOUCHES + USER STATE NOW block builders

prior_touches: queries proactive_dispatch_telemetry for last fire on
this topic + last fire any topic in the lookback window. Lets Tier 3
avoid double-tapping.

user_state_now: time-of-day in user tz + last user msg + latest
observation. Lean — no Haiku tone read yet (Phase 2.5). Just enough
signal for soft-register fires to time correctly.

Both degrade to placeholder on DB error.

Phase 2A of proactive brain redesign."
```

---

## Task 6: Wire real builders into `_escalate_to_brain` + replace stub with real `donna_turn`

**Files:**
- Modify: `proactive/dispatcher.py`
- Test: `backend/tests/proactive/test_dispatcher_tier3_real_call.py`

**Why:** This is the moment Tier 3 actually fires Sonnet. Replace the discarded `_ = build_tier3_user_message(...)` with real block builders + real `donna_turn(state, cfg)` call. Capture the actual outcome (ship/skip/reshape/kill) into telemetry. Mirror discipline: legacy ship still happens unchanged, Tier 3's outcome is logged but never sent.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_dispatcher_tier3_real_call.py`:

```python
"""Dispatcher Tier 3 real LLM call — Phase 2A.

After Phase 2A, every escalation runs both legacy donna_turn AND a
counterfactual donna_turn(mode='proactive_tier3'). The Tier 3 outcome
is captured to telemetry. Legacy ship reaches the user; Tier 3 is
mirror-only.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from db.models import ProactiveDispatchTelemetry
from proactive.dispatcher import _escalate_to_brain
from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


def _event() -> ProactiveEvent:
    return ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="msg_real_call",
        topic_key="thread_real_call",
        speech_act="heads_up",
        payload={
            "from_address": "x@y.com",
            "subject": "phase 2a",
            "body_excerpt": "...",
            "phone": "+1",
        },
        signals={"score": 0.7, "event_age_minutes": 30},
    )


def _judge() -> JudgeResult:
    return JudgeResult(
        action="ping",
        register="alert",
        draft="luca replied to the term sheet",
        tie_in=(),
        needs_tools=True,
        reasoning="thread state may have moved",
        raw_response="{}",
    )


@pytest.mark.asyncio
async def test_tier3_real_call_telemetry_captures_skip_outcome(db):
    """When the model calls skip(), telemetry captures outcome=skip."""
    legacy_calls: list[str] = []
    counterfactual_calls: list[str] = []

    async def fake_donna_turn(state, cfg):
        if cfg.mode == "proactive":
            legacy_calls.append("legacy")
            return {"_outbound": [{"type": "text", "body": "legacy draft"}]}
        if cfg.mode == "proactive_tier3":
            counterfactual_calls.append("tier3")
            # Simulate the model calling skip()
            return {
                "_outbound": [],
                "_tier3_outcome": {
                    "action": "skip",
                    "reason": "user already replied in chat",
                },
            }
        return {"_outbound": []}

    async def fake_record_ping(*args, **kwargs):
        return None

    with patch(
        "donna_runtime.brain.donna_turn",
        side_effect=fake_donna_turn,
    ), patch(
        "backend.integrations.proactive_rate_limit.record_ping",
        side_effect=fake_record_ping,
    ):
        outcome = await _escalate_to_brain(
            event=_event(),
            judge=_judge(),
        )

    assert "legacy" in legacy_calls
    assert "tier3" in counterfactual_calls

    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_real_call"
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.counterfactual_fat_contract_outcome == "skip"
    assert row.counterfactual_fat_contract_skip_reason == "user already replied in chat"
    assert row.counterfactual_legacy_outbound_count == 1


@pytest.mark.asyncio
async def test_tier3_real_call_telemetry_captures_ship_outcome(db):
    """When the model calls send_burst(), telemetry captures outcome=ship + draft."""
    async def fake_donna_turn(state, cfg):
        if cfg.mode == "proactive_tier3":
            return {
                "_outbound": [],
                "_tier3_outcome": {
                    "action": "ship",
                    "messages": [
                        {"type": "text", "body": "luca replied to the term sheet thread"}
                    ],
                    "push": True,
                    "surface_at": None,
                },
            }
        return {"_outbound": [{"type": "text", "body": "legacy"}]}

    async def fake_record_ping(*a, **kw):
        return None

    with patch(
        "donna_runtime.brain.donna_turn",
        side_effect=fake_donna_turn,
    ), patch(
        "backend.integrations.proactive_rate_limit.record_ping",
        side_effect=fake_record_ping,
    ):
        await _escalate_to_brain(event=_event(), judge=_judge())

    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_real_call"
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.counterfactual_fat_contract_outcome == "ship"
    assert "luca replied" in (row.counterfactual_fat_contract_draft or "")


@pytest.mark.asyncio
async def test_tier3_real_call_legacy_unchanged_when_tier3_errors(db):
    """If the Tier 3 call raises, the legacy outcome still ships."""
    async def fake_donna_turn(state, cfg):
        if cfg.mode == "proactive_tier3":
            raise RuntimeError("simulated Tier 3 SDK failure")
        return {"_outbound": [{"type": "text", "body": "legacy"}]}

    async def fake_record_ping(*a, **kw):
        return None

    with patch(
        "donna_runtime.brain.donna_turn",
        side_effect=fake_donna_turn,
    ), patch(
        "backend.integrations.proactive_rate_limit.record_ping",
        side_effect=fake_record_ping,
    ):
        outcome = await _escalate_to_brain(event=_event(), judge=_judge())

    # Legacy outbound count > 0 → legacy reached the user
    assert outcome.action in {"escalated", "shipped"}

    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_real_call"
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.counterfactual_fat_contract_outcome == "error"
    assert "RuntimeError" in (row.counterfactual_fat_contract_error or "")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/proactive/test_dispatcher_tier3_real_call.py -v
```
Expected: failures (current code only logs `input_built` / `input_failed`, doesn't run a Tier 3 call).

- [ ] **Step 3: Modify `proactive/dispatcher.py`**

Find `_escalate_to_brain`. Find the Phase 1 counterfactual block (look for `# PHASE 1 MIRROR:` comment). Replace it with the Phase 2A version:

```python
    # ──────────────────────────────────────────────────────────────────
    # PHASE 2A: build the Tier 3 input contract with real block data,
    # then call donna_turn(mode="proactive_tier3"). Capture the actual
    # outcome (ship/skip/reshape/kill/error) to telemetry.
    #
    # Mirror discipline: the Tier 3 call's outbound buffer is NEVER sent
    # to the user. Legacy outbound (already populated above) is what
    # reaches WhatsApp.
    # ──────────────────────────────────────────────────────────────────
    counterfactual_outcome: str | None = None
    counterfactual_draft: str | None = None
    counterfactual_skip_reason: str | None = None
    counterfactual_elapsed_ms: int | None = None
    counterfactual_error: str | None = None
    started = time.monotonic()

    try:
        from donna_runtime.brain import donna_turn
        from donna_runtime.config import DonnaAgentConfig
        from donna_runtime.context_builder_tier3 import (
            build_tier3_user_message,
            load_day_view_block,
            load_pending_notes_block,
            load_prior_touches_block,
            load_user_model_block_for_tier3,
            load_user_state_now_block,
        )

        # Build real blocks. Each builder degrades gracefully.
        user_model_block = await load_user_model_block_for_tier3(user_id=event.user_id)
        day_view_block = await load_day_view_block(user_id=event.user_id)
        prior_touches_block = await load_prior_touches_block(
            user_id=event.user_id, topic_key=event.topic_key
        )
        user_state_block = await load_user_state_now_block(user_id=event.user_id)
        pending_notes_block = await load_pending_notes_block(user_id=event.user_id)

        user_message = build_tier3_user_message(
            event=event,
            judge=judge if judge is not None else _placeholder_judge(),
            escalation_reason=(
                "needs_tools" if (judge and judge.needs_tools) else "tier2_failed"
            ),
            user_model_block=user_model_block,
            queued_thing_block="(phase 2a — queued spec block deferred to Phase 2.5)",
            day_view_block=day_view_block,
            prior_touches_block=prior_touches_block,
            user_state_block=user_state_block,
            pending_notes_block=pending_notes_block,
            fresh_signal_block=None,
        )

        tier3_cfg = DonnaAgentConfig(
            mode="proactive_tier3",
            user_id=event.user_id,
            user_phone=phone,
            stateless_sessions=True,
        )
        tier3_state: dict[str, Any] = {
            "user_id": event.user_id,
            "raw_input": user_message,
            "user_message": user_message,
            "phone": phone,
            "trigger": {
                "source": event.source,
                "speech_act": event.speech_act,
                "topic_key": event.topic_key,
                "escalation_reason": (
                    "needs_tools" if (judge and judge.needs_tools) else "tier2_failed"
                ),
            },
        }

        tier3_result = await donna_turn(tier3_state, tier3_cfg)
        outcome = (
            tier3_result.get("_tier3_outcome")
            if isinstance(tier3_result, dict)
            else None
        ) or {}

        action = outcome.get("action")
        if action == "ship":
            counterfactual_outcome = "ship"
            messages = outcome.get("messages") or []
            if messages and isinstance(messages[0], dict):
                counterfactual_draft = (messages[0].get("body") or "")[:500]
        elif action == "skip":
            counterfactual_outcome = "skip"
            counterfactual_skip_reason = (outcome.get("reason") or "")[:500]
        elif action == "reshape":
            counterfactual_outcome = "reshape"
        elif action == "kill":
            counterfactual_outcome = "kill"
            counterfactual_skip_reason = (outcome.get("reason") or "")[:500]
        else:
            counterfactual_outcome = "no_terminator"
    except Exception as exc:
        logger.exception(
            "dispatcher: Tier 3 counterfactual call raised user=%s",
            event.user_id,
        )
        counterfactual_outcome = "error"
        counterfactual_error = f"{type(exc).__name__}: {str(exc)[:200]}"

    counterfactual_elapsed_ms = int((time.monotonic() - started) * 1000)

    # Write telemetry. Best-effort — never block the legacy outcome.
    try:
        await _write_dispatch_telemetry(
            event=event,
            judge=judge,
            legacy_outbound_count=len(outbound),
            counterfactual_outcome=counterfactual_outcome,
            counterfactual_draft=counterfactual_draft,
            counterfactual_skip_reason=counterfactual_skip_reason,
            counterfactual_elapsed_ms=counterfactual_elapsed_ms,
            counterfactual_error=counterfactual_error,
        )
    except Exception:
        logger.exception(
            "dispatcher: telemetry write failed user=%s",
            event.user_id,
        )
```

Update `_write_dispatch_telemetry` to accept the new args (it already accepts them per the Phase 1 signature; verify draft + skip_reason are persisted):

The Phase 1 signature was:
```python
async def _write_dispatch_telemetry(
    *,
    event: ProactiveEvent,
    judge: "JudgeResult | None",
    legacy_outbound_count: int,
    counterfactual_outcome: str | None,
    counterfactual_elapsed_ms: int | None,
    counterfactual_error: str | None,
) -> None:
```

Add `counterfactual_draft` and `counterfactual_skip_reason` parameters and persist them into `counterfactual_fat_contract_draft` and `counterfactual_fat_contract_skip_reason`:

```python
async def _write_dispatch_telemetry(
    *,
    event: ProactiveEvent,
    judge: "JudgeResult | None",
    legacy_outbound_count: int,
    counterfactual_outcome: str | None,
    counterfactual_draft: str | None = None,
    counterfactual_skip_reason: str | None = None,
    counterfactual_elapsed_ms: int | None,
    counterfactual_error: str | None,
) -> None:
    """..."""
    # ... existing imports + score parsing ...
    async with async_session() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id=event.user_id,
            source=event.source,
            speech_act=event.speech_act,
            topic_key=event.topic_key,
            tier1_score=score,
            arbiter_decision=None,
            arbiter_reason=None,
            tier2_action=judge.action if judge else None,
            tier2_register=judge.register if judge else None,
            tier2_draft=judge.draft if judge else None,
            tier2_needs_tools=judge.needs_tools if judge else None,
            tier2_channel_hint=getattr(judge, "channel_hint", None),
            tier2_reclassify=getattr(judge, "reclassify_speech_act", None),
            tier3_invoked=True,
            tier3_outcome="legacy_thin_directive",
            channel="whatsapp" if legacy_outbound_count > 0 else None,
            counterfactual_legacy_outbound_count=legacy_outbound_count,
            counterfactual_fat_contract_outcome=counterfactual_outcome,
            counterfactual_fat_contract_draft=counterfactual_draft,            # NEW
            counterfactual_fat_contract_skip_reason=counterfactual_skip_reason,  # NEW
            counterfactual_fat_contract_elapsed_ms=counterfactual_elapsed_ms,
            counterfactual_fat_contract_error=counterfactual_error,
        )
        session.add(row)
        await session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/proactive/test_dispatcher_tier3_real_call.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Smoke-run existing dispatcher tests for regressions**

```
pytest backend/tests/proactive/test_dispatcher.py backend/tests/proactive/test_dispatcher_tier3_mirror.py -v 2>&1 | tail -10
```
Expected: same pass count as before (the Phase 1 mirror test should still pass — its `outcome in {input_built, input_failed}` assertion needs to be relaxed to also accept `{ship, skip, reshape, kill, error, no_terminator}`).

If `test_dispatcher_tier3_mirror.py::test_counterfactual_logs_telemetry_after_legacy_escalation` fails because the outcome value changed, update its assertion:

```python
    assert row.counterfactual_fat_contract_outcome in {
        "ship", "skip", "reshape", "kill", "error", "no_terminator",
    }
```

- [ ] **Step 6: Commit**

```bash
git add proactive/dispatcher.py backend/tests/proactive/test_dispatcher_tier3_real_call.py backend/tests/proactive/test_dispatcher_tier3_mirror.py
git commit -m "feat(proactive): wire real Tier 3 LLM call into dispatcher counterfactual

Replaces the Phase 1 placeholder-strings + discarded-result with:
  - real DB-backed block builders (USER MODEL, DAY view, prior touches,
    user state now, pending notes)
  - real donna_turn(mode='proactive_tier3') call
  - capture of the actual outcome (ship/skip/reshape/kill/error) into
    telemetry, including the model's draft and skip reason

Mirror discipline preserved: the Tier 3 call's outbound buffer is
NEVER sent. Legacy donna_turn(mode='proactive') still ships to the
user. Tier 3 outcome is logged-only.

Phase 2A of proactive brain redesign — Tier 3 LLM fires for real."
```

---

## Task 7: Update eval script for new outcome values

**Files:**
- Modify: `scripts/proactive_counterfactual_eval.py`
- Modify: `backend/tests/proactive/test_counterfactual_eval.py` (add new outcome cases)

**Why:** The eval script currently expects `input_built` / `input_failed`. Phase 2A produces `ship` / `skip` / `reshape` / `kill` / `error` / `no_terminator`. Update the report.

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/proactive/test_counterfactual_eval.py`:

```python
def test_summarize_counts_phase_2a_outcomes():
    rows = [
        _row(outcome="ship"),
        _row(outcome="ship"),
        _row(outcome="skip"),
        _row(outcome="reshape"),
        _row(outcome="kill"),
        _row(outcome="error", error="RuntimeError: SDK failure"),
        _row(outcome="no_terminator"),
    ]
    summary = _summarize(rows)
    assert summary["ship"] == 2
    assert summary["skip"] == 1
    assert summary["reshape"] == 1
    assert summary["kill"] == 1
    assert summary["error"] == 1
    assert summary["no_terminator"] == 1


def test_summarize_per_speech_act_includes_phase_2a_outcomes():
    rows = [
        _row(speech_act="heads_up", outcome="ship"),
        _row(speech_act="heads_up", outcome="skip"),
        _row(speech_act="i_noticed", outcome="ship"),
    ]
    summary = _summarize(rows)
    heads = summary["by_speech_act"]["heads_up"]
    assert heads["ship"] == 1
    assert heads["skip"] == 1
    iotc = summary["by_speech_act"]["i_noticed"]
    assert iotc["ship"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/proactive/test_counterfactual_eval.py::test_summarize_counts_phase_2a_outcomes -v
```
Expected: KeyError or AssertionError.

- [ ] **Step 3: Modify `scripts/proactive_counterfactual_eval.py`**

Find `_summarize`. Replace the body with a version that counts the Phase 2A outcomes:

```python
def _summarize(rows: list[Any]) -> dict[str, Any]:
    total = len(rows)
    legacy_ships = sum(
        1 for r in rows if (r.counterfactual_legacy_outbound_count or 0) > 0
    )

    # Phase 2A outcomes
    outcomes = ("ship", "skip", "reshape", "kill", "error", "no_terminator",
                "input_built", "input_failed")
    counts = {
        outcome: sum(
            1 for r in rows
            if r.counterfactual_fat_contract_outcome == outcome
        )
        for outcome in outcomes
    }

    # Per-speech-act breakdown
    by_act: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "n": 0, "legacy_ships": 0,
            **{o: 0 for o in outcomes},
        }
    )
    for r in rows:
        act = r.speech_act or "unknown"
        by_act[act]["n"] += 1
        if (r.counterfactual_legacy_outbound_count or 0) > 0:
            by_act[act]["legacy_ships"] += 1
        outcome = r.counterfactual_fat_contract_outcome
        if outcome in by_act[act]:
            by_act[act][outcome] += 1

    # Per-source breakdown
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, **{o: 0 for o in outcomes}}
    )
    for r in rows:
        src = r.source or "unknown"
        by_source[src]["n"] += 1
        outcome = r.counterfactual_fat_contract_outcome
        if outcome in by_source[src]:
            by_source[src][outcome] += 1

    elapsed = [
        r.counterfactual_fat_contract_elapsed_ms
        for r in rows
        if r.counterfactual_fat_contract_elapsed_ms is not None
    ]
    p50 = _percentile(elapsed, 0.50)
    p95 = _percentile(elapsed, 0.95)

    errors = Counter()
    for r in rows:
        if (
            r.counterfactual_fat_contract_outcome == "error"
            and r.counterfactual_fat_contract_error
        ):
            err_type = r.counterfactual_fat_contract_error.split(":", 1)[0]
            errors[err_type] += 1

    return {
        "total": total,
        "legacy_ships": legacy_ships,
        **counts,
        "by_speech_act": dict(by_act),
        "by_source": dict(by_source),
        "elapsed_ms_p50": p50,
        "elapsed_ms_p95": p95,
        "top_errors": errors.most_common(5),
    }
```

Also update `_print_report` to print the new counts. Find the existing printer and replace the body:

```python
def _print_report(summary: dict[str, Any], days: int) -> None:
    total = summary["total"]
    print(f"=== proactive counterfactual eval — last {days} days ===\n")
    print(f"total events dispatched:  {total}")
    print(f"  legacy ships:           {summary['legacy_ships']}")
    print(f"  ship (tier 3):          {summary['ship']}")
    print(f"  skip (tier 3):          {summary['skip']}")
    print(f"  reshape (tier 3):       {summary['reshape']}")
    print(f"  kill (tier 3):          {summary['kill']}")
    print(f"  error (tier 3):         {summary['error']}")
    print(f"  no_terminator:          {summary['no_terminator']}")
    print(f"  input_built (legacy):   {summary['input_built']}")
    print(f"  input_failed (legacy):  {summary['input_failed']}")
    print(f"  elapsed_ms p50 / p95:   {summary['elapsed_ms_p50']} / {summary['elapsed_ms_p95']}")
    print()

    if summary["by_speech_act"]:
        print("per speech_act:")
        for act, stats in sorted(summary["by_speech_act"].items()):
            print(
                f"  {act:20} n={stats['n']:>4}  "
                f"ship={stats['ship']:>3}  "
                f"skip={stats['skip']:>3}  "
                f"reshape={stats['reshape']:>2}  "
                f"kill={stats['kill']:>2}  "
                f"err={stats['error']:>2}"
            )
        print()

    if summary["by_source"]:
        print("per source:")
        for src, stats in sorted(summary["by_source"].items()):
            print(
                f"  {src:20} n={stats['n']:>4}  "
                f"ship={stats['ship']:>3}  "
                f"skip={stats['skip']:>3}  "
                f"err={stats['error']:>2}"
            )
        print()

    if summary["top_errors"]:
        print("top error types (Tier 3 SDK exceptions):")
        for err_type, count in summary["top_errors"]:
            print(f"  {err_type}: {count}")
```

- [ ] **Step 4: Run tests**

```
pytest backend/tests/proactive/test_counterfactual_eval.py -v
```
Expected: 9 passed (7 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/proactive_counterfactual_eval.py backend/tests/proactive/test_counterfactual_eval.py
git commit -m "feat(scripts): eval reports Phase 2A Tier 3 outcomes

Recognizes the new counterfactual_fat_contract_outcome values from the
real Tier 3 call: ship / skip / reshape / kill / error / no_terminator.
Per-speech-act and per-source breakdowns now show ship/skip ratios per
act so calibration can be measured against the spec's targets
(dont_forget ~95%, heads_up ~50-70%, i_noticed ~15-25%, etc.).

Backwards-compatible with Phase 1 outcomes (input_built / input_failed)
still counted alongside.

Phase 2A of proactive brain redesign."
```

---

## Self-Review

After all 7 tasks complete:

- [ ] **Spec coverage:**
  - Task 1 → SDK tool registration (Phase 2 surface area in spec's migration plan)
  - Task 2 → options.py mode-aware tool registration (the unlock)
  - Tasks 3-5 → real block builders for the Tier 3 input contract (replaces Phase 1 placeholders)
  - Task 6 → real donna_turn(mode="proactive_tier3") call (the actual LLM fires)
  - Task 7 → eval recognizes the new outcomes (calibration data)

  Coverage: every Phase 2A item in the leaner cut is implemented.

- [ ] **Placeholder scan:** no "TBD"/"TODO" in plan steps. The "queued_thing_block" stays as a placeholder string in Task 6's `build_tier3_user_message` call — that builder is deferred to Phase 2.5 along with `fresh_signal` real fetchers and per-source speech_act adapters.

- [ ] **Type consistency:**
  - `TIER3_SDK_TOOLS` tuple name matches between Tasks 1 and 2
  - `mode="proactive_tier3"` matches between Tasks 2 and 6
  - `counterfactual_fat_contract_outcome` values (`ship`/`skip`/`reshape`/`kill`/`error`) match between Task 6 and Task 7
  - `_tier3_outcome` key on the `donna_turn` result dict matches between Task 6's dispatcher code and the test fakes

- [ ] **Run order:** Tasks 1 and 2 are independent of each other but Task 2 imports from Task 1's module. Tasks 3, 4, 5 are independent (each adds a block builder). Task 6 depends on Tasks 1-5. Task 7 depends on Task 6's outcome shape.

  Recommended order: 1 → 2 → 3 → 4 → 5 → 6 → 7.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-04-proactive-brain-phase-2a.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality). Same flow Phase 1 used.

**2. Inline Execution** — execute tasks in this session with executing-plans.

Which approach?
