import { NextRequest, NextResponse } from 'next/server';
import { selectFixture } from '@/lib/manifest-source';

/**
 * GET /api/dashboard/{user_id}/manifest
 *
 * Production semantics:
 * - When `DONNA_BACKEND_URL` is set, this route proxies to the FastAPI
 *   backend. A 404 from the backend means "no manifest yet for this
 *   user" and is forwarded to the client unchanged. The page renders
 *   an "ask Donna to compose one" empty state — never a fixture.
 *
 * Dev escape hatches (kept so /generator, /moments, and design iteration
 * don't break):
 * - `?fixture=<name>` always returns the named fixture, regardless of
 *   backend state.
 * - `?dev=1` allows the rotating-fixture fallback when the backend is
 *   absent or returns 404. Without it, production stays honest.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ user_id: string }> },
) {
  const { user_id } = await params;
  const fixtureName = req.nextUrl.searchParams.get('fixture') ?? undefined;
  const devFallback = req.nextUrl.searchParams.get('dev') === '1';

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
      // the caller opted into dev mode.
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
    // No backend configured AND no dev opt-in → tell the truth.
    return NextResponse.json(
      { error: 'backend not configured' },
      { status: 503 },
    );
  }

  // Dev fallback path only.
  const plan = selectFixture({ userId: user_id, fixtureName, now: new Date() });
  return NextResponse.json(plan, {
    headers: { 'cache-control': 'no-store' },
  });
}
