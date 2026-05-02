import { NextRequest, NextResponse } from 'next/server';
import type { ActionVerb } from '@/lib/plan';

interface ActionRequest {
  verb: ActionVerb;
  user_id?: string;
}

interface ActionResponse {
  ok: boolean;
  /** Donna-voice ack to surface as a toast. */
  message?: string;
  /** Echoed verb for trace + debug. */
  verb?: ActionVerb;
  [key: string]: unknown;
}

/**
 * POST /api/dashboard/action
 *
 * Forwards the verb to the backend dashboard action endpoint with the
 * resolved user_id (from the session cookie or `?user_id=` dev escape
 * hatch). The backend executes the verb against the right tool —
 * log_observation, create_attention, mark_reminder_done, etc. — and
 * returns the Donna-voice ack the dashboard surfaces as a toast.
 *
 * The frontend then re-fetches the manifest (or relies on the SSE event
 * stream) so the next render reflects the new state.
 */
export async function POST(req: NextRequest): Promise<NextResponse<ActionResponse>> {
  let body: ActionRequest;
  try {
    body = (await req.json()) as ActionRequest;
  } catch {
    return NextResponse.json({ ok: false, message: 'invalid body' }, { status: 400 });
  }
  if (!body.verb || typeof body.verb.v !== 'string') {
    return NextResponse.json(
      { ok: false, message: 'verb required' },
      { status: 400 },
    );
  }

  const userId = body.user_id || resolveUserIdFromCookie(req);
  if (!userId) {
    return NextResponse.json(
      {
        ok: false,
        message: "can't tell who you are — are you signed in?",
      },
      { status: 401 },
    );
  }

  const backendUrl = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  if (!backendUrl) {
    return NextResponse.json(
      { ok: false, message: 'backend not configured' },
      { status: 503 },
    );
  }

  // Strip the `v` field, keep verb-specific fields. Backend unwraps
  // ``request.action`` so the wire shape is { action: { v, ...rest } }.
  const action = body.verb as Record<string, unknown>;

  try {
    const upstream = await fetch(
      `${backendUrl}/api/dashboard/${encodeURIComponent(userId)}/action`,
      {
        method: 'POST',
        cache: 'no-store',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ action }),
      },
    );
    const upstreamBody = await upstream.text();
    let parsed: Record<string, unknown> = {};
    try {
      parsed = upstreamBody ? JSON.parse(upstreamBody) : {};
    } catch {
      parsed = { raw: upstreamBody };
    }
    if (!upstream.ok) {
      return NextResponse.json(
        {
          ok: false,
          message: typeof parsed.detail === 'string'
            ? parsed.detail
            : (typeof parsed.message === 'string'
              ? parsed.message
              : `something broke (HTTP ${upstream.status})`),
          verb: body.verb,
          ...parsed,
        },
        { status: upstream.status },
      );
    }
    return NextResponse.json({
      ok: true,
      verb: body.verb,
      message:
        typeof parsed.message === 'string' ? parsed.message : 'done.',
      ...parsed,
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        message: 'backend unreachable',
        detail: String(err),
        verb: body.verb,
      },
      { status: 502 },
    );
  }
}

function resolveUserIdFromCookie(req: NextRequest): string | null {
  // Production session cookie path. Match whatever the auth flow sets.
  const sess = req.cookies.get('donna_session')?.value;
  if (sess) {
    // The session cookie is a signed token; we don't decode it here —
    // a future iteration calls /api/auth/whoami. For now, accept the
    // dev escape hatch in the URL.
    void sess;
  }
  const fromQs = req.nextUrl.searchParams.get('user_id');
  if (fromQs) return fromQs;
  return null;
}
