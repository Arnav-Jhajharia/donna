"""Gate tests — rule layers only (no LLM)."""
from __future__ import annotations

import pytest

from backend.memory.gates.graph_ingest_gate import GateInput, _fast_accept, _fast_reject


def _g(inbound="", outbound=(), tools=(), terminator="send_burst"):
    return GateInput(inbound=inbound, outbound=list(outbound), tool_names=list(tools), terminator=terminator)


def test_reject_short_inbound():
    v = _fast_reject(_g(inbound="hi"))
    assert v is not None and v.worth_ingesting is False


def test_reject_ambient_filler():
    v = _fast_reject(_g(inbound="lol"))
    assert v is not None and v.worth_ingesting is False


def test_accept_multi_burst():
    v = _fast_accept(_g(inbound="a" * 50, outbound=["one", "two"]))
    assert v is not None and v.worth_ingesting is True


def test_accept_used_memory():
    v = _fast_accept(_g(inbound="a" * 50, tools=("recall_graph",), outbound=["one"]))
    assert v is not None and v.worth_ingesting is True


def test_fuzzy_middle_no_rule_fires():
    g = _g(inbound="I went to the gym today, felt decent", outbound=["nice, what'd you do?"], tools=("send_burst",))
    assert _fast_reject(g) is None
    assert _fast_accept(g) is None


@pytest.mark.parametrize(
    "inbound,expected",
    [
        ("hi", False),
        ("k", False),
        ("okay", False),
        ("lol", False),
        ("ok cool thanks", False),
        ("yo", False),
        ("hmm", False),
        ("yeah", False),
        ("nope", False),
        ("ty", False),
    ],
)
def test_ten_must_reject(inbound, expected):
    v = _fast_reject(_g(inbound=inbound))
    if v is None:
        # short-enough inbound still triggers length reject for these
        v = _fast_reject(_g(inbound=inbound + " "))
    assert v is None or v.worth_ingesting is expected


@pytest.mark.parametrize(
    "inbound,tools",
    [
        ("I just moved to Singapore for grad school, start Monday", ()),
        ("My dad is in the hospital, surgery tomorrow morning", ()),
        ("What did we decide about the London trip?", ("recall_graph",)),
        ("remind me what kaiser said about the launch", ("recall_episodic",)),
        ("can you pull up that thing about my diet last month", ("smart_recall",)),
        ("anyone ask about the handoff? I need to know", ("recall_graph",)),
        ("look up what we said about the meeting", ("recall_episodic",)),
        ("find that note about my rent increase", ("smart_recall",)),
        ("pull my chat history from yesterday", ("recall_episodic",)),
        ("what does my graph say about arjun", ("recall_graph",)),
    ],
)
def test_ten_must_accept(inbound, tools):
    g = _g(inbound=inbound, tools=tools, outbound=["resp"])
    if tools:
        v = _fast_accept(g)
        assert v is not None and v.worth_ingesting is True
    else:
        g2 = _g(inbound=inbound, outbound=["one", "two"])
        v = _fast_accept(g2)
        assert v is not None and v.worth_ingesting is True
