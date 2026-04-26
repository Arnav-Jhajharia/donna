import { NextRequest, NextResponse } from 'next/server';

/**
 * Edge middleware: gate the dashboard on a session cookie OR an explicit
 * `?user_id=` query (dev escape hatch).
 *
 * - Auth endpoints (`/auth/*`, `/api/auth/*`) are always allowed so users
 *   can land + redeem links + verify OTP without a prior session.
 * - The manifest endpoint (`/api/dashboard/.../manifest`) is allowed when
 *   it carries `?user_id=` (dev) or the session cookie (prod).
 * - Anything else under `/` requires a session cookie. Missing → redirect
 *   to `/auth/expired` so the user knows to text Donna.
 *
 * We deliberately do NOT verify the cookie's signature here — Edge runtime
 * can't cleanly run our HMAC code, and the backend re-verifies on every
 * manifest fetch anyway. Middleware just checks "is a cookie present?"
 * which is enough to keep unauthenticated visitors out of the renderer.
 */
const PUBLIC_PATHS = ['/auth/magic', '/auth/otp', '/auth/signin', '/auth/expired'];
// All ``/api/*`` routes pass through middleware untouched — each route
// owns its own auth (or lack of) and returns JSON. Redirecting an API
// call to an HTML page breaks the caller's JSON parser. Dev / internal
// page surfaces (observe, moments, etc.) also bypass auth so iteration
// stays unblocked without minting a session every time.
const PUBLIC_PREFIXES = [
  '/api/',
  '/_next/',
  '/favicon',
  '/observe',
  '/moments',
  '/expansion',
  '/generator',
];

function isPublic(pathname: string): boolean {
  if (PUBLIC_PATHS.includes(pathname)) return true;
  return PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

// HTTP Basic auth gate for the /admin observability surface. Hosted on
// the same instance as the user-facing dashboard, so without this gate
// anyone who knows the URL would be a few clicks from raw user data.
function requireAdminBasic(req: NextRequest): NextResponse | null {
  const expectedPw = process.env.ADMIN_PASSWORD;
  if (!expectedPw) {
    return new NextResponse(
      'admin disabled — set ADMIN_PASSWORD env var',
      { status: 503 },
    );
  }
  const expectedUser = process.env.ADMIN_USER || 'admin';
  const header = req.headers.get('authorization') || '';
  if (header.startsWith('Basic ')) {
    try {
      const decoded = atob(header.slice(6));
      const idx = decoded.indexOf(':');
      const user = idx >= 0 ? decoded.slice(0, idx) : decoded;
      const pw = idx >= 0 ? decoded.slice(idx + 1) : '';
      if (user === expectedUser && pw === expectedPw) return null;
    } catch {
      // fall through to 401
    }
  }
  return new NextResponse('admin auth required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="donna-admin"' },
  });
}

export function middleware(req: NextRequest) {
  const { pathname, searchParams } = req.nextUrl;

  // Admin paths get their own auth — Basic, not the user-session cookie.
  // Both the page surface and the API proxy are gated.
  if (
    pathname === '/admin' ||
    pathname.startsWith('/admin/') ||
    pathname.startsWith('/api/admin/')
  ) {
    const denied = requireAdminBasic(req);
    if (denied) return denied;
    return NextResponse.next();
  }

  if (isPublic(pathname)) {
    return NextResponse.next();
  }

  const session = req.cookies.get('donna_session')?.value;
  const userIdQuery = searchParams.get('user_id');

  // Dev escape hatch: ?user_id=… bypasses auth so we can keep iterating
  // on the renderer without a real session. Backend still authoritative
  // on what user that maps to.
  if (session || userIdQuery) {
    return NextResponse.next();
  }

  return NextResponse.redirect(new URL('/auth/signin', req.url));
}

export const config = {
  // Match everything except the Next.js asset paths and the favicon.
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
