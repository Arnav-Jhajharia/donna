from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from donna_runtime.audit import audit_trace
from donna_runtime.context_builder import build_user_context
from donna_runtime import context_builder
from donna_runtime.config import DonnaAgentConfig
from donna_runtime.env import load_dotenv
from donna_runtime.health import render_health_report
from donna_runtime.langsmith_tracing import langsmith_available, run_smoke_test
from donna_runtime.prompt import build_system_prompt, wrap_user_message_with_context
from donna_runtime.session_store import resolve_session_id, save_user_session
from donna_runtime.tool_logic import (
    _build_outbound,
    render_burst_items_text,
    render_outbound_text,
    send_burst_text,
)
from donna_runtime.tracing import TurnTrace
from donna_runtime.runner import _is_missing_resume_error, _should_retry_without_resume


class DonnaRuntimeTests(unittest.TestCase):
    def test_prompt_keeps_terminal_contract(self) -> None:
        prompt = build_system_prompt(runtime_context="## Runtime Context\nUser id: test-user")
        self.assertIn("send_burst", prompt)
        self.assertIn("Do not fabricate", prompt)
        self.assertIn("Tools are affordances", prompt)
        self.assertIn("Default to high agency", prompt)
        # runtime_context is intentionally ignored now — prefix must stay
        # byte-stable across turns for SDK prefix caching. Volatile context
        # is injected via wrap_user_message_with_context instead.
        self.assertNotIn("User id: test-user", prompt)

    def test_real_mode_exposes_affordance_tools(self) -> None:
        from donna_runtime.config import ALLOWED_TOOLS
        from donna_runtime.options import build_options

        expected = {
            "mcp__donna__recall",
            "mcp__donna__remember",
            "mcp__donna__watch",
            "mcp__donna__schedule",
            "mcp__donna__check_calendar",
            "mcp__donna__image",
            "mcp__donna__web_search",
            "mcp__donna__agentic_web_search",
            "mcp__donna__research",
            "mcp__donna__send_burst",
            "mcp__donna__connect_integration",
            "mcp__donna__list_gmail_recent",
            "mcp__donna__read_gmail_thread",
            "mcp__donna__list_calendar",
            "mcp__donna__composio_search_tools",
            "mcp__donna__composio_manage_connections",
            "mcp__donna__composio_wait_for_connections",
            "mcp__donna__composio_execute_tool",
        }
        self.assertEqual(set(ALLOWED_TOOLS), expected)
        self.assertEqual(set(build_options().allowed_tools), expected)

        # Fake mode is offline dev-only; integration tools have no fake
        # implementations so they're absent from FAKE_ALLOWED_TOOLS.
        from donna_runtime.fake_tools import FAKE_ALLOWED_TOOLS

        self.assertEqual(
            set(build_options(DonnaAgentConfig(tool_mode="fake")).allowed_tools),
            set(FAKE_ALLOWED_TOOLS),
        )

    def test_tool_logic_is_sdk_free(self) -> None:
        self.assertEqual("Sent 2 messages.", send_burst_text(("a", "b")))

    def test_remember_tool_no_longer_exposes_fact_key(self) -> None:
        """Profile facts moved out of the remember tool — the pre-BRAIN
        deterministic detector and the post-turn Haiku extractor handle them
        automatically now. The schema must not expose fact_key/kind='fact'
        anymore or the model will still try to call it."""
        from donna_runtime import tools as runtime_tools

        properties = runtime_tools.remember.input_schema["properties"]
        self.assertNotIn(
            "fact_key", properties,
            "fact_key should be removed from remember schema (handled by hooks)",
        )
        kind_desc = properties["kind"]["description"]
        self.assertNotIn("fact", kind_desc)
        self.assertNotIn("preference", kind_desc)

    def test_remember_fact_kind_returns_deprecation_message(self) -> None:
        """If the model still calls remember(kind='fact'), the tool must tell
        it the path is gone and to just reply — not fail silently or write."""
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(
                runtime_tools.remember.handler(
                    {"kind": "fact", "content": "Arnav"}
                )
            )
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("removed", text.lower())
        # Must steer the model toward doing nothing (not another tool call).
        self.assertIn("reply", text.lower())

    def test_memory_tool_result_text_is_readable(self) -> None:
        from donna_runtime import tools as runtime_tools

        no_hits = runtime_tools._tool_text({"status": "no_hits", "payload": []})
        degraded = runtime_tools._tool_text(
            {"status": "degraded", "payload": {"reason": "db unavailable"}}
        )
        ok = runtime_tools._tool_text(
            {"status": "ok", "payload": [{"content": "remembered thing", "source": "test"}]}
        )

        self.assertEqual(no_hits["content"][0]["text"], "No hits.")
        self.assertIn("db unavailable", degraded["content"][0]["text"])
        self.assertIn("remembered thing", ok["content"][0]["text"])

    def test_render_payload_emits_truncation_hint_only_when_truncating(self) -> None:
        """When a list result exceeds the render cap, the tool response must
        tell the agent HOW to narrow — not silently drop hits. Blog principle:
        'Steer agents with helpful instructions' when truncating."""
        from donna_runtime import tools as runtime_tools

        short = [{"content": f"item {i}"} for i in range(3)]
        self.assertNotIn("showing", runtime_tools._render_payload(short))

        long = [{"content": f"item {i}"} for i in range(25)]
        rendered = runtime_tools._render_payload(long)
        self.assertIn("showing 10 of 25", rendered)
        self.assertIn("narrow", rendered)

    def test_remember_empty_kind_returns_actionable_error(self) -> None:
        """Opaque 'Memory not recorded.' was hostile. Empty kind must surface
        valid values inline so the agent can self-correct without re-reading
        the tool description."""
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(
                runtime_tools.remember.handler({"kind": "", "content": "hi"})
            )
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("'kind' is required", text)
        self.assertIn("observation", text)
        self.assertIn("timezone", text)

    def test_remember_unsupported_kind_lists_valid_kinds(self) -> None:
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(
                runtime_tools.remember.handler({"kind": "gossip", "content": "x"})
            )
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("unsupported kind", text)
        self.assertIn("observation", text)
        self.assertIn("timezone", text)
        # fact/preference intentionally absent — handled by pre-BRAIN detector + post-turn hook.
        self.assertNotIn("fact", text)

    def test_remember_observation_missing_fields_explains_payload_shape(self) -> None:
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(
                runtime_tools.remember.handler(
                    {"kind": "observation", "content": "6 bucks coffee",
                     "observation_type": "expense"}
                )
            )
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("'fields' is required", text)
        self.assertIn("amount_usd", text)  # example shape included

    def test_close_open_loop_missing_id_tells_agent_how_to_get_one(self) -> None:
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(
                runtime_tools.remember.handler({"kind": "loop_closed", "content": "done"})
            )
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("loop_id", text)
        # must tell the agent how to acquire a loop_id, not just that it's missing
        self.assertIn("recall", text.lower())

    def test_schedule_missing_time_tells_agent_the_three_options(self) -> None:
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(
                runtime_tools.schedule.handler({"text": "ping me about the thing"})
            )
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("fire_at", text)
        self.assertIn("in_minutes", text)
        self.assertIn("when", text)
        self.assertIn("do not invent", text.lower())

    def test_set_timezone_missing_value_rejects_abbreviations(self) -> None:
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(runtime_tools.set_timezone.handler({}))
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("IANA", text)
        self.assertIn("Asia/Singapore", text)
        self.assertIn("PST", text)  # names an abbreviation to avoid

    def test_watch_missing_intent_gives_example(self) -> None:
        from donna_runtime import tools as runtime_tools
        from donna_runtime.hooks import _CURRENT_USER_ID

        token = _CURRENT_USER_ID.set("test-user")
        try:
            result = asyncio.run(runtime_tools.watch.handler({}))
        finally:
            _CURRENT_USER_ID.reset(token)

        text = result["content"][0]["text"]
        self.assertIn("'intent' is required", text)
        self.assertIn("e.g.", text)  # must include an example

    def test_exported_tools_carry_when_not_to_use_clauses(self) -> None:
        """CLAUDE.md non-negotiable: every tool description must include a
        when-NOT-to-use clause. Blog principle: explicit boundaries prevent
        tool-selection ambiguity."""
        from donna_runtime import tools as runtime_tools

        for tool_fn in runtime_tools.DONNA_TOOLS:
            name = tool_fn.name
            if name == "send_burst":
                continue  # terminator has its own unique contract
            desc = (tool_fn.description or "").lower()
            self.assertIn(
                "do not", desc,
                f"tool {name!r} description missing when-NOT-to-use clause",
            )

    def test_trace_records_pre_and_post_hooks_separately(self) -> None:
        trace = TurnTrace("how much did i spend this week")
        trace.record_prompts(
            system_prompt="# IDENTITY\nDonna",
            wrapped_user_prompt="## RUNTIME\nx\n\n## USER MESSAGE\nhi",
            metadata={"tool_mode": "real"},
        )
        trace.record_hook_pre({"tool_name": "mcp__donna__read_tracker", "tool_input": {"name": "expenses_week"}}, "call_1")
        trace.record_tool_call("mcp__donna__read_tracker", {"name": "expenses_week"}, "call_1")
        trace.record_hook_post({"tool_name": "mcp__donna__read_tracker"}, "call_1")
        trace.record_tool_call("mcp__donna__send_burst", {"messages": ["127 sgd"], "tone": "crisp"}, "call_2")
        trace.record_usage({"cache_creation_input_tokens": 10, "cache_read_input_tokens": 20})
        trace.finalize(cost=0.01, num_turns=2)

        payload = trace.to_dict()
        self.assertEqual(len(payload["tool_calls"]), 2)
        self.assertEqual([event["phase"] for event in payload["hook_events"]], ["pre", "post"])
        self.assertEqual(payload["tool_results"][0]["call_id"], "call_1")
        self.assertEqual(payload["cache_creation_input_tokens"], 10)
        self.assertEqual(payload["cache_read_input_tokens"], 20)
        self.assertEqual(payload["system_prompt"], "# IDENTITY\nDonna")
        self.assertIn("## USER MESSAGE\nhi", payload["wrapped_user_prompt"])
        self.assertEqual(payload["prompt_metadata"]["tool_mode"], "real")
        self.assertTrue(trace.has_terminal_tool_call())

    def test_runner_falls_back_plain_result_text_to_send_burst(self) -> None:
        from delivery.messages import TextMessage
        from donna_runtime.hooks import _OUTBOUND_BUFFER
        from donna_runtime.runner import _fallback_plain_text_to_send_burst

        trace = TurnTrace("how much did i spend")
        trace.record_result(subtype="success", result="sgd 6 today.", is_error=False)
        buffer: list = []
        token = _OUTBOUND_BUFFER.set(buffer)
        try:
            asyncio.run(_fallback_plain_text_to_send_burst(trace))
        finally:
            _OUTBOUND_BUFFER.reset(token)

        self.assertTrue(trace.has_terminal_tool_call())
        self.assertEqual(trace.tool_calls[-1]["tool"], "mcp__donna__send_burst")
        self.assertEqual(len(buffer), 1)
        self.assertIsInstance(buffer[0], TextMessage)
        self.assertEqual(buffer[0].body, "sgd 6 today.")

    def test_context_builder_renders_runtime_context(self) -> None:
        context = build_user_context("user-1")
        rendered = context.render_system_context()
        self.assertIn("User id: user-1", rendered)

    def test_render_turn_context_is_volatile_only(self) -> None:
        state = {
            "user_id": "user-1",
            "_user_name": "Arnav",
            "_user_timezone": "Asia/Singapore",
            "_is_first_message": False,
            "_resume_session_id": "session-xyz",
            "reply_to_role": "assistant",
            "reply_to_content": "old answer",
            "url_contents": [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "text": "page excerpt",
                    "status": "ok",
                }
            ],
        }
        rendered = asyncio.run(context_builder.render_turn_context(state))

        self.assertIn("user_id: user-1", rendered)
        self.assertIn("name: Arnav", rendered)
        self.assertIn("timezone: Asia/Singapore", rendered)
        self.assertIn("REPLY CONTEXT", rendered)
        self.assertIn("URL CONTEXT", rendered)
        self.assertNotIn("USER MODEL", rendered)
        self.assertNotIn("RECENT CHAT", rendered)
        self.assertNotIn("OPEN LOOPS", rendered)
        self.assertNotIn("7-DAY TRACKER SNAPSHOT", rendered)
        self.assertLessEqual(len(rendered), 1200)

    def test_render_turn_context_hydrates_on_cold_start(self) -> None:
        async def fake_recent(user_id):
            return ["- user: last thing", "- assistant: noted"]

        state = {
            "user_id": "user-1",
            "_user_timezone": "Asia/Singapore",
            "_resume_session_id": None,
        }
        with patch.object(context_builder, "_safe_recent_chat", fake_recent):
            rendered = asyncio.run(context_builder.render_turn_context(state))
        # Cold start header still calls out session hydration; count is inline.
        self.assertIn("RECENT CHAT (last 2 messages, session cold-start hydration)", rendered)
        self.assertIn("last thing", rendered)

    def test_render_turn_context_always_hydrates_when_resumed(self) -> None:
        """Stateless/resumed alike should include recent chat — it's the only
        durable conversation history the model sees in stateless mode."""
        async def fake_recent(user_id):
            return ["- user: earlier", "- assistant: ack"]

        state = {
            "user_id": "user-1",
            "_user_timezone": "Asia/Singapore",
            "_resume_session_id": "session-xyz",
        }
        with patch.object(context_builder, "_safe_recent_chat", fake_recent):
            rendered = asyncio.run(context_builder.render_turn_context(state))
        self.assertIn("RECENT CHAT (last 2 messages)", rendered)
        self.assertNotIn("cold-start hydration", rendered)
        self.assertIn("earlier", rendered)

    def test_system_prompt_does_not_bake_user_model(self) -> None:
        prompt = build_system_prompt(
            tool_mode="real",
            user_model_block="USER MODEL\n  name: Arnav\n  timezone: Asia/Kolkata",
        )
        self.assertNotIn("# WHO YOU'RE TALKING TO", prompt)
        self.assertNotIn("name: Arnav", prompt)
        self.assertNotIn("timezone: Asia/Kolkata", prompt)

    def test_wrap_user_message_includes_user_model_block(self) -> None:
        prompt = wrap_user_message_with_context(
            "hi",
            "## Runtime Context\nuser_id: user-1",
            "USER MODEL\n  name: Arnav\n\nSITUATION BRIEF\n  current: testing donna",
        )
        self.assertIn("## USER MODEL", prompt)
        self.assertIn("name: Arnav", prompt)
        self.assertIn("SITUATION BRIEF", prompt)
        self.assertIn("## Runtime Context", prompt)
        self.assertTrue(prompt.endswith("## USER MESSAGE\nhi"))

    def test_brain_passes_rendered_context_to_runner(self) -> None:
        from delivery.messages import TextMessage
        from donna_runtime import brain
        from donna_runtime.hooks import _OUTBOUND_BUFFER

        captured = {}

        async def fake_resolve(**kwargs):
            return "session-1"

        async def fake_save(user_id, session_id):
            captured["saved"] = (user_id, session_id)

        async def fake_context(state):
            return "REPLY CONTEXT\nreply_to_content: prior message"

        async def fake_user_model(user_id):
            return "USER MODEL\n  name: Arnav"

        async def fake_turn(message, config):
            captured["message"] = message
            captured["config"] = config
            buffer = _OUTBOUND_BUFFER.get()
            if buffer is not None:
                buffer.append(TextMessage(body="ack"))
            trace = TurnTrace(message)
            trace.record_session_id("session-2")
            return trace

        state = {
            "user_id": "user-1",
            "raw_input": "hello",
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
            patch.object(brain, "resolve_session_id_db", fake_resolve), \
            patch.object(brain, "save_user_session_db", fake_save), \
            patch.object(brain, "render_turn_context", fake_context), \
            patch.object(brain, "load_user_model_block", fake_user_model), \
            patch.object(brain, "traced_donna_turn", fake_turn):
            cfg = DonnaAgentConfig(trace_file=Path(tmpdir) / "trace.jsonl")
            result = asyncio.run(brain.donna_turn(state, config=cfg))

        self.assertEqual(captured["message"], "hello")
        self.assertIn("REPLY CONTEXT", captured["config"].system_context)
        self.assertIn("USER MODEL", captured["config"].user_model_block)
        self.assertTrue(captured["config"].chat_already_persisted)
        self.assertEqual(captured["saved"], ("user-1", "session-2"))
        self.assertEqual(result["_outbound"][0].body, "ack")

    def test_audit_flags_disallowed_tools_and_send_burst_policy(self) -> None:
        findings = audit_trace(
            {
                "turn_id": "turn_test",
                "tool_calls": [
                    {"tool": "ToolSearch", "inputs": {}, "call_id": "call_search"},
                    {
                        "tool": "mcp__donna__send_burst",
                        "call_id": "call_send",
                        "inputs": {"messages": ["HARP first - logged"], "tone": "direct"},
                    },
                ],
            }
        )
        codes = {finding.code for finding in findings}
        self.assertIn("disallowed_tool", codes)
        self.assertIn("send_burst_not_lowercase", codes)
        self.assertIn("claims_write_without_tool", codes)

    def test_audit_handles_discriminated_union_burst(self) -> None:
        findings = audit_trace(
            {
                "turn_id": "turn_union",
                "tool_calls": [
                    {
                        "tool": "mcp__donna__send_burst",
                        "call_id": "call_send",
                        "inputs": {
                            "messages": [
                                {"type": "text", "body": "ack"},
                                {"type": "delay", "seconds": 1.0},
                                {
                                    "type": "cta",
                                    "body": "ship it?",
                                    "buttons": [
                                        {"id": "yes", "title": "yes"},
                                        {"id": "no", "title": "no"},
                                    ],
                                },
                            ]
                        },
                    }
                ],
            }
        )
        codes = {finding.code for finding in findings}
        # delay shouldn't count toward 1-3 cap; this burst has 2 real items.
        self.assertNotIn("bad_send_burst_count", codes)
        self.assertNotIn("send_burst_not_lowercase", codes)

    def test_audit_flags_em_dash_in_cta_body(self) -> None:
        findings = audit_trace(
            {
                "turn_id": "turn_cta_em",
                "tool_calls": [
                    {
                        "tool": "mcp__donna__send_burst",
                        "call_id": "c1",
                        "inputs": {
                            "messages": [
                                {
                                    "type": "cta",
                                    "body": "pick one — quickly",
                                    "buttons": [{"id": "a", "title": "a"}],
                                }
                            ]
                        },
                    }
                ],
            }
        )
        codes = {finding.code for finding in findings}
        self.assertIn("send_burst_em_dash", codes)

    def test_build_outbound_constructs_each_message_type(self) -> None:
        from delivery.messages import (
            CTAMessage, CTAUrlMessage, Delay, ImageMessage, ListMessage, TextMessage,
        )
        text = _build_outbound({"type": "text", "body": "hi"})
        self.assertIsInstance(text, TextMessage)
        self.assertEqual(text.body, "hi")

        cta = _build_outbound({
            "type": "cta", "body": "?",
            "buttons": [{"id": "y", "title": "yes"}],
        })
        self.assertIsInstance(cta, CTAMessage)
        self.assertEqual(cta.buttons[0].id, "y")

        cta_url = _build_outbound({
            "type": "cta_url", "body": "open",
            "display_text": "Open", "url": "https://example.com",
        })
        self.assertIsInstance(cta_url, CTAUrlMessage)

        lst = _build_outbound({
            "type": "list", "body": "pick", "button_label": "Pick",
            "sections": [{"title": "Opts", "rows": [{"id": "a", "title": "A"}]}],
        })
        self.assertIsInstance(lst, ListMessage)

        img = _build_outbound({"type": "image", "url": "https://x/y.jpg", "caption": "c"})
        self.assertIsInstance(img, ImageMessage)

        d = _build_outbound({"type": "delay", "seconds": 1.5})
        self.assertIsInstance(d, Delay)
        self.assertEqual(d.seconds, 1.5)

        # Bare-string back-compat path
        bare = _build_outbound("plain")
        self.assertIsInstance(bare, TextMessage)

        # Empty body / unknown type rejected
        self.assertIsNone(_build_outbound({"type": "text", "body": ""}))
        self.assertIsNone(_build_outbound({"type": "what", "body": "x"}))

    def test_render_burst_items_text_skips_delays(self) -> None:
        items = [
            {"type": "text", "body": "ack"},
            {"type": "delay", "seconds": 1.0},
            {"type": "cta", "body": "ship?", "buttons": [{"id": "y", "title": "yes"}]},
        ]
        rendered = render_burst_items_text(items)
        self.assertEqual(len(rendered), 2)
        self.assertEqual(rendered[0], "ack")
        self.assertIn("yes", rendered[1])

    def test_render_outbound_text_handles_cta_and_image(self) -> None:
        from delivery.messages import Button, CTAMessage, Delay, ImageMessage
        cta = CTAMessage(body="ship?", buttons=[Button(id="y", title="yes"), Button(id="n", title="no")])
        rendered = render_outbound_text(cta)
        self.assertIn("ship?", rendered)
        self.assertIn("yes | no", rendered)

        img = ImageMessage(url="https://x/y.jpg", caption="receipt")
        self.assertIn("receipt", render_outbound_text(img))

        # Delay is not persistable
        self.assertIsNone(render_outbound_text(Delay(seconds=1.0)))

    def test_audit_reports_sdk_error_without_missing_tool_noise(self) -> None:
        findings = audit_trace(
            {
                "turn_id": "turn_auth",
                "result_is_error": True,
                "result_text": "Not logged in",
                "runtime_error": "Command failed",
                "tool_calls": [],
            }
        )
        codes = {finding.code for finding in findings}
        self.assertIn("sdk_result_error", codes)
        self.assertIn("runtime_error", codes)
        self.assertNotIn("missing_tool_call", codes)

    def test_entrypoint_audit_only_does_not_require_sdk_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_path = Path(tmpdir) / "trace.jsonl"
            trace_path.write_text(
                json.dumps(
                    {
                        "turn_id": "turn_test",
                        "tool_calls": [
                            {
                                "tool": "mcp__donna__send_burst",
                                "inputs": {"messages": ["k"], "tone": "crisp"},
                                "call_id": "call_1",
                            }
                        ],
                    }
                )
                + "\n"
            )
            result = subprocess.run(
                [sys.executable, "donna.py", "--audit-only", "--trace-file", str(trace_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertIn("Donna Trace Audit", result.stdout)
        self.assertIn("Findings: 0", result.stdout)

    def test_langsmith_smoke_test_runs_without_api_key(self) -> None:
        result = run_smoke_test(project_name="donna-test")
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["project"], "donna-test")
        self.assertEqual(result["payload"]["status"], "ok")
        self.assertEqual(result["langsmith_available"], langsmith_available())

    def test_entrypoint_langsmith_smoke_test_outputs_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "donna.py", "--langsmith-smoke-test", "--langsmith-project", "donna-test"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["project"], "donna-test")
        self.assertEqual(payload["payload"]["status"], "ok")

    def test_health_report_runs(self) -> None:
        report = render_health_report()
        self.assertIn("Donna Health", report)
        self.assertIn("Claude CLI", report)

    def test_missing_resume_error_detection(self) -> None:
        self.assertTrue(_is_missing_resume_error(Exception("No conversation found with session ID: abc")))
        self.assertFalse(_is_missing_resume_error(Exception("authentication failed")))
        self.assertTrue(_should_retry_without_resume(Exception("Command failed with exit code 1")))

    def test_config_has_request_timeout(self) -> None:
        self.assertGreater(DonnaAgentConfig().request_timeout_s, 0)

    def test_local_session_store_maps_user_to_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "sessions.json"
            save_user_session(store_path, "user-1", "session-abc")
            self.assertEqual(
                resolve_session_id(
                    explicit_session_id=None,
                    user_id="user-1",
                    store_path=store_path,
                ),
                "session-abc",
            )
            self.assertIsNone(
                resolve_session_id(
                    explicit_session_id=None,
                    user_id="user-1",
                    store_path=store_path,
                    new_session=True,
                )
            )
            self.assertEqual(
                resolve_session_id(
                    explicit_session_id="session-explicit",
                    user_id="user-1",
                    store_path=store_path,
                ),
                "session-explicit",
            )

    def test_dotenv_loader_sets_missing_values(self) -> None:
        os.environ.pop("DONNA_TEST_ENV", None)
        os.environ.pop("QUOTED", None)
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("DONNA_TEST_ENV=value\nQUOTED='hello world'\n")
            loaded = load_dotenv(env_path)
        self.assertIn("DONNA_TEST_ENV", loaded)
        self.assertEqual(loaded.count("DONNA_TEST_ENV"), 1)
        self.assertEqual(os.environ["DONNA_TEST_ENV"], "value")
        self.assertEqual(os.environ["QUOTED"], "hello world")


if __name__ == "__main__":
    unittest.main()
