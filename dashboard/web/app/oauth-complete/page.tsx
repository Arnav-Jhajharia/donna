'use client';

import { useEffect, useMemo, useState } from 'react';
import { buildWaUrl } from '@/lib/wa-deeplink';

/**
 * The page Composio's OAuth chain redirects to after every toolkit in
 * the chain has completed.
 *
 * Composio walks each toolkit's ``redirect_url`` → ``callback_url`` until
 * the final callback fires (this page). We render a brief confirmation
 * with the toolkits that just landed, then auto-redirect to WhatsApp
 * so the user lands back in Donna's chat — where the
 * ``composio.connected_account.created`` webhook will have already
 * posted a "<toolkit> connected" message via ``notify_integration_complete``.
 *
 * Query params:
 *   ?tk=gmail,googlecalendar  (comma-separated toolkit slugs)
 *
 * Falls back gracefully when ``tk`` is absent — Composio sometimes
 * appends its own params, so we accept either form.
 *
 * Why an interstitial instead of an immediate 302:
 *   1. The user sees a Donna-branded confirmation, not a Composio one.
 *      Trust signal: "yes, this completed, on the right account."
 *   2. Mobile browsers occasionally suppress automatic redirects to
 *      app deeplinks (wa.me) on cold visits — a deliberate user gesture
 *      on a "tap to open WhatsApp" button works around that.
 *   3. We get a moment to fire any client-side analytics if needed.
 */
const REDIRECT_DELAY_MS = 1500;

const TOOLKIT_LABEL: Record<string, string> = {
  gmail: 'Gmail',
  googlecalendar: 'Calendar',
  googledrive: 'Drive',
  googledocs: 'Docs',
  github: 'GitHub',
  slack: 'Slack',
  notion: 'Notion',
  linear: 'Linear',
  asana: 'Asana',
};

function prettyToolkits(slugs: string[]): string {
  if (slugs.length === 0) return 'your account';
  const labels = slugs.map((s) => TOOLKIT_LABEL[s.toLowerCase()] ?? s);
  if (labels.length === 1) return labels[0];
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return labels.slice(0, -1).join(', ') + `, and ${labels[labels.length - 1]}`;
}

export default function OAuthCompletePage() {
  const [opening, setOpening] = useState(false);

  const toolkits = useMemo(() => {
    if (typeof window === 'undefined') return [];
    const params = new URLSearchParams(window.location.search);
    const raw =
      params.get('tk') || params.get('toolkits') || params.get('toolkit') || '';
    return raw
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
  }, []);

  const label = prettyToolkits(toolkits);
  const waPrimer =
    toolkits.length === 0
      ? 'connection landed'
      : `${prettyToolkits(toolkits).toLowerCase()} just connected`;
  const waUrl = useMemo(() => buildWaUrl(waPrimer), [waPrimer]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setOpening(true);
      window.location.href = waUrl;
    }, REDIRECT_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [waUrl]);

  return (
    <main
      style={{
        minHeight: '100dvh',
        background: 'var(--bg-paper, #f7f3e8)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '32px 24px',
      }}
    >
      <article
        style={{
          maxWidth: 420,
          width: '100%',
          padding: '32px 28px',
          background: 'var(--paper-100, #f5f0e3)',
          border: '1px solid var(--border-hairline, #e5e1d6)',
          borderRadius: 14,
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: 11,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--rust-700, #6a3a08)',
            fontWeight: 500,
            marginBottom: 14,
          }}
        >
          connected
        </div>
        <CheckMark />
        <h1
          style={{
            fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
            fontWeight: 400,
            fontSize: 26,
            lineHeight: 1.2,
            color: 'var(--ink-900, #1E1A18)',
            margin: '20px 0 8px',
            letterSpacing: '-0.015em',
          }}
        >
          {label} {toolkits.length === 1 ? 'is' : 'are'} on the line.
        </h1>
        <p
          style={{
            fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
            fontStyle: 'italic',
            fontSize: 16,
            lineHeight: 1.45,
            color: 'var(--ink-500, #6b6b6b)',
            margin: '0 0 24px',
          }}
        >
          opening whatsapp so we can pick up where we left off.
        </p>
        <a
          href={waUrl}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 18px',
            background: 'var(--rust-700, #6a3a08)',
            color: 'var(--paper-100, #f5f0e3)',
            fontFamily: 'var(--font-sans, "Red Hat Text", system-ui)',
            fontSize: 13,
            fontWeight: 500,
            borderRadius: 999,
            textDecoration: 'none',
            letterSpacing: '0.02em',
          }}
        >
          <WhatsAppGlyph />
          {opening ? 'opening…' : 'open whatsapp'}
        </a>
        <div
          style={{
            marginTop: 14,
            fontSize: 11,
            color: 'var(--ink-400, #9a9a9a)',
            letterSpacing: '0.04em',
          }}
        >
          {opening ? '' : 'redirects automatically'}
        </div>
      </article>
    </main>
  );
}

function CheckMark() {
  return (
    <svg width={48} height={48} viewBox="0 0 48 48" fill="none" aria-hidden>
      <circle
        cx={24}
        cy={24}
        r={22}
        stroke="var(--rust-700, #6a3a08)"
        strokeWidth={1.4}
        fill="var(--paper-50, #fbf8f0)"
      />
      <path
        d="M14 24.5l7 7 13-15"
        stroke="var(--rust-700, #6a3a08)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function WhatsAppGlyph() {
  return (
    <svg width={14} height={14} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M8 1.5a6.5 6.5 0 00-5.6 9.8L1.5 14.5l3.3-.9A6.5 6.5 0 108 1.5z"
        stroke="currentColor"
        strokeWidth="1.3"
        fill="none"
      />
    </svg>
  );
}
