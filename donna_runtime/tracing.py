from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any


TERMINATOR_TOOL_SUFFIXES = ("send_burst",)

# Rates per 1M tokens (USD). Input / Output / CacheWrite5m / CacheRead.
_MODEL_RATES: dict[str, tuple[float, float, float, float]] = {
    "haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "opus-4-7": (15.00, 75.00, 18.75, 1.50),
}
_DEFAULT_RATES = _MODEL_RATES["sonnet-4-6"]


def _rates_for(model: str | None) -> tuple[float, float, float, float]:
    if not model:
        return _DEFAULT_RATES
    for key, rates in _MODEL_RATES.items():
        if key in model:
            return rates
    return _DEFAULT_RATES


def _estimate_cost_from_usage(usage: dict[str, Any], model: str | None = None) -> float:
    """Fallback cost estimate when the SDK returns total_cost_usd=0.

    input_tokens in the SDK usage dict already excludes cached tokens,
    so we add the cache buckets separately.
    """
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    in_rate, out_rate, cw_rate, cr_rate = _rates_for(model or usage.get("model"))
    return (
        input_tokens * in_rate
        + output_tokens * out_rate
        + cache_write * cw_rate
        + cache_read * cr_rate
    ) / 1_000_000


class TurnTrace:
    """Collects emitted blocks, hook events, and persisted trace state for one turn."""

    def __init__(self, user_message: str):
        self.turn_id = f"turn_{int(time.time() * 1000)}"
        self.user_message = user_message
        self.started_at = datetime.now().isoformat()
        self.tool_calls: list[dict[str, Any]] = []
        self.tool_results: list[dict[str, Any]] = []
        self.hook_events: list[dict[str, Any]] = []
        self.model_thoughts: list[str] = []
        self.total_cost_usd = 0.0
        self.usage: dict[str, Any] = {}
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0
        self.num_turns = 0
        self.duration_ms = 0
        self.resume_session_id: str | None = None
        self.session_id: str | None = None
        self.result_subtype: str | None = None
        self.result_text: str | None = None
        self.result_is_error: bool | None = None
        self.runtime_error: str | None = None
        self._start = time.time()
        self._tool_call_index: dict[str, dict[str, Any]] = {}
        self._tool_result_index: dict[str, dict[str, Any]] = {}
        self._hook_starts: dict[str, float] = {}

    def record_tool_call(self, name: str, inputs: dict[str, Any], call_id: str) -> None:
        call = self._ensure_tool_call(call_id, name=name, inputs=inputs)
        call["tool"] = name
        call["inputs"] = inputs

    def record_hook_pre(self, input_data: dict[str, Any], tool_use_id: str) -> None:
        tool_name = str(input_data.get("tool_name") or input_data.get("name") or "unknown")
        tool_input = input_data.get("tool_input") or input_data.get("input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {"value": tool_input}
        elapsed_ms = self._elapsed_ms()
        self._hook_starts[tool_use_id] = time.time()
        call = self._ensure_tool_call(tool_use_id, name=tool_name, inputs=tool_input)
        call["hook_started_at_ms"] = elapsed_ms
        self.hook_events.append(
            {
                "phase": "pre",
                "call_id": tool_use_id,
                "tool": tool_name,
                "at_ms": elapsed_ms,
            }
        )

    def record_hook_post(self, input_data: dict[str, Any], tool_use_id: str) -> None:
        tool_name = str(input_data.get("tool_name") or input_data.get("name") or "unknown")
        elapsed_ms = self._elapsed_ms()
        start = self._hook_starts.get(tool_use_id)
        duration_ms = int((time.time() - start) * 1000) if start is not None else None
        call = self._ensure_tool_call(tool_use_id, name=tool_name, inputs={})
        call["hook_completed_at_ms"] = elapsed_ms
        if duration_ms is not None:
            call["hook_duration_ms"] = duration_ms
            self.record_tool_result(tool_use_id, duration_ms)
        self.hook_events.append(
            {
                "phase": "post",
                "call_id": tool_use_id,
                "tool": tool_name,
                "at_ms": elapsed_ms,
                "duration_ms": duration_ms,
            }
        )

    def record_tool_result(self, call_id: str, duration_ms: int) -> None:
        result = self._tool_result_index.get(call_id)
        if result is None:
            result = {"call_id": call_id}
            self.tool_results.append(result)
            self._tool_result_index[call_id] = result
        result["duration_ms"] = duration_ms

    def record_thought(self, text: str) -> None:
        if text.strip():
            self.model_thoughts.append(text[:500])

    def finalize(self, cost: float, num_turns: int) -> None:
        self.total_cost_usd = cost
        self.num_turns = num_turns
        self.duration_ms = self._elapsed_ms()

    def record_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        self.usage = dict(usage)
        self.cache_creation_input_tokens = int(usage.get("cache_creation_input_tokens") or 0)
        self.cache_read_input_tokens = int(usage.get("cache_read_input_tokens") or 0)
        if not self.total_cost_usd:
            self.total_cost_usd = _estimate_cost_from_usage(usage)

    def record_resume_session_id(self, session_id: str | None) -> None:
        self.resume_session_id = session_id

    def record_session_id(self, session_id: str | None) -> None:
        if session_id:
            self.session_id = session_id

    def record_result(
        self,
        subtype: str | None = None,
        result: str | None = None,
        is_error: bool | None = None,
    ) -> None:
        self.result_subtype = subtype
        self.result_text = result
        self.result_is_error = is_error

    def record_runtime_error(self, error: str) -> None:
        self.runtime_error = error
        if self.duration_ms == 0:
            self.duration_ms = self._elapsed_ms()

    def has_terminal_tool_call(self) -> bool:
        return bool(self.tool_calls and self.tool_calls[-1]["tool"].endswith(TERMINATOR_TOOL_SUFFIXES))

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "user_message": self.user_message,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "num_turns": self.num_turns,
            "resume_session_id": self.resume_session_id,
            "session_id": self.session_id,
            "result_subtype": self.result_subtype,
            "result_text": self.result_text,
            "result_is_error": self.result_is_error,
            "runtime_error": self.runtime_error,
            "total_cost_usd": self.total_cost_usd,
            "usage": self.usage,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "hook_events": self.hook_events,
            "model_thoughts": self.model_thoughts,
        }

    def to_langsmith_outputs(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "duration_ms": self.duration_ms,
            "num_turns": self.num_turns,
            "resume_session_id": self.resume_session_id,
            "session_id": self.session_id,
            "result_subtype": self.result_subtype,
            "result_is_error": self.result_is_error,
            "runtime_error": self.runtime_error,
            "total_cost_usd": self.total_cost_usd,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "tool_call_count": len(self.tool_calls),
            "tools": [call["tool"] for call in self.tool_calls],
            "terminal_tool_ok": self.has_terminal_tool_call(),
        }

    def pretty_print(self) -> None:
        print(f"\n{'=' * 70}")
        print(f"USER: {self.user_message}")
        print(f"{'=' * 70}")

        for index, call in enumerate(self.tool_calls, start=1):
            result = self._tool_result_index.get(call["call_id"])
            short_inputs = json.dumps(call.get("inputs", {}), default=str)
            if len(short_inputs) > 150:
                short_inputs = short_inputs[:150] + "..."
            print(f"  [{index}] {call['tool']}({short_inputs})")
            if result:
                print(f"      tool ran in {result['duration_ms']}ms")

        if self.model_thoughts:
            print("  model narration between calls:")
            for thought in self.model_thoughts:
                preview = thought[:140] + "..." if len(thought) > 140 else thought
                print(f'    "{preview}"')

        if self.result_text:
            preview = self.result_text[:140] + "..." if len(self.result_text) > 140 else self.result_text
            print(f"  result: {preview}")
        if self.session_id:
            print(f"  session id: {self.session_id}")
        if self.runtime_error:
            preview = self.runtime_error[:140] + "..." if len(self.runtime_error) > 140 else self.runtime_error
            print(f"  runtime error: {preview}")
        if self.usage:
            print(
                "  cache: "
                f"created={self.cache_creation_input_tokens} "
                f"read={self.cache_read_input_tokens}"
            )

        print(
            f"  -> {self.duration_ms}ms | ${self.total_cost_usd:.4f} | "
            f"{self.num_turns} loop turns | {len(self.tool_calls)} tool calls"
        )

    def persist(self, path: Path) -> None:
        with path.open("a") as file:
            file.write(json.dumps(self.to_dict()) + "\n")

    def _ensure_tool_call(self, call_id: str, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        call = self._tool_call_index.get(call_id)
        if call is None:
            call = {
                "call_id": call_id,
                "tool": name,
                "inputs": inputs,
                "called_at_ms": self._elapsed_ms(),
            }
            self.tool_calls.append(call)
            self._tool_call_index[call_id] = call
        return call

    def _elapsed_ms(self) -> int:
        return int((time.time() - self._start) * 1000)


def load_trace_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
