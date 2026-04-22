"""Retrieval tests: top-k hits for known intents, determinism."""
from __future__ import annotations

import pytest

from donna.attention.retrieve import retrieve_top_k


EXPECTED_HITS = [
    ("keep an eye on Poke", "poke_watch"),
    ("watch for any Series A news about our competitors", "series_a_watch"),
    ("follow the latest arxiv papers on RAG", "arxiv_rag"),
    ("monitor shipment 1Z999", "shipment_1z999"),
    ("track how much I spend on subscriptions", "subscriptions_tally"),
    ("track my sleep quality over the month", "sleep_tally"),
    ("summarize my week every Friday evening", "weekly_brief"),
    ("brief me before my 1:1 with Sarah", "sarah_prep"),
    ("remind me 2 hours before any flight", "flight_prep"),
    ("close the loop on investor follow ups", "investor_loop"),
    ("remind me to call mom at 6pm", "call_mom_ping"),
]


@pytest.mark.unit
@pytest.mark.parametrize("query,expected_id", EXPECTED_HITS)
def test_top1_or_top3_hit(query, expected_id):
    hits = retrieve_top_k(query, k=3)
    ids = [h.example.example_id for h in hits]
    assert expected_id in ids, f"{query!r} -> {ids}, expected {expected_id}"


@pytest.mark.unit
def test_retrieve_is_deterministic():
    a = [h.example.example_id for h in retrieve_top_k("keep an eye on Poke", k=3)]
    b = [h.example.example_id for h in retrieve_top_k("keep an eye on Poke", k=3)]
    assert a == b


@pytest.mark.unit
def test_k_zero_returns_empty():
    assert retrieve_top_k("anything", k=0) == []


@pytest.mark.unit
def test_scores_are_sorted_descending():
    hits = retrieve_top_k("weekly digest summary", k=5)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
