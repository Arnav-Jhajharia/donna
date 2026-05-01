import { NextRequest, NextResponse } from 'next/server';
import { selectFixture } from '@/lib/manifest-source';

const DEFAULT_INTERNAL_HOSTS = ['localhost:3001', '127.0.0.1:3001'];

function isInternalHost(req: NextRequest): boolean {
  const host = (req.headers.get('host') || '').toLowerCase();
  if (!host) return false;
  const hosts = (process.env.NEXT_PUBLIC_INTERNAL_HOSTS || '')
    .split(',')
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean);
  const allowList = hosts.length > 0 ? hosts : DEFAULT_INTERNAL_HOSTS;
  return allowList.includes(host);
}

/**
 * GET /api/dashboard/{user_id}/manifest
 *
 * Production semantics (USER host):
 * - Always proxies to FastAPI backend via `DONNA_BACKEND_URL`.
 * - 404 from backend → 404 to client → page shows the "ask Donna" empty
 *   state. Never serves a fixture.
 * - `?fixture=` and `?dev=1` are silently ignored on the user host —
 *   they're not part of the user-facing contract and would leak
 *   internal fixtures.
 *
 * Dev / fixture preview (INTERNAL host only):
 * - `?fixture=<name>` returns the named fixture for design iteration.
 * - `?dev=1` allows the rotating-fixture fallback when backend is
 *   absent or returns 404.
 *
 * Hostname allowlist comes from NEXT_PUBLIC_INTERNAL_HOSTS (same as
 * middleware.ts). Defaults to localhost:3001.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ user_id: string }> },
) {
  const { user_id } = await params;
  const internal = isInternalHost(req);

  // Fixture overrides only honoured on the internal host. On the user
  // host, silently strip them.
  const fixtureName =
    internal ? (req.nextUrl.searchParams.get('fixture') ?? undefined) : undefined;
  const devFallback =
    internal && req.nextUrl.searchParams.get('dev') === '1';

  if (fixtureName) {
    const plan = selectFixture({ userId: user_id, fixtureName, now: new Date() });
    return NextResponse.json(plan, { headers: { 'cache-control': 'no-store' } });
  }

  const backendUrl = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (backendUrl) {
    try {
      const upstream = await fetch(
        `${backendUrl}/api/dashboard/${encodeURIComponent(user_id)}/manifest`,
        { cache: 'no-store' },
      );
      if (upstream.ok) {
        const plan = await upstream.json();
        return NextResponse.json(plan, {
          headers: { 'cache-control': 'no-store' },
        });
      }
      // Forward backend status (typically 404) so the page can show a
      // real empty state. Only fall through to fixture rotation when
      // the caller is on the internal host AND opted into dev mode.
      if (!devFallback) {
        return NextResponse.json(
          { error: 'no manifest yet' },
          { status: upstream.status === 404 ? 404 : 502 },
        );
      }
    } catch {
      // Network error reaching backend.
      if (!devFallback) {
        return NextResponse.json({ error: 'backend unreachable' }, { status: 502 });
      }
    }
  } else if (!devFallback) {
    // No backend configured AND not internal-dev opt-in → tell the truth.
    return NextResponse.json(
      { error: 'backend not configured' },
      { status: 503 },
    );
  }

  // Dev fallback path — internal host only by construction.
  const plan = selectFixture({ userId: user_id, fixtureName, now: new Date() });
  return NextResponse.json(plan, {
    headers: { 'cache-control': 'no-store' },
  });
}
