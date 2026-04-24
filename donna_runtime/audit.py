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
                f"final tool was {final_tool}, expected send_burst",
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


_KNOWN_ITEM_TYPES = {"text", "cta", "cta_url", "list", "image", "delay"}


def _audit_send_burst(turn_id: str, call: dict[str, Any]) -> list[TraceFinding]:
    """Trace audit for the discriminated-union send_burst payload.

    Structural validation (required fields, button counts, max lengths) is
    enforced compose-time by the JSON Schema. This audit is the secondary
    layer for content rules: voice (lowercase, no em dash), 1-3 non-delay
    items, and false-write claims.
    """
    findings: list[TraceFinding] = []
    inputs = call.get("inputs") or {}
    messages = inputs.get("messages") or []
    if not isinstance(messages, list):
        return [TraceFinding(turn_id, "error", "bad_send_burst_messages", "messages must be a list")]

    real_indexed: list[tuple[int, str, Any]] = []
    for index, message in enumerate(messages, start=1):
        if isinstance(message, str):
            real_indexed.append((index, "text", message))
            continue
        if not isinstance(message, dict):
            findings.append(
                TraceFinding(turn_id, "error", "bad_send_burst_message", f"message {index} is not a dict")
            )
            continue
        item_type = str(message.get("type", "")).lower()
        if item_type not in _KNOWN_ITEM_TYPES:
            findings.append(
                TraceFinding(turn_id, "warn", "send_burst_unknown_type", f"message {index} has unknown type {item_type!r}")
            )
            continue
        if item_type == "delay":
            continue
        real_indexed.append((index, item_type, message))

    if not 1 <= len(real_indexed) <= 3:
        findings.append(
            TraceFinding(
                turn_id,
                "error",
                "bad_send_burst_count",
                f"expected 1-3 non-delay messages, got {len(real_indexed)}",
            )
        )

    for index, item_type, payload in real_indexed:
        bodies: list[str] = []
        if item_type == "text":
            body = payload if isinstance(payload, str) else str(payload.get("body", ""))
            bodies.append(body)
            if len(body) > 200:
                findings.append(
                    TraceFinding(turn_id, "error", "send_burst_too_long", f"message {index} has {len(body)} chars")
                )
        elif item_type in ("cta", "cta_url", "list"):
            bodies.append(str(payload.get("body", "")))
        elif item_type == "image":
            cap = payload.get("caption")
            if cap:
                bodies.append(str(cap))

        for body in bodies:
            if not body:
                continue
            if "—" in body:
                findings.append(
                    TraceFinding(turn_id, "error", "send_burst_em_dash", f"message {index} contains em dash")
                )
            if body != body.lower():
                findings.append(
                    TraceFinding(turn_id, "warn", "send_burst_not_lowercase", f"message {index} is not lowercase")
                )
            lower = body.lower()
            if "logged" in lower and "can't log" not in lower and "cannot log" not in lower:
                findings.append(
                    TraceFinding(
                        turn_id,
                        "warn",
                        "claims_write_without_tool",
                        f"message {index} may imply a write happened without a write tool",
                    )
                )
    return findings
