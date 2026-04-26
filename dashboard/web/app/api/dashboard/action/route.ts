import { NextRequest, NextResponse } from 'next/server';
import type { ActionVerb } from '@/lib/plan';

interface ActionRequest {
  verb: ActionVerb;
  user_id?: string;
}

interface ActionResponse {
  ok: boolean;
  /** Optional message that the dashboard surfaces as a fake-WA toast. */
  wa_ack?: string;
  /** Echoed verb for trace + debug. */
  verb?: ActionVerb;
}

/**
 * POST /api/dashboard/action
 *
 * Phase 1 — the action verb is logged + acknowledged with a templated reply
 * that mimics what Donna would send on WhatsApp. No real state mutation.
 *
 * Phase 2 will:
 *   1. Execute the verb against the backend (start tracker, complete loop, ...)
 *   2. Fire a hook so the brain can decide whether to send a richer follow-up
 *   3. Re-compose the manifest
 */
export async function POST(req: NextRequest): Promise<NextResponse<ActionResponse>> {
  let body: ActionRequest;
  try {
    body = (await req.json()) as ActionRequest;
  } catch {
    return NextResponse.json({ ok: false }, { status: 400 });
  }
  if (!body.verb || typeof body.verb.v !== 'string') {
    return NextResponse.json({ ok: false }, { status: 400 });
  }

  // Telemetry hook — replace with a real logger in phase 2.
  if (process.env.NODE_ENV !== 'production') {
    // eslint-disable-next-line no-console
    console.info('[dashboard.action]', body.user_id ?? 'unknown', body.verb);
  }

  const wa_ack = templateAck(body.verb);
  return NextResponse.json({ ok: true, wa_ack, verb: body.verb });
}

/**
 * Deterministic ack per verb. Donna voice: lowercase, terse, no em dashes.
 * These are the messages she'd send on WhatsApp without any LLM call.
 */
function templateAck(verb: ActionVerb): string {
  switch (verb.v) {
    case 'start_tracker':
      return `${verb.name} tracker on. tell me when you log something.`;
    case 'log_value':
      return `${verb.value}${verb.unit ? ' ' + verb.unit : ''} logged on ${verb.tracker}.`;
    case 'complete_pick':
      return 'kept. nice.';
    case 'snooze_reminder':
      return `snoozed until ${verb.until}.`;
    case 'mark_reminder_done':
      return 'kept. nice.';
    case 'dismiss_attention':
      return "got it. I'll stop bringing that one up.";
    case 'accept_attention':
      return "on it. surfacing it now.";
    case 'connect_integration':
      return `pulling ${verb.provider} now. give me a minute.`;
    case 'accept_draft':
      return 'sending it.';
    case 'decide_option':
      return 'noted. I picked the same.';
    case 'quick_log':
      return `logged. (${verb.kind})`;
    case 'open_relationship':
      return 'pulling up what I have on them.';
    case 'open_news':
      return 'opening.';
    case 'open_tracker':
      return `${verb.tracker} — full sheet coming up.`;
    case 'reply_chip':
      return `drafting a reply about ${verb.intent}.`;
    default: {
      const _exhaustive: never = verb;
      return 'done.';
    }
  }
}
