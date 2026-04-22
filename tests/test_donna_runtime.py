from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from donna_runtime.audit import audit_trace
from donna_runtime.context_builder import build_user_context
from donna_runtime.config import DonnaAgentConfig
from donna_runtime.env import load_dotenv
from donna_runtime.health import render_health_report
from donna_runtime.langsmith_tracing import langsmith_available, run_smoke_test
from donna_runtime.prompt import build_system_prompt
from donna_runtime.session_store import resolve_session_id, save_user_session
from donna_runtime.tool_logic import send_burst_text, stay_silent_text
from donna_runtime.tracing import TurnTrace
from donna_runtime.runner import _is_missing_resume_error, _should_retry_without_resume


class DonnaRuntimeTests(unittest.TestCase):
    def test_prompt_keeps_terminal_contract(self) -> None:
        prompt = build_system_prompt(runtime_context="## Runtime Context\nUser id: test-user")
        self.assertIn("Every turn MUST end with send_burst or stay_silent", prompt)
        self.assertIn("Do not pretend to have done it", prompt)
        self.assertIn("User id: test-user", prompt)

    def test_tool_logic_is_sdk_free(self) -> None:
        self.assertEqual("Sent 2 messages.", send_burst_text(("a", "b")))
        self.assertEqual("Silence logged.", stay_silent_text())

    def test_trace_records_pre_and_post_hooks_separately(self) -> None:
        trace = TurnTrace("how much did i spend this week")
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
        self.assertTrue(trace.has_terminal_tool_call())

    def test_context_builder_renders_runtime_context(self) -> None:
        context = build_user_context("user-1")
        rendered = context.render_system_context()
        self.assertIn("User id: user-1", rendered)

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
                                "tool": "mcp__donna__stay_silent",
                                "inputs": {"reason": "ack"},
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
