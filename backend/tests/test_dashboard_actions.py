"""Dashboard action handler tests.

Covers the accept/dismiss verbs at the unit level. The endpoint layer
gets a separate FastAPI test that monkey-patches these handlers.

DB writes (DonnaInstance materialize, manifest upsert) are exercised
via monkey-patched callables — we don't reach for the real DB here so
the tests stay fast and hermetic.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.dashboard import actions as dba
from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
)
from donna.attention.store import AttentionStore


def _gold_spec_by_id(example_id: str):
    return next(g for g in GOLD_EXAMPLES if g.example_id == example_id).spec


def _offered_attention(user_id, *, spec=None) -> Attention:
    spec = spec or _gold_spec_by_id("poke_watch")
    return Attention(
        user_id=user_id,
        spec=spec,
        origin=AttentionOrigin.SHADOW_INFERRED,
        status=AttentionStatus.OFFERED,
        created_at=datetime.now(timezone.utc),
    )


def _wire_store(monkeypatch, store: AttentionStore) -> None:
    """Force every code path that constructs an AttentionStore() to use our temp one.

    We patch each module's bound reference because ``from … import``
    captures the class at import-time; module-level patches on
    ``donna.attention.store`` don't reach into already-imported modules.
    """
    factory = lambda *_a, **_kw: store  # noqa: E731 - terse intent here
    monkeypatch.setattr("donna.attention.store.AttentionStore", factory)
    monkeypatch.setattr("donna.attention.promote.AttentionStore", factory)
    monkeypatch.setattr("donna.attention.tools.AttentionStore", factory)


@pytest.mark.asyncio
async def test_accept_unknown_attention_returns_not_found(monkeypatch, tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)

    # No-op materialize + recompose so the test only exercises load + flip.
    monkeypatch.setattr(
        dba, "_maybe_materialize_instance",
        lambda **_: asyncio.sleep(0, result=(None, False)),
    )
    monkeypatch.setattr(
        dba, "_recompose_after_accept", lambda **_: asyncio.sleep(0, result=False)
    )

    result = await dba.accept_offered_attention(
        user_id=str(uuid4()), attention_id=str(uuid4())
    )
    assert result.ok is False
    assert "not found" in (result.error or "")


@pytest.mark.asyncio
async def test_accept_wrong_user_is_rejected(monkeypatch, tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)
    monkeypatch.setattr(
        dba, "_maybe_materialize_instance",
        lambda **_: asyncio.sleep(0, result=(None, False)),
    )
    monkeypatch.setattr(
        dba, "_recompose_after_accept", lambda **_: asyncio.sleep(0, result=False)
    )

    owner = uuid4()
    a = _offered_attention(owner)
    store.save(a)

    result = await dba.accept_offered_attention(
        user_id=str(uuid4()), attention_id=str(a.id)
    )
    assert result.ok is False
    assert "another user" in (result.error or "")


@pytest.mark.asyncio
async def test_accept_already_live_returns_not_offered(monkeypatch, tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)
    monkeypatch.setattr(
        dba, "_maybe_materialize_instance",
        lambda **_: asyncio.sleep(0, result=(None, False)),
    )
    monkeypatch.setattr(
        dba, "_recompose_after_accept", lambda **_: asyncio.sleep(0, result=False)
    )

    owner = uuid4()
    a = _offered_attention(owner).model_copy(update={"status": AttentionStatus.LIVE})
    store.save(a)

    result = await dba.accept_offered_attention(
        user_id=str(owner), attention_id=str(a.id)
    )
    assert result.ok is False
    assert result.error == "attention is not OFFERED"


@pytest.mark.asyncio
async def test_accept_offered_flips_to_live_and_runs_followups(monkeypatch, tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)

    materialized: list[str] = []
    recomposed: list[str] = []

    async def fake_materialize(*, user_id, attention):
        materialized.append(str(attention.id))
        return ("inst-1", True)

    def fake_spawn(*, user_id):
        recomposed.append(user_id)
        return "scheduled"

    monkeypatch.setattr(dba, "_maybe_materialize_instance", fake_materialize)
    monkeypatch.setattr(dba, "_spawn_recompose", fake_spawn)

    owner = uuid4()
    a = _offered_attention(owner)
    store.save(a)

    result = await dba.accept_offered_attention(
        user_id=str(owner), attention_id=str(a.id)
    )
    assert result.ok is True
    assert result.status == "live"
    assert result.instance_id == "inst-1"
    assert result.instance_created is True
    assert result.recomposed == "scheduled"
    assert materialized == [str(a.id)]
    assert recomposed == [str(owner)]


@pytest.mark.asyncio
async def test_dismiss_offered_returns_true(monkeypatch, tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)
    owner = uuid4()
    a = _offered_attention(owner)
    store.save(a)

    ok = await dba.dismiss_offered_attention(
        user_id=str(owner), attention_id=str(a.id)
    )
    assert ok is True

    refreshed = store.get(a.id)
    assert refreshed.status is AttentionStatus.REJECTED


@pytest.mark.asyncio
async def test_dismiss_wrong_user_is_rejected(monkeypatch, tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)
    owner = uuid4()
    a = _offered_attention(owner)
    store.save(a)
    ok = await dba.dismiss_offered_attention(
        user_id=str(uuid4()), attention_id=str(a.id)
    )
    assert ok is False


def test_extract_target_finds_liters():
    class S:
        description = "drink 2L of water today"

        class extractor:  # noqa: D106 - dataclass-like stub
            prompt = ""

    assert dba._extract_target(S()) == 2.0


def test_extract_target_finds_glasses():
    class S:
        description = "aim for 8 glasses"

        class extractor:
            prompt = ""

    assert dba._extract_target(S()) == 8.0


def test_extract_target_falls_back_to_none_when_no_number():
    class S:
        description = "hydrate well"

        class extractor:
            prompt = ""

    assert dba._extract_target(S()) is None
