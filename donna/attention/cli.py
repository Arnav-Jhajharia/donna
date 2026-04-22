"""CLI entrypoint for the Attention Harness.

Subcommands:
    run     <intent>          # one-shot pipeline, no persistence
    create  <intent>          # author + persist; status=live
    list                      # print all saved attentions
    show    <id>              # full spec + tick history
    tick    <id>              # fetch + extract + render + append tick
    pause   <id>
    resume  <id>
    resolve <id>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Callable

from donna.attention.harness import run_attention_pipeline
from donna.attention.normalize import UserContext
from donna.attention.promote import accept_offer, reject_offer, run_shadow_cycle
from donna.attention.propose import propose_and_shadow, propose_candidates
from donna.attention.schema import Attention
from donna.attention.store import AttentionStore
from donna.attention.tools import (
    create_attention,
    get_attention,
    list_attentions,
    pause_attention,
    resolve_attention,
    resume_attention,
    tick_attention,
)


_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"


def _section(title: str, color: str = _CYAN) -> None:
    print(f"\n{color}{_BOLD}[{title}]{_RESET}")


def _short(aid: str) -> str:
    return aid[:8]


# -- run: one-shot pipeline (no persistence) ---------------------------------


async def _cmd_run(args: argparse.Namespace) -> int:
    ctx = UserContext(user_id=args.user_id)
    result = await run_attention_pipeline(args.intent, ctx)

    _section("NORMALIZE")
    print(f"{_DIM}normalized:{_RESET} {result.normalized.normalized_text}")

    _section("RETRIEVE")
    for r in result.retrieved:
        print(f"  {r.score:0.3f}  {r.example.example_id}")

    _section("AUTHOR")
    print(f"{_DIM}via:{_RESET} {result.authored.via}  {_DIM}confidence:{_RESET} {result.authored.confidence:0.2f}")
    print(f"{_DIM}reasoning:{_RESET} {result.authored.reasoning}")
    print(json.dumps(result.authored.spec.model_dump(mode="json"), indent=2))

    _section("DRY RUN", _GREEN)
    for w in result.preview.warnings:
        print(f"  {_YELLOW}!{_RESET} {w}")
    print(result.preview.rendered_markdown)

    _section("TOTAL")
    for t in result.timings:
        print(f"  {t.stage:<10} {t.ms:7.1f} ms")
    print(f"  {_BOLD}total     {result.total_ms:7.1f} ms{_RESET}")
    return 0


# -- create ------------------------------------------------------------------


async def _cmd_create(args: argparse.Namespace) -> int:
    result = await create_attention(args.intent, user_id=args.user_id)
    _section("CREATED", _GREEN)
    print(f"  id:     {result.attention.id}")
    print(f"  card:   {result.attention.spec.card.value}")
    print(f"  title:  {result.attention.spec.title}")
    print(f"  status: {result.attention.status.value}")
    print(f"  via:    {result.authored_via} (conf {result.authored_confidence:0.2f})")
    _section("PREVIEW", _CYAN)
    print(result.preview.rendered_markdown)
    return 0


# -- list --------------------------------------------------------------------


def _cmd_list(args: argparse.Namespace) -> int:
    attentions = list_attentions()
    if not attentions:
        print(f"{_DIM}no attentions yet{_RESET}")
        return 0
    print(f"{_BOLD}{'ID':<10}{'STATUS':<12}{'CARD':<14}{'TITLE':<40}{'#UPD':>5}{_RESET}")
    for a in attentions:
        print(
            f"{_short(str(a.id)):<10}"
            f"{a.status.value:<12}"
            f"{a.spec.card.value:<14}"
            f"{a.spec.title[:38]:<40}"
            f"{a.update_count:>5}"
        )
    return 0


# -- show --------------------------------------------------------------------


def _cmd_show(args: argparse.Namespace) -> int:
    attention = _resolve(args.id)
    if attention is None:
        print(f"{_RED}not found{_RESET}", file=sys.stderr)
        return 1
    _section("SPEC")
    print(json.dumps(attention.model_dump(mode="json"), indent=2))
    _section("TICKS")
    store = AttentionStore()
    for i, tick in enumerate(store.ticks(attention.id), 1):
        print(f"{_DIM}#{i}  {tick.at}{_RESET}")
        for w in tick.warnings:
            print(f"  {_YELLOW}!{_RESET} {w}")
        print(tick.rendered_markdown)
    return 0


# -- tick --------------------------------------------------------------------


def _cmd_tick(args: argparse.Namespace) -> int:
    attention = _resolve(args.id)
    if attention is None:
        print(f"{_RED}not found{_RESET}", file=sys.stderr)
        return 1
    result = tick_attention(str(attention.id))
    assert result is not None
    _refreshed, preview = result
    _section("TICK", _GREEN)
    for w in preview.warnings:
        print(f"  {_YELLOW}!{_RESET} {w}")
    print(preview.rendered_markdown)
    return 0


# -- status transitions ------------------------------------------------------


def _make_status_cmd(fn: Callable[[str], Attention | None], label: str):
    def _cmd(args: argparse.Namespace) -> int:
        attention = _resolve(args.id)
        if attention is None:
            print(f"{_RED}not found{_RESET}", file=sys.stderr)
            return 1
        updated = fn(str(attention.id))
        assert updated is not None
        print(f"{_GREEN}{label}{_RESET}  {updated.id}  → {updated.status.value}")
        return 0

    return _cmd


# -- propose -----------------------------------------------------------------


async def _cmd_propose(args: argparse.Namespace) -> int:
    if not args.shadow:
        candidates = propose_candidates(args.user_id)
        _section("CANDIDATES", _CYAN)
        if not candidates:
            print(f"{_DIM}no candidates{_RESET}")
            return 0
        for c in candidates:
            print(f"  {_BOLD}{c.proposer}{_RESET} [{c.priority}]")
            print(f"    intent:    {c.raw_intent}")
            print(f"    rationale: {c.rationale}")
        return 0

    results = await propose_and_shadow(args.user_id)
    _section("SHADOW AUTHORED", _GREEN)
    if not results:
        print(f"{_DIM}no candidates{_RESET}")
        return 0
    for r in results:
        tag = "SKIP" if r.attention is None else "OK"
        color = _YELLOW if r.attention is None else _GREEN
        print(f"  {color}{tag}{_RESET} [{r.candidate.proposer}] {r.candidate.raw_intent}")
        if r.attention is not None:
            print(
                f"    id: {_short(str(r.attention.id))}  "
                f"card: {r.attention.spec.card.value}  "
                f"via: {r.authored_via} (conf {r.authored_confidence:0.2f})"
            )
        elif r.error:
            print(f"    {_DIM}skip reason: {r.error}{_RESET}")
    return 0


# -- promote -----------------------------------------------------------------


def _cmd_promote(args: argparse.Namespace) -> int:
    results = run_shadow_cycle()
    _section("SHADOW CYCLE", _CYAN)
    if not results:
        print(f"{_DIM}no shadow attentions{_RESET}")
        return 0
    for r in results:
        if r.action == "promoted":
            color = _GREEN
        elif r.action == "archived":
            color = _DIM
        else:
            color = _YELLOW
        print(
            f"  {color}{r.action:<9}{_RESET} {_short(r.attention_id)}  "
            f"{r.from_status.value} → {r.to_status.value}  "
            f"ticks={r.tick_count} hits={r.promotion_hits}"
        )
    return 0


# -- id resolution (accept short or full id) --------------------------------


def _resolve(id_prefix: str) -> Attention | None:
    a = get_attention(id_prefix)
    if a is not None:
        return a
    for candidate in list_attentions():
        if str(candidate.id).startswith(id_prefix):
            return candidate
    return None


# -- argparse wiring ---------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="donna.attention.cli")
    parser.add_argument("--user-id", default="cli-user")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="one-shot pipeline, no persistence")
    p_run.add_argument("intent")
    p_run.set_defaults(func=_cmd_run, async_=True)

    p_create = sub.add_parser("create", help="author + persist, status=live")
    p_create.add_argument("intent")
    p_create.set_defaults(func=_cmd_create, async_=True)

    p_list = sub.add_parser("list", help="print all saved attentions")
    p_list.set_defaults(func=_cmd_list, async_=False)

    p_show = sub.add_parser("show", help="full spec + tick history")
    p_show.add_argument("id")
    p_show.set_defaults(func=_cmd_show, async_=False)

    p_tick = sub.add_parser("tick", help="fetch + extract + render")
    p_tick.add_argument("id")
    p_tick.set_defaults(func=_cmd_tick, async_=False)

    p_pause = sub.add_parser("pause")
    p_pause.add_argument("id")
    p_pause.set_defaults(func=_make_status_cmd(pause_attention, "paused"), async_=False)

    p_resume = sub.add_parser("resume")
    p_resume.add_argument("id")
    p_resume.set_defaults(func=_make_status_cmd(resume_attention, "resumed"), async_=False)

    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("id")
    p_resolve.set_defaults(func=_make_status_cmd(resolve_attention, "resolved"), async_=False)

    p_propose = sub.add_parser(
        "propose", help="scan ambient signal for candidate intents"
    )
    p_propose.add_argument(
        "--shadow",
        action="store_true",
        help="author candidates and persist as SHADOW (default: dry-list only)",
    )
    p_propose.set_defaults(func=_cmd_propose, async_=True)

    p_promote = sub.add_parser(
        "promote", help="tick all shadow attentions; promote or archive"
    )
    p_promote.set_defaults(func=_cmd_promote, async_=False)

    p_accept = sub.add_parser("accept", help="accept an OFFERED attention → LIVE")
    p_accept.add_argument("id")
    p_accept.set_defaults(
        func=_make_status_cmd(
            lambda aid: accept_offer(aid), "accepted"
        ),
        async_=False,
    )

    p_reject = sub.add_parser("reject", help="reject an OFFERED attention → REJECTED")
    p_reject.add_argument("id")
    p_reject.set_defaults(
        func=_make_status_cmd(
            lambda aid: reject_offer(aid), "rejected"
        ),
        async_=False,
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.async_:
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
