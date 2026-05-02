'use client';

import { motion } from 'framer-motion';
import { useState, type ReactNode } from 'react';
import type { Domain } from '@/lib/plan';

/**
 * A rail per user-side surface (body, people, work, money, mind, day).
 *
 * Two states:
 *   - **active**: at least one block has signal → renders the header +
 *     all child blocks
 *   - **quiet**: no child blocks → renders a single collapsed line
 *     ("no spend logged today · log spend") that the user can tap
 *
 * The rail header is the editorial signal that the dashboard is
 * organised around the user's life, not around our schema. Each rail
 * carries a tiny tone tint (moss/amber/rust) to make scanning easy.
 */

const DOMAIN_LABEL: Record<Domain, string> = {
  body: 'body',
  people: 'people',
  work: 'work',
  money: 'money',
  mind: 'mind',
  day: 'today',
};

const DOMAIN_TINT: Record<Domain, string> = {
  body: 'var(--moss-700, #4a6534)',
  people: 'var(--rust-700, #6a3a08)',
  work: 'var(--ink-800, #2a2a2a)',
  money: 'var(--amber-700, #6a4308)',
  mind: 'var(--rust-500, #b07030)',
  day: 'var(--ink-700, #3a3a3a)',
};

const DOMAIN_QUIET_PROMPT: Record<Domain, string> = {
  body: 'nothing logged yet today.',
  people: 'no one needs you right now.',
  work: 'no open commitments today.',
  money: 'no spend logged today.',
  mind: 'a quiet mind is a fine thing.',
  day: 'tomorrow is unwritten.',
};

const DOMAIN_QUIET_CTA: Record<Domain, string | null> = {
  body: 'log a meal',
  people: null,
  work: null,
  money: 'log spend',
  mind: 'reflect for 30 seconds',
  day: null,
};

export function DomainRail({
  domain,
  children,
  hasContent,
  onQuietTap,
}: {
  domain: Domain;
  children: ReactNode;
  hasContent: boolean;
  onQuietTap?: () => void;
}) {
  const [expanded, setExpanded] = useState(hasContent);

  if (!hasContent) {
    return (
      <button
        type="button"
        onClick={() => {
          setExpanded((v) => !v);
          onQuietTap?.();
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          width: '100%',
          padding: '12px 22px',
          background: 'transparent',
          border: 'none',
          borderTop: '1px solid var(--border-hairline, #e5e1d6)',
          fontFamily: 'inherit',
          textAlign: 'left',
          cursor: DOMAIN_QUIET_CTA[domain] ? 'pointer' : 'default',
          gap: 12,
        }}
      >
        <RailHeader domain={domain} muted />
        <span
          style={{
            color: 'var(--ink-500, #6b6b6b)',
            fontSize: 13,
            flex: 1,
          }}
        >
          {DOMAIN_QUIET_PROMPT[domain]}
        </span>
        {DOMAIN_QUIET_CTA[domain] && (
          <span
            style={{
              color: 'var(--rust-700, #6a3a08)',
              fontSize: 11,
              letterSpacing: '0.06em',
              fontWeight: 500,
            }}
          >
            {DOMAIN_QUIET_CTA[domain]} →
          </span>
        )}
      </button>
    );
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      style={{
        borderTop: '1px solid var(--border-hairline, #e5e1d6)',
        paddingTop: 14,
        marginTop: 4,
      }}
    >
      <div style={{ padding: '0 22px 8px' }}>
        <RailHeader domain={domain} />
      </div>
      <div>{children}</div>
    </motion.section>
  );
}

function RailHeader({ domain, muted }: { domain: Domain; muted?: boolean }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: 999,
          background: muted
            ? 'var(--ink-300, #c2bdb1)'
            : DOMAIN_TINT[domain],
        }}
      />
      <span
        style={{
          fontSize: 10,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color: muted
            ? 'var(--ink-500, #6b6b6b)'
            : DOMAIN_TINT[domain],
          fontWeight: 600,
        }}
      >
        {DOMAIN_LABEL[domain]}
      </span>
    </div>
  );
}

export const ALL_DOMAINS: Domain[] = ['day', 'body', 'work', 'people', 'money', 'mind'];
