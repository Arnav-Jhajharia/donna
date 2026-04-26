'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import DashboardRenderer from '@/components/DashboardRenderer';
import Toasts from '@/components/Toasts';
import { ActionProvider } from '@/lib/action-context';
import type { DashboardPlan } from '@/lib/plan';
import { resolveUserId } from '@/lib/whoami';

const POLL_INTERVAL_MS = 20_000;

type LoadState =
  | { kind: 'loading' }
  | { kind: 'no-user' }
  | { kind: 'no-manifest'; userId: string }
  | { kind: 'error'; message: string }
  | { kind: 'plan'; plan: DashboardPlan };

export default function Page() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [fixture, setFixture] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [devMode, setDevMode] = useState(false);

  // Read ?dev=1 once on mount. The flag opts into FixtureSwitch + the
  // rotating-fixture fallback so design work + showcase pages keep
  // working without polluting the production view.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    setDevMode(params.get('dev') === '1');
  }, []);

  // Resolve user_id once (cookie or ?user_id= query). Production no
  // longer pretends to be 'aarav' — if there's no user we render an
  // explicit empty state.
  useEffect(() => {
    let cancelled = false;
    void resolveUserId().then((id) => {
      if (cancelled) return;
      setUserId(id);
      if (!id) setState({ kind: 'no-user' });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    const fetchPlan = async () => {
      try {
        const params = new URLSearchParams();
        if (fixture) params.set('fixture', fixture);
        if (devMode) params.set('dev', '1');
        const qs = params.toString();
        const url = `/api/dashboard/${encodeURIComponent(userId)}/manifest${
          qs ? `?${qs}` : ''
        }`;
        const res = await fetch(url, { cache: 'no-store' });
        if (res.status === 404) {
          if (!cancelled) setState({ kind: 'no-manifest', userId });
          return;
        }
        if (!res.ok) {
          throw new Error(`status ${res.status}`);
        }
        const next = (await res.json()) as DashboardPlan;
        if (!cancelled) setState({ kind: 'plan', plan: next });
      } catch (err: unknown) {
        if (!cancelled) {
          setState({
            kind: 'error',
            message: err instanceof Error ? err.message : 'fetch failed',
          });
        }
      }
    };
    void fetchPlan();
    const pollId = setInterval(fetchPlan, POLL_INTERVAL_MS);

    // Server-Sent Events: when the backend writes a fresh manifest
    // (Donna calls update_dashboard, an attention is accepted, etc.),
    // the SSE stream emits ``manifest_changed`` and we re-fetch within
    // ~1s instead of waiting for the next 20s poll. The polling stays
    // as a fallback when SSE drops or the proxy buffers.
    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource(
        `/api/dashboard/${encodeURIComponent(userId)}/events`,
      );
      eventSource.onmessage = () => {
        void fetchPlan();
      };
      eventSource.onerror = () => {
        // EventSource auto-reconnects; we just rely on polling in the meantime.
      };
    } catch {
      // EventSource not supported / blocked — polling-only mode.
    }

    return () => {
      cancelled = true;
      clearInterval(pollId);
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [fixture, userId, devMode]);

  return (
    <ActionProvider>
      <main
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: 'var(--space-5) 0',
        }}
      >
        {devMode && <FixtureSwitch current={fixture} onSelect={setFixture} />}
        <DashboardSurface state={state} devMode={devMode} />
      </main>
      <Toasts />
    </ActionProvider>
  );
}

function DashboardSurface({
  state,
  devMode,
}: {
  state: LoadState;
  devMode: boolean;
}) {
  const shellStyle: React.CSSProperties = {
    width: '100%',
    maxWidth: 440,
    background: 'var(--bg-canvas)',
    borderLeft: '1px solid var(--border-hairline)',
    borderRight: '1px solid var(--border-hairline)',
    overflow: 'hidden',
    minHeight: 320,
  };

  if (state.kind === 'plan') {
    return (
      <div style={shellStyle}>
        <DashboardRenderer plan={state.plan} />
      </div>
    );
  }

  return (
    <div style={shellStyle}>
      <EmptyState state={state} devMode={devMode} />
    </div>
  );
}

function EmptyState({ state, devMode }: { state: LoadState; devMode: boolean }) {
  if (state.kind === 'loading') {
    return <EmptyShell kicker="loading" title="warming up." body={null} />;
  }
  if (state.kind === 'no-user') {
    // The middleware should have redirected to /auth/signin before this
    // ever rendered. If we still hit it (e.g. dev mode bypass), point
    // the user at the sign-in page in client-land too.
    if (typeof window !== 'undefined') {
      window.location.replace('/auth/signin');
    }
    return <EmptyShell kicker="redirecting" title="taking you to sign in." body={null} />;
  }
  if (state.kind === 'no-manifest') {
    return (
      <EmptyShell
        kicker="no manifest yet"
        title="your dashboard is being composed."
        body={
          <>
            text donna with &ldquo;redo my dashboard&rdquo; and she&apos;ll
            assemble one for the moment you&apos;re in. it&apos;ll appear here
            within ~20 seconds of her finishing.
          </>
        }
        footer={
          devMode ? (
            <span className="empty-meta">
              dev mode — add <code>?fixture=morning</code> to preview a canned plan
            </span>
          ) : null
        }
      />
    );
  }
  if (state.kind === 'error') {
    return (
      <EmptyShell
        kicker="couldn't reach donna"
        title="hold on a sec."
        body={<>backend didn&apos;t respond. {state.message}.</>}
      />
    );
  }
  return null;
}

function EmptyShell({
  kicker,
  title,
  body,
  footer,
}: {
  kicker: string;
  title: string;
  body: React.ReactNode | null;
  footer?: React.ReactNode;
}) {
  return (
    <div
      style={{
        padding: 'var(--space-7) var(--space-5)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        minHeight: 320,
        justifyContent: 'center',
      }}
    >
      <span
        style={{
          fontSize: 11,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color: 'var(--ink-500)',
          fontWeight: 500,
        }}
      >
        {kicker}
      </span>
      <h2
        style={{
          fontFamily: 'var(--font-serif)',
          fontWeight: 500,
          fontSize: 28,
          lineHeight: 1.2,
          margin: 0,
          color: 'var(--ink-900)',
        }}
      >
        {title}
      </h2>
      {body && (
        <p
          style={{
            fontSize: 14,
            lineHeight: 1.55,
            color: 'var(--ink-600)',
            margin: 0,
            maxWidth: 36,
          }}
        >
          {body}
        </p>
      )}
      {footer && <div style={{ marginTop: 'var(--space-3)' }}>{footer}</div>}
    </div>
  );
}

const FIXTURE_OPTIONS: Array<{ key: string | null; label: string }> = [
  { key: null, label: 'live (rotating)' },
  { key: 'morning', label: 'morning' },
  { key: 'busy-pitch', label: 'busy pitch' },
  { key: 'drunk-water', label: 'drunk → water' },
  { key: 'integration-prompt', label: 'connect gmail' },
  { key: 'midday', label: 'midday' },
  { key: 'low-energy', label: 'low energy' },
  { key: 'evening', label: 'evening' },
];

function FixtureSwitch({
  current,
  onSelect,
}: {
  current: string | null;
  onSelect: (next: string | null) => void;
}) {
  return (
    <nav
      style={{
        width: '100%',
        maxWidth: 440,
        display: 'flex',
        gap: 8,
        padding: '0 20px 20px',
        flexWrap: 'wrap',
        justifyContent: 'flex-end',
        fontSize: 10,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        fontWeight: 500,
      }}
    >
      <span
        style={{
          alignSelf: 'center',
          marginRight: 'auto',
          color: 'var(--ink-500)',
        }}
      >
        dev · fixture preview
      </span>
      {FIXTURE_OPTIONS.map((opt) => {
        const active = (opt.key ?? null) === current;
        return (
          <button
            key={opt.key ?? 'live'}
            onClick={() => onSelect(opt.key)}
            style={{
              border: '1px solid var(--border-hairline)',
              borderRadius: 999,
              padding: '4px 10px',
              background: active ? 'var(--rust-700)' : 'var(--paper-50)',
              color: active ? 'var(--paper-100)' : 'var(--rust-700)',
              cursor: 'pointer',
              letterSpacing: '0.14em',
              fontFamily: 'var(--font-sans)',
              fontWeight: 500,
            }}
          >
            {opt.label}
          </button>
        );
      })}
      <Link href="/moments" style={{ color: 'var(--rust-700)', textDecoration: 'none', alignSelf: 'center' }}>
        moments →
      </Link>
    </nav>
  );
}
