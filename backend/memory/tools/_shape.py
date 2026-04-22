"""Shared tool-return shape per spec §5: {status, payload}.

status:
  - ok       — success, payload populated
  - no_hits  — success but empty result (distinct from failure)
  - degraded — backend unreachable / missing creds
"""
from __future__ import annotations

from typing import Any, TypedDict


class ToolResult(TypedDict):
    status: str
    payload: Any


def ok(payload: Any) -> ToolResult:
    return {"status": "ok", "payload": payload}


def no_hits(payload: Any = None) -> ToolResult:
    return {"status": "no_hits", "payload": payload if payload is not None else []}


def degraded(reason: str = "") -> ToolResult:
    return {"status": "degraded", "payload": {"reason": reason}}
