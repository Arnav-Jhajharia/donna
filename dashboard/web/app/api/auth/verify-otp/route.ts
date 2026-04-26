import { NextRequest, NextResponse } from 'next/server';

/**
 * POST /api/auth/verify-otp — same-origin proxy to the FastAPI endpoint so
 * the session cookie lands on the dashboard's domain (cross-origin
 * Set-Cookie would be dropped by the browser).
 */
export async function POST(req: NextRequest) {
  const backend = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backend) {
    return NextResponse.json(
      { error: 'auth not configured' },
      { status: 503 },
    );
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'bad request' }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backend}/api/auth/verify-otp`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ error: 'upstream unreachable' }, { status: 502 });
  }

  const text = await upstream.text();
  const res = new NextResponse(text, {
    status: upstream.status,
    headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json' },
  });
  const cookie = upstream.headers.get('set-cookie');
  if (cookie) {
    res.headers.set('set-cookie', cookie);
  }
  return res;
}
