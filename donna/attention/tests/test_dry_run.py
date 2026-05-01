"""Dry-run tests: previews populate, rendering covers all cards, warnings on empty."""
from __future__ import annotations

import pytest

from donna.attention.dry_run import StubFetcher, dry_run, fetcher_for
from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.vocabulary import CardType, SourceType


@pytest.mark.unit
def test_every_gold_dry_runs_without_exception():
    for ex in GOLD_EXAMPLES:
        result = dry_run(ex.spec)
        assert result.spec_title == ex.spec.title
        assert result.rendered_markdown
        assert result.card is ex.spec.card


@pytest.mark.unit
def test_empty_fixture_emits_warning():
    # Pick the shipment gold — api_17track has no fixture.
    shipment = next(e for e in GOLD_EXAMPLES if e.example_id == "shipment_1z999")
    result = dry_run(shipment.spec)
    assert any("api_17track" in w or "no items" in w for w in result.warnings)


@pytest.mark.unit
def test_fetcher_registry_routes_web_sources_to_exa():
    # All web-shaped source types now resolve to the real ExaWebFetcher
    # (which hits the network when EXA_API_KEY is set). Truly-unhandled
    # source types still fall through to StubFetcher.
    from donna.attention.dry_run import ExaWebFetcher

    web_fetcher = fetcher_for(SourceType.WEB_HN)
    assert isinstance(web_fetcher, ExaWebFetcher)

    exa_fetcher = fetcher_for(SourceType.WEB_EXA)
    assert isinstance(exa_fetcher, ExaWebFetcher)

    # Attention-internal types that aren't web-shaped and aren't
    # explicitly registered (e.g. INTERNAL_EPISODES) still fall through
    # to the stub.
    internal = fetcher_for(SourceType.INTERNAL_EPISODES)
    assert isinstance(internal, StubFetcher)


@pytest.mark.unit
def test_poke_watch_renders_events_from_fixtures():
    poke = next(e for e in GOLD_EXAMPLES if e.example_id == "poke_watch")
    result = dry_run(poke.spec)
    assert "Poke" in result.rendered_markdown


@pytest.mark.unit
def test_ping_rendering_includes_question():
    ping = next(e for e in GOLD_EXAMPLES if e.example_id == "call_mom_ping")
    result = dry_run(ping.spec)
    assert "ping" in result.rendered_markdown.lower()
    assert "call mom" in result.rendered_markdown.lower()


@pytest.mark.unit
def test_all_cards_have_a_render_path():
    seen = {ex.spec.card for ex in GOLD_EXAMPLES}
    assert seen == set(CardType)
