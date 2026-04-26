import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/dashboard/{user_id}/events  (SSE)
 *
 * Streams ``manifest_changed`` events from the FastAPI backend. The
 * frontend re-fetches the manifest endpoint on each event, replacing
 * the 20s polling cadence with sub-second updates after Donna runs
 * ``update_dashboard`` or accepts an attention.
 *
 * Returns 503 when ``DONNA_BACKEND_URL`` is unset (the polling
 * fallback in the page handles that case).
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ user_id: string }> },
) {
  const { user_id } = await params;
  const backendUrl = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backendUrl) {
    return NextResponse.json(
      { error: 'DONNA_BACKEND_URL not set; events require the live backend' },
      { status: 503 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${backendUrl}/api/dashboard/${encodeURIComponent(user_id)}/events`,
      {
        signal: req.signal,
        cache: 'no-store',
        // SSE: keep the connection open and proxy the chunked stream
        // through. ``no-store`` + the upstream's own ``x-accel-buffering: no``
        // header keep buffers from collecting events.
      },
    );
  } catch {
    return NextResponse.json(
      { error: 'failed to reach backend' },
      { status: 502 },
    );
  }

  if (!upstream.body) {
    return NextResponse.json(
      { error: 'backend returned no body' },
      { status: 502 },
    );
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': 'text/event-stream',
      'cache-control': 'no-store',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    },
  });
}
