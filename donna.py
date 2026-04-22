"""
Donna - Agent SDK prototype entrypoint.

The runtime is split into donna_runtime:
- config.py: model, tool allow/deny lists, and exercise messages
- data.py: temporary profile, memory, and tracker fixtures
- prompt.py: system prompt construction
- tool_logic.py: SDK-free tool behavior
- tools.py: Claude Agent SDK tool wrappers
- hooks.py: differentiated pre/post tool hooks
- tracing.py: turn trace persistence and pretty printing
- langsmith_tracing.py: optional LangSmith instrumentation helpers
- audit.py: trace policy checks
- options.py: MCP server and ClaudeAgentOptions wiring
- runner.py: async client loop
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from donna_runtime.audit import render_audit_report
from donna_runtime.config import DEFAULT_TEST_MESSAGES, EXERCISE_MESSAGES, DonnaAgentConfig, SESSION_STORE_FILE, TRACE_FILE
from donna_runtime.context_builder import build_user_context
from donna_runtime.env import env_bool, load_dotenv
from donna_runtime.health import render_health_report
from donna_runtime.langsmith_tracing import run_smoke_test
from donna_runtime.session_store import resolve_session_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or audit the Donna Agent SDK prototype")
    parser.add_argument("--message", action="append", help="run one message; repeat for multiple messages")
    parser.add_argument("--exercise", action="store_true", help="run the full 10-message prediction exercise")
    parser.add_argument("--trace-file", default=os.getenv("DONNA_TRACE_FILE", str(TRACE_FILE)), help="JSONL trace output or audit path")
    parser.add_argument("--audit-only", action="store_true", help="audit an existing trace file without importing the SDK runner")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=float(os.getenv("DONNA_REQUEST_TIMEOUT_S", "45")), help="Agent SDK query timeout in seconds")
    parser.add_argument("--model", default=os.getenv("DONNA_MODEL", DonnaAgentConfig.model))
    parser.add_argument("--thinking", action="store_true", help="enable model thinking if supported by the SDK")
    parser.add_argument("--session-id", help="Claude Agent SDK session id to resume with options.resume")
    parser.add_argument("--user-id", default=os.getenv("DONNA_USER_ID"), help="application user id for local session-id lookup")
    parser.add_argument("--session-store", default=os.getenv("DONNA_SESSION_STORE", str(SESSION_STORE_FILE)), help="local JSON file mapping user ids to Claude session ids")
    parser.add_argument("--new-session", action="store_true", help="ignore stored session id and start a fresh Claude session")
    parser.add_argument("--fork-session", action="store_true", help="resume then fork the session into a new Claude session id")
    parser.add_argument("--langsmith", action="store_true", help="force LangSmith tracing on for this run")
    parser.add_argument("--no-langsmith", action="store_true", help="force LangSmith tracing off for this run")
    parser.add_argument("--langsmith-local", action="store_true", help="use LangSmith local tracing mode without posting")
    parser.add_argument("--langsmith-project", default=os.getenv("LANGSMITH_PROJECT"), help="LangSmith project name for this run")
    parser.add_argument("--langsmith-smoke-test", action="store_true", help="run a local LangSmith instrumentation smoke test")
    parser.add_argument("--health", action="store_true", help="check local Donna/Agent SDK runtime readiness")
    parser.add_argument("--phone", default=os.getenv("FOUNDER_PHONE"), help="WhatsApp phone (E.164) to deliver send_burst outputs to")
    return parser


def select_messages(args: argparse.Namespace) -> tuple[str, ...]:
    if args.message:
        return tuple(args.message)
    if args.exercise:
        return EXERCISE_MESSAGES
    return DEFAULT_TEST_MESSAGES


async def async_main(args: argparse.Namespace) -> None:
    try:
        from donna_runtime.runner import run_messages
    except ModuleNotFoundError as exc:
        if exc.name == "claude_agent_sdk":
            raise SystemExit(
                "Missing dependency: claude_agent_sdk. Install it with `python -m pip install claude-agent-sdk`."
            ) from exc
        raise

    trace_file = Path(args.trace_file)
    session_store_file = Path(args.session_store)
    resume_session_id = resolve_session_id(
        explicit_session_id=args.session_id,
        user_id=args.user_id,
        store_path=session_store_file,
        new_session=args.new_session,
    )
    config = DonnaAgentConfig(
        model=args.model,
        max_turns=args.max_turns,
        request_timeout_s=args.timeout,
        trace_file=trace_file,
        session_store_file=session_store_file,
        thinking_enabled=args.thinking,
        system_context=build_user_context(args.user_id).render_system_context(),
        resume_session_id=resume_session_id,
        user_id=args.user_id,
        fork_session=args.fork_session,
        langsmith_enabled=resolve_langsmith_enabled(args),
        langsmith_project=args.langsmith_project,
        target_phone=args.phone,
    )
    await run_messages(select_messages(args), config=config, trace_file=trace_file)


def resolve_langsmith_enabled(args: argparse.Namespace):
    if args.no_langsmith:
        return False
    if args.langsmith_local:
        return "local"
    if args.langsmith:
        return True
    return env_bool("LANGSMITH_TRACING", default=False)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    trace_file = Path(args.trace_file)
    if args.langsmith_smoke_test:
        print(json.dumps(run_smoke_test(project_name=args.langsmith_project), indent=2))
        return 0
    if args.health:
        print(render_health_report())
        return 0
    if args.audit_only:
        print(render_audit_report(trace_file))
        return 0
    asyncio.run(async_main(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
