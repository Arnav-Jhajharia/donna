'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

type RawEvent = {
  event: string;
  ts: string;
  turn_id: string | null;
  user_id: string | null;
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
  tool_chain: string[];
  tool_calls: ToolCall[];
  terminal_tool: string | null;
  terminal_ok: boolean | null;
  result_is_error: boolean | null;
  runtime_error: string | null;
  prompt_snapshot: PromptSnapshot | null;
  hook_denies: RawEvent[];
  events: RawEvent[];
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
  issue_counts: Record<IssueTag, number>;
};

type Payload = {
  events_path: string;
  total_events: number;
  total_turns: number;
  turns: Turn[];
  aggregate: Aggregate;
};

// ── State snapshot (per-user, distinct from per-turn events) ───────────────
type StateAttention = {
  id: string;
  status: string;
  origin: string;
  card: string;
  title: string;
  description: string;
  subject: string | null;
  domain_tags: string[];
  cadence_type: string;
  created_at: string | null;
  last_update_at: string | null;
  update_count: number;
  shadow_state: {
    tick_count: number;
    promotion_hits: number;
    max_ticks: number;
  } | null;
};

type StateInstance = {
  id: string;
  primitive: string;
  connector: string;
  label: string;
  status: string;
  config: Record<string, unknown>;
  used_count: number;
  last_used_at: string | null;
  created_at: string | null;
};

type StateSchedule = {
  id: string;
  fire_at: string | null;
  status: string;
  origin: string;
  fired: boolean;
  fired_at: string | null;
  attention_id: string | null;
  context: Record<string, unknown>;
};

type StateObservation = {
  id: string;
  type: string;
  event_time: string | null;
  fields: Record<string, unknown>;
  raw: string | null;
};

type StateOpenLoop = {
  id: string;
  content: string;
  created_at: string | null;
};

type StateChat = {
  role: string;
  content: string;
  created_at: string | null;
  is_proactive: boolean;
};

type StateUser = {
  id: string;
  name: string | null;
  phone: string | null;
  timezone: string | null;
  last_active_at: string | null;
  living_profile: {
    narrative?: string;
    current_situation?: string;
    generated_at?: string;
    yesterday_refreshed_at?: string;
  } | null;
};

type StateSnapshot = {
  user_id: string;
  user: StateUser | null;
  attentions?: StateAttention[];
  instances?: StateInstance[];
  schedules?: StateSchedule[];
  observations?: StateObservation[];
  open_loops?: StateOpenLoop[];
  chat?: StateChat[];
  fetched_at?: string;
};

const ISSUE_LABELS: Record<IssueTag, string> = {
  silent_exit: 'silent exit',
  runtime_error: 'runtime error',
  result_error: 'result error',
  expensive: 'expensive',
  slow: 'slow',
  runaway: 'runaway loop',
  hook_blocked: 'hook denied',
};

const ISSUE_TONES: Record<IssueTag, 'red' | 'amber' | 'rust'> = {
  silent_exit: 'amber',
  runtime_error: 'red',
  result_error: 'red',
  expensive: 'rust',
  slow: 'rust',
  runaway: 'red',
  hook_blocked: 'amber',
};

function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function fmtCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return '—';
  return `$${usd.toFixed(4)}`;
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtChars(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return `${n.toLocaleString()} chars`;
}

function shortUser(uid: string | null | undefined): string {
  if (!uid) return '—';
  return uid.length > 12 ? `${uid.slice(0, 8)}…${uid.slice(-3)}` : uid;
}

function toneColor(tone: 'red' | 'amber' | 'rust'): { bg: string; fg: string } {
  if (tone === 'red') return { bg: 'var(--oxblood-100)', fg: 'var(--oxblood-700)' };
  if (tone === 'amber') return { bg: 'var(--amber-100)', fg: 'var(--amber-700)' };
  return { bg: 'var(--rust-100)', fg: 'var(--rust-700)' };
}

export default function ObservePage() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const [filter, setFilter] = useState<'all' | 'issues' | IssueTag>('all');
  const [userFilter, setUserFilter] = useState<string | null>(null);
  const [stateSnapshot, setStateSnapshot] = useState<StateSnapshot | null>(null);
  const [stateError, setStateError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/events?limit=100', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = (await res.json()) as Payload;
      setData(payload);
      setError(null);
      setLastFetched(new Date());
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  const fetchState = useCallback(async (uid: string) => {
    try {
      const res = await fetch(
        `/api/dashboard/${encodeURIComponent(uid)}/state`,
        { cache: 'no-store' },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(`HTTP ${res.status}${body?.error ? ': ' + body.error : ''}`);
      }
      const payload = (await res.json()) as StateSnapshot;
      setStateSnapshot(payload);
      setStateError(null);
    } catch (err) {
      setStateError((err as Error).message);
      setStateSnapshot(null);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(fetchData, 2000);
    return () => clearInterval(id);
  }, [autoRefresh, fetchData]);

  // State snapshot: fetch when a single user is selected, refresh on
  // the same auto-refresh tick as events.
  useEffect(() => {
    if (!userFilter) {
      setStateSnapshot(null);
      setStateError(null);
      return;
    }
    fetchState(userFilter);
  }, [userFilter, fetchState]);

  useEffect(() => {
    if (!autoRefresh || !userFilter) return;
    const id = setInterval(() => fetchState(userFilter), 5000);
    return () => clearInterval(id);
  }, [autoRefresh, userFilter, fetchState]);

  const filteredTurns = useMemo(() => {
    if (!data) return [] as Turn[];
    let out = data.turns;
    if (filter === 'issues') {
      out = out.filter((t) => t.issues.length > 0);
    } else if (filter !== 'all') {
      out = out.filter((t) => t.issues.includes(filter));
    }
    if (userFilter) {
      out = out.filter((t) => t.user_id === userFilter);
    }
    return out;
  }, [data, filter, userFilter]);

  const userOptions = useMemo(() => {
    if (!data) return [] as string[];
    const set = new Set<string>();
    for (const t of data.turns) {
      if (t.user_id) set.add(t.user_id);
    }
    return Array.from(set).sort();
  }, [data]);

  const selectedTurn = useMemo(() => {
    if (!data || !selected) return null;
    return data.turns.find((t) => t.turn_id === selected) ?? null;
  }, [data, selected]);

  return (
    <main
      style={{
        minHeight: '100vh',
        background: 'var(--paper-100)',
        color: 'var(--ink-900)',
        padding: '24px 32px 96px',
        fontFamily: 'var(--font-sans, system-ui)',
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 20,
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em', margin: 0 }}>
            donna / observe
          </h1>
          <div style={{ fontSize: 11, color: 'var(--ink-600)', marginTop: 4 }}>
            self-observability · {data?.events_path ?? 'loading…'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 11, color: 'var(--ink-600)' }}>
          {lastFetched && <span>updated {fmtTime(lastFetched.toISOString())}</span>}
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            auto-refresh
          </label>
          <button
            onClick={fetchData}
            style={{
              border: '1px solid var(--alpha-ink-14)',
              background: 'transparent',
              padding: '4px 12px',
              fontSize: 11,
              cursor: 'pointer',
              color: 'var(--ink-800)',
            }}
          >
            refresh
          </button>
        </div>
      </header>

      {error && (
        <div
          style={{
            padding: 12,
            background: 'var(--oxblood-100)',
            color: 'var(--oxblood-700)',
            fontSize: 12,
            marginBottom: 16,
          }}
        >
          error: {error}
        </div>
      )}

      {data && (
        <AggregateStrip agg={data.aggregate} totalEvents={data.total_events} totalTurns={data.total_turns} />
      )}

      {data && <IssuesPanel agg={data.aggregate} active={filter} onSelect={setFilter} />}

      <StatePanel
        userFilter={userFilter}
        snapshot={stateSnapshot}
        error={stateError}
      />

      <FilterBar
        filter={filter}
        userFilter={userFilter}
        userOptions={userOptions}
        onFilter={setFilter}
        onUserFilter={setUserFilter}
        visibleCount={filteredTurns.length}
        totalCount={data?.turns.length ?? 0}
      />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.2fr)',
          gap: 20,
          marginTop: 12,
        }}
      >
        <section>
          <h2
            style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--ink-600)',
              marginBottom: 8,
            }}
          >
            turns ({filteredTurns.length})
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {filteredTurns.map((t) => (
              <TurnRow
                key={t.turn_id}
                turn={t}
                selected={t.turn_id === selected}
                onClick={() => setSelected(t.turn_id === selected ? null : t.turn_id)}
              />
            ))}
            {filteredTurns.length === 0 && (
              <div style={{ fontSize: 12, color: 'var(--ink-500)', padding: 12 }}>
                {data ? 'no turns match this filter.' : 'loading…'}
              </div>
            )}
          </div>
        </section>

        <section>
          <h2
            style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--ink-600)',
              marginBottom: 8,
            }}
          >
            turn detail
          </h2>
          {selectedTurn ? (
            <TurnDetail turn={selectedTurn} />
          ) : (
            <div
              style={{
                fontSize: 12,
                color: 'var(--ink-500)',
                padding: 12,
                border: '1px dashed var(--alpha-ink-14)',
              }}
            >
              click a turn on the left to inspect events.
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function AggregateStrip({
  agg,
  totalEvents,
  totalTurns,
}: {
  agg: Aggregate;
  totalEvents: number;
  totalTurns: number;
}) {
  const backends = Object.keys(agg.memory_backend_count).sort();

  return (
    <div style={{ display: 'grid', gap: 8, marginBottom: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, minmax(0, 1fr))', gap: 8 }}>
        <Stat label="turns (all)" value={String(totalTurns)} />
        <Stat label="events" value={String(totalEvents)} />
        <Stat
          label="silent-exit"
          value={fmtPct(agg.silent_exit_rate)}
          tone={agg.silent_exit_rate > 0 ? 'warn' : 'ok'}
        />
        <Stat
          label="errors"
          value={fmtPct(agg.error_rate)}
          tone={agg.error_rate > 0 ? 'warn' : 'ok'}
        />
        <Stat
          label="dur p50/p95"
          value={`${fmtMs(agg.duration_p50_ms)} · ${fmtMs(agg.duration_p95_ms)}`}
        />
        <Stat label="cost p50/p95" value={`${fmtCost(agg.cost_p50_usd)} · ${fmtCost(agg.cost_p95_usd)}`} />
        <Stat
          label="hook denies"
          value={`${agg.hook_deny_count}${agg.hook_deny_orphan_count > 0 ? ` (+${agg.hook_deny_orphan_count} orphan)` : ''}`}
          tone={agg.hook_deny_count > 0 ? 'warn' : 'neutral'}
        />
        <Stat label="retries" value={String(agg.retry_count)} tone={agg.retry_count > 0 ? 'warn' : 'neutral'} />
      </div>

      {backends.length > 0 && (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--paper-50)',
            border: '1px solid var(--alpha-ink-08)',
            fontSize: 11,
          }}
        >
          <div
            style={{
              color: 'var(--ink-600)',
              marginBottom: 6,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
            }}
          >
            memory backends · p50 / p95 / count
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: 8,
            }}
          >
            {backends.map((b) => (
              <div
                key={b}
                style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}
              >
                <span style={{ color: 'var(--ink-800)' }}>{b}</span>
                <span style={{ color: 'var(--ink-600)', fontVariantNumeric: 'tabular-nums' }}>
                  {fmtMs(agg.memory_backend_p50_ms[b])} / {fmtMs(agg.memory_backend_p95_ms[b])} /{' '}
                  {agg.memory_backend_count[b]}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function IssuesPanel({
  agg,
  active,
  onSelect,
}: {
  agg: Aggregate;
  active: 'all' | 'issues' | IssueTag;
  onSelect: (next: 'all' | 'issues' | IssueTag) => void;
}) {
  const total = (Object.values(agg.issue_counts) as number[]).reduce((a, b) => a + b, 0);
  if (total === 0 && agg.hook_deny_orphan_count === 0) {
    return (
      <div
        style={{
          padding: '10px 12px',
          background: 'var(--moss-100)',
          color: 'var(--moss-700)',
          border: '1px solid var(--alpha-ink-08)',
          fontSize: 12,
          marginBottom: 12,
        }}
      >
        no issues in the visible turns. ✓
      </div>
    );
  }

  const tags: IssueTag[] = [
    'runtime_error',
    'result_error',
    'silent_exit',
    'runaway',
    'expensive',
    'slow',
    'hook_blocked',
  ];

  return (
    <div
      style={{
        padding: '12px',
        background: 'var(--paper-50)',
        border: '1px solid var(--alpha-ink-08)',
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 8,
        }}
      >
        <div
          style={{
            fontSize: 11,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--ink-600)',
          }}
        >
          issues — what&apos;s going wrong
        </div>
        {agg.hook_deny_orphan_count > 0 && (
          <div style={{ fontSize: 11, color: 'var(--amber-700)' }}>
            {agg.hook_deny_orphan_count} hook.deny event{agg.hook_deny_orphan_count === 1 ? '' : 's'} could not be tied to any turn (turn_id missing in tracer).
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {tags.map((tag) => {
          const count = agg.issue_counts[tag] ?? 0;
          if (count === 0) return null;
          const tone = ISSUE_TONES[tag];
          const colors = toneColor(tone);
          const isActive = active === tag;
          return (
            <button
              key={tag}
              onClick={() => onSelect(isActive ? 'all' : tag)}
              style={{
                padding: '6px 10px',
                background: isActive ? colors.fg : colors.bg,
                color: isActive ? colors.bg : colors.fg,
                border: `1px solid ${colors.fg}`,
                fontSize: 11,
                cursor: 'pointer',
                fontFamily: 'inherit',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {ISSUE_LABELS[tag]} · {count}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StatePanel({
  userFilter,
  snapshot,
  error,
}: {
  userFilter: string | null;
  snapshot: StateSnapshot | null;
  error: string | null;
}) {
  if (!userFilter) {
    return (
      <div
        style={{
          padding: 12,
          marginTop: 12,
          fontSize: 11,
          color: 'var(--ink-500)',
          border: '1px solid var(--alpha-ink-08)',
          borderRadius: 2,
        }}
      >
        pick a user above to inspect their state (attentions, instances,
        schedules, observations, open loops, recent chat).
      </div>
    );
  }
  if (error) {
    return (
      <div
        style={{
          padding: 12,
          marginTop: 12,
          background: 'var(--oxblood-100)',
          color: 'var(--oxblood-700)',
          fontSize: 11,
        }}
      >
        state error: {error}
      </div>
    );
  }
  if (!snapshot || !snapshot.user) {
    return (
      <div
        style={{
          padding: 12,
          marginTop: 12,
          fontSize: 11,
          color: 'var(--ink-500)',
          border: '1px solid var(--alpha-ink-08)',
        }}
      >
        loading state for {userFilter}…
      </div>
    );
  }

  const u = snapshot.user;
  const profile = u.living_profile ?? {};
  const narrative = profile.narrative ?? profile.current_situation ?? '';
  const attentions = snapshot.attentions ?? [];
  const instances = snapshot.instances ?? [];
  const schedules = snapshot.schedules ?? [];
  const observations = snapshot.observations ?? [];
  const openLoops = snapshot.open_loops ?? [];
  const chat = snapshot.chat ?? [];

  // Group attentions by status for the section.
  const byStatus: Record<string, StateAttention[]> = {};
  for (const a of attentions) {
    (byStatus[a.status] = byStatus[a.status] ?? []).push(a);
  }
  const statusOrder = [
    'live', 'offered', 'shadow', 'spec_drafted', 'dry_run_pending',
    'paused', 'rejected', 'resolved', 'expired', 'quietly_archived',
  ];
  const orderedStatuses = [
    ...statusOrder.filter((s) => byStatus[s]?.length),
    ...Object.keys(byStatus).filter((s) => !statusOrder.includes(s)),
  ];

  return (
    <div
      style={{
        marginTop: 12,
        border: '1px solid var(--alpha-ink-08)',
        borderRadius: 2,
        padding: 14,
        background: 'var(--paper-50, transparent)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 12,
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              textTransform: 'uppercase',
              letterSpacing: '0.14em',
              color: 'var(--ink-600)',
              marginBottom: 4,
            }}
          >
            user state
          </div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {u.name ?? '(no name)'}{' '}
            <span
              style={{
                fontSize: 11,
                color: 'var(--ink-500)',
                fontWeight: 400,
              }}
            >
              · {u.timezone ?? 'no tz'} · {u.phone ?? 'no phone'}
            </span>
          </div>
          <div
            style={{
              fontSize: 10,
              color: 'var(--ink-500)',
              fontFamily: 'monospace',
              marginTop: 2,
            }}
          >
            {u.id} · last_active {u.last_active_at ?? '—'}
          </div>
        </div>
        {snapshot.fetched_at && (
          <div style={{ fontSize: 10, color: 'var(--ink-500)' }}>
            fetched {fmtTime(snapshot.fetched_at)}
          </div>
        )}
      </div>

      {narrative && (
        <StateSection title="living profile">
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.5,
              color: 'var(--ink-800)',
              marginBottom: 4,
            }}
          >
            {narrative}
          </div>
          <div style={{ fontSize: 10, color: 'var(--ink-500)' }}>
            generated {profile.generated_at ?? '—'} · morning refresh{' '}
            {profile.yesterday_refreshed_at ?? '—'}
          </div>
        </StateSection>
      )}

      <StateSection title={`attentions (${attentions.length})`}>
        {attentions.length === 0 && <StateEmpty />}
        {orderedStatuses.map((status) => {
          const bucket = byStatus[status] ?? [];
          if (bucket.length === 0) return null;
          return (
            <div key={status} style={{ marginBottom: 10 }}>
              <div
                style={{
                  fontSize: 10,
                  textTransform: 'uppercase',
                  letterSpacing: '0.1em',
                  color: status === 'live'
                    ? 'var(--moss-700, var(--ink-800))'
                    : status === 'offered'
                      ? 'var(--amber-700, var(--ink-800))'
                      : 'var(--ink-600)',
                  marginBottom: 4,
                }}
              >
                {status} · {bucket.length}
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '120px 90px 1fr 110px 130px',
                  rowGap: 3,
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: 'var(--ink-700)',
                }}
              >
                {bucket.map((a) => (
                  <StateAttentionRow key={a.id} a={a} />
                ))}
              </div>
            </div>
          );
        })}
      </StateSection>

      <StateSection title={`instances (${instances.length})`}>
        {instances.length === 0 && <StateEmpty />}
        {instances.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '120px 90px 130px 1fr 80px 120px',
              rowGap: 3,
              fontSize: 11,
              fontFamily: 'monospace',
            }}
          >
            <StateGridHeader cols={['id', 'primitive', 'connector', 'label', 'status', 'last used']} />
            {instances.map((r) => (
              <>
                <StateMono key={`${r.id}-id`} value={r.id} truncate={8} />
                <StateMono key={`${r.id}-prim`} value={r.primitive} />
                <StateMono key={`${r.id}-conn`} value={r.connector} />
                <StateMono key={`${r.id}-label`} value={r.label} />
                <StateMono key={`${r.id}-status`} value={r.status} />
                <StateMono key={`${r.id}-used`} value={r.last_used_at ?? '—'} />
              </>
            ))}
          </div>
        )}
      </StateSection>

      <StateSection title={`schedules (${schedules.length})`}>
        {schedules.length === 0 && <StateEmpty />}
        {schedules.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '90px 130px 90px 80px 80px 1fr',
              rowGap: 3,
              fontSize: 11,
              fontFamily: 'monospace',
            }}
          >
            <StateGridHeader cols={['id', 'fire_at', 'status', 'origin', 'fired', 'attention']} />
            {schedules.map((r) => (
              <>
                <StateMono key={`${r.id}-id`} value={r.id} truncate={8} />
                <StateMono key={`${r.id}-fa`} value={r.fire_at ?? '—'} />
                <StateMono key={`${r.id}-st`} value={r.status} />
                <StateMono key={`${r.id}-or`} value={r.origin} />
                <StateMono key={`${r.id}-fd`} value={r.fired ? '✓' : '—'} />
                <StateMono key={`${r.id}-at`} value={r.attention_id ? r.attention_id.slice(0, 8) : '—'} />
              </>
            ))}
          </div>
        )}
      </StateSection>

      <StateSection title={`observations (${observations.length})`}>
        {observations.length === 0 && <StateEmpty />}
        {observations.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '160px 130px 1fr',
              rowGap: 3,
              fontSize: 11,
              fontFamily: 'monospace',
            }}
          >
            <StateGridHeader cols={['event_time', 'type', 'fields']} />
            {observations.map((r) => {
              const fieldStr = Object.entries(r.fields ?? {})
                .slice(0, 4)
                .map(([k, v]) => `${k}=${String(v).slice(0, 40)}`)
                .join(', ') || '—';
              return (
                <>
                  <StateMono key={`${r.id}-t`} value={r.event_time ?? '—'} />
                  <StateMono key={`${r.id}-ty`} value={r.type} />
                  <StateMono key={`${r.id}-f`} value={fieldStr} />
                </>
              );
            })}
          </div>
        )}
      </StateSection>

      <StateSection title={`open loops (${openLoops.length})`}>
        {openLoops.length === 0 && <StateEmpty />}
        {openLoops.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {openLoops.map((r) => (
              <div
                key={r.id}
                style={{
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: 'var(--ink-700)',
                }}
              >
                <span style={{ color: 'var(--ink-500)' }}>
                  [{r.created_at ?? '—'}]
                </span>{' '}
                {r.content}
              </div>
            ))}
          </div>
        )}
      </StateSection>

      <StateSection title={`recent chat (${chat.length})`}>
        {chat.length === 0 && <StateEmpty />}
        {chat.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {chat.map((m, i) => (
              <div
                key={i}
                style={{
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: 'var(--ink-700)',
                }}
              >
                <span style={{ color: 'var(--ink-500)' }}>
                  [{m.created_at ?? '—'}]
                </span>{' '}
                <span
                  style={{
                    fontWeight: m.role === 'user' ? 600 : 400,
                    color: m.role === 'assistant'
                      ? 'var(--ink-700)'
                      : 'var(--ink-900)',
                  }}
                >
                  {m.role}
                  {m.is_proactive ? '*' : ''}:
                </span>{' '}
                {m.content}
              </div>
            ))}
          </div>
        )}
      </StateSection>
    </div>
  );
}

function StateSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: '0.12em',
          color: 'var(--ink-600)',
          marginBottom: 6,
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function StateEmpty() {
  return (
    <div style={{ fontSize: 11, color: 'var(--ink-500)' }}>(none)</div>
  );
}

function StateGridHeader({ cols }: { cols: string[] }) {
  return (
    <>
      {cols.map((c) => (
        <div
          key={c}
          style={{
            fontSize: 10,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--ink-500)',
            paddingBottom: 2,
            borderBottom: '1px solid var(--alpha-ink-08)',
          }}
        >
          {c}
        </div>
      ))}
    </>
  );
}

function StateMono({ value, truncate }: { value: string; truncate?: number }) {
  const text = truncate && value.length > truncate ? value.slice(0, truncate) : value;
  return (
    <div
      style={{
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        color: 'var(--ink-800)',
      }}
      title={value}
    >
      {text}
    </div>
  );
}

function StateAttentionRow({ a }: { a: StateAttention }) {
  return (
    <>
      <StateMono value={a.id.slice(0, 8)} />
      <StateMono value={a.card} />
      <StateMono value={a.title} />
      <StateMono value={`subj=${a.subject ?? '—'}`} />
      <StateMono value={`upd=${a.last_update_at ?? '—'}`} />
    </>
  );
}

function FilterBar({
  filter,
  userFilter,
  userOptions,
  onFilter,
  onUserFilter,
  visibleCount,
  totalCount,
}: {
  filter: 'all' | 'issues' | IssueTag;
  userFilter: string | null;
  userOptions: string[];
  onFilter: (next: 'all' | 'issues' | IssueTag) => void;
  onUserFilter: (next: string | null) => void;
  visibleCount: number;
  totalCount: number;
}) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        padding: '8px 0',
        flexWrap: 'wrap',
        borderTop: '1px solid var(--alpha-ink-08)',
      }}
    >
      <span
        style={{
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: '0.12em',
          color: 'var(--ink-600)',
        }}
      >
        filter
      </span>
      {(['all', 'issues'] as const).map((v) => (
        <button
          key={v}
          onClick={() => onFilter(v)}
          style={{
            padding: '4px 10px',
            background: filter === v ? 'var(--ink-900)' : 'transparent',
            color: filter === v ? 'var(--paper-50)' : 'var(--ink-800)',
            border: '1px solid var(--alpha-ink-14)',
            fontSize: 11,
            cursor: 'pointer',
          }}
        >
          {v}
        </button>
      ))}
      {userOptions.length > 0 && (
        <>
          <span style={{ color: 'var(--ink-400)' }}>·</span>
          <span
            style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--ink-600)',
            }}
          >
            user
          </span>
          <select
            value={userFilter ?? ''}
            onChange={(e) => onUserFilter(e.target.value || null)}
            style={{
              padding: '4px 8px',
              background: 'var(--paper-50)',
              color: 'var(--ink-900)',
              border: '1px solid var(--alpha-ink-14)',
              fontSize: 11,
              fontFamily: 'inherit',
              cursor: 'pointer',
            }}
          >
            <option value="">all</option>
            {userOptions.map((uid) => (
              <option key={uid} value={uid}>
                {shortUser(uid)}
              </option>
            ))}
          </select>
        </>
      )}
      <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-500)' }}>
        showing {visibleCount} of {totalCount}
      </span>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'ok' | 'warn' | 'neutral';
}) {
  const bg = tone === 'warn' ? 'var(--amber-100)' : tone === 'ok' ? 'var(--moss-100)' : 'var(--paper-50)';
  const fg = tone === 'warn' ? 'var(--amber-700)' : tone === 'ok' ? 'var(--moss-700)' : 'var(--ink-900)';
  return (
    <div
      style={{
        padding: '10px 12px',
        background: bg,
        border: '1px solid var(--alpha-ink-08)',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        minWidth: 0,
      }}
    >
      <span
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: '0.12em',
          color: 'var(--ink-600)',
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: fg,
          fontVariantNumeric: 'tabular-nums',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </span>
    </div>
  );
}

function IssuePill({ tag }: { tag: IssueTag }) {
  const tone = ISSUE_TONES[tag];
  const colors = toneColor(tone);
  return (
    <span
      style={{
        background: colors.bg,
        color: colors.fg,
        padding: '1px 6px',
        fontSize: 10,
        letterSpacing: '0.04em',
        borderRadius: 2,
        fontWeight: 500,
      }}
    >
      {ISSUE_LABELS[tag]}
    </span>
  );
}

function ToolChain({ tools }: { tools: string[] }) {
  if (tools.length === 0) {
    return <span style={{ color: 'var(--ink-400)', fontSize: 10 }}>(no tools)</span>;
  }
  // Compact display — show full chain on hover via title attribute.
  const display = tools.length > 4 ? [...tools.slice(0, 3), `+${tools.length - 3}`] : tools;
  return (
    <span
      title={tools.join(' → ')}
      style={{
        display: 'inline-flex',
        gap: 4,
        alignItems: 'center',
        fontSize: 10,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        color: 'var(--ink-600)',
      }}
    >
      {display.map((t, i) => (
        <span key={i}>
          {i > 0 && <span style={{ color: 'var(--ink-400)' }}> › </span>}
          <span style={{ color: t === 'send_burst' ? 'var(--moss-700)' : 'var(--ink-800)' }}>{t}</span>
        </span>
      ))}
    </span>
  );
}

function TurnRow({ turn, selected, onClick }: { turn: Turn; selected: boolean; onClick: () => void }) {
  const isError = turn.issues.includes('runtime_error') || turn.issues.includes('result_error');
  const isSilent = turn.issues.includes('silent_exit');
  const toneBg = selected
    ? 'var(--rust-100)'
    : isError
      ? 'var(--oxblood-100)'
      : isSilent
        ? 'var(--amber-100)'
        : 'var(--paper-50)';

  return (
    <button
      onClick={onClick}
      style={{
        textAlign: 'left',
        display: 'grid',
        gridTemplateColumns: '70px minmax(0, 1.6fr) minmax(0, 1.4fr) 80px',
        gap: 10,
        padding: '10px 12px',
        background: toneBg,
        border: '1px solid var(--alpha-ink-08)',
        cursor: 'pointer',
        fontSize: 12,
        color: 'var(--ink-900)',
      }}
    >
      <span style={{ color: 'var(--ink-600)', fontVariantNumeric: 'tabular-nums' }}>
        {fmtTime(turn.started_at)}
      </span>
      <span
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          minWidth: 0,
        }}
      >
        <span
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {turn.user_message_preview ?? <em style={{ color: 'var(--ink-500)' }}>(no preview)</em>}
        </span>
        <ToolChain tools={turn.tool_chain} />
      </span>
      <span style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center', minWidth: 0 }}>
        {turn.issues.map((tag) => (
          <IssuePill key={tag} tag={tag} />
        ))}
        {turn.user_id && (
          <span
            style={{
              fontSize: 10,
              color: 'var(--ink-500)',
              fontFamily: 'ui-monospace, SFMono-Regular, monospace',
            }}
          >
            {shortUser(turn.user_id)}
          </span>
        )}
      </span>
      <span
        style={{
          color: 'var(--ink-600)',
          fontVariantNumeric: 'tabular-nums',
          textAlign: 'right',
          fontSize: 11,
        }}
      >
        <div>{fmtMs(turn.duration_ms)}</div>
        <div>{fmtCost(turn.total_cost_usd)}</div>
      </span>
    </button>
  );
}

function TurnDetail({ turn }: { turn: Turn }) {
  const start = new Date(turn.started_at).getTime();
  const burstCall = turn.tool_calls.find((c) => c.short === 'send_burst');

  return (
    <div
      style={{
        padding: 12,
        background: 'var(--paper-50)',
        border: '1px solid var(--alpha-ink-08)',
        fontSize: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 10,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--ink-600)',
            }}
          >
            turn {turn.turn_id} · {shortUser(turn.user_id)}
          </div>
          <div style={{ marginTop: 6 }}>
            <ToolChain tools={turn.tool_chain} />
          </div>
        </div>
        <div
          style={{
            color: 'var(--ink-600)',
            fontVariantNumeric: 'tabular-nums',
            textAlign: 'right',
            fontSize: 11,
          }}
        >
          <div>{fmtMs(turn.duration_ms)} · {fmtCost(turn.total_cost_usd)}</div>
          <div>
            {turn.tool_chain.length} tool{turn.tool_chain.length === 1 ? '' : 's'} ·{' '}
            {turn.model ?? ''}
          </div>
        </div>
      </div>

      {turn.issues.length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {turn.issues.map((tag) => (
            <IssuePill key={tag} tag={tag} />
          ))}
        </div>
      )}

      {turn.runtime_error && (
        <div
          style={{
            padding: 10,
            background: 'var(--oxblood-100)',
            color: 'var(--oxblood-700)',
            fontSize: 12,
            fontFamily: 'ui-monospace, SFMono-Regular, monospace',
          }}
        >
          runtime_error: {turn.runtime_error}
        </div>
      )}

      <Conversation
        userMessage={turn.user_message_preview}
        donnaMessages={burstCall?.send_burst_messages ?? null}
        burstCaptured={Boolean(burstCall && burstCall.input_preview_present)}
      />

      {turn.hook_denies.length > 0 && <HookDeniesPanel denies={turn.hook_denies} />}

      <PromptSnapshotPanel snapshot={turn.prompt_snapshot} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div
          style={{
            fontSize: 10,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--ink-600)',
            marginBottom: 4,
          }}
        >
          event timeline
        </div>
        {turn.events.map((ev, idx) => (
          <EventRow key={idx} ev={ev} offsetMs={new Date(ev.ts).getTime() - start} />
        ))}
      </div>
    </div>
  );
}

function Conversation({
  userMessage,
  donnaMessages,
  burstCaptured,
}: {
  userMessage: string | null;
  donnaMessages: unknown;
  burstCaptured: boolean;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div
        style={{
          padding: 10,
          background: 'var(--paper-100)',
          border: '1px solid var(--alpha-ink-08)',
        }}
      >
        <div
          style={{
            fontSize: 10,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--ink-600)',
            marginBottom: 4,
          }}
        >
          user said
        </div>
        <div
          style={{
            fontSize: 13,
            color: 'var(--ink-900)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {userMessage ?? <em style={{ color: 'var(--ink-500)' }}>(no preview captured)</em>}
        </div>
      </div>
      <div
        style={{
          padding: 10,
          background: 'var(--moss-100)',
          border: '1px solid var(--alpha-ink-08)',
        }}
      >
        <div
          style={{
            fontSize: 10,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--moss-700)',
            marginBottom: 4,
          }}
        >
          donna said
        </div>
        <DonnaMessages messages={donnaMessages} burstCaptured={burstCaptured} />
      </div>
    </div>
  );
}

function DonnaMessages({
  messages,
  burstCaptured,
}: {
  messages: unknown;
  burstCaptured: boolean;
}) {
  if (!burstCaptured || !Array.isArray(messages) || messages.length === 0) {
    return (
      <div style={{ fontSize: 12, color: 'var(--ink-500)' }}>
        <em>(send_burst payload not captured by tracer — fix in donna_runtime/observability.py)</em>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {messages.map((m, i) => (
        <RenderedBubble key={i} m={m} />
      ))}
    </div>
  );
}

function RenderedBubble({ m }: { m: unknown }) {
  if (typeof m === 'string') {
    return <div style={{ fontSize: 13, color: 'var(--ink-900)', whiteSpace: 'pre-wrap' }}>{m}</div>;
  }
  if (!m || typeof m !== 'object') return null;
  const obj = m as Record<string, unknown>;
  const type = (obj.type as string) ?? 'text';
  const body = (obj.body as string) ?? (obj.caption as string) ?? '';
  if (type === 'delay') {
    return (
      <div style={{ fontSize: 11, color: 'var(--ink-500)', fontStyle: 'italic' }}>
        ⏱ delay {(obj.seconds as number)?.toFixed?.(1) ?? '?'}s
      </div>
    );
  }
  if (type === 'image') {
    return (
      <div style={{ fontSize: 12, color: 'var(--ink-800)' }}>
        🖼 image{obj.url ? ` (${(obj.url as string).slice(0, 50)}…)` : ''}
        {body && <div style={{ marginTop: 2, fontSize: 12 }}>{body}</div>}
      </div>
    );
  }
  if (type === 'voice_response') {
    return (
      <div style={{ fontSize: 11, color: 'var(--ink-500)', fontStyle: 'italic' }}>
        🎤 voice response (synth from text bodies below)
      </div>
    );
  }
  if (type === 'cta' || type === 'cta_url') {
    return (
      <div>
        <div style={{ fontSize: 13, color: 'var(--ink-900)', whiteSpace: 'pre-wrap' }}>{body}</div>
        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--rust-700)' }}>
          [{(obj.display_text as string) ?? ((obj.buttons as unknown[])?.length ?? 0) + ' buttons'}
          {obj.url ? ` → ${(obj.url as string).slice(0, 50)}…` : ''}]
        </div>
      </div>
    );
  }
  return (
    <div style={{ fontSize: 13, color: 'var(--ink-900)', whiteSpace: 'pre-wrap' }}>
      {body || <em style={{ color: 'var(--ink-500)' }}>({type})</em>}
    </div>
  );
}

function HookDeniesPanel({ denies }: { denies: RawEvent[] }) {
  return (
    <div
      style={{
        padding: 10,
        background: 'var(--amber-100)',
        border: '1px solid var(--amber-700)',
      }}
    >
      <div
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: '0.12em',
          color: 'var(--amber-700)',
          marginBottom: 6,
        }}
      >
        hook denies in this turn ({denies.length})
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {denies.map((d, i) => (
          <div
            key={i}
            style={{
              fontSize: 11,
              fontFamily: 'ui-monospace, SFMono-Regular, monospace',
              color: 'var(--amber-700)',
            }}
          >
            <strong>{(d.tool as string) ?? '?'}</strong> · {(d.decision_kind as string) ?? '?'} ·{' '}
            {(d.reason as string) ?? ''}
          </div>
        ))}
      </div>
    </div>
  );
}

function PromptSnapshotPanel({ snapshot }: { snapshot: PromptSnapshot | null }) {
  if (!snapshot) {
    return (
      <div
        style={{
          padding: 8,
          background: 'var(--paper-100)',
          border: '1px dashed var(--alpha-ink-14)',
          color: 'var(--ink-500)',
          fontSize: 11,
        }}
      >
        no prompt snapshot for this turn.
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: 6,
        }}
      >
        <MiniStat label="system" value={fmtChars(snapshot.system_prompt_len)} />
        <MiniStat label="user prompt" value={fmtChars(snapshot.wrapped_user_prompt_len)} />
        <MiniStat label="tool mode" value={snapshot.tool_mode ?? '—'} />
        <MiniStat
          label="max turns"
          value={snapshot.max_turns === null ? '—' : String(snapshot.max_turns)}
        />
      </div>

      <PromptDetails title="exact system prompt" text={snapshot.system_prompt} defaultOpen={false} />
      <PromptDetails title="exact wrapped user prompt" text={snapshot.wrapped_user_prompt} defaultOpen />
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: 'var(--paper-100)', border: '1px solid var(--alpha-ink-08)', padding: '7px 8px' }}>
      <div
        style={{
          fontSize: 9,
          textTransform: 'uppercase',
          letterSpacing: '0.12em',
          color: 'var(--ink-500)',
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: 2,
          fontSize: 11,
          color: 'var(--ink-800)',
          fontVariantNumeric: 'tabular-nums',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function PromptDetails({
  title,
  text,
  defaultOpen = false,
}: {
  title: string;
  text: string;
  defaultOpen?: boolean;
}) {
  return (
    <details
      open={defaultOpen}
      style={{
        background: 'var(--paper-100)',
        border: '1px solid var(--alpha-ink-08)',
      }}
    >
      <summary
        style={{
          cursor: 'pointer',
          padding: '8px 10px',
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: '0.12em',
          color: 'var(--ink-800)',
          userSelect: 'none',
        }}
      >
        {title}
      </summary>
      <pre
        style={{
          margin: 0,
          padding: '10px',
          maxHeight: 360,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          overflowWrap: 'anywhere',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
          fontSize: 11,
          lineHeight: 1.45,
          color: 'var(--ink-800)',
          background: 'var(--paper-50)',
          borderTop: '1px solid var(--alpha-ink-08)',
        }}
      >
        {text || '(empty)'}
      </pre>
    </details>
  );
}

function EventRow({ ev, offsetMs }: { ev: RawEvent; offsetMs: number }) {
  const { event } = ev;
  const label = eventLabel(ev);
  const detail = eventDetail(ev);
  const tone = toneForEvent(event);
  const drilldown = eventDrilldown(ev);

  return (
    <details
      style={{
        borderLeft: `2px solid ${tone}`,
        background: 'var(--paper-100)',
        fontSize: 11,
      }}
    >
      <summary
        style={{
          display: 'grid',
          gridTemplateColumns: '70px 110px minmax(0, 1fr)',
          gap: 8,
          padding: '4px 8px',
          cursor: drilldown ? 'pointer' : 'default',
          listStyle: 'none',
        }}
      >
        <span style={{ color: 'var(--ink-500)', fontVariantNumeric: 'tabular-nums' }}>
          +{fmtMs(offsetMs)}
        </span>
        <span style={{ color: 'var(--ink-800)', fontWeight: 500 }}>{label}</span>
        <span
          style={{
            color: 'var(--ink-600)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {detail}
        </span>
      </summary>
      {drilldown && (
        <pre
          style={{
            margin: 0,
            padding: '8px 10px 10px 188px',
            maxHeight: 280,
            overflow: 'auto',
            whiteSpace: 'pre-wrap',
            overflowWrap: 'anywhere',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            fontSize: 10,
            lineHeight: 1.45,
            color: 'var(--ink-800)',
            background: 'var(--paper-50)',
            borderTop: '1px solid var(--alpha-ink-08)',
          }}
        >
          {drilldown}
        </pre>
      )}
    </details>
  );
}

function shortToolName(name: string | null | undefined): string {
  if (!name) return '';
  return name.split('__').slice(-1)[0];
}

function eventLabel(ev: RawEvent): string {
  if (ev.event === 'tool.call') return `tool · ${shortToolName(ev.tool as string)}`;
  if (ev.event === 'memory.op') return `mem · ${ev.backend as string}`;
  if (ev.event === 'prompt.snapshot') return 'prompt';
  return ev.event;
}

function eventDetail(ev: RawEvent): string {
  if (ev.event === 'tool.call') {
    const keys = (ev.input_keys as string[]) ?? [];
    return keys.length ? `keys: ${keys.join(', ')}` : '';
  }
  if (ev.event === 'memory.op') {
    const dur = fmtMs(ev.duration_ms as number);
    const ok = ev.ok === false ? '·fail' : '';
    return `${ev.op}${ok} · ${dur}`;
  }
  if (ev.event === 'turn.start') {
    return `model=${ev.model ?? '—'} resume=${ev.resume_session_id ? 'yes' : 'no'}`;
  }
  if (ev.event === 'prompt.snapshot') {
    return `system ${fmtChars(ev.system_prompt_len as number)} · user ${fmtChars(ev.wrapped_user_prompt_len as number)}`;
  }
  if (ev.event === 'turn.end') {
    const terminal = ev.terminal_tool ?? 'none';
    return `terminal=${terminal} turns=${ev.num_turns}`;
  }
  if (ev.event === 'hook.deny') {
    return `${ev.decision_kind} · ${ev.tool}`;
  }
  if (ev.event === 'retry.fired') {
    return `${ev.kind} · ${ev.source}`;
  }
  if (ev.event === 'error') {
    return `${ev.where}: ${ev.error}`;
  }
  return '';
}

function eventDrilldown(ev: RawEvent): string {
  if (ev.event === 'tool.call') {
    return JSON.stringify(
      {
        tool: ev.tool,
        input_keys: ev.input_keys,
        input: ev.input_preview,
      },
      null,
      2,
    );
  }
  if (ev.event === 'memory.op') {
    return JSON.stringify(
      {
        backend: ev.backend,
        op: ev.op,
        args: ev.args_preview ?? ev.args,
        result: ev.result_preview ?? ev.result,
        duration_ms: ev.duration_ms,
        ok: ev.ok,
      },
      null,
      2,
    );
  }
  if (ev.event === 'prompt.snapshot') {
    return JSON.stringify(
      {
        system_prompt_len: ev.system_prompt_len,
        wrapped_user_prompt_len: ev.wrapped_user_prompt_len,
        model: ev.model,
        tool_mode: ev.tool_mode,
        max_turns: ev.max_turns,
      },
      null,
      2,
    );
  }
  if (ev.event === 'error' || ev.event === 'hook.deny' || ev.event === 'retry.fired') {
    return JSON.stringify(ev, null, 2);
  }
  return '';
}

function toneForEvent(event: string): string {
  if (event === 'turn.start' || event === 'turn.end') return 'var(--ink-400)';
  if (event === 'prompt.snapshot') return 'var(--rust-700)';
  if (event === 'tool.call') return 'var(--rust-500)';
  if (event === 'memory.op') return 'var(--moss-700)';
  if (event === 'hook.deny') return 'var(--amber-700)';
  if (event === 'retry.fired') return 'var(--amber-700)';
  if (event === 'error') return 'var(--oxblood-700)';
  return 'var(--ink-300)';
}
