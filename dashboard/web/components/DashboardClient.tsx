'use client';

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

export default function DashboardClient() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [userId, setUserId] = useState<string | null>(null);

  // Resolve user_id once (cookie or ?user_id= query). Production no
  // longer pretends to be 'aarav' — if there's no user we render an
  // explicit empty state. Fixture preview lives on the internal host
  // (/moments, /generator) — not exposed here.
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
        const url = `/api/dashboard/${encodeURIComponent(userId)}/manifest`;
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
  }, [userId]);

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
        <DashboardSurface state={state} />
      </main>
      <Toasts />
    </ActionProvider>
  );
}

function DashboardSurface({ state }: { state: LoadState }) {
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
      <EmptyState state={state} />
    </div>
  );
}

function EmptyState({ state }: { state: LoadState }) {
  if (state.kind === 'loading') {
    return <EmptyShell kicker="loading" title="warming up." body={null} />;
  }
  if (state.kind === 'no-user') {
    // The page server component only mounts this client when a session
    // cookie is present, so this branch is rare. If it does fire (cookie
    // expired between request and whoami), surface a quiet redirect.
    if (typeof window !== 'undefined') {
      window.location.replace('/auth/signin');
    }
    return <EmptyShell kicker="redirecting" title="taking you to sign in." body={null} />;
  }
  if (state.kind === 'no-manifest') {
    return (
      <EmptyShell
        kicker="warming up"
        title="your dashboard is being composed."
        body={
          <>
            text donna anything you&apos;re holding right now. she&apos;ll
            start the page from there. refreshes within ~20 seconds of her
            reply.
          </>
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
}: {
  kicker: string;
  title: string;
  body: React.ReactNode | null;
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
    </div>
  );
}
