/**
 * Catalogue archetype #04 — Tracker.
 * Three variants: pair (canonical) · borderless (editorial rows) · hero (single, big).
 */

import type { CSSProperties } from 'react';
import { cIcons, type CatIconName } from './icons';
import { SERIF, SANS, BORDER, Eyebrow, SectionHead } from './atoms';
import { BlockActions } from './CatBlocks';

export type TrackerTint = 'amber' | 'paper' | 'rust' | 'moss';
const tintToBg: Record<TrackerTint, string> = {
  amber: 'var(--amber-100)',
  paper: 'var(--paper-400)',
  rust: 'var(--rust-100)',
  moss: 'var(--moss-100)',
};
const tintToBar: Record<TrackerTint, string> = {
  amber: 'var(--amber-700)',
  paper: 'var(--ink-700)',
  rust: 'var(--rust-700)',
  moss: 'var(--moss-700)',
};
const tintToIcon: Record<TrackerTint, string> = {
  amber: 'var(--amber-700)',
  paper: 'var(--ink-700)',
  rust: 'var(--rust-700)',
  moss: 'var(--moss-700)',
};

export interface TrackerCatItem {
  label: string;
  value: string;
  unit: string;
  detail?: string;
  progress: number; // 0..1
  icon: CatIconName;
  tint: TrackerTint;
}

export interface CatTrackerSpec {
  type: 'c-tracker';
  variant: 'pair' | 'borderless' | 'hero';
  title?: string;
  right?: string;
  items: TrackerCatItem[];
  // hero variant additions
  history?: number[]; // 7 values
  todayIndex?: number; // index of today in history
  weekLabels?: string[]; // 7 single-letter day labels
  /** Optional footer actions, rendered as ActionChips. */
  actions?: import('@/lib/plan').ActionVerb[];
}

export default function CatTracker({ spec }: { spec: CatTrackerSpec }) {
  return (
    <>
      {spec.variant === 'borderless' ? (
        <Borderless spec={spec} />
      ) : spec.variant === 'hero' ? (
        <Hero spec={spec} />
      ) : (
        <Pair spec={spec} />
      )}
      <BlockActions actions={spec.actions} />
    </>
  );
}

// ─── pair (canonical morning trackers) ────────────────────────────────────
function Pair({ spec }: { spec: CatTrackerSpec }) {
  return (
    <div style={{ margin: '12px 16px 0' }}>
      <SectionHead title={spec.title ?? 'your body, your money'} right={spec.right} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 12 }}>
        {spec.items.slice(0, 2).map((it, i) => (
          <Tile key={i} item={it} />
        ))}
      </div>
    </div>
  );
}

function Tile({ item }: { item: TrackerCatItem }) {
  const Icon = cIcons[item.icon];
  return (
    <div
      style={{
        background: tintToBg[item.tint],
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        padding: '14px 14px 12px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-700)', fontWeight: 500 }}>
          {item.label}
        </span>
        <Icon s={16} c={tintToIcon[item.tint]} />
      </div>
      <div>
        <div
          style={{
            fontFamily: SERIF,
            fontSize: 28,
            fontWeight: 500,
            lineHeight: 1,
            color: 'var(--ink-900)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {item.value}
        </div>
        <div style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-500)', marginTop: 4 }}>
          {item.unit}
        </div>
      </div>
      <div
        style={{
          height: 3,
          background: 'rgba(30,26,24,0.08)',
          borderRadius: 2,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${Math.max(0, Math.min(1, item.progress)) * 100}%`,
            height: '100%',
            background: tintToBar[item.tint],
          }}
        />
      </div>
      {item.detail && (
        <div style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-700)' }}>{item.detail}</div>
      )}
    </div>
  );
}

// ─── borderless rows (editorial, no card) ────────────────────────────────
function Borderless({ spec }: { spec: CatTrackerSpec }) {
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead title={spec.title ?? "what i'm tracking"} right={spec.right} />
      <div style={{ marginTop: 8 }}>
        {spec.items.map((it, i) => (
          <Row key={i} item={it} />
        ))}
      </div>
    </div>
  );
}

function Row({ item }: { item: TrackerCatItem }) {
  return (
    <div style={{ padding: '14px 0', borderBottom: `1px solid ${BORDER}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)' }}>{item.label}</span>
        <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--ink-400)' }}>{item.unit}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 4 }}>
        <span
          style={{
            fontFamily: SERIF,
            fontSize: 34,
            fontWeight: 500,
            lineHeight: 1,
            color: 'var(--ink-900)',
            fontVariantNumeric: 'tabular-nums',
            letterSpacing: '-0.02em',
          }}
        >
          {item.value}
        </span>
        <div
          style={{
            flex: 1,
            height: 2,
            background: 'rgba(30,26,24,0.08)',
            position: 'relative',
            top: -4,
          }}
        >
          <div
            style={{
              width: `${Math.max(0, Math.min(1, item.progress)) * 100}%`,
              height: '100%',
              background: tintToBar[item.tint],
            }}
          />
        </div>
      </div>
    </div>
  );
}

// ─── hero single (one tracker, big, with history bars) ──────────────────
function Hero({ spec }: { spec: CatTrackerSpec }) {
  const item = spec.items[0];
  if (!item) return null;
  const dots = spec.history ?? [4, 6, 7, 5, 3, 8, 2];
  const today = spec.todayIndex ?? 6;
  const labels = spec.weekLabels ?? ['s', 'm', 't', 'w', 't', 'f', 's'];
  // Split a "value/limit" pair if value contains "/"
  const numeric = item.value.split('/')[0] ?? item.value;
  const limit = item.value.includes('/') ? `/${item.value.split('/')[1]}` : '';
  return (
    <div style={{ margin: '12px 16px 0' }}>
      <SectionHead title={spec.title ?? item.label} right={spec.right ?? 'today'} />
      <div
        style={{
          marginTop: 12,
          padding: '16px 16px 14px',
          background: 'var(--paper-50)',
          border: `1px solid ${BORDER}`,
          borderRadius: 14,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14 }}>
          <div
            style={{
              fontFamily: SERIF,
              fontWeight: 500,
              fontSize: 62,
              lineHeight: 0.9,
              color: 'var(--ink-900)',
              letterSpacing: '-0.03em',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {numeric}
            {limit && (
              <span style={{ fontSize: 24, color: 'var(--ink-400)', marginLeft: 4 }}>{limit}</span>
            )}
          </div>
          <div style={{ paddingBottom: 8 }}>
            <Eyebrow tone={tintToBar[item.tint]}>{item.unit}</Eyebrow>
            {item.detail && (
              <div style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', marginTop: 3 }}>
                {item.detail}
              </div>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 14, alignItems: 'flex-end', height: 38 }}>
          {dots.map((v, i) => (
            <div
              key={i}
              style={{
                flex: 1,
                height: `${(v / Math.max(...dots)) * 100}%`,
                background: i === today ? tintToBar[item.tint] : 'var(--paper-400)',
                borderRadius: 2,
              }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          {labels.map((d, i) => (
            <span
              key={i}
              style={{
                fontFamily: SANS,
                fontSize: 10,
                color: i === today ? tintToBar[item.tint] : 'var(--ink-400)',
                fontWeight: 500,
                flex: 1,
                textAlign: 'center',
              }}
            >
              {d}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
