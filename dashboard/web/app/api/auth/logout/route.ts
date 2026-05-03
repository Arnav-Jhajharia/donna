import { NextRequest, NextResponse } from 'next/server';

/**
 * POST /api/auth/logout — same-origin proxy that forwards to FastAPI's
 * logout endpoint and relays the resulting Set-Cookie header (which
 * deletes the HttpOnly `donna_session` cookie). Used by the dashboard
 * client and by manual cookie-swap workflows where JS can't touch the
 * HttpOnly cookie directly.
 */
export async function POST(req: NextRequest) {
  const backend = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backend) {
    return NextResponse.json({ error: 'auth not configured' }, { status: 503 });
  }
  const cookie = req.headers.get('cookie') ?? '';
  let upstream: Response;
  try {
    upstream = await fetch(`${backend}/api/auth/logout`, {
      method: 'POST',
      headers: { cookie },
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ error: 'upstream unreachable' }, { status: 502 });
  }
  const text = await upstream.text();
  const res = new NextResponse(text, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') ?? 'application/json',
    },
  });
  const setCookie = upstream.headers.get('set-cookie');
  if (setCookie) res.headers.set('set-cookie', setCookie);
  return res;
}
