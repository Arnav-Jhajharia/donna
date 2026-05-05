import { NextResponse } from 'next/server';
import { promises as fs } from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

/**
 * Source-of-truth selection:
 *   1. ``DONNA_BACKEND_URL`` set → fetch DB-backed events from
 *      ``/api/admin/events`` (production / staging path)
 *   2. otherwise → fall back to local ``.donna/events.jsonl`` for dev
 *      machines running the brain on the same filesystem
 *
 * The fallback exists so dev workflows that don't run a backend still get
 * /observe working off the brain's local file output.
 */

type RawEvent = {
  event: string;
  ts: string;
  turn_id: string | null;
  user_id: string | null;
  schema_version?: number;
  [key: string]: unknown;
};

type PromptSnapshot = {
  system_prompt: string;
  wrapped_user_prompt: string;
  system_prompt_len: number | null;
  wrapped_user_prompt_len: number | null;
  model: string | null;
  tool_mode: string | null;
  resume_session_id: string | null;
  fork_session: boolean | null;
  max_turns: number | null;
};

type IssueTag =
  | 'silent_exit'
  | 'runtime_error'
  | 'result_error'
  | 'expensive'
  | 'slow'
  | 'runaway'
  | 'hook_blocked';

type ToolCall = {
  tool: string;
  short: string;
  ts: string;
  input_keys: string[];
  input_preview_present: boolean;
  /** When the brain reaches send_burst we copy the messages payload up
   *  so the observe page can show what Donna actually said without
   *  hunting through events. ``null`` when the tracer didn't capture it. */
  send_burst_messages: unknown;
};

type Turn = {
  turn_id: string;
  user_id: string | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  user_message_preview: string | null;
  model: string | null;
  total_cost_usd: number | null;
  num_turns: number | null;
  /** Ordered short tool names — `recall → log_obs → send_burst`. */
  tool_chain: string[];
  /** Tool calls in order, with the bits useful in /observe. */
  tool_calls: ToolCall[];
  terminal_tool: string | null;
  terminal_ok: boolean | null;
  result_is_error: boolean | null;
  runtime_error: string | null;
  prompt_snapshot: PromptSnapshot | null;
  /** Hook denies that fell within this turn's window (originally orphaned
   *  with turn_id=null in the raw stream — we re-associate by timestamp). */
  hook_denies: RawEvent[];
  events: RawEvent[];
  /** Issue classification — drives the IssuesPanel + filter chips. */
  issues: IssueTag[];
};

type Aggregate = {
  turns_total: number;
  turns_with_terminator: number;
  silent_exit_rate: number;
  error_rate: number;
  avg_duration_ms: number | null;
  avg_cost_usd: number | null;
  total_cost_usd: number;
  /** Median + p95 for duration and cost so the UI can flag outliers. */
  duration_p50_ms: number | null;
  duration_p95_ms: number | null;
  cost_p50_usd: number | null;
  cost_p95_usd: number | null;
  memory_backend_p50_ms: Record<string, number>;
  memory_backend_p95_ms: Record<string, number>;
  memory_backend_count: Record<string, number>;
  tool_counts: Record<string, number>;
  retry_count: number;
  hook_deny_count: number;
  hook_deny_orphan_count: number;
  error_count: number;
  /** Per-issue rollup so /observe can render bucket counts. */
  issue_counts: Record<IssueTag, number>;
};

// Issue thresholds. Adjust if median drifts.
const SLOW_DURATION_MS = 15_000;
const EXPENSIVE_COST_USD = 0.1;
const RUNAWAY_HEADROOM = 1; // num_turns >= max_turns - this = runaway

function resolveEventsPath(): string {
  const override = process.env.DONNA_OBS_LOG;
  if (override) return path.resolve(override);
  // dev server cwd is dashboard/web/. repo root is two levels up.
  return path.resolve(process.cwd(), '..', '..', '.donna', 'events.jsonl');
}

async function readEventsLines(filePath: string): Promise<RawEvent[]> {
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    const lines = content.split('\n').filter((line) => line.trim().length > 0);
    const events: RawEvent[] = [];
    for (const line of lines) {
      try {
        events.push(JSON.parse(line) as RawEvent);
      } catch {
        // skip malformed line
      }
    }
    return events;
  } catch (err) {
    const e = err as NodeJS.ErrnoException;
    if (e.code === 'ENOENT') return [];
    throw err;
  }
}

async function fetchEventsFromBackend(
  backendUrl: string,
  limit: number,
  userId: string | null,
): Promise<RawEvent[]> {
  // Backend events route is admin-gated; auth from server env so the
  // dashboard browser session never sees the credential.
  const adminUser = process.env.ADMIN_USER || 'admin';
  const adminPw = process.env.ADMIN_PASSWORD || '';
  if (!adminPw) {
    throw new Error('ADMIN_PASSWORD not configured for backend events fetch');
  }
  const auth = Buffer.from(`${adminUser}:${adminPw}`).toString('base64');
  // Pull a generous tail — /observe groups by turn and trims by turn count
  // downstream, so the raw event budget here is the limiting factor.
  const eventBudget = Math.max(limit * 30, 2000);
  const params = new URLSearchParams({ limit: String(eventBudget) });
  if (userId) params.set('user_id', userId);
  const upstream = await fetch(
    `${backendUrl}/api/admin/events?${params.toString()}`,
    {
      headers: { authorization: `Basic ${auth}` },
      cache: 'no-store',
    },
  );
  if (!upstream.ok) {
    const text = await upstream.text();
    throw new Error(`backend events ${upstream.status}: ${text.slice(0, 200)}`);
  }
  const body = (await upstream.json()) as { events?: RawEvent[] };
  return body.events ?? [];
}

function shortTool(name: string | null | undefined): string {
  if (!name) return '';
  return name.split('__').slice(-1)[0];
}

function groupTurns(events: RawEvent[]): Turn[] {
  const byTurn = new Map<string, Turn>();

  for (const ev of events) {
    const turnId = ev.turn_id;
    if (!turnId) continue;
    let t = byTurn.get(turnId);
    if (!t) {
      t = {
        turn_id: turnId,
        user_id: ev.user_id,
        started_at: ev.ts,
        ended_at: null,
        duration_ms: null,
        user_message_preview: null,
        model: null,
        total_cost_usd: null,
        num_turns: null,
        tool_chain: [],
        tool_calls: [],
        terminal_tool: null,
        terminal_ok: null,
        result_is_error: null,
        runtime_error: null,
        prompt_snapshot: null,
        hook_denies: [],
        events: [],
        issues: [],
      };
      byTurn.set(turnId, t);
    }
    t.events.push(ev);

    if (ev.event === 'turn.start') {
      t.started_at = ev.ts;
      t.user_message_preview = (ev.user_message_preview as string) ?? null;
      t.model = (ev.model as string) ?? null;
    } else if (ev.event === 'turn.end') {
      t.ended_at = ev.ts;
      t.duration_ms = (ev.duration_ms as number) ?? null;
      t.total_cost_usd = (ev.total_cost_usd as number) ?? null;
      t.num_turns = (ev.num_turns as number) ?? null;
      t.terminal_tool = (ev.terminal_tool as string) ?? null;
      t.terminal_ok = (ev.terminal_ok as boolean) ?? null;
      t.result_is_error = (ev.result_is_error as boolean) ?? null;
      t.runtime_error = (ev.runtime_error as string) ?? null;
    } else if (ev.event === 'prompt.snapshot') {
      t.prompt_snapshot = {
        system_prompt: (ev.system_prompt as string) ?? '',
        wrapped_user_prompt: (ev.wrapped_user_prompt as string) ?? '',
        system_prompt_len: (ev.system_prompt_len as number) ?? null,
        wrapped_user_prompt_len: (ev.wrapped_user_prompt_len as number) ?? null,
        model: (ev.model as string) ?? null,
        tool_mode: (ev.tool_mode as string) ?? null,
        resume_session_id: (ev.resume_session_id as string) ?? null,
        fork_session: (ev.fork_session as boolean) ?? null,
        max_turns: (ev.max_turns as number) ?? null,
      };
    } else if (ev.event === 'tool.call') {
      const fullName = (ev.tool as string) ?? '';
      const short = (ev.tool_short as string) ?? shortTool(fullName);
      const inputKeys = (ev.input_keys as string[]) ?? [];
      const preview = ev.input_preview ?? null;
      // The send_burst payload is the user-facing reply; surface the messages
      // array (when the tracer captured it) so /observe can render "donna said".
      const sendBurstMessages =
        short === 'send_burst' && preview && typeof preview === 'object' && 'messages' in (preview as Record<string, unknown>)
          ? (preview as Record<string, unknown>).messages
          : null;
      t.tool_calls.push({
        tool: fullName,
        short,
        ts: ev.ts,
        input_keys: inputKeys,
        input_preview_present: preview !== null && preview !== undefined,
        send_burst_messages: sendBurstMessages,
      });
      t.tool_chain.push(short);
    }
  }

  return Array.from(byTurn.values()).sort((a, b) => {
    return a.started_at < b.started_at ? 1 : -1;
  });
}

/**
 * The brain emits hook.deny with turn_id=null because hooks fire in a
 * different async context. Re-associate by timestamp — a deny that
 * lands while a turn is open belongs to that turn.
 *
 * Returns the count of orphans that couldn't be tied to any turn so we
 * can show them as ungrouped issues.
 */
function attachOrphanHookDenies(events: RawEvent[], turns: Turn[]): number {
  const sortedTurns = turns
    .filter((t) => t.ended_at !== null)
    .map((t) => ({
      turn: t,
      start: new Date(t.started_at).getTime(),
      end: new Date(t.ended_at as string).getTime(),
    }))
    .sort((a, b) => a.start - b.start);

  let orphans = 0;
  for (const ev of events) {
    if (ev.event !== 'hook.deny') continue;
    if (ev.turn_id) continue;
    const ts = new Date(ev.ts).getTime();
    const owner = sortedTurns.find((s) => ts >= s.start && ts <= s.end);
    if (owner) {
      owner.turn.hook_denies.push(ev);
    } else {
      orphans += 1;
    }
  }
  return orphans;
}

function classifyIssues(turn: Turn, costP50: number | null, durationP50: number | null): IssueTag[] {
  const tags: IssueTag[] = [];
  // Silent exit — turn ended without send_burst (the canonical terminator).
  if (turn.ended_at !== null && turn.terminal_tool !== 'send_burst') {
    tags.push('silent_exit');
  }
  if (turn.runtime_error) tags.push('runtime_error');
  if (turn.result_is_error === true) tags.push('result_error');
  if (turn.total_cost_usd !== null && turn.total_cost_usd >= EXPENSIVE_COST_USD) {
    tags.push('expensive');
  }
  // Also flag turns at 3× median cost even if below absolute threshold.
  if (
    !tags.includes('expensive') &&
    turn.total_cost_usd !== null &&
    costP50 !== null &&
    costP50 > 0 &&
    turn.total_cost_usd >= costP50 * 3
  ) {
    tags.push('expensive');
  }
  if (turn.duration_ms !== null && turn.duration_ms >= SLOW_DURATION_MS) {
    tags.push('slow');
  }
  if (
    !tags.includes('slow') &&
    turn.duration_ms !== null &&
    durationP50 !== null &&
    durationP50 > 0 &&
    turn.duration_ms >= durationP50 * 3
  ) {
    tags.push('slow');
  }
  // Runaway loop — brain hit (or got close to) max_turns.
  const maxTurns = turn.prompt_snapshot?.max_turns ?? null;
  if (
    turn.num_turns !== null &&
    maxTurns !== null &&
    turn.num_turns >= maxTurns - RUNAWAY_HEADROOM
  ) {
    tags.push('runaway');
  }
  if (turn.hook_denies.length > 0) tags.push('hook_blocked');
  return tags;
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length));
  return sorted[idx];
}

function buildAggregate(events: RawEvent[], turns: Turn[], orphanDenies: number): Aggregate {
  const closed = turns.filter((t) => t.ended_at !== null);
  const withTerminator = closed.filter((t) => t.terminal_tool === 'send_burst').length;
  const errorCount = closed.filter((t) => t.result_is_error === true || t.runtime_error).length;

  const durations = closed.map((t) => t.duration_ms ?? 0).filter((d) => d > 0).sort((a, b) => a - b);
  const costs = closed.map((t) => t.total_cost_usd ?? 0).filter((c) => c > 0).sort((a, b) => a - b);

  const backendDurations = new Map<string, number[]>();
  const toolCounts = new Map<string, number>();
  let retryCount = 0;
  let hookDenyCount = 0;
  let errorEventCount = 0;

  for (const ev of events) {
    if (ev.event === 'memory.op') {
      const backend = (ev.backend as string) ?? 'unknown';
      const dur = (ev.duration_ms as number) ?? 0;
      if (!backendDurations.has(backend)) backendDurations.set(backend, []);
      backendDurations.get(backend)!.push(dur);
    } else if (ev.event === 'tool.call') {
      const short = (ev.tool_short as string) ?? shortTool(ev.tool as string) ?? 'unknown';
      toolCounts.set(short, (toolCounts.get(short) ?? 0) + 1);
    } else if (ev.event === 'retry.fired') {
      retryCount += 1;
    } else if (ev.event === 'hook.deny') {
      hookDenyCount += 1;
    } else if (ev.event === 'error') {
      errorEventCount += 1;
    }
  }

  const p50: Record<string, number> = {};
  const p95: Record<string, number> = {};
  const counts: Record<string, number> = {};
  for (const [backend, arr] of backendDurations) {
    const sorted = arr.slice().sort((a, b) => a - b);
    p50[backend] = percentile(sorted, 50);
    p95[backend] = percentile(sorted, 95);
    counts[backend] = sorted.length;
  }

  const issueCounts: Record<IssueTag, number> = {
    silent_exit: 0,
    runtime_error: 0,
    result_error: 0,
    expensive: 0,
    slow: 0,
    runaway: 0,
    hook_blocked: 0,
  };
  for (const t of turns) {
    for (const tag of t.issues) issueCounts[tag] += 1;
  }

  return {
    turns_total: closed.length,
    turns_with_terminator: withTerminator,
    silent_exit_rate: closed.length ? (closed.length - withTerminator) / closed.length : 0,
    error_rate: closed.length ? errorCount / closed.length : 0,
    avg_duration_ms: durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null,
    avg_cost_usd: costs.length ? costs.reduce((a, b) => a + b, 0) / costs.length : null,
    total_cost_usd: costs.reduce((a, b) => a + b, 0),
    duration_p50_ms: durations.length ? percentile(durations, 50) : null,
    duration_p95_ms: durations.length ? percentile(durations, 95) : null,
    cost_p50_usd: costs.length ? percentile(costs, 50) : null,
    cost_p95_usd: costs.length ? percentile(costs, 95) : null,
    memory_backend_p50_ms: p50,
    memory_backend_p95_ms: p95,
    memory_backend_count: counts,
    tool_counts: Object.fromEntries(toolCounts),
    retry_count: retryCount,
    hook_deny_count: hookDenyCount,
    hook_deny_orphan_count: orphanDenies,
    error_count: errorEventCount,
    issue_counts: issueCounts,
  };
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  // Cap raised from 200 → 1000 so paginated user-scoped views can dig
  // back through long histories. Per-user volume is bounded; the cap
  // protects against runaway global queries.
  const limit = Math.min(
    1000,
    Math.max(1, parseInt(url.searchParams.get('limit') ?? '50', 10)),
  );
  const userId = url.searchParams.get('user_id');

  const backendUrl = process.env.DONNA_BACKEND_URL?.replace(/\/$/, '');
  let events: RawEvent[] = [];
  let source = 'db';
  let sourceLabel = backendUrl ? `${backendUrl}/api/admin/events` : '';
  let warning: string | null = null;

  if (backendUrl) {
    try {
      events = await fetchEventsFromBackend(backendUrl, limit, userId);
    } catch (err) {
      // Backend reachable-but-failing should NOT fall back silently — the
      // operator needs to see why /observe is empty in prod. Surface the
      // error in the response so the dashboard can show a banner.
      warning = `backend events fetch failed: ${String(err).slice(0, 200)}`;
      events = [];
    }
  } else {
    // Local-dev fallback: read the brain's append-only JSONL file.
    const filePath = resolveEventsPath();
    sourceLabel = filePath;
    source = 'file';
    events = await readEventsLines(filePath);
    // Apply user_id filter at the file-source layer too so dev parity
    // matches prod when a userFilter is set.
    if (userId) {
      events = events.filter((e) => e.user_id === userId);
    }
  }

  const turns = groupTurns(events);
  const orphanDenies = attachOrphanHookDenies(events, turns);
  const trimmed = turns.slice(0, limit);

  // First-pass aggregate to compute medians, then classify with those medians,
  // then a final aggregate that includes per-issue counts. Two passes is fine
  // for the volumes /observe sees (200 turns max).
  const firstPass = buildAggregate(events, trimmed, orphanDenies);
  for (const t of trimmed) {
    t.issues = classifyIssues(t, firstPass.cost_p50_usd, firstPass.duration_p50_ms);
  }
  const aggregate = buildAggregate(events, trimmed, orphanDenies);

  return NextResponse.json({
    events_path: sourceLabel,
    source,
    warning,
    total_events: events.length,
    total_turns: turns.length,
    turns: trimmed,
    aggregate,
  });
}
