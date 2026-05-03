'use client';

/**
 * Internal observability dashboard for the attention runtime.
 *
 * Reachable at /observe/attention on the INTERNAL host (Basic-auth gated
 * by edge middleware). Pulls /api/admin/attention/observe and renders
 * four parallel sections so a developer can see the runtime in motion:
 *
 *   1. attentions table — every live/paused row with current_state
 *   2. ticks feed — append-only audit history (what evaluated, what fired)
 *   3. proactive messages — what Donna decided to say (shadow + live)
 *   4. pending schedule — DonnaSchedule rows about to fire
 *
 * Auto-refreshes every 5s. Toggle to pause. Filter by user_id.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

interface AttentionSummary {
  id: string;
  id_short: string | null;
  user_id: string;
  user_id_short: string | null;
  card: string | null;
  status: string | null;
  title: string | null;
  subject: string | null;
  cadence_type: string | null;
  cadence_params: Record<string, unknown> | null;
  value: string | null;
  value_numeric: number | null;
  target: number | null;
  progress: number | null;
  count: number | null;
  last_event_at: string | null;
  day: string | null;
  rollup: string | null;
  evidence_ids: string[];
  escalations_n: number;
  nudge_silent_for: number | null;
  poller_cursors: Record<string, unknown>;
  last_update_at: string | null;
  last_surfaced_at: string | null;
  created_at: string | null;
  current_state: Record<string, unknown>;
}

interface TickRow {
  id: string;
  attention_id: string;
  attention_id_short: string | null;
  at: string | null;
  rendered_markdown: string | null;
  warnings: unknown[];
  source_counts: Record<string, unknown>;
}

interface ProactiveMsg {
  id: string;
  user_id: string;
  user_id_short: string | null;
  role: string;
  content: string;
  is_shadow: boolean;
  wa_message_id: string | null;
  created_at: string | null;
}

interface ScheduleRow {
  id: string;
  id_short: string | null;
  user_id: string;
  user_id_short: string | null;
  phone: string;
  fire_at: string | null;
  origin: string;
  recurrence: string | null;
  context: Record<string, unknown>;
  attention_id: string | null;
  attention_id_short: string | null;
  attempts: number;
  last_error: string | null;
  created_at: string | null;
}

interface IntegrationLocalRow {
  provider: string | null;
  product: string | null;
  status: string | null;
  composio_connection_id: string | null;
  connected_at: string | null;
  last_synced_at: string | null;
  redirect_url: string | null;
  redirect_url_issued_at: string | null;
  last_error: string | null;
  updated_at: string | null;
}
interface IntegrationComposioRow {
  id: string | null;
  status: string | null;
  toolkit: string | null;
  created_at: string | null;
  error?: string;
}
interface IntegrationsResponse {
  local: IntegrationLocalRow[];
  composio: IntegrationComposioRow[];
}

interface ProactiveTrace {
  message: {
    id: string;
    user_id: string;
    role: string;
    content: string;
    is_proactive: boolean;
    is_shadow: boolean;
    wa_message_id: string | null;
    created_at: string | null;
  };
  window_seconds: number;
  probable_source: string;
  confidence: number;
  rationale: string[];
  siblings: {
    id: string;
    content: string;
    is_shadow: boolean;
    created_at: string | null;
    self: boolean;
  }[];
  proactive_pings: {
    id: string;
    source: string;
    topic_key: string | null;
    message_ref: string | null;
    suppressed_reason: string | null;
    fired_at: string | null;
  }[];
  schedule_fired: {
    id: string;
    fire_at: string | null;
    fired_at: string | null;
    origin: string;
    attention_id: string | null;
    context: Record<string, unknown>;
    last_error: string | null;
  }[];
  signals: {
    id: string;
    intent_key: string | null;
    subscription_id: string | null;
    arrived_at: string | null;
    consumed_at: string | null;
    title: string;
    url: string;
    highlights: string[];
  }[];
  subscriptions: {
    id: string;
    intent_key: string;
    description: string | null;
    webset_id: string | null;
    monitor_id: string | null;
    cadence: string | null;
    active: boolean;
    created_at: string | null;
    last_refreshed_at: string | null;
    last_hit_at: string | null;
  }[];
  attentions: {
    id: string;
    card: string | null;
    status: string | null;
    title: string | null;
    last_surfaced_at: string | null;
    current_state: Record<string, unknown>;
  }[];
  turns: {
    turn_id: string;
    started_at: string | null;
    ended_at: string | null;
    mode: string | null;
    tools: { ts: string | null; tool: string | null; short: string | null; input_keys: string[] }[];
    in_tokens: number | null;
    out_tokens: number | null;
    cache_read: number | null;
    cache_creation: number | null;
    cost_usd: number | null;
    model: string | null;
    errors: { ts: string | null; msg: string }[];
    prompt_snapshot: { system_len: number | null; user_len: number | null; model: string | null; tool_mode: string | null } | null;
  }[];
  now: string | null;
}

interface ChatRow {
  id: string;
  role: string;
  content: string;
  is_proactive: boolean;
  wa_message_id: string | null;
  created_at: string | null;
}

interface ComposeResult {
  attention_id: string;
  user_id: string;
  reused: boolean;
  authored_via: string;
  authored_confidence: number;
  spec: Record<string, unknown>;
  preview: {
    rendered_markdown: string | null;
    warnings: string[];
    source_previews: { source_type: string; item_count: number }[];
  };
}

interface WorkerStatus {
  name: string;
  last_at: string | null;
  since_seconds: number | null;
  recent_count: number;
}

interface UserOption {
  id: string;
  name: string | null;
  phone: string | null;
  timezone: string | null;
  last_active_at: string | null;
  chat_messages: number;
  emails: number;
}

interface ObserveResponse {
  filter: { user_id: string | null };
  counts: {
    attentions: number;
    ticks: number;
    proactive_messages: number;
    pending_schedule: number;
    by_card: Record<string, number>;
    by_status: Record<string, number>;
  };
  workers: WorkerStatus[];
  attentions: AttentionSummary[];
  ticks: TickRow[];
  proactive: ProactiveMsg[];
  schedule: ScheduleRow[];
  now: string | null;
}

// Expected max idle time (seconds) before a worker is flagged stale.
// Tuned to each worker's natural cadence; values past this turn the row red.
const WORKER_STALE_THRESHOLDS: Record<string, number> = {
  log_observation_hook: 60 * 60 * 24, // event-driven; idle is fine
  attention_sweep_worker: 60 * 75, // hourly + a 15-min grace
  attention_nudge_worker: 60 * 75,
  attention_schedule_materializer: 60 * 10, // 5-min cadence + grace
  schedule_worker: 60 * 5,
  manual_invocation: 60 * 60 * 24 * 30, // ad-hoc
};

const REFRESH_MS = 5000;

function fmtRelative(iso: string | null, now: Date): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '—';
  const deltaSec = Math.round((now.getTime() - t) / 1000);
  if (deltaSec < 0) return `in ${fmtAbsSec(-deltaSec)}`;
  return `${fmtAbsSec(deltaSec)} ago`;
}

function fmtAbsSec(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`;
  return `${Math.round(s / 86400)}d`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: string | null }) {
  const color =
    status === 'live'
      ? '#1f9d55'
      : status === 'shadow'
        ? '#9c8b3a'
        : status === 'paused'
          ? '#7a7a7a'
          : status === 'resolved'
            ? '#3a8ad6'
            : '#9a3a3a';
  return (
    <span
      style={{
        background: color,
        color: '#fff',
        padding: '1px 6px',
        borderRadius: 3,
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
      }}
    >
      {status || '?'}
    </span>
  );
}

function CardBadge({ card }: { card: string | null }) {
  return (
    <span
      style={{
        background: '#1a1a1a',
        color: '#e9e7e1',
        padding: '1px 6px',
        borderRadius: 3,
        fontSize: 10,
        fontFamily: 'ui-monospace, SFMono-Regular, monospace',
      }}
    >
      {card || '?'}
    </span>
  );
}

function ModeBadge({ shadow }: { shadow: boolean }) {
  return (
    <span
      style={{
        background: shadow ? '#5a5a5a' : '#1f9d55',
        color: '#fff',
        padding: '1px 5px',
        borderRadius: 3,
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
      }}
    >
      {shadow ? 'shadow' : 'live'}
    </span>
  );
}

export default function AttentionObservePage() {
  const [userQuery, setUserQuery] = useState('');
  const [appliedUserId, setAppliedUserId] = useState('');
  const [users, setUsers] = useState<UserOption[]>([]);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [data, setData] = useState<ObserveResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState<Date>(() => new Date());
  const [expandedAttention, setExpandedAttention] = useState<string | null>(null);
  const [chatRows, setChatRows] = useState<ChatRow[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);
  const [composeIntent, setComposeIntent] = useState('');
  const [composeAutoLive, setComposeAutoLive] = useState(true);
  const [composeRunning, setComposeRunning] = useState(false);
  const [composeResult, setComposeResult] = useState<ComposeResult | null>(null);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [busyAttentionId, setBusyAttentionId] = useState<string | null>(null);
  const [traceMessageId, setTraceMessageId] = useState<string | null>(null);
  const [traceData, setTraceData] = useState<ProactiveTrace | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const fetchSeq = useRef(0);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const r = await fetch('/api/admin/users?limit=200', { cache: 'no-store' });
        if (!r.ok) {
          if (alive) setUsersError(`HTTP ${r.status}`);
          return;
        }
        const json = (await r.json()) as { users?: UserOption[] };
        if (alive) setUsers(json.users || []);
      } catch (err) {
        if (alive) setUsersError(String(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const userById = useMemo(() => {
    const m = new Map<string, UserOption>();
    users.forEach((u) => m.set(u.id, u));
    return m;
  }, [users]);

  const selectedUser = appliedUserId ? userById.get(appliedUserId) ?? null : null;

  const filteredUsers = useMemo(() => {
    const q = userQuery.trim().toLowerCase();
    const sorted = [...users].sort((a, b) => {
      const ta = a.last_active_at ? Date.parse(a.last_active_at) : 0;
      const tb = b.last_active_at ? Date.parse(b.last_active_at) : 0;
      return tb - ta;
    });
    if (!q) return sorted.slice(0, 50);
    return sorted
      .filter((u) => {
        const hay = `${u.name || ''} ${u.phone || ''} ${u.id}`.toLowerCase();
        return hay.includes(q);
      })
      .slice(0, 50);
  }, [users, userQuery]);

  const fetchData = useCallback(async () => {
    const seq = ++fetchSeq.current;
    setLoading(true);
    setError(null);
    const qs = appliedUserId ? `?user_id=${encodeURIComponent(appliedUserId)}` : '';
    try {
      const r = await fetch(`/api/admin/attention/observe${qs}`, {
        cache: 'no-store',
      });
      if (!r.ok) {
        setError(`HTTP ${r.status}`);
        return;
      }
      const json = (await r.json()) as ObserveResponse;
      if (seq === fetchSeq.current) {
        setData(json);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      if (seq === fetchSeq.current) setLoading(false);
    }
  }, [appliedUserId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const fetchChat = useCallback(async () => {
    if (!appliedUserId) {
      setChatRows([]);
      return;
    }
    setChatLoading(true);
    setChatError(null);
    try {
      const r = await fetch(
        `/api/admin/${encodeURIComponent(appliedUserId)}/chat?limit=100`,
        { cache: 'no-store' },
      );
      if (!r.ok) {
        setChatError(`HTTP ${r.status}`);
        return;
      }
      const json = (await r.json()) as { messages?: ChatRow[] };
      setChatRows((json.messages || []).slice().reverse());
    } catch (err) {
      setChatError(String(err));
    } finally {
      setChatLoading(false);
    }
  }, [appliedUserId]);

  useEffect(() => {
    void fetchChat();
  }, [fetchChat]);

  useEffect(() => {
    if (!autoRefresh || !appliedUserId) return;
    const id = setInterval(() => void fetchChat(), REFRESH_MS);
    return () => clearInterval(id);
  }, [autoRefresh, appliedUserId, fetchChat]);

  const submitCompose = useCallback(async () => {
    if (!appliedUserId) {
      setComposeError('pick a user first');
      return;
    }
    if (!composeIntent.trim()) {
      setComposeError('intent required');
      return;
    }
    setComposeRunning(true);
    setComposeError(null);
    setComposeResult(null);
    try {
      const r = await fetch('/api/admin/attention/compose', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          user_id: appliedUserId,
          raw_intent: composeIntent.trim(),
          auto_live: composeAutoLive,
        }),
      });
      const json = await r.json();
      if (!r.ok) {
        setComposeError(json?.detail || `HTTP ${r.status}`);
        return;
      }
      setComposeResult(json as ComposeResult);
      void fetchData();
    } catch (err) {
      setComposeError(String(err));
    } finally {
      setComposeRunning(false);
    }
  }, [appliedUserId, composeIntent, composeAutoLive, fetchData]);

  const openTrace = useCallback(async (messageId: string) => {
    setTraceMessageId(messageId);
    setTraceData(null);
    setTraceError(null);
    setTraceLoading(true);
    try {
      const r = await fetch(
        `/api/admin/proactive/trace?message_id=${encodeURIComponent(messageId)}&window_seconds=600`,
        { cache: 'no-store' },
      );
      const json = await r.json();
      if (!r.ok) {
        setTraceError(json?.detail || `HTTP ${r.status}`);
        return;
      }
      setTraceData(json as ProactiveTrace);
    } catch (err) {
      setTraceError(String(err));
    } finally {
      setTraceLoading(false);
    }
  }, []);

  const closeTrace = useCallback(() => {
    setTraceMessageId(null);
    setTraceData(null);
    setTraceError(null);
  }, []);

  const updateAttentionStatus = useCallback(
    async (attentionId: string, status: string) => {
      setBusyAttentionId(attentionId);
      try {
        const r = await fetch(
          `/api/admin/attention/${encodeURIComponent(attentionId)}/status`,
          {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ status }),
          },
        );
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          alert(
            `update failed: ${j?.detail || `HTTP ${r.status}`} (id ${attentionId.slice(0, 8)})`,
          );
          return;
        }
        await fetchData();
      } catch (err) {
        alert(`update raised: ${err}`);
      } finally {
        setBusyAttentionId(null);
      }
    },
    [fetchData],
  );

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => void fetchData(), REFRESH_MS);
    return () => clearInterval(id);
  }, [autoRefresh, fetchData]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const pickUser = useCallback((id: string) => {
    setAppliedUserId(id);
    setPickerOpen(false);
    setUserQuery('');
  }, []);

  const clearUser = useCallback(() => {
    setAppliedUserId('');
    setUserQuery('');
    setPickerOpen(false);
  }, []);

  const counts = data?.counts;
  const workers = data?.workers || [];
  const attentions = data?.attentions || [];
  const ticks = data?.ticks || [];
  const proactive = data?.proactive || [];
  const schedule = data?.schedule || [];

  // Integrations panel — fetches /api/admin/{user}/integrations for the
  // currently-selected user. Shows local DB rows joined with composio
  // truth so we can spot OAuth chain drift, expired connections, and
  // stuck pending states. Refreshes alongside the rest of the page.
  const [integrationsData, setIntegrationsData] = useState<IntegrationsResponse | null>(null);
  const [integrationsError, setIntegrationsError] = useState<string | null>(null);
  useEffect(() => {
    if (!appliedUserId) {
      setIntegrationsData(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`/api/admin/${encodeURIComponent(appliedUserId)}/integrations`, {
          cache: 'no-store',
        });
        if (!res.ok) throw new Error(`http ${res.status}`);
        const json = (await res.json()) as IntegrationsResponse;
        if (cancelled) return;
        setIntegrationsData(json);
        setIntegrationsError(null);
      } catch (err: unknown) {
        if (cancelled) return;
        setIntegrationsError(String(err));
      }
    };
    void load();
    if (!autoRefresh) return () => { cancelled = true; };
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [appliedUserId, autoRefresh]);

  const filteredTicks = useMemo(() => {
    if (!expandedAttention) return ticks;
    return ticks.filter((t) => t.attention_id === expandedAttention);
  }, [ticks, expandedAttention]);

  return (
    <main
      style={{
        minHeight: '100vh',
        padding: '24px 28px',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        background: '#0f0f10',
        color: '#e9e7e1',
        fontSize: 12,
      }}
    >
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 16, margin: 0, letterSpacing: 0.4 }}>
          attention.observe
          {loading && <span style={{ color: '#888', marginLeft: 8 }}>· refreshing…</span>}
          {error && <span style={{ color: '#e06868', marginLeft: 8 }}>· {error}</span>}
        </h1>
        <div style={{ marginTop: 8, fontSize: 11, color: '#8a8a8a' }}>
          server now {fmtTime(data?.now || null)} · client now {fmtTime(now.toISOString())}
        </div>
        <div
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            marginTop: 12,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ position: 'relative', width: 360 }}>
            <button
              onClick={() => setPickerOpen((v) => !v)}
              style={{
                background: '#1a1a1a',
                color: '#e9e7e1',
                border: '1px solid #333',
                padding: '4px 10px',
                fontFamily: 'inherit',
                fontSize: 12,
                width: '100%',
                textAlign: 'left',
                cursor: 'pointer',
              }}
            >
              {selectedUser ? (
                <>
                  <span style={{ color: '#e9e7e1' }}>
                    {selectedUser.name || '(no name)'}
                  </span>
                  <span style={{ color: '#8a8a8a', marginLeft: 8 }}>
                    {selectedUser.phone || ''} · {selectedUser.id.slice(0, 8)}
                  </span>
                </>
              ) : (
                <span style={{ color: '#777' }}>
                  pick user — blank = all ({users.length})
                </span>
              )}
              <span style={{ float: 'right', color: '#777' }}>
                {pickerOpen ? '▲' : '▼'}
              </span>
            </button>
            {pickerOpen && (
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  marginTop: 4,
                  background: '#15161a',
                  border: '1px solid #333',
                  borderRadius: 4,
                  zIndex: 10,
                  maxHeight: 360,
                  overflowY: 'auto',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                }}
              >
                <input
                  autoFocus
                  value={userQuery}
                  onChange={(e) => setUserQuery(e.target.value)}
                  placeholder="search by name / phone / id"
                  style={{
                    background: '#0c0d10',
                    color: '#e9e7e1',
                    border: 'none',
                    borderBottom: '1px solid #333',
                    padding: '6px 10px',
                    fontFamily: 'inherit',
                    fontSize: 12,
                    width: '100%',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
                {appliedUserId && (
                  <div
                    onClick={clearUser}
                    style={{
                      padding: '6px 10px',
                      cursor: 'pointer',
                      borderBottom: '1px solid #2a2a2a',
                      color: '#d6c87a',
                    }}
                  >
                    × clear filter (show all users)
                  </div>
                )}
                {usersError && (
                  <div style={{ padding: '8px 10px', color: '#e06868' }}>
                    couldn&apos;t load users: {usersError}
                  </div>
                )}
                {!usersError && filteredUsers.length === 0 && (
                  <div style={{ padding: '8px 10px', color: '#666' }}>
                    no users match
                  </div>
                )}
                {filteredUsers.map((u) => (
                  <div
                    key={u.id}
                    onClick={() => pickUser(u.id)}
                    style={{
                      padding: '6px 10px',
                      cursor: 'pointer',
                      borderBottom: '1px solid #1f1f22',
                      background:
                        appliedUserId === u.id ? '#1d1f24' : 'transparent',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = '#1d1f24';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background =
                        appliedUserId === u.id ? '#1d1f24' : 'transparent';
                    }}
                  >
                    <div>
                      <span style={{ color: '#e9e7e1' }}>
                        {u.name || '(no name)'}
                      </span>
                      <span
                        style={{ color: '#9ab07a', marginLeft: 8, fontSize: 11 }}
                      >
                        {u.phone || ''}
                      </span>
                    </div>
                    <div style={{ color: '#8a8a8a', fontSize: 10, marginTop: 2 }}>
                      {u.id.slice(0, 8)} · tz {u.timezone || '—'} · last active{' '}
                      {fmtRelative(u.last_active_at, now)} · chat {u.chat_messages} · email {u.emails}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          {appliedUserId && (
            <button
              onClick={clearUser}
              style={{
                background: 'transparent',
                color: '#9a9a9a',
                border: '1px solid #333',
                padding: '4px 10px',
                fontFamily: 'inherit',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              clear
            </button>
          )}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            auto-refresh ({REFRESH_MS / 1000}s)
          </label>
          <button
            onClick={() => void fetchData()}
            style={{
              background: '#2a2a2a',
              color: '#e9e7e1',
              border: '1px solid #444',
              padding: '4px 10px',
              fontFamily: 'inherit',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            refresh now
          </button>
          <button
            onClick={() => {
              setComposeOpen(true);
              setComposeError(null);
              setComposeResult(null);
            }}
            style={{
              background: '#2d4a2d',
              color: '#d6e7c0',
              border: '1px solid #3a6a3a',
              padding: '4px 10px',
              fontFamily: 'inherit',
              fontSize: 12,
              cursor: 'pointer',
              marginLeft: 'auto',
            }}
            title={
              appliedUserId ? 'compose for selected user' : 'pick a user first'
            }
          >
            + compose attention
          </button>
        </div>
      </header>

      {composeOpen && (
        <ComposeModal
          targetUser={selectedUser}
          intent={composeIntent}
          setIntent={setComposeIntent}
          autoLive={composeAutoLive}
          setAutoLive={setComposeAutoLive}
          running={composeRunning}
          result={composeResult}
          error={composeError}
          onClose={() => {
            setComposeOpen(false);
            setComposeIntent('');
            setComposeResult(null);
            setComposeError(null);
          }}
          onSubmit={submitCompose}
        />
      )}

      {traceMessageId && (
        <TraceModal
          loading={traceLoading}
          error={traceError}
          data={traceData}
          onClose={closeTrace}
        />
      )}

      {counts && (
        <section
          style={{
            display: 'flex',
            gap: 16,
            flexWrap: 'wrap',
            marginBottom: 18,
            padding: '8px 12px',
            background: '#15161a',
            border: '1px solid #2a2a2a',
            borderRadius: 4,
          }}
        >
          <CountTile label="attentions" value={counts.attentions} />
          <CountTile label="ticks" value={counts.ticks} />
          <CountTile label="proactive msgs" value={counts.proactive_messages} />
          <CountTile label="pending schedule" value={counts.pending_schedule} />
          <div style={{ borderLeft: '1px solid #2a2a2a', paddingLeft: 12 }}>
            <div style={{ color: '#8a8a8a', fontSize: 10 }}>by card</div>
            <div>
              {Object.entries(counts.by_card)
                .map(([k, v]) => `${k}:${v}`)
                .join('  ')}
            </div>
          </div>
          <div style={{ borderLeft: '1px solid #2a2a2a', paddingLeft: 12 }}>
            <div style={{ color: '#8a8a8a', fontSize: 10 }}>by status</div>
            <div>
              {Object.entries(counts.by_status)
                .map(([k, v]) => `${k}:${v}`)
                .join('  ')}
            </div>
          </div>
        </section>
      )}

      {expandedAttention && (
        <div
          style={{
            marginBottom: 12,
            padding: '6px 10px',
            background: '#23241c',
            border: '1px solid #5a5530',
            borderRadius: 4,
            display: 'flex',
            gap: 12,
            alignItems: 'center',
          }}
        >
          <span style={{ color: '#d6c87a' }}>
            scoped to attention {expandedAttention.slice(0, 8)}
          </span>
          <button
            onClick={() => setExpandedAttention(null)}
            style={{
              background: 'transparent',
              color: '#d6c87a',
              border: '1px solid #5a5530',
              padding: '2px 8px',
              fontSize: 11,
              cursor: 'pointer',
            }}
          >
            clear scope
          </button>
        </div>
      )}

      <Section title={`workers (${workers.length})`}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>worker</th>
              <th style={thStyle}>last activity</th>
              <th style={thStyle}>since</th>
              <th style={thStyle}>health</th>
              <th style={thStyle}>recent ticks</th>
            </tr>
          </thead>
          <tbody>
            {workers.length === 0 && (
              <tr>
                <td colSpan={5} style={{ ...tdStyle, color: '#666' }}>
                  no worker activity in the recent window
                </td>
              </tr>
            )}
            {workers.map((w) => {
              const threshold =
                WORKER_STALE_THRESHOLDS[w.name] ?? 60 * 60;
              const stale =
                w.since_seconds === null
                  ? true
                  : w.since_seconds > threshold;
              const color = stale ? '#e06868' : '#1f9d55';
              const label = stale ? 'stale' : 'alive';
              return (
                <tr key={w.name}>
                  <td style={tdStyle}>{w.name}</td>
                  <td style={tdStyle}>{fmtTime(w.last_at)}</td>
                  <td style={tdStyle}>
                    {w.since_seconds === null
                      ? '—'
                      : fmtAbsSec(w.since_seconds) + ' ago'}
                  </td>
                  <td style={tdStyle}>
                    <span
                      style={{
                        background: color,
                        color: '#fff',
                        padding: '1px 6px',
                        borderRadius: 3,
                        fontSize: 10,
                        textTransform: 'uppercase',
                        letterSpacing: 0.5,
                      }}
                    >
                      {label}
                    </span>
                    <span style={{ color: '#8a8a8a', marginLeft: 6, fontSize: 10 }}>
                      threshold {fmtAbsSec(threshold)}
                    </span>
                  </td>
                  <td style={tdStyle}>{w.recent_count}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>

      {appliedUserId && (
        <Section
          title={`integrations${
            integrationsData
              ? ` (${integrationsData.local.length} local · ${integrationsData.composio.length} composio)`
              : ''
          }`}
        >
          {integrationsError && (
            <div style={{ color: '#e06868', padding: '6px 0', fontSize: 11 }}>
              {integrationsError}
            </div>
          )}
          {integrationsData && integrationsData.local.length === 0 &&
            integrationsData.composio.length === 0 && (
              <div style={{ color: '#666', padding: '6px 0' }}>
                no integrations recorded for this user
              </div>
            )}
          {integrationsData && (
            <>
              <div style={{ color: '#888', fontSize: 10, marginBottom: 4 }}>
                local · postgres `integrations` table
              </div>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>provider</th>
                    <th style={thStyle}>product</th>
                    <th style={thStyle}>status</th>
                    <th style={thStyle}>connection id</th>
                    <th style={thStyle}>connected at</th>
                    <th style={thStyle}>last synced</th>
                    <th style={thStyle}>redirect url</th>
                    <th style={thStyle}>last error</th>
                  </tr>
                </thead>
                <tbody>
                  {integrationsData.local.map((r, i) => {
                    const stale =
                      r.status === 'pending' &&
                      r.redirect_url_issued_at &&
                      Date.now() - new Date(r.redirect_url_issued_at).getTime() >
                        15 * 60 * 1000;
                    return (
                      <tr key={i}>
                        <td style={tdStyle}>{r.provider}</td>
                        <td style={tdStyle}>{r.product}</td>
                        <td style={tdStyle}>
                          <span
                            style={{
                              color:
                                r.status === 'connected'
                                  ? '#1f9d55'
                                  : r.status === 'pending'
                                    ? stale
                                      ? '#e0a868'
                                      : '#a0a0a0'
                                    : '#e06868',
                            }}
                          >
                            {r.status ?? '—'}
                            {stale ? ' · stale' : ''}
                          </span>
                        </td>
                        <td style={{ ...tdStyle, color: '#888' }}>
                          {r.composio_connection_id?.slice(0, 12) ?? '—'}
                        </td>
                        <td style={tdStyle}>{fmtTime(r.connected_at)}</td>
                        <td style={tdStyle}>{fmtTime(r.last_synced_at)}</td>
                        <td style={{ ...tdStyle, color: '#888', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {r.redirect_url ? (
                            <a
                              href={r.redirect_url}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: '#7aa6d6' }}
                            >
                              open
                            </a>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td style={{ ...tdStyle, color: r.last_error ? '#e06868' : '#888', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {r.last_error ?? '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{ color: '#888', fontSize: 10, marginTop: 12, marginBottom: 4 }}>
                composio · live api
              </div>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>connection id</th>
                    <th style={thStyle}>toolkit</th>
                    <th style={thStyle}>status</th>
                    <th style={thStyle}>created at</th>
                  </tr>
                </thead>
                <tbody>
                  {integrationsData.composio.map((r, i) => (
                    <tr key={r.id ?? i}>
                      <td style={{ ...tdStyle, color: '#888' }}>
                        {r.id ? r.id.slice(0, 12) : '—'}
                      </td>
                      <td style={tdStyle}>{r.toolkit ?? '—'}</td>
                      <td style={tdStyle}>
                        <span
                          style={{
                            color:
                              r.status === 'ACTIVE'
                                ? '#1f9d55'
                                : r.status === 'INITIATED'
                                  ? '#a0a0a0'
                                  : '#e06868',
                          }}
                        >
                          {r.status ?? '—'}
                          {r.error ? ` · ${r.error.slice(0, 40)}` : ''}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        {r.created_at ? fmtTime(r.created_at) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Section>
      )}

      <Section title={`attentions (${attentions.length})`}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>id</th>
              <th style={thStyle}>user</th>
              <th style={thStyle}>card</th>
              <th style={thStyle}>status</th>
              <th style={thStyle}>title / subject</th>
              <th style={thStyle}>value</th>
              <th style={thStyle}>target</th>
              <th style={thStyle}>count</th>
              <th style={thStyle}>last update</th>
              <th style={thStyle}>last surface</th>
              <th style={thStyle}>cadence</th>
              <th style={thStyle}>esc / nudge</th>
              <th style={thStyle}>actions</th>
            </tr>
          </thead>
          <tbody>
            {attentions.length === 0 && (
              <tr>
                <td colSpan={13} style={{ ...tdStyle, color: '#666' }}>
                  no attentions
                </td>
              </tr>
            )}
            {attentions.map((a) => {
              const expanded = expandedAttention === a.id;
              return (
                <>
                  <tr
                    key={a.id}
                    onClick={() =>
                      setExpandedAttention(expanded ? null : a.id)
                    }
                    style={{
                      background: expanded ? '#1d1f24' : 'transparent',
                      cursor: 'pointer',
                    }}
                  >
                    <td style={tdStyle}>
                      <span style={{ color: '#7aa2d6' }}>{a.id_short}</span>
                    </td>
                    <td style={tdStyle}>
                      <span style={{ color: '#9ab07a' }}>{a.user_id_short}</span>
                    </td>
                    <td style={tdStyle}>
                      <CardBadge card={a.card} />
                    </td>
                    <td style={tdStyle}>
                      <StatusBadge status={a.status} />
                    </td>
                    <td style={tdStyle}>
                      <div>{a.title || '—'}</div>
                      {a.subject && (
                        <div style={{ color: '#8a8a8a', fontSize: 10 }}>
                          subj: {a.subject}
                        </div>
                      )}
                    </td>
                    <td style={tdStyle}>{a.value ?? '—'}</td>
                    <td style={tdStyle}>{a.target ?? '—'}</td>
                    <td style={tdStyle}>{a.count ?? '—'}</td>
                    <td style={tdStyle}>{fmtRelative(a.last_update_at, now)}</td>
                    <td style={tdStyle}>{fmtRelative(a.last_surfaced_at, now)}</td>
                    <td style={tdStyle}>
                      <div>{a.cadence_type || '—'}</div>
                      {a.cadence_params && (
                        <div style={{ color: '#8a8a8a', fontSize: 10 }}>
                          {summarizeCadenceParams(a.cadence_params)}
                        </div>
                      )}
                    </td>
                    <td style={tdStyle}>
                      <span style={{ color: '#d68a8a' }}>{a.escalations_n}e</span>{' '}
                      <span style={{ color: '#7aa2d6' }}>
                        {a.nudge_silent_for ? `${Math.round(a.nudge_silent_for / 60)}m` : '—'}
                      </span>
                    </td>
                    <td
                      style={tdStyle}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <AttentionActions
                        status={a.status}
                        busy={busyAttentionId === a.id}
                        onAction={(s) => void updateAttentionStatus(a.id, s)}
                      />
                    </td>
                  </tr>
                  {expanded && (
                    <tr key={`${a.id}-x`}>
                      <td colSpan={13} style={{ ...tdStyle, background: '#16181c' }}>
                        <div style={{ padding: '6px 4px' }}>
                          <div style={{ color: '#8a8a8a', marginBottom: 4 }}>
                            current_state
                          </div>
                          <pre style={preStyle}>
                            {JSON.stringify(a.current_state, null, 2)}
                          </pre>
                          {Object.keys(a.poller_cursors || {}).length > 0 && (
                            <>
                              <div style={{ color: '#8a8a8a', margin: '8px 0 4px' }}>
                                poller_cursors
                              </div>
                              <pre style={preStyle}>
                                {JSON.stringify(a.poller_cursors, null, 2)}
                              </pre>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </Section>

      <Section title={`ticks (${filteredTicks.length})`}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>at</th>
              <th style={thStyle}>attention</th>
              <th style={thStyle}>kind</th>
              <th style={thStyle}>trigger</th>
              <th style={thStyle}>value / count</th>
              <th style={thStyle}>rendered</th>
            </tr>
          </thead>
          <tbody>
            {filteredTicks.length === 0 && (
              <tr>
                <td colSpan={6} style={{ ...tdStyle, color: '#666' }}>
                  no ticks
                </td>
              </tr>
            )}
            {filteredTicks.map((t) => {
              const sc = t.source_counts || {};
              const kind = String(sc.kind || '—');
              const trigger = String(sc.trigger || '—');
              const value = sc.value ?? sc.count ?? '—';
              const kindColor =
                kind === 'escalation'
                  ? '#e06868'
                  : kind === 'nudge'
                    ? '#e0b868'
                    : kind === 'burst'
                      ? '#68b6e0'
                      : '#7a7a7a';
              return (
                <tr
                  key={t.id}
                  onClick={() => setExpandedAttention(t.attention_id)}
                  style={{ cursor: 'pointer' }}
                >
                  <td style={tdStyle}>{fmtTime(t.at)}</td>
                  <td style={tdStyle}>
                    <span style={{ color: '#7aa2d6' }}>
                      {t.attention_id_short}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <span style={{ color: kindColor }}>{kind}</span>
                  </td>
                  <td style={tdStyle}>{trigger}</td>
                  <td style={tdStyle}>{String(value)}</td>
                  <td style={{ ...tdStyle, maxWidth: 480 }}>
                    {t.rendered_markdown ? (
                      <span style={{ color: '#d6d6c0' }}>
                        {t.rendered_markdown.slice(0, 240)}
                      </span>
                    ) : (
                      <span style={{ color: '#555' }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>

      <Section title={`proactive messages (${proactive.length})`}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>at</th>
              <th style={thStyle}>user</th>
              <th style={thStyle}>role</th>
              <th style={thStyle}>mode</th>
              <th style={thStyle}>wa id</th>
              <th style={thStyle}>content</th>
              <th style={thStyle}>trace</th>
            </tr>
          </thead>
          <tbody>
            {proactive.length === 0 && (
              <tr>
                <td colSpan={7} style={{ ...tdStyle, color: '#666' }}>
                  no proactive messages yet
                </td>
              </tr>
            )}
            {proactive.map((m) => (
              <tr key={m.id}>
                <td style={tdStyle}>{fmtTime(m.created_at)}</td>
                <td style={tdStyle}>
                  <span style={{ color: '#9ab07a' }}>{m.user_id_short}</span>
                </td>
                <td style={tdStyle}>{m.role}</td>
                <td style={tdStyle}>
                  <ModeBadge shadow={m.is_shadow} />
                </td>
                <td style={tdStyle}>
                  {m.wa_message_id ? (
                    <span style={{ color: '#7aa2d6' }}>
                      {m.wa_message_id.slice(0, 12)}
                    </span>
                  ) : (
                    <span style={{ color: '#555' }}>—</span>
                  )}
                </td>
                <td style={{ ...tdStyle, maxWidth: 600, whiteSpace: 'pre-wrap' }}>
                  {m.content}
                </td>
                <td style={tdStyle}>
                  <button
                    onClick={() => void openTrace(m.id)}
                    style={{
                      background: 'transparent',
                      color: '#7aa2d6',
                      border: '1px solid #7aa2d666',
                      padding: '1px 8px',
                      fontFamily: 'inherit',
                      fontSize: 10,
                      cursor: 'pointer',
                      borderRadius: 3,
                    }}
                  >
                    trace
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {appliedUserId && (
        <Section
          title={`chat with ${selectedUser?.name || appliedUserId.slice(0, 8)} (${chatRows.length})`}
        >
          <div style={{ padding: '8px 10px' }}>
            {chatLoading && (
              <div style={{ color: '#888', fontSize: 11 }}>loading…</div>
            )}
            {chatError && (
              <div style={{ color: '#e06868', fontSize: 11 }}>
                {chatError}
              </div>
            )}
            {!chatLoading && chatRows.length === 0 && (
              <div style={{ color: '#666', fontSize: 11 }}>
                no chat history
              </div>
            )}
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
                maxHeight: 520,
                overflowY: 'auto',
              }}
            >
              {chatRows.map((m) => {
                const fromUser = m.role === 'user';
                const isProactive = m.is_proactive;
                const bg = fromUser
                  ? '#1d2a3a'
                  : isProactive
                    ? '#2a2a1a'
                    : '#1f231f';
                const accent = fromUser
                  ? '#7aa2d6'
                  : isProactive
                    ? '#d6c87a'
                    : '#9ab07a';
                return (
                  <div
                    key={m.id}
                    style={{
                      alignSelf: fromUser ? 'flex-start' : 'flex-end',
                      maxWidth: '80%',
                      background: bg,
                      border: `1px solid ${accent}33`,
                      borderRadius: 6,
                      padding: '6px 10px',
                    }}
                  >
                    <div
                      style={{
                        color: accent,
                        fontSize: 10,
                        textTransform: 'uppercase',
                        letterSpacing: 0.5,
                        marginBottom: 4,
                      }}
                    >
                      {m.role}
                      {isProactive && ' · proactive'}
                      <span style={{ color: '#888', marginLeft: 8 }}>
                        {fmtTime(m.created_at)}
                      </span>
                    </div>
                    <div style={{ whiteSpace: 'pre-wrap', color: '#e9e7e1' }}>
                      {m.content}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </Section>
      )}

      <Section title={`pending schedule (${schedule.length})`}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>fire_at</th>
              <th style={thStyle}>in</th>
              <th style={thStyle}>id</th>
              <th style={thStyle}>user</th>
              <th style={thStyle}>attention</th>
              <th style={thStyle}>origin</th>
              <th style={thStyle}>recurrence</th>
              <th style={thStyle}>attempts</th>
              <th style={thStyle}>last_error</th>
            </tr>
          </thead>
          <tbody>
            {schedule.length === 0 && (
              <tr>
                <td colSpan={9} style={{ ...tdStyle, color: '#666' }}>
                  queue empty
                </td>
              </tr>
            )}
            {schedule.map((s) => (
              <tr
                key={s.id}
                onClick={() => s.attention_id && setExpandedAttention(s.attention_id)}
                style={{ cursor: s.attention_id ? 'pointer' : 'default' }}
              >
                <td style={tdStyle}>{fmtTime(s.fire_at)}</td>
                <td style={tdStyle}>{fmtRelative(s.fire_at, now)}</td>
                <td style={tdStyle}>
                  <span style={{ color: '#7aa2d6' }}>{s.id_short}</span>
                </td>
                <td style={tdStyle}>
                  <span style={{ color: '#9ab07a' }}>{s.user_id_short}</span>
                </td>
                <td style={tdStyle}>
                  {s.attention_id_short ? (
                    <span style={{ color: '#7aa2d6' }}>
                      {s.attention_id_short}
                    </span>
                  ) : (
                    <span style={{ color: '#555' }}>—</span>
                  )}
                </td>
                <td style={tdStyle}>{s.origin}</td>
                <td style={tdStyle}>{s.recurrence || '—'}</td>
                <td style={tdStyle}>{s.attempts}</td>
                <td style={{ ...tdStyle, color: '#e06868', maxWidth: 280 }}>
                  {s.last_error ? s.last_error.slice(0, 200) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </main>
  );
}

function CountTile({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div style={{ color: '#8a8a8a', fontSize: 10 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 24 }}>
      <h2
        style={{
          fontSize: 12,
          color: '#a8a8a8',
          textTransform: 'uppercase',
          letterSpacing: 1,
          margin: '0 0 6px 0',
        }}
      >
        {title}
      </h2>
      <div
        style={{
          background: '#15161a',
          border: '1px solid #2a2a2a',
          borderRadius: 4,
          overflowX: 'auto',
        }}
      >
        {children}
      </div>
    </section>
  );
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 11,
};
const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  borderBottom: '1px solid #2a2a2a',
  color: '#8a8a8a',
  fontWeight: 500,
  textTransform: 'uppercase',
  letterSpacing: 0.5,
  position: 'sticky',
  top: 0,
  background: '#15161a',
};
const tdStyle: React.CSSProperties = {
  padding: '5px 10px',
  borderBottom: '1px solid #1f1f22',
  verticalAlign: 'top',
};
const preStyle: React.CSSProperties = {
  background: '#0c0d10',
  color: '#c0c0a8',
  padding: 8,
  fontSize: 10,
  margin: 0,
  border: '1px solid #2a2a2a',
  borderRadius: 3,
  overflowX: 'auto',
};

function summarizeCadenceParams(p: Record<string, unknown>): string {
  if (!p) return '';
  if (typeof p.cron === 'string') return `cron ${p.cron}`;
  if (typeof p.fire_at === 'string') return `at ${String(p.fire_at).slice(11, 16)}`;
  if (typeof p.interval_seconds === 'number')
    return `every ${Math.round((p.interval_seconds as number) / 60)}m`;
  return JSON.stringify(p).slice(0, 60);
}

function AttentionActions({
  status,
  busy,
  onAction,
}: {
  status: string | null;
  busy: boolean;
  onAction: (status: string) => void;
}) {
  const buttons: { label: string; status: string; show: boolean; color: string }[] = [
    { label: 'pause', status: 'paused', show: status === 'live', color: '#a3935f' },
    { label: 'resume', status: 'live', show: status === 'paused', color: '#5fa37a' },
    {
      label: 'resolve',
      status: 'resolved',
      show: status === 'live' || status === 'paused',
      color: '#5f7aa3',
    },
    {
      label: 'archive',
      status: 'archived',
      show: status === 'live' || status === 'paused',
      color: '#a35f5f',
    },
  ];
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      {buttons
        .filter((b) => b.show)
        .map((b) => (
          <button
            key={b.label}
            disabled={busy}
            onClick={() => {
              if (b.status === 'archived' || b.status === 'resolved') {
                if (
                  !confirm(
                    `${b.label} this attention? this is sticky.`,
                  )
                )
                  return;
              }
              onAction(b.status);
            }}
            style={{
              background: 'transparent',
              color: b.color,
              border: `1px solid ${b.color}66`,
              padding: '1px 6px',
              fontFamily: 'inherit',
              fontSize: 10,
              cursor: busy ? 'wait' : 'pointer',
              borderRadius: 3,
            }}
          >
            {b.label}
          </button>
        ))}
    </div>
  );
}

function TraceModal({
  loading,
  error,
  data,
  onClose,
}: {
  loading: boolean;
  error: string | null;
  data: ProactiveTrace | null;
  onClose: () => void;
}) {
  const sourceColors: Record<string, string> = {
    dispatcher_tier2: '#7aa2d6',
    webset_subscription: '#d6c87a',
    schedule_worker: '#9ab07a',
    attention_runtime: '#a380c8',
    unknown: '#a35f5f',
  };
  const totalCost = (data?.turns || []).reduce(
    (acc, t) => acc + (t.cost_usd || 0),
    0,
  );
  const totalTools = (data?.turns || []).reduce(
    (acc, t) => acc + (t.tools?.length || 0),
    0,
  );

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        zIndex: 110,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#15161a',
          color: '#e9e7e1',
          border: '1px solid #2a2a2a',
          borderRadius: 6,
          width: 'min(960px, 100%)',
          maxHeight: '94vh',
          overflowY: 'auto',
          padding: 20,
          fontFamily: 'inherit',
          fontSize: 12,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <h2 style={{ margin: 0, fontSize: 14, letterSpacing: 0.5 }}>
            proactive trace
          </h2>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              color: '#9a9a9a',
              border: '1px solid #333',
              padding: '2px 8px',
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: 12,
            }}
          >
            close
          </button>
        </div>

        {loading && <div style={{ color: '#888' }}>loading trace…</div>}
        {error && (
          <div
            style={{
              padding: 10,
              background: '#3a1f1f',
              border: '1px solid #5a2a2a',
              borderRadius: 4,
              color: '#e0a8a8',
            }}
          >
            {error}
          </div>
        )}

        {data && (
          <>
            <div
              style={{
                padding: '10px 12px',
                background: '#1a1d22',
                border: '1px solid #2a2a2a',
                borderRadius: 4,
                marginBottom: 14,
              }}
            >
              <div style={{ color: '#8a8a8a', fontSize: 10 }}>message</div>
              <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                {data.message.content}
              </div>
              <div style={{ color: '#8a8a8a', fontSize: 10, marginTop: 6 }}>
                {fmtTime(data.message.created_at)} ·{' '}
                <ModeBadge shadow={data.message.is_shadow} /> · id{' '}
                {data.message.id.slice(0, 8)}
              </div>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 8,
                marginBottom: 16,
              }}
            >
              <Tile label="probable source">
                <span
                  style={{
                    color: sourceColors[data.probable_source] || '#fff',
                    fontWeight: 600,
                  }}
                >
                  {data.probable_source}
                </span>
              </Tile>
              <Tile label="confidence">
                {(data.confidence * 100).toFixed(0)}%
              </Tile>
              <Tile label="window">
                ±{data.window_seconds}s
              </Tile>
              <Tile label="signals">{data.signals.length}</Tile>
              <Tile label="proactive_pings">
                {data.proactive_pings.length}
              </Tile>
              <Tile label="schedule fires">
                {data.schedule_fired.length}
              </Tile>
              <Tile label="attentions">{data.attentions.length}</Tile>
              <Tile label="brain turns">{data.turns.length}</Tile>
              <Tile label="tool calls">{totalTools}</Tile>
              <Tile label="cost">
                {totalCost > 0 ? `$${totalCost.toFixed(5)}` : '—'}
              </Tile>
            </div>

            {data.rationale.length > 0 && (
              <Block title="why this source">
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {data.rationale.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </Block>
            )}

            {data.signals.length > 0 && (
              <Block title="webset signals matched">
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <th style={thStyle}>at</th>
                      <th style={thStyle}>intent</th>
                      <th style={thStyle}>title</th>
                      <th style={thStyle}>url</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.signals.map((s) => (
                      <tr key={s.id}>
                        <td style={tdStyle}>{fmtTime(s.arrived_at)}</td>
                        <td style={{ ...tdStyle, color: '#d6c87a' }}>
                          {s.intent_key?.slice(0, 60) || '—'}
                        </td>
                        <td style={{ ...tdStyle, maxWidth: 320 }}>
                          {s.title}
                        </td>
                        <td style={tdStyle}>
                          {s.url ? (
                            <a
                              href={s.url}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: '#7aa2d6' }}
                            >
                              open
                            </a>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Block>
            )}

            {data.subscriptions.length > 0 && (
              <Block title="webset subscriptions">
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <th style={thStyle}>active</th>
                      <th style={thStyle}>description</th>
                      <th style={thStyle}>cadence</th>
                      <th style={thStyle}>last hit</th>
                      <th style={thStyle}>webset</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.subscriptions.map((s) => (
                      <tr key={s.id}>
                        <td style={tdStyle}>
                          <span
                            style={{
                              color: s.active ? '#1f9d55' : '#9a3a3a',
                            }}
                          >
                            {s.active ? 'on' : 'off'}
                          </span>
                        </td>
                        <td style={{ ...tdStyle, maxWidth: 360 }}>
                          {s.description}
                        </td>
                        <td style={tdStyle}>{s.cadence || '—'}</td>
                        <td style={tdStyle}>{fmtTime(s.last_hit_at)}</td>
                        <td style={{ ...tdStyle, color: '#666' }}>
                          {(s.webset_id || '').slice(0, 18) || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Block>
            )}

            {data.proactive_pings.length > 0 && (
              <Block title="proactive_pings (dispatcher tier2 record)">
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <th style={thStyle}>at</th>
                      <th style={thStyle}>source</th>
                      <th style={thStyle}>topic_key</th>
                      <th style={thStyle}>suppressed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.proactive_pings.map((p) => (
                      <tr key={p.id}>
                        <td style={tdStyle}>{fmtTime(p.fired_at)}</td>
                        <td style={tdStyle}>{p.source}</td>
                        <td style={tdStyle}>{p.topic_key || '—'}</td>
                        <td style={{ ...tdStyle, color: '#d6c87a' }}>
                          {p.suppressed_reason || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Block>
            )}

            {data.schedule_fired.length > 0 && (
              <Block title="schedule fires in window">
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <th style={thStyle}>fired_at</th>
                      <th style={thStyle}>origin</th>
                      <th style={thStyle}>attention</th>
                      <th style={thStyle}>error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.schedule_fired.map((s) => (
                      <tr key={s.id}>
                        <td style={tdStyle}>{fmtTime(s.fired_at)}</td>
                        <td style={tdStyle}>{s.origin}</td>
                        <td style={{ ...tdStyle, color: '#7aa2d6' }}>
                          {s.attention_id?.slice(0, 8) || '—'}
                        </td>
                        <td style={{ ...tdStyle, color: '#e06868' }}>
                          {s.last_error?.slice(0, 80) || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Block>
            )}

            {data.attentions.length > 0 && (
              <Block title="attentions surfaced near this message">
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <th style={thStyle}>id</th>
                      <th style={thStyle}>card</th>
                      <th style={thStyle}>title</th>
                      <th style={thStyle}>last surfaced</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.attentions.map((a) => (
                      <tr key={a.id}>
                        <td style={{ ...tdStyle, color: '#7aa2d6' }}>
                          {a.id.slice(0, 8)}
                        </td>
                        <td style={tdStyle}>
                          <CardBadge card={a.card} />
                        </td>
                        <td style={tdStyle}>{a.title || '—'}</td>
                        <td style={tdStyle}>{fmtTime(a.last_surfaced_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Block>
            )}

            {data.turns.length > 0 && (
              <Block title="brain turns in window">
                {data.turns.map((t) => (
                  <div
                    key={t.turn_id}
                    style={{
                      padding: '8px 10px',
                      background: '#0c0d10',
                      border: '1px solid #2a2a2a',
                      borderRadius: 4,
                      marginBottom: 8,
                    }}
                  >
                    <div style={{ color: '#8a8a8a', fontSize: 11 }}>
                      <span style={{ color: '#7aa2d6' }}>
                        {t.turn_id.slice(0, 12)}
                      </span>
                      {' · '}
                      {fmtTime(t.started_at)} → {fmtTime(t.ended_at)}
                      {t.mode && ` · mode ${t.mode}`}
                      {t.model && ` · ${t.model}`}
                    </div>
                    <div style={{ marginTop: 4 }}>
                      tokens in/out{' '}
                      <span style={{ color: '#9ab07a' }}>
                        {t.in_tokens ?? '?'}
                      </span>{' '}
                      /{' '}
                      <span style={{ color: '#9ab07a' }}>
                        {t.out_tokens ?? '?'}
                      </span>
                      {t.cache_read != null && (
                        <>
                          {' '}· cache read{' '}
                          <span style={{ color: '#7aa2d6' }}>
                            {t.cache_read}
                          </span>
                        </>
                      )}
                      {' '}· cost{' '}
                      <span style={{ color: '#d6c87a' }}>
                        {t.cost_usd != null ? `$${t.cost_usd.toFixed(5)}` : '—'}
                      </span>
                    </div>
                    {t.tools.length > 0 && (
                      <div style={{ marginTop: 6 }}>
                        <div style={{ color: '#8a8a8a', fontSize: 10 }}>
                          tools ({t.tools.length})
                        </div>
                        {t.tools.map((tc, i) => (
                          <div
                            key={i}
                            style={{
                              fontSize: 11,
                              color: '#c8d6c0',
                              marginTop: 2,
                            }}
                          >
                            {fmtTime(tc.ts)} · {tc.tool}
                            {tc.short ? ` · ${tc.short.slice(0, 60)}` : ''}
                          </div>
                        ))}
                      </div>
                    )}
                    {t.errors.length > 0 && (
                      <div style={{ marginTop: 6, color: '#e06868' }}>
                        errors:{' '}
                        {t.errors.map((e, i) => (
                          <div key={i} style={{ fontSize: 11 }}>
                            {e.msg}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </Block>
            )}

            {data.siblings.length > 1 && (
              <Block
                title={`siblings in ${data.window_seconds}s window (${data.siblings.length})`}
              >
                {data.siblings.map((s) => (
                  <div
                    key={s.id}
                    style={{
                      padding: '4px 8px',
                      borderLeft: s.self
                        ? '2px solid #d6c87a'
                        : '2px solid #2a2a2a',
                      marginBottom: 4,
                      background: s.self ? '#1d1f24' : 'transparent',
                    }}
                  >
                    <div style={{ color: '#8a8a8a', fontSize: 10 }}>
                      {fmtTime(s.created_at)} ·{' '}
                      <ModeBadge shadow={s.is_shadow} />
                    </div>
                    <div style={{ marginTop: 2 }}>{s.content}</div>
                  </div>
                ))}
              </Block>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        background: '#0c0d10',
        border: '1px solid #2a2a2a',
        borderRadius: 4,
        padding: '6px 10px',
      }}
    >
      <div style={{ color: '#8a8a8a', fontSize: 10, marginBottom: 2 }}>
        {label}
      </div>
      <div>{children}</div>
    </div>
  );
}

function Block({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          color: '#a8a8a8',
          textTransform: 'uppercase',
          letterSpacing: 1,
          fontSize: 10,
          marginBottom: 4,
        }}
      >
        {title}
      </div>
      <div
        style={{
          background: '#15161a',
          border: '1px solid #2a2a2a',
          borderRadius: 4,
          overflowX: 'auto',
        }}
      >
        {children}
      </div>
    </div>
  );
}

function ComposeModal({
  targetUser,
  intent,
  setIntent,
  autoLive,
  setAutoLive,
  running,
  result,
  error,
  onClose,
  onSubmit,
}: {
  targetUser: UserOption | null;
  intent: string;
  setIntent: (v: string) => void;
  autoLive: boolean;
  setAutoLive: (v: boolean) => void;
  running: boolean;
  result: ComposeResult | null;
  error: string | null;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#15161a',
          color: '#e9e7e1',
          border: '1px solid #2a2a2a',
          borderRadius: 6,
          width: 'min(720px, 100%)',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: 20,
          fontFamily: 'inherit',
          fontSize: 12,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <h2 style={{ margin: 0, fontSize: 14, letterSpacing: 0.5 }}>
            compose attention
          </h2>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              color: '#9a9a9a',
              border: '1px solid #333',
              padding: '2px 8px',
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: 12,
            }}
          >
            close
          </button>
        </div>

        <div style={{ marginBottom: 8, fontSize: 11, color: '#9a9a9a' }}>
          target user{' '}
          {targetUser ? (
            <span style={{ color: '#e9e7e1' }}>
              {targetUser.name || '(no name)'} · {targetUser.phone || ''} ·{' '}
              {targetUser.id.slice(0, 8)}
            </span>
          ) : (
            <span style={{ color: '#e06868' }}>
              none — pick a user in the filter first
            </span>
          )}
        </div>

        <textarea
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="raw intent — exactly as the user would phrase it. e.g. 'track my calories with a 2000 cal goal'"
          rows={4}
          style={{
            width: '100%',
            boxSizing: 'border-box',
            background: '#0c0d10',
            color: '#e9e7e1',
            border: '1px solid #333',
            padding: 8,
            fontFamily: 'inherit',
            fontSize: 12,
            resize: 'vertical',
          }}
        />

        <div
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            marginTop: 10,
          }}
        >
          <label
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <input
              type="checkbox"
              checked={autoLive}
              onChange={(e) => setAutoLive(e.target.checked)}
            />
            auto_live (else status=spec_drafted)
          </label>
          <button
            disabled={running || !targetUser || !intent.trim()}
            onClick={onSubmit}
            style={{
              background: running ? '#333' : '#2d4a2d',
              color: '#d6e7c0',
              border: '1px solid #3a6a3a',
              padding: '6px 14px',
              cursor: running ? 'wait' : 'pointer',
              fontFamily: 'inherit',
              fontSize: 12,
              marginLeft: 'auto',
            }}
          >
            {running ? 'authoring…' : 'compose'}
          </button>
        </div>

        {error && (
          <div
            style={{
              marginTop: 12,
              padding: '8px 10px',
              background: '#3a1f1f',
              border: '1px solid #5a2a2a',
              borderRadius: 4,
              color: '#e0a8a8',
            }}
          >
            {error}
          </div>
        )}

        {result && (
          <div style={{ marginTop: 14 }}>
            <div
              style={{
                padding: '6px 10px',
                background: '#1f3a23',
                border: '1px solid #2a5a30',
                borderRadius: 4,
                color: '#c0e0c8',
                marginBottom: 12,
              }}
            >
              {result.reused
                ? 'reused existing PING (dedup window)'
                : 'authored + persisted'}{' '}
              · id {result.attention_id.slice(0, 8)} · via{' '}
              {result.authored_via} · confidence{' '}
              {(result.authored_confidence ?? 0).toFixed(2)}
            </div>
            {result.preview.warnings.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ color: '#d6c87a', fontSize: 11 }}>
                  preview warnings
                </div>
                <ul style={{ margin: 4, paddingLeft: 18 }}>
                  {result.preview.warnings.map((w, i) => (
                    <li key={i} style={{ color: '#d6c87a' }}>
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.preview.rendered_markdown && (
              <>
                <div style={{ color: '#8a8a8a', marginBottom: 4 }}>
                  preview
                </div>
                <pre
                  style={{
                    ...preStyle,
                    whiteSpace: 'pre-wrap',
                    maxHeight: 220,
                    overflowY: 'auto',
                  }}
                >
                  {result.preview.rendered_markdown}
                </pre>
              </>
            )}
            <div style={{ color: '#8a8a8a', margin: '10px 0 4px' }}>
              spec
            </div>
            <pre
              style={{
                ...preStyle,
                maxHeight: 280,
                overflowY: 'auto',
              }}
            >
              {JSON.stringify(result.spec, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
