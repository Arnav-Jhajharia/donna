/**
 * Shared admin fetch helper. Server-side only — runs inside React Server
 * Components. The /api/admin/[...path] route forwards the Authorization
 * header from the original request, but this helper is called from the
 * RSC layer where headers() can be used to forward.
 */
import { headers } from 'next/headers';

export async function adminFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const h = await headers();
  const proto = h.get('x-forwarded-proto') || 'http';
  const host = h.get('host') || 'localhost:3000';
  const auth = h.get('authorization') || '';
  const url = `${proto}://${host}/api/admin/${path.replace(/^\//, '')}`;
  const res = await fetch(url, {
    ...init,
    cache: 'no-store',
    headers: {
      ...(init?.headers || {}),
      authorization: auth,
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`admin ${path}: ${res.status} ${text.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}
