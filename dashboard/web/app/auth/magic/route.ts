import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /auth/magic?t=<token>
 *
 * Validates the magic-link token against the backend, lets the backend set
 * the session cookie via `Set-Cookie` on the redeem response, then forwards
 * that header on a 302 redirect to `/`. The user lands logged-in for 5
 * minutes per the product spec.
 *
 * On any failure (missing token, invalid, expired) we redirect to
 * `/auth/expired` so the user knows to ask Donna for a new link rather
 * than seeing a generic error page.
 */
export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get('t');
  const expiredUrl = new URL('/auth/signin?reason=expired', req.url);
  if (!token) {
    return NextResponse.redirect(expiredUrl);
  }

  const backend = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backend) {
    // No backend wired — dev mode without auth. Fall through to fixture
    // rotation so the page still renders something.
    return NextResponse.redirect(new URL('/', req.url));
  }

  try {
    const upstream = await fetch(`${backend}/api/auth/redeem-magic`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ token }),
      cache: 'no-store',
    });
    if (!upstream.ok) {
      return NextResponse.redirect(expiredUrl);
    }
    // Forward the upstream Set-Cookie header onto our redirect response so
    // the session cookie lands in the user's browser.
    const cookie = upstream.headers.get('set-cookie');
    const res = NextResponse.redirect(new URL('/', req.url));
    if (cookie) {
      res.headers.set('set-cookie', cookie);
    }
    return res;
  } catch {
    return NextResponse.redirect(expiredUrl);
  }
}
