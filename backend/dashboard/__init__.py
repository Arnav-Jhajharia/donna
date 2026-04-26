"""Dashboard subsystem — brain → DashboardPlan → Postgres → frontend.

Modules:
    schema   — Pydantic mirror of dashboard/web/lib/plan.ts.
    compose  — input assembly + Sonnet 4.6 call → DashboardPlan.
    store    — Postgres upsert + read helpers.
"""
