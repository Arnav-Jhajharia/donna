import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/dashboard/{user_id}/state
 *
 * Thin proxy to the FastAPI ``/api/dashboard/{user_id}/state`` endpoint.
 * Returns a per-user state snapshot used by the /observe page (attentions,
 * instances, schedules, observations, open loops, chat) — distinct from
 * the per-turn event stream at /api/events.
 *
 * Returns 503 when ``DONNA_BACKEND_URL`` is unset (no fixture fallback —
 * state is real or it isn't).
 */
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ user_id: string }> },
) {
  const { user_id } = await params;
  const backendUrl = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backendUrl) {
    return NextResponse.json(
      { error: 'DONNA_BACKEND_URL not set; state requires the live backend' },
      { status: 503 },
    );
  }

  const upstreamUrl = `${backendUrl}/api/dashboard/${encodeURIComponent(user_id)}/state`;
  try {
    const upstream = await fetch(upstreamUrl, { cache: 'no-store' });
    const body = await upstream.json().catch(() => ({}));
    return NextResponse.json(body, {
      status: upstream.status,
      headers: { 'cache-control': 'no-store' },
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: 'failed to reach backend',
        upstream_url: upstreamUrl,
        detail: String(err),
        hint: `verify DONNA_BACKEND_URL points at the running uvicorn (e.g. http://localhost:8000)`,
      },
      { status: 502 },
    );
  }
}
