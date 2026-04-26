import { NextRequest, NextResponse } from 'next/server';

/**
 * Catch-all proxy: /api/admin/<anything> → DONNA_BACKEND_URL/api/admin/<anything>.
 *
 * The edge middleware has already enforced HTTP Basic auth before any
 * request reaches us. We forward the same Authorization header so the
 * FastAPI ``_require_admin`` dependency re-validates server-side and
 * direct curl access against the backend remains gated.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const backendUrl = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backendUrl) {
    return NextResponse.json(
      { error: 'DONNA_BACKEND_URL not set' },
      { status: 503 },
    );
  }
  const upstreamPath = path.map(encodeURIComponent).join('/');
  const search = req.nextUrl.search;
  const authHeader = req.headers.get('authorization') || '';
  try {
    const upstream = await fetch(
      `${backendUrl}/api/admin/${upstreamPath}${search}`,
      {
        cache: 'no-store',
        headers: { authorization: authHeader },
      },
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
      { error: 'failed to reach backend', detail: String(err) },
      { status: 502 },
    );
  }
}
