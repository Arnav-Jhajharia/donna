import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/auth/whoami — same-origin proxy that forwards the session
 * cookie to FastAPI and returns the resolved user_id (or 401).
 */
export async function GET(req: NextRequest) {
  const backend = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backend) {
    return NextResponse.json({ error: 'auth not configured' }, { status: 503 });
  }
  const cookie = req.headers.get('cookie') ?? '';
  let upstream: Response;
  try {
    upstream = await fetch(`${backend}/api/auth/whoami`, {
      method: 'GET',
      headers: { cookie },
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ error: 'upstream unreachable' }, { status: 502 });
  }
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json' },
  });
}
