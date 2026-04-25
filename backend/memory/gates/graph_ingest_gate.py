"""Graph-ingest selectivity gate (spec §7).

Three layers: fast-reject rules → fast-accept rules → Haiku judgment for the
fuzzy middle. Verdicts appended to DONNA_GATE_LOG (JSONL) for tuning.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.memory.retrieval.structured import call_structured

logger = logging.getLogger(__name__)

AMBIENT_FILLER = {
    "k", "lol", "ok", "okay", "haha", "bro", "yo", "yeah", "yup", "nope",
    "cool", "nice", "hmm", "thanks", "ty", "np",
}

MEMORY_TOOLS = {"recall_graph", "recall_episodic", "smart_recall"}


@dataclass(frozen=True)
class GateInput:
    inbound: str
    outbound: Sequence[str]
    tool_names: Sequence[str]
    terminator: str  # "send_burst"


@dataclass(frozen=True)
class GateVerdict:
    worth_ingesting: bool
    reason: str
    layer: str  # "fast_reject" | "fast_accept" | "haiku"


class _HaikuOut(BaseModel):
    worth_ingesting: bool = Field(description="True if turn has durable facts.")
    reason: str = Field(description="One short sentence.")


def _fast_reject(g: GateInput) -> GateVerdict | None:
    if len(g.inbound.strip()) < 20:
        return GateVerdict(False, "inbound too short", "fast_reject")
    if g.inbound.strip().lower() in AMBIENT_FILLER:
        return GateVerdict(False, "ambient filler", "fast_reject")
    return None


def _fast_accept(g: GateInput) -> GateVerdict | None:
    if g.terminator == "send_burst" and len(g.outbound) >= 2:
        return GateVerdict(True, "multi-message burst", "fast_accept")
    if any(t in MEMORY_TOOLS for t in g.tool_names):
        return GateVerdict(True, "turn needed memory recall", "fast_accept")
    return None


def _hash_key(g: GateInput) -> str:
    h = hashlib.sha1()
    h.update(g.inbound.encode())
    h.update(b"|")
    h.update("||".join(g.outbound).encode())
    return h.hexdigest()[:16]


def _log_verdict(g: GateInput, v: GateVerdict) -> None:
    settings = get_settings()
    path = Path(settings.gate_log_path)
    try:
        with path.open("a") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "key": _hash_key(g),
                        "inbound_len": len(g.inbound),
                        "n_outbound": len(g.outbound),
                        "tools": list(g.tool_names),
                        "terminator": g.terminator,
                        "verdict": v.worth_ingesting,
                        "reason": v.reason,
                        "layer": v.layer,
                    }
                )
                + "\n"
            )
    except Exception:
        logger.debug("gate log write failed (non-fatal)")


async def should_ingest_to_graph(g: GateInput) -> GateVerdict:
    reject = _fast_reject(g)
    if reject is not None:
        _log_verdict(g, reject)
        return reject
    accept = _fast_accept(g)
    if accept is not None:
        _log_verdict(g, accept)
        return accept

    prompt_path = Path(__file__).resolve().parents[1] / "synthesis" / "prompts" / "graph_ingest_gate.md"
    try:
        sysprompt = prompt_path.read_text()
    except Exception:
        sysprompt = "Decide if this turn has durable user facts. JSON: {worth_ingesting, reason}."

    user_msg = json.dumps(
        {
            "inbound": g.inbound,
            "outbound": list(g.outbound),
            "tool_names": list(g.tool_names),
            "terminator": g.terminator,
        }
    )
    result = await call_structured(
        model="claude-haiku-4-5-20251001",
        system_prompt=sysprompt,
        user_message=user_msg,
        schema=_HaikuOut,
        max_tokens=120,
    )
    if result is None:
        v = GateVerdict(False, "haiku unavailable, defaulting to reject", "haiku")
    else:
        v = GateVerdict(result.worth_ingesting, result.reason, "haiku")
    _log_verdict(g, v)
    return v
