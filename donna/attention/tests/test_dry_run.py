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
def test_fetcher_registry_defaults_to_stub():
    # A non-registered source type resolves to the default stub fetcher.
    fetcher = fetcher_for(SourceType.WEB_HN)
    assert isinstance(fetcher, StubFetcher)


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
