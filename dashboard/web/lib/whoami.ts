/**
 * Resolve the current user_id, in priority order:
 *
 *   1. `?user_id=` query string (dev escape hatch — middleware also honors
 *      this so you can drive the renderer without auth).
 *   2. The session cookie, via `/api/auth/whoami`. Backend verifies the
 *      cookie's signature + expiry; we just take whatever it returns.
 *
 * Returns null when neither is available; the caller falls back to a
 * fixture or shows an empty state.
 */
export async function resolveUserId(): Promise<string | null> {
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get('user_id');
    if (fromQuery) return fromQuery;
  }
  try {
    const res = await fetch('/api/auth/whoami', {
      credentials: 'include',
      cache: 'no-store',
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { user_id?: string };
    return body.user_id ?? null;
  } catch {
    return null;
  }
}
