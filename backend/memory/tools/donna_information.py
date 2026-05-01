"""donna_information — canonical curated facts about Donna herself.

Returns hand-calibrated answers for meta questions about Donna (privacy,
data storage, voice handling, capabilities, pricing, etc.) so she does
not hallucinate when the user asks "where is my data?", "what's your
privacy policy?", or similar.

NOT yet wired to the BRAIN. Topic content is curated by the team in
``DONNA_INFO`` below — empty strings mean "not yet calibrated" and the
tool returns ``no_hits`` rather than letting the model invent an answer.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from backend.memory.tools._shape import ToolResult, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Return curated information about Donna herself — privacy policy, "
    "where user data is stored, how voice notes / photos / documents are "
    "handled, supported integrations, pricing, contact, and similar meta "
    "questions.\n\n"
    "Use when:\n"
    "  - the user asks about Donna the product (not about themselves)\n"
    "  - questions like 'where is my data', 'what's your privacy policy', "
    "'who can see my messages', 'how do you handle voice notes'\n"
    "Do NOT use:\n"
    "  - for anything about the user's own life, memory, or schedule\n"
    "  - to invent product facts when the topic is not in the curated set "
    "(the tool will return no_hits — say you don't know rather than guess)\n"
    "Returns: ``{topic, answer}`` for a known topic, or ``{topics: [...]}`` "
    "listing every calibrated topic when ``topic`` is omitted."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": (
                "Canonical topic key (e.g. 'privacy_policy', "
                "'data_storage'). Omit to list every calibrated topic."
            ),
        }
    },
    "required": [],
}


# Curated answers in Donna's voice. Empty string means "not calibrated
# yet" — the team fills these in as we lock the language. Keep keys
# snake_case and stable; the BRAIN will eventually pass them through.
_DONNA_INFO_RAW: dict[str, str] = {
    "privacy_policy": "",
    "data_storage": "",
    "data_retention": "",
    "data_deletion": "",
    "voice_notes": "",
    "photos": "",
    "documents": "",
    "third_party_sharing": "",
    "security": "",
    "encryption": "",
    "what_donna_is": "",
    "what_donna_is_not": "",
    "supported_integrations": "",
    "pricing": "",
    "contact": "",
    "model_provider": "",
    "open_source": "",
}

DONNA_INFO: Mapping[str, str] = MappingProxyType(_DONNA_INFO_RAW)


def _calibrated_topics() -> list[str]:
    return sorted(k for k, v in DONNA_INFO.items() if v)


@instrument_memory_op("donna_information")
async def donna_information(
    user_id: str, topic: str | None = None
) -> ToolResult:
    if topic is None or not str(topic).strip():
        topics = _calibrated_topics()
        if not topics:
            return no_hits({"topics": []})
        return ok({"topics": topics})

    key = str(topic).strip().lower()
    answer = DONNA_INFO.get(key, "")
    if not answer:
        return no_hits({"topic": key, "answer": None})
    return ok({"topic": key, "answer": answer})
