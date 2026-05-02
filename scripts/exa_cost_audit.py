"""Where Exa credits are going. One-screen audit.

Counts every recurring code path that hits Exa and projects monthly
credit cost so we can see which knob to turn first.

Cost model (current proactive architecture, /search-only):
  - exa_search       ~5 credits/call (regardless of numResults)
  - exa_find_similar ~5 credits/call
  - exa_webset_create  one-time, ~10 credits/seed item (DEPRECATED path)
  - exa_monitor run    ~10 credits/delivered row    (DEPRECATED path)

Budget reality: $49 = 8000 credits/month. The /search-only model
brings projected proactive burn into the ~200-700 credits/month
range, leaving plenty for user-facing brain tools (web_search,
research, recall web fanout).

Usage:
    python scripts/exa_cost_audit.py
    python scripts/exa_cost_audit.py --user <user_id>     # one user only
    python scripts/exa_cost_audit.py --no-exa             # skip Exa API calls
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from backend.db.session import async_session
from db.models import ProactiveSignal, ProactiveSubscription, User


# -- Cadence helpers ---------------------------------------------------------

# Monitor crons we emit (see backend/web/client.py::_CADENCE_TO_CRON).
# Map cron expression → runs per month so we can project burn.
_CRON_TO_RUNS_PER_MONTH: dict[str, int] = {
    "0 0 * * *": 30,   # daily
    "0 0 * * 0": 4,    # weekly
    "0 * * * *": 720,  # hourly
}


def _runs_per_month(cron: str | None) -> int:
    if not cron:
        return 30
    return _CRON_TO_RUNS_PER_MONTH.get(cron, 30)


def _label_cadence(cron: str | None) -> str:
    if not cron:
        return "?"
    if cron == "0 0 * * *":
        return "daily"
    if cron == "0 0 * * 0":
        return "weekly"
    if cron == "0 * * * *":
        return "hourly"
    return cron


# -- Defaults pulled from the codebase --------------------------------------
# Keep in sync with the modules that own these knobs. Each is annotated
# with the source file so future divergence is easy to catch.

# DEPRECATED webset+monitor path — only used to project legacy state.
WEBSET_INITIAL_COUNT = 3                       # subscriptions.py exa_webset_create call
MONITOR_DEFAULT_COUNT = 2                      # client.py exa_monitor_create

# Active /search-only path.
POLLER_NUM_RESULTS = 2                         # poller.poll_pending_subscriptions
POLL_INTERVAL_S = 3600.0                       # run_proactive_worker DEFAULT_POLL_INTERVAL_S = 1h
URL_SIMILAR_INTERVAL_S = 7 * 24 * 3600.0       # weekly
URL_SIMILAR_MAX_SEEDS = 5                      # url_similar._DEFAULT_MAX_SEEDS
URL_SIMILAR_NUM_RESULTS = 4                    # url_similar._DEFAULT_NUM_RESULTS

# Attention worker (separate from proactive worker).
PROPOSE_INTERVAL_S = 30 * 60                   # attention_worker.PROPOSE_INTERVAL_SEC
PROMOTE_INTERVAL_S = 15 * 60                   # attention_worker.PROMOTE_INTERVAL_SEC
DRY_RUN_NUM_RESULTS = 5                        # dry_run.ExaWebFetcher num_results default

# Credit cost per Exa endpoint. Source: Exa pricing page + observed bills.
CREDITS_PER_SEARCH = 5
CREDITS_PER_FIND_SIMILAR = 5
CREDITS_PER_WEBSET_ITEM = 10  # legacy / deprecated path

# Cadence -> seconds for projecting /search call frequency.
CADENCE_SECONDS: dict[str, float] = {
    "hourly": 3600.0,
    "daily": 24 * 3600.0,
    "weekly": 7 * 24 * 3600.0,
    "monthly": 30 * 24 * 3600.0,
}

SECONDS_PER_MONTH = 30.0 * 24 * 3600
MONTHLY_CREDIT_BUDGET = 8000  # $49 Starter tier


# -- Data containers --------------------------------------------------------


@dataclass
class ExaSnapshot:
    websets: list[dict[str, Any]] = field(default_factory=list)
    monitors: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class LocalSnapshot:
    subs_total_active: int = 0
    subs_with_monitor: int = 0
    subs_pending: int = 0
    subs_per_user: dict[str, int] = field(default_factory=dict)
    subs_by_cadence: dict[str, int] = field(default_factory=dict)
    monitor_ids_local: set[str] = field(default_factory=set)
    webset_ids_local: set[str] = field(default_factory=set)
    signals_pending: int = 0
    signals_consumed_recent: int = 0
    attention_shadow: int = 0
    attention_live: int = 0
    attention_offered: int = 0
    attention_avg_web_sources: float = 0.0


@dataclass
class BurnEstimate:
    label: str
    credits_per_month: float
    calls_per_month: float
    note: str = ""


# -- Live Exa state ---------------------------------------------------------


async def _fetch_exa_state() -> ExaSnapshot:
    try:
        import httpx
    except ImportError:
        return ExaSnapshot(error="httpx not installed")
    key = (os.environ.get("EXA_API_KEY") or "").strip()
    if not key:
        return ExaSnapshot(error="EXA_API_KEY not set")

    snap = ExaSnapshot()
    headers = {"x-api-key": key}
    async with httpx.AsyncClient(timeout=12.0) as c:
        try:
            r = await c.get(
                "https://api.exa.ai/websets/v0/websets", headers=headers
            )
            r.raise_for_status()
            snap.websets = list((r.json() or {}).get("data") or [])
        except Exception as exc:
            snap.error = f"websets list failed: {exc}"
            return snap
        try:
            r = await c.get(
                "https://api.exa.ai/websets/v0/monitors", headers=headers
            )
            r.raise_for_status()
            snap.monitors = list((r.json() or {}).get("data") or [])
        except Exception as exc:
            snap.error = f"monitors list failed: {exc}"
    return snap


# -- Local DB snapshot ------------------------------------------------------


async def _fetch_local_snapshot(user_filter: str | None) -> LocalSnapshot:
    snap = LocalSnapshot()

    async with async_session() as s:
        sub_stmt = select(ProactiveSubscription).where(
            ProactiveSubscription.active.is_(True)
        )
        if user_filter:
            sub_stmt = sub_stmt.where(ProactiveSubscription.user_id == user_filter)
        rows = (await s.execute(sub_stmt)).scalars().all()

        per_user: dict[str, int] = defaultdict(int)
        per_cadence: dict[str, int] = defaultdict(int)
        for row in rows:
            snap.subs_total_active += 1
            per_user[row.user_id] += 1
            per_cadence[(row.cadence or "weekly").lower()] += 1
            if row.monitor_id:
                snap.subs_with_monitor += 1
                snap.monitor_ids_local.add(row.monitor_id)
            else:
                snap.subs_pending += 1
            if row.webset_id:
                snap.webset_ids_local.add(row.webset_id)
        snap.subs_per_user = dict(per_user)
        snap.subs_by_cadence = dict(per_cadence)

        sig_pending_stmt = select(func.count()).select_from(ProactiveSignal).where(
            ProactiveSignal.consumed_at.is_(None)
        )
        sig_consumed_stmt = select(func.count()).select_from(ProactiveSignal).where(
            ProactiveSignal.consumed_at.isnot(None)
        )
        if user_filter:
            sig_pending_stmt = sig_pending_stmt.where(
                ProactiveSignal.user_id == user_filter
            )
            sig_consumed_stmt = sig_consumed_stmt.where(
                ProactiveSignal.user_id == user_filter
            )
        snap.signals_pending = int(
            (await s.execute(sig_pending_stmt)).scalar() or 0
        )
        snap.signals_consumed_recent = int(
            (await s.execute(sig_consumed_stmt)).scalar() or 0
        )

    snap.attention_shadow, snap.attention_live, snap.attention_offered, snap.attention_avg_web_sources = (
        _read_attention_store(user_filter)
    )
    return snap


def _read_attention_store(user_filter: str | None) -> tuple[int, int, int, float]:
    """Count attention rows by status and avg web-source count per spec.

    The store is a JSON file (`~/.donna/attentions.json` by default).
    Reads via the AttentionStore class so schema validation runs.
    """
    try:
        from donna.attention.schema import AttentionStatus
        from donna.attention.store import AttentionStore
        from donna.attention.vocabulary import SourceType
    except Exception:
        return (0, 0, 0, 0.0)

    web_types = {
        SourceType.WEB_EXA,
        SourceType.WEB_GOOGLE_NEWS,
        SourceType.WEB_HN,
        SourceType.WEB_REDDIT,
        SourceType.WEB_X_TWITTER,
        SourceType.WEB_PRODUCTHUNT,
        SourceType.WEB_YOUTUBE,
        SourceType.WEB_SUBSTACK,
        SourceType.WEB_PODCAST_TRANSCRIPT,
        SourceType.WEB_RSS,
        SourceType.WEB_GITHUB_TRENDING,
        SourceType.WEB_GITHUB_REPO,
        SourceType.WEB_ARXIV,
        SourceType.WEB_DOMAIN,
        SourceType.WEB_SEARCH_GOOGLE,
    }

    try:
        store = AttentionStore()
        rows = store.list(user_id=user_filter) if user_filter else store.list()
    except Exception:
        return (0, 0, 0, 0.0)

    shadow = live = offered = 0
    web_source_counts: list[int] = []
    for a in rows:
        try:
            sources = list(a.spec.sources)
        except Exception:
            sources = []
        web_count = sum(1 for s in sources if s.type in web_types)
        if a.status is AttentionStatus.SHADOW:
            shadow += 1
            web_source_counts.append(web_count)
        elif a.status is AttentionStatus.LIVE:
            live += 1
            web_source_counts.append(web_count)
        elif a.status is AttentionStatus.OFFERED:
            offered += 1
    avg = (
        sum(web_source_counts) / len(web_source_counts)
        if web_source_counts
        else 0.0
    )
    return (shadow, live, offered, avg)


# -- Burn projection --------------------------------------------------------


def _project_burn(
    local: LocalSnapshot, exa: ExaSnapshot, num_users: int
) -> list[BurnEstimate]:
    """Project monthly Exa burn under the /search-only model.

    Each entry returns both calls/mo and credits/mo so the operator
    can read either lens.
    """
    out: list[BurnEstimate] = []

    # 1. /search calls per sub, one per cadence interval per month.
    # daily=30 calls/mo, weekly=4, monthly=1. Each call ~5 credits.
    cadence_calls_per_month = {
        "hourly": SECONDS_PER_MONTH / CADENCE_SECONDS["hourly"],
        "daily": SECONDS_PER_MONTH / CADENCE_SECONDS["daily"],
        "weekly": SECONDS_PER_MONTH / CADENCE_SECONDS["weekly"],
        "monthly": SECONDS_PER_MONTH / CADENCE_SECONDS["monthly"],
    }
    total_search_calls = 0.0
    cadence_breakdown: list[str] = []
    for cad, count in sorted(local.subs_by_cadence.items()):
        runs = cadence_calls_per_month.get(cad, cadence_calls_per_month["weekly"])
        cad_calls = count * runs
        total_search_calls += cad_calls
        cadence_breakdown.append(f"{count}×{cad} ({int(cad_calls)})")
    if local.subs_total_active:
        out.append(
            BurnEstimate(
                "/search poll (cadence-aware)",
                credits_per_month=total_search_calls * CREDITS_PER_SEARCH,
                calls_per_month=total_search_calls,
                note=f"breakdown: {', '.join(cadence_breakdown) or 'no subs'}",
            )
        )

    # 2. URL-similar loop. Weekly × users × seeds × find_similar.
    seeds_per_user_per_month = (
        SECONDS_PER_MONTH / URL_SIMILAR_INTERVAL_S
    ) * URL_SIMILAR_MAX_SEEDS
    url_similar_calls = seeds_per_user_per_month * num_users
    out.append(
        BurnEstimate(
            "url_similar loop (weekly)",
            credits_per_month=url_similar_calls * CREDITS_PER_FIND_SIMILAR,
            calls_per_month=url_similar_calls,
            note=(
                f"{int(url_similar_calls)}/mo across {num_users} active user(s) "
                f"× {URL_SIMILAR_MAX_SEEDS} seeds × ~{URL_SIMILAR_NUM_RESULTS} results each"
            ),
        )
    )

    # 3. Attention promote_pass: tick every SHADOW row every 15 min.
    promote_ticks_per_month = SECONDS_PER_MONTH / PROMOTE_INTERVAL_S
    promote_exa_calls = (
        promote_ticks_per_month
        * local.attention_shadow
        * max(1.0, local.attention_avg_web_sources)
    )
    out.append(
        BurnEstimate(
            "attention promote_pass (every 15 min)",
            credits_per_month=promote_exa_calls * CREDITS_PER_SEARCH,
            calls_per_month=promote_exa_calls,
            note=(
                f"{local.attention_shadow} SHADOW rows × "
                f"{local.attention_avg_web_sources:.1f} web sources avg × "
                f"{int(promote_ticks_per_month)} ticks/mo"
            ),
        )
    )

    # 4. Attention propose_pass: ONE probe per new candidate.
    propose_passes_per_month = SECONDS_PER_MONTH / PROPOSE_INTERVAL_S
    propose_exa_calls = (
        propose_passes_per_month * 1.0 * max(1.0, local.attention_avg_web_sources)
    )
    out.append(
        BurnEstimate(
            "attention propose_pass (every 30 min)",
            credits_per_month=propose_exa_calls * CREDITS_PER_SEARCH,
            calls_per_month=propose_exa_calls,
            note=(
                f"~1 candidate/pass × {int(propose_passes_per_month)} passes/mo × "
                f"{local.attention_avg_web_sources:.1f} web sources avg "
                "(rough — actual depends on proposer output)"
            ),
        )
    )

    # 5. Legacy webset+monitor burn — only show if any monitors still
    # exist at Exa (DEPRECATED path, should be 0 after cleanup).
    if exa.monitors:
        legacy_items = 0.0
        for m in exa.monitors:
            cron = ((m.get("cadence") or {}).get("cron")) or "0 0 * * *"
            count = (
                ((m.get("behavior") or {}).get("config") or {}).get("count")
                or MONITOR_DEFAULT_COUNT
            )
            runs = _runs_per_month(cron)
            legacy_items += runs * int(count)
        out.append(
            BurnEstimate(
                "[LEGACY] monitor runs (DEPRECATED — delete monitors at Exa)",
                credits_per_month=legacy_items * CREDITS_PER_WEBSET_ITEM,
                calls_per_month=legacy_items,
                note=(
                    f"{int(legacy_items)} items/mo × ~10 credits/row. "
                    "These should be 0 — delete remaining monitors at Exa."
                ),
            )
        )

    return out


# -- Reduction recommendations ---------------------------------------------


def _recommendations(
    local: LocalSnapshot, exa: ExaSnapshot, burn: list[BurnEstimate]
) -> list[str]:
    """Reductions ordered by impact under the /search-only model."""
    rec: list[str] = []

    # The pivot to /search-only deprecates websets+monitors entirely.
    # Anything still at Exa is pure waste under the current architecture.
    if exa.monitors:
        rec.append(
            f"DELETE all {len(exa.monitors)} monitor(s) at Exa — the "
            "/search-only model bypasses monitors. They cost ~10 credits "
            "per delivered row and produce nothing we use anymore."
        )
    if exa.websets:
        rec.append(
            f"DELETE all {len(exa.websets)} webset(s) at Exa — same reason. "
            "Free to delete; no recurring cost while attached to no monitor "
            "but cluttering the dashboard."
        )

    # Daily subs in /search-only model are the expensive ones (30 calls
    # vs 4 weekly). Surface if many.
    daily_subs = local.subs_by_cadence.get("daily", 0)
    if daily_subs > 1:
        weekly_credits = daily_subs * 4 * CREDITS_PER_SEARCH
        daily_credits = daily_subs * 30 * CREDITS_PER_SEARCH
        rec.append(
            f"REVIEW {daily_subs} daily-cadence sub(s). Each costs "
            f"~{30 * CREDITS_PER_SEARCH} credits/mo vs ~{4 * CREDITS_PER_SEARCH} "
            f"if downgraded to weekly. {daily_credits - weekly_credits} credits "
            "saved if all moved to weekly. Daily should be only for fast news beats."
        )

    # SHADOW attention rows: every one ticks every 15 min, hitting Exa.
    if local.attention_shadow:
        ticks_per_mo = SECONDS_PER_MONTH / PROMOTE_INTERVAL_S
        wasted_calls = (
            local.attention_shadow * ticks_per_mo * max(1.0, local.attention_avg_web_sources)
        )
        wasted_credits = wasted_calls * CREDITS_PER_SEARCH
        rec.append(
            f"ARCHIVE {local.attention_shadow} legacy SHADOW attention(s) — "
            "the one-probe model means SHADOW is dead path; each row burns "
            f"~{int(wasted_credits)} credits/mo. SQL: UPDATE attention_rows "
            "SET status='quietly_archived' WHERE status='shadow'."
        )

    # Subscription cap: max_active default is 3 now.
    over_cap = sum(1 for c in local.subs_per_user.values() if c > 3)
    if over_cap:
        rec.append(
            f"REDUCE active subs for {over_cap} user(s) over 3 watches. "
            "max_active default is 3; existing rows beyond that should be "
            "deactivated via reconcile."
        )

    if not rec:
        rec.append("No obvious leaks. Watch monthly burn projection above.")
    return rec


# -- Print ------------------------------------------------------------------


def _hr() -> None:
    print("─" * 70)


def _print_exa(exa: ExaSnapshot) -> None:
    _hr()
    print("1. LIVE EXA STATE")
    _hr()
    if exa.error:
        print(f"  (skipped: {exa.error})")
        print()
        return
    print(f"  websets:  {len(exa.websets)}")
    print(f"  monitors: {len(exa.monitors)}")
    if exa.monitors:
        print()
        print(
            "  monitor                            cadence    count  webset"
        )
        for m in exa.monitors[:30]:
            mid = (m.get("id") or "?")[:32]
            cron = ((m.get("cadence") or {}).get("cron")) or "?"
            count = ((m.get("behavior") or {}).get("config") or {}).get("count") or "?"
            ws = (m.get("websetId") or "?")[:24]
            print(
                f"  {mid:<34} {_label_cadence(cron):<10} {str(count):<6} {ws}"
            )
    print()


def _print_local(local: LocalSnapshot) -> None:
    _hr()
    print("2. LOCAL SUBSCRIPTIONS")
    _hr()
    print(
        f"  active subs:        {local.subs_total_active}  "
        f"(provisioned={local.subs_with_monitor}, pending={local.subs_pending})"
    )
    print(f"  signals pending:    {local.signals_pending}")
    print(f"  signals consumed:   {local.signals_consumed_recent}")
    if local.subs_per_user:
        print()
        print("  per-user breakdown:")
        for uid, cnt in sorted(
            local.subs_per_user.items(), key=lambda x: -x[1]
        )[:10]:
            print(f"    {uid[:8]}…  {cnt} subs")
    print()


def _print_attention(local: LocalSnapshot) -> None:
    _hr()
    print("3. ATTENTION BURN")
    _hr()
    if local.attention_shadow + local.attention_live + local.attention_offered == 0:
        print("  (no attention rows in store — store path may not match worker)")
        print()
        return
    print(
        f"  SHADOW:   {local.attention_shadow}  "
        "(ticks every 15 min via promote_pass)"
    )
    print(f"  LIVE:     {local.attention_live}")
    print(f"  OFFERED:  {local.attention_offered}")
    print(f"  avg web sources per spec: {local.attention_avg_web_sources:.1f}")
    print()


def _print_burn(burn: list[BurnEstimate]) -> None:
    _hr()
    print(
        "4. MONTHLY BURN PROJECTION  "
        f"(budget: {MONTHLY_CREDIT_BUDGET:,} credits / mo on $49 plan)"
    )
    _hr()
    print(f"  {'credits':>8}  {'calls':>7}   path")
    print(f"  {'-' * 8}  {'-' * 7}   ----")
    total_credits = 0.0
    total_calls = 0.0
    for b in sorted(burn, key=lambda x: -x.credits_per_month):
        total_credits += b.credits_per_month
        total_calls += b.calls_per_month
        print(
            f"  {int(b.credits_per_month):>8,}  {int(b.calls_per_month):>7,}   {b.label}"
        )
        if b.note:
            print(f"                       {b.note}")
    _hr()
    pct = (total_credits / MONTHLY_CREDIT_BUDGET) * 100 if MONTHLY_CREDIT_BUDGET else 0
    print(
        f"  {int(total_credits):>8,}  {int(total_calls):>7,}   "
        f"TOTAL  ({pct:.1f}% of budget)"
    )
    print()


def _print_recs(recs: list[str]) -> None:
    _hr()
    print("5. TOP REDUCTIONS (do these first)")
    _hr()
    for i, r in enumerate(recs, 1):
        print(f"  {i}. {r}")
    print()


# -- Entry point ------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit where Exa credits are going."
    )
    parser.add_argument(
        "--user",
        help="Restrict local DB queries to this user_id (Exa state is global).",
    )
    parser.add_argument(
        "--no-exa",
        action="store_true",
        help="Skip live Exa API calls (faster, less accurate).",
    )
    args = parser.parse_args()

    print()
    if args.user:
        print(f"Auditing user: {args.user}")
        print()

    exa = ExaSnapshot(error="--no-exa") if args.no_exa else await _fetch_exa_state()
    local = await _fetch_local_snapshot(args.user)
    num_users = max(1, len(local.subs_per_user))
    burn = _project_burn(local, exa, num_users)
    recs = _recommendations(local, exa, burn)

    _print_exa(exa)
    _print_local(local)
    _print_attention(local)
    _print_burn(burn)
    _print_recs(recs)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    asyncio.run(main())
