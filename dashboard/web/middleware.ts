import { NextRequest, NextResponse } from 'next/server';

/**
 * Edge middleware: split user surface from internal surface by hostname.
 *
 * - User host (e.g. donna.app, localhost:3000)
 *     - Allowed: `/`, `/auth/*`, `/api/dashboard/*`, `/api/auth/*`
 *     - Blocked (404): `/observe`, `/moments`, `/generator`, `/expansion`,
 *       `/admin/*`, `/api/admin/*`, `/api/events`, `/internal-home`
 *     - `/` requires session cookie (or `?user_id=` dev escape hatch)
 *
 * - Internal host (e.g. internal.donna.app, localhost:3001)
 *     - Allowed: `/observe`, `/moments`, `/generator`, `/expansion`,
 *       `/admin/*`, `/api/admin/*`, `/api/events`, `/internal-home`
 *     - Blocked (404): user-facing routes
 *     - All allowed routes require HTTP Basic auth
 *       (ADMIN_USER + ADMIN_PASSWORD)
 *     - `/` redirects to `/internal-home`
 *
 * - Unknown host: 404. No default routing — explicit hosts only.
 *
 * Hostname allowlists come from NEXT_PUBLIC_USER_HOSTS and
 * NEXT_PUBLIC_INTERNAL_HOSTS (comma-separated). Sensible local-dev
 * defaults: localhost:3000 = user, localhost:3001 = internal.
 *
 * Cookie signature is NOT verified here — Edge runtime can't run our
 * HMAC code. The backend re-verifies on every manifest fetch.
 */

const DEFAULT_USER_HOSTS = ['localhost:3000', '127.0.0.1:3000'];
const DEFAULT_INTERNAL_HOSTS = ['localhost:3001', '127.0.0.1:3001'];

function parseHostList(envValue: string | undefined, fallback: string[]): string[] {
  if (!envValue) return fallback;
  return envValue
    .split(',')
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean);
}

const USER_HOSTS = parseHostList(
  process.env.NEXT_PUBLIC_USER_HOSTS,
  DEFAULT_USER_HOSTS,
);
const INTERNAL_HOSTS = parseHostList(
  process.env.NEXT_PUBLIC_INTERNAL_HOSTS,
  DEFAULT_INTERNAL_HOSTS,
);

type Surface = 'user' | 'internal' | 'unknown';

function classifyHost(host: string | null): Surface {
  if (!host) return 'unknown';
  const normalized = host.toLowerCase();
  if (USER_HOSTS.includes(normalized)) return 'user';
  if (INTERNAL_HOSTS.includes(normalized)) return 'internal';
  return 'unknown';
}

// Routes that may be served from the USER host.
//
// /moments is internal-only — it's the design catalogue of dashboard
// archetypes for staff iteration, not a public surface. End users see
// only their own composed manifest at `/`.
const USER_PUBLIC_PATHS = new Set([
  '/auth/magic',
  '/auth/otp',
  '/auth/signin',
  '/auth/expired',
  // Composio's OAuth chain redirects here after a connection completes.
  // No session cookie required (user is mid-OAuth flow); the page just
  // confirms + auto-redirects to WhatsApp.
  '/oauth-complete',
]);
const USER_PUBLIC_PREFIXES = ['/api/dashboard/', '/api/auth/'];

// Routes that may only be served from the INTERNAL host.
const INTERNAL_ALLOWED_PATHS = new Set([
  '/observe',
  '/moments',
  '/generator',
  '/expansion',
  '/internal-home',
  '/admin',
]);
const INTERNAL_ALLOWED_PREFIXES = [
  '/admin/',
  '/api/admin/',
  '/api/dashboard/',
  '/api/events',
  '/observe/',
  '/moments/',
  '/generator/',
  '/expansion/',
];

// Always-allowed (asset / framework) prefixes — neutral, served on both.
const NEUTRAL_PREFIXES = ['/_next/', '/favicon'];

function isNeutral(pathname: string): boolean {
  return NEUTRAL_PREFIXES.some((p) => pathname.startsWith(p));
}

function isUserAllowed(pathname: string): boolean {
  if (pathname === '/') return true;
  if (USER_PUBLIC_PATHS.has(pathname)) return true;
  if (USER_PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) return true;
  return false;
}

// User-host paths that bypass the session-cookie gate. /auth/* lands
// users here without a session.
function isUserNoAuth(pathname: string): boolean {
  if (USER_PUBLIC_PATHS.has(pathname)) return true;
  return false;
}

function isInternalAllowed(pathname: string): boolean {
  if (INTERNAL_ALLOWED_PATHS.has(pathname)) return true;
  if (INTERNAL_ALLOWED_PREFIXES.some((p) => pathname.startsWith(p))) return true;
  return false;
}

function notFound(): NextResponse {
  return new NextResponse('not found', { status: 404 });
}

/**
 * HTTP Basic auth gate for the internal surface. Reuses the
 * ADMIN_USER + ADMIN_PASSWORD env vars previously scoped to /admin.
 */
function requireStaffBasic(req: NextRequest): NextResponse | null {
  const expectedPw = process.env.ADMIN_PASSWORD;
  if (!expectedPw) {
    return new NextResponse(
      'internal disabled — set ADMIN_PASSWORD env var',
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
  return new NextResponse('staff auth required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="donna-internal"' },
  });
}

function handleUserHost(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;

  if (isNeutral(pathname)) return NextResponse.next();
  if (!isUserAllowed(pathname)) return notFound();

  // /api/* is allowed-as-listed; each route owns its own auth and
  // returns JSON. Don't redirect API calls to HTML pages.
  if (pathname.startsWith('/api/')) return NextResponse.next();

  // /auth/* + /moments are public — the user lands here without a
  // session, or arrives via the LP recipe gallery.
  if (isUserNoAuth(pathname)) return NextResponse.next();

  // Bare / always passes through. The page server component reads the
  // `donna_session` cookie itself and renders either the landing page
  // (no cookie) or the dashboard surface (cookie present). Same route,
  // auth-state branch.
  return NextResponse.next();
}

function handleInternalHost(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;

  if (isNeutral(pathname)) return NextResponse.next();

  // / on internal host → /internal-home (the staff navigation page).
  if (pathname === '/') {
    return NextResponse.redirect(new URL('/internal-home', req.url));
  }

  if (!isInternalAllowed(pathname)) return notFound();

  // Every internal route — page or API — is staff-Basic gated.
  const denied = requireStaffBasic(req);
  if (denied) return denied;

  return NextResponse.next();
}

export function middleware(req: NextRequest) {
  const host = req.headers.get('host');
  const surface = classifyHost(host);

  if (surface === 'user') return handleUserHost(req);
  if (surface === 'internal') return handleInternalHost(req);
  return notFound();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
