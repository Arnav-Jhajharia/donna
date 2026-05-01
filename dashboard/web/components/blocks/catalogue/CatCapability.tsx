'use client';

/**
 * Catalogue archetype #22 — Capability.
 *
 * The dashboard's command palette. Renders a list of verbs Donna can do
 * for the user given today's context — "draft an email to mom", "check my
 * inbox", "log a glass", "summarize my week". Tapping a chip opens a
 * WhatsApp deeplink with the `intent` pre-filled, so Donna receives the
 * request and does the thing.
 *
 * Two variants:
 *   chips — compact pill row, 1 line each. for many items.
 *   rows  — fuller list with icons + arrow chevs. for fewer, weightier verbs.
 */

import { cIcons, type CatIconName } from './icons';
import { SERIF, SANS, BORDER, BORDER_STRONG, Eyebrow, SectionHead } from './atoms';
import type { CatCapabilitySpec } from '@/lib/plan';

const WA_DEFAULT = 'https://wa.me/';

function buildWaUrl(intent: string): string {
  const base = (process.env.NEXT_PUBLIC_WA_URL || WA_DEFAULT).replace(/\/$/, '');
  const sep = base.includes('?') ? '&' : '?';
  return `${base}${sep}text=${encodeURIComponent(intent)}`;
}

export default function CatCapability({ spec }: { spec: CatCapabilitySpec }) {
  if (spec.variant === 'rows') return <Rows spec={spec} />;
  return <Chips spec={spec} />;
}

function Chips({ spec }: { spec: CatCapabilitySpec }) {
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow tone="var(--rust-700)">{spec.eyebrow ?? 'i can'}</Eyebrow>
      {spec.title && (
        <div
          style={{
            fontFamily: SERIF,
            fontSize: 18,
            fontWeight: 500,
            color: 'var(--ink-900)',
            marginTop: 4,
            letterSpacing: '-0.01em',
            lineHeight: 1.2,
          }}
        >
          {spec.title}
        </div>
      )}
      <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {spec.items.map((it, i) => {
          const Icon = it.icon ? cIcons[it.icon as CatIconName] : null;
          return (
            <a
              key={i}
              href={buildWaUrl(it.intent)}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '7px 12px',
                borderRadius: 999,
                background: 'var(--paper-100)',
                border: `1px solid ${BORDER_STRONG}`,
                fontFamily: SANS,
                fontSize: 12.5,
                color: 'var(--ink-900)',
                fontWeight: 500,
                textDecoration: 'none',
                cursor: 'pointer',
              }}
            >
              {Icon && <Icon s={13} c="var(--ink-700)" />}
              {it.label}
            </a>
          );
        })}
      </div>
    </div>
  );
}

function Rows({ spec }: { spec: CatCapabilitySpec }) {
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead title={spec.title ?? "things i can do for you"} />
      <div style={{ marginTop: 6 }}>
        {spec.items.map((it, i) => {
          const Icon = it.icon ? cIcons[it.icon as CatIconName] : null;
          return (
            <a
              key={i}
              href={buildWaUrl(it.intent)}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'grid',
                gridTemplateColumns: '20px 1fr 12px',
                gap: 12,
                padding: '12px 0',
                borderBottom: `1px solid ${BORDER}`,
                alignItems: 'center',
                textDecoration: 'none',
                color: 'inherit',
              }}
            >
              <span style={{ display: 'inline-flex' }}>
                {Icon ? (
                  <Icon s={16} c="var(--rust-700)" />
                ) : (
                  <span style={{ width: 6, height: 6, borderRadius: 999, background: 'var(--rust-700)', marginLeft: 6 }} />
                )}
              </span>
              <span
                style={{
                  fontFamily: SANS,
                  fontSize: 13.5,
                  color: 'var(--ink-900)',
                  fontWeight: 500,
                }}
              >
                {it.label}
              </span>
              <cIcons.chev s={11} c="var(--ink-400)" />
            </a>
          );
        })}
      </div>
    </div>
  );
}
