"""Supabase call logging.

Writes one row per call into `voice_calls`:

    create table voice_calls (
        id uuid primary key default gen_random_uuid(),
        call_id text unique not null,        -- livekit room name
        room_id text,                        -- livekit RM_… id
        from_number text,
        to_number text,
        direction text,                       -- 'inbound' | 'outbound'
        started_at timestamptz not null default now(),
        ended_at timestamptz,
        duration_seconds integer,
        ended_reason text,
        transcript_summary text,
        agent_metadata jsonb default '{}'::jsonb
    );

The logger is best-effort. Failures are logged and swallowed — call
audio must never depend on the analytics surface staying up.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)


class SupabaseLogger:
    """Thin REST wrapper around the Supabase voice_calls table.

    Uses the PostgREST endpoint (no client lib dep) so we stay light.
    No-op when SUPABASE_URL or service key is empty.
    """

    def __init__(self, url: str, service_key: str) -> None:
        self.enabled = bool(url and service_key)
        self.base = url.rstrip("/") if url else ""
        self.headers = (
            {
                "apikey": service_key,
                "authorization": f"Bearer {service_key}",
                "content-type": "application/json",
                "prefer": "return=minimal",
            }
            if self.enabled
            else {}
        )

    async def log_call_start(
        self,
        *,
        call_id: str,
        room_id: str | None,
        from_number: str | None,
        to_number: str | None,
        direction: str,
        started_at: datetime | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload = {
            "call_id": call_id,
            "room_id": room_id,
            "from_number": from_number,
            "to_number": to_number,
            "direction": direction,
            "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
        }
        await self._upsert(payload)

    async def log_call_end(
        self,
        *,
        call_id: str,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
        ended_reason: str | None = None,
        transcript_summary: str | None = None,
        agent_metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload: dict[str, Any] = {
            "ended_at": (ended_at or datetime.now(timezone.utc)).isoformat(),
        }
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        if ended_reason:
            payload["ended_reason"] = ended_reason
        if transcript_summary:
            payload["transcript_summary"] = transcript_summary
        if agent_metadata:
            payload["agent_metadata"] = agent_metadata
        await self._patch(call_id, payload)

    # ─── internals ────────────────────────────────────────────────────

    async def _upsert(self, payload: dict[str, Any]) -> None:
        url = f"{self.base}/rest/v1/voice_calls?on_conflict=call_id"
        headers = {**self.headers, "prefer": "resolution=merge-duplicates,return=minimal"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    log.warning(
                        "supabase upsert %s body=%s",
                        r.status_code, r.text[:200],
                    )
        except Exception:
            log.exception("supabase upsert failed (non-fatal)")

    async def _patch(self, call_id: str, payload: dict[str, Any]) -> None:
        url = f"{self.base}/rest/v1/voice_calls?call_id=eq.{call_id}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.patch(url, headers=self.headers, json=payload)
                if r.status_code >= 400:
                    log.warning(
                        "supabase patch %s body=%s",
                        r.status_code, r.text[:200],
                    )
        except Exception:
            log.exception("supabase patch failed (non-fatal)")
