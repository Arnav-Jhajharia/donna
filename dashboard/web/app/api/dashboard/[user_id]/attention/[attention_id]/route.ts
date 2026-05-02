import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/dashboard/{user_id}/attention/{attention_id}
 *
 * Proxies the FastAPI attention-detail endpoint that powers the
 * AttentionSheet bottom drawer. User-scoped on the backend — the FastAPI
 * route 404s if the requested attention doesn't belong to the caller.
 */
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ user_id: string; attention_id: string }> },
) {
  const { user_id, attention_id } = await params;
  const backendUrl = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backendUrl) {
    return NextResponse.json(
      { error: 'backend not configured' },
      { status: 503 },
    );
  }
  try {
    const upstream = await fetch(
      `${backendUrl}/api/dashboard/${encodeURIComponent(user_id)}/attention/${encodeURIComponent(attention_id)}`,
      { cache: 'no-store' },
    );
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        'content-type':
          upstream.headers.get('content-type') || 'application/json',
        'cache-control': 'no-store',
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: 'backend unreachable', detail: String(err) },
      { status: 502 },
    );
  }
}
