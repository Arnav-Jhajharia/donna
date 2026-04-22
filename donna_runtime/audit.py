from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DISALLOWED_TOOLS
from .tracing import TERMINATOR_TOOL_SUFFIXES, load_trace_file


@dataclass(frozen=True)
class TraceFinding:
    turn_id: str
    severity: str
    code: str
    detail: str


def audit_trace(trace: dict[str, Any]) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    turn_id = str(trace.get("turn_id", "unknown"))
    tool_calls = trace.get("tool_calls") or []
    disallowed = set(DISALLOWED_TOOLS)

    if trace.get("runtime_error"):
        findings.append(
            TraceFinding(turn_id, "error", "runtime_error", str(trace["runtime_error"]).splitlines()[0])
        )
    if trace.get("result_is_error"):
        findings.append(
            TraceFinding(turn_id, "error", "sdk_result_error", str(trace.get("result_text") or "SDK result marked as error"))
        )

    if not tool_calls:
        if not trace.get("result_is_error"):
            findings.append(TraceFinding(turn_id, "error", "missing_tool_call", "turn emitted no tool call"))
        return findings

    for call in tool_calls:
        tool_name = str(call.get("tool", "unknown"))
        if tool_name in disallowed:
            findings.append(TraceFinding(turn_id, "error", "disallowed_tool", f"{tool_name} was used"))
        if tool_name.endswith("send_burst"):
            findings.extend(_audit_send_burst(turn_id, call))

    final_tool = str(tool_calls[-1].get("tool", "unknown"))
    if not final_tool.endswith(TERMINATOR_TOOL_SUFFIXES):
        findings.append(
            TraceFinding(
                turn_id,
                "error",
                "missing_terminator",
                f"final tool was {final_tool}, expected send_burst or stay_silent",
            )
        )
    return findings


def audit_trace_file(path: Path) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    for trace in load_trace_file(path):
        findings.extend(audit_trace(trace))
    return findings


def render_audit_report(path: Path) -> str:
    traces = load_trace_file(path)
    findings = [finding for trace in traces for finding in audit_trace(trace)]
    lines = [
        "# Donna Trace Audit",
        "",
        f"Trace file: {path}",
        f"Turns: {len(traces)}",
        f"Findings: {len(findings)}",
        "",
    ]
    if not findings:
        lines.append("No trace policy findings.")
        return "\n".join(lines)
    for finding in findings:
        lines.append(f"- [{finding.severity}] {finding.turn_id} {finding.code}: {finding.detail}")
    return "\n".join(lines)


def _audit_send_burst(turn_id: str, call: dict[str, Any]) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    inputs = call.get("inputs") or {}
    messages = inputs.get("messages") or []
    if not isinstance(messages, list):
        return [TraceFinding(turn_id, "error", "bad_send_burst_messages", "messages must be a list")]
    if not 1 <= len(messages) <= 3:
        findings.append(
            TraceFinding(turn_id, "error", "bad_send_burst_count", f"expected 1-3 messages, got {len(messages)}")
        )
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, str):
            findings.append(TraceFinding(turn_id, "error", "bad_send_burst_message", f"message {index} is not text"))
            continue
        if len(message) > 200:
            findings.append(
                TraceFinding(turn_id, "error", "send_burst_too_long", f"message {index} has {len(message)} chars")
            )
        if "\u2014" in message:
            findings.append(TraceFinding(turn_id, "error", "send_burst_em_dash", f"message {index} contains em dash"))
        if message != message.lower():
            findings.append(TraceFinding(turn_id, "warn", "send_burst_not_lowercase", f"message {index} is not lowercase"))
        if "logged" in message.lower() and "can't log" not in message.lower() and "cannot log" not in message.lower():
            findings.append(
                TraceFinding(
                    turn_id,
                    "warn",
                    "claims_write_without_tool",
                    f"message {index} may imply a write happened without a write tool",
                )
            )
    return findings
