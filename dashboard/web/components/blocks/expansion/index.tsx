/**
 * React implementations of the six expansion blocks.
 *
 * See `dashboard/web/lib/expansion-blocks.ts` for types and
 * `donna-design-system/components.md` for layout contracts.
 *
 * Every block here uses only tokens from `globals.css`. No raw hex.
 * No arbitrary px font sizes — all type is `.type-*` utility classes.
 */

'use client';

import SectionHead from '../SectionHead';
import type {
  DryRunOfferBlock as DryRunOfferSpec,
  InvitationPromptBlock as InvitationPromptSpec,
  LifecycleBandBlock as LifecycleBandSpec,
  MiniStatGridBlock as MiniStatGridSpec,
  ProvenanceFactRowBlock as ProvenanceFactRowSpec,
  SparklineStatusBlock as SparklineStatusSpec,
} from '@/lib/expansion-blocks';

/* ───────── 1 · SparklineStatus ───────── */

const SPARK_HEIGHT: Record<SparklineStatusSpec['days'][number]['state'], number> = {
  hit: 22,
  half: 12,
  miss: 4,
};

const SPARK_COLOR: Record<SparklineStatusSpec['days'][number]['state'], string> = {
  hit: 'var(--color-ink)',
  half: 'var(--color-muted)',
  miss: 'var(--paper-500)',
};

export function SparklineStatusBlock({ spec }: { spec: SparklineStatusSpec }) {
  const pct = Math.round((spec.hitCount / spec.total) * 100);
  return (
    <section style={{ margin: 'var(--space-5) var(--space-4) 0', padding: 'var(--space-5)', background: 'var(--color-surface)', borderRadius: 'var(--radius-md)' }}>
      <SectionHead title={spec.title} />
      <div
        aria-label={`${spec.hitCount} of ${spec.total} · ${pct}%`}
        style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 28, marginTop: 'var(--space-3)' }}
      >
        {spec.days.map((d, i) => (
          <div
            key={i}
            style={{
              width: 6,
              height: SPARK_HEIGHT[d.state],
              background: SPARK_COLOR[d.state],
              borderRadius: 1,
            }}
          />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 'var(--space-3)' }}>
        <span className="type-small" style={{ color: 'var(--color-muted)' }}>{spec.window}</span>
        <span className="num-tabular type-small" style={{ color: 'var(--color-ink)' }}>
          {spec.hitCount} / {spec.total} · {pct}%
        </span>
      </div>
    </section>
  );
}

/* ───────── 2 · ProvenanceFactRow ───────── */

const PROV_SOURCE_LABEL: Record<ProvenanceFactRowSpec['rows'][number]['kind'], string> = {
  'told-me': 'told me',
  'observed': 'observed',
  'inferred': 'inferred',
  'from-calendar': 'from calendar',
  'from-email': 'from email',
  'from-chat': 'from chat',
  'auto': 'auto',
};

export function ProvenanceFactRowBlock({ spec }: { spec: ProvenanceFactRowSpec }) {
  return (
    <section style={{ margin: 'var(--space-5) var(--space-4) 0', padding: 'var(--space-5)', background: 'var(--color-surface)', borderRadius: 'var(--radius-md)' }}>
      {spec.title && <SectionHead title={spec.title} />}
      <div style={{ marginTop: 'var(--space-3)' }}>
        {spec.rows.map((row, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '96px 1fr',
              gap: 'var(--space-5)',
              padding: 'var(--space-3) 0',
              borderBottom: i < spec.rows.length - 1 ? '1px solid var(--ink-300)' : 'none',
              alignItems: 'baseline',
            }}
          >
            <span className="type-label">{row.key}</span>
            <div>
              <div style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 'var(--type-body-size)',
                lineHeight: 'var(--type-body-line)',
                color: 'var(--color-ink)',
              }}>
                {row.value}
              </div>
              <div className="type-caption" style={{ color: 'var(--color-muted)', marginTop: 2 }}>
                {PROV_SOURCE_LABEL[row.kind]}
                <span style={{ opacity: 0.5, margin: '0 var(--space-1)' }}>·</span>
                {row.detail}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ───────── 3 · DryRunOffer · the promotion ritual ───────── */

export function DryRunOfferBlock({ spec }: { spec: DryRunOfferSpec }) {
  return (
    <section
      style={{
        margin: 'var(--space-5) var(--space-4) 0',
        padding: 'var(--space-5)',
        background: 'var(--color-paper)',
        border: '1px solid var(--ink-300)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-3)' }}>
        <span className="type-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span style={{ display: 'inline-block', width: 5, height: 5, borderRadius: 9999, background: 'var(--color-muted)' }} />
          {spec.status}
        </span>
        <span
          className="type-caption"
          style={{
            fontFamily: 'var(--font-mono)',
            color: 'var(--color-muted)',
            padding: '2px var(--space-2)',
            border: '1px solid var(--ink-300)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          {spec.kind}
        </span>
      </div>

      <h4 className="type-h4" style={{ marginTop: 'var(--space-3)', color: 'var(--color-ink)' }}>
        {spec.headline.prefix}
        <em className="italic-accent-inline" style={{ color: 'var(--color-rust)' }}>
          {spec.headline.accent}
        </em>
        {spec.headline.suffix ?? ''}
      </h4>

      <p className="type-body" style={{ color: 'var(--color-ink)', marginTop: 'var(--space-2)' }}>
        {spec.body}
      </p>
      <div className="type-caption" style={{ color: 'var(--color-muted)', marginTop: 'var(--space-2)' }}>
        sources · {spec.sources.join(' · ')}
      </div>

      <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-5)' }}>
        <button
          className="type-button"
          style={{
            background: 'var(--color-rust)',
            color: 'var(--color-paper)',
            border: 0,
            padding: '8px 16px',
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
          }}
        >
          {spec.actions.live}
        </button>
        <button
          className="type-button"
          style={{
            background: 'transparent',
            color: 'var(--color-ink)',
            border: 0,
            padding: '8px 16px',
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
          }}
        >
          {spec.actions.tweak}
        </button>
        <button
          className="type-button"
          style={{
            background: 'transparent',
            color: 'var(--color-ink)',
            border: 0,
            padding: '8px 16px',
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
          }}
        >
          {spec.actions.dismiss}
        </button>
      </div>
    </section>
  );
}

/* ───────── 4 · LifecycleBand · state-grouped header ───────── */

const LIFECYCLE_BORDER: Record<LifecycleBandSpec['state'], string> = {
  living:   'var(--color-rust)',
  today:    'var(--color-ink)',
  live:     'var(--signal-success)',
  shadow:   'var(--color-muted)',
  paused:   'var(--signal-warning)',
  resolved: 'var(--ink-300)',
};

const LIFECYCLE_TEXT: Record<LifecycleBandSpec['state'], string> = {
  living:   'var(--color-rust)',
  today:    'var(--color-ink)',
  live:     'var(--signal-success)',
  shadow:   'var(--color-muted)',
  paused:   'var(--signal-warning)',
  resolved: 'var(--color-muted)',
};

export function LifecycleBandBlock({ spec }: { spec: LifecycleBandSpec }) {
  if (spec.count === 0) return null;
  return (
    <div
      style={{
        margin: 'var(--space-4) var(--space-4) 0',
        padding: 'var(--space-3) var(--space-3) var(--space-2)',
        borderTop: '1px solid var(--ink-300)',
        borderBottom: '1px solid var(--ink-300)',
        borderLeft: `2px solid ${LIFECYCLE_BORDER[spec.state]}`,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
      }}
    >
      <span
        className="type-label"
        style={{ color: LIFECYCLE_TEXT[spec.state] }}
      >
        {spec.label}
      </span>
      <span
        className="num-tabular type-small"
        style={{ color: 'var(--color-muted)' }}
      >
        {spec.count}
      </span>
    </div>
  );
}

/* ───────── 5 · InvitationPrompt · bootstrap ───────── */

export function InvitationPromptBlock({ spec }: { spec: InvitationPromptSpec }) {
  return (
    <section style={{ margin: 'var(--space-5) var(--space-4) 0', padding: 'var(--space-5)', background: 'var(--color-surface)', borderRadius: 'var(--radius-md)' }}>
      <span className="type-label">{spec.eyebrow}</span>
      <h3
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 'var(--type-h3-size)',
          lineHeight: 'var(--type-h3-line)',
          fontWeight: 500,
          letterSpacing: 'var(--type-h3-track)',
          margin: 'var(--space-2) 0 0',
          color: 'var(--color-ink)',
        }}
      >
        <em className="italic-accent-heading" style={{ color: 'var(--color-rust)' }}>{spec.verb}</em>
        {' '}something.
      </h3>
      <div
        style={{
          marginTop: 'var(--space-4)',
          padding: 'var(--space-3) var(--space-4)',
          background: 'var(--color-paper)',
          border: '1px solid var(--ink-300)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--color-muted)',
        }}
      >
        <span className="type-input">{spec.placeholder}</span>
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            width: 1,
            height: 14,
            background: 'var(--color-ink)',
            verticalAlign: 'middle',
          }}
        />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginTop: 'var(--space-3)' }}>
        {spec.hints.slice(0, 4).map((h) => (
          <span
            key={h}
            className="type-small"
            style={{
              color: 'var(--color-muted)',
              padding: '2px var(--space-3)',
              border: '1px solid var(--ink-300)',
              borderRadius: 9999,
              cursor: 'pointer',
            }}
          >
            {h}
          </span>
        ))}
      </div>
    </section>
  );
}

/* ───────── 6 · MiniStatGrid · three tallies in one card ───────── */

export function MiniStatGridBlock({ spec }: { spec: MiniStatGridSpec }) {
  return (
    <section
      style={{
        margin: 'var(--space-5) var(--space-4) 0',
        padding: 'var(--space-4) 0',
        background: 'var(--color-surface)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)' }}>
        {spec.cells.map((cell, i) => (
          <div
            key={cell.key}
            style={{
              padding: 'var(--space-3) var(--space-4)',
              borderRight: i < 2 ? '1px solid var(--ink-300)' : 'none',
            }}
          >
            <div className="type-label">{cell.key}</div>
            <div
              className="num-tabular"
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 26,
                lineHeight: 1,
                fontWeight: 500,
                letterSpacing: '-0.02em',
                marginTop: 'var(--space-2)',
                color: 'var(--color-ink)',
              }}
            >
              {cell.value}
              {cell.total && (
                <span className="type-small" style={{ color: 'var(--color-muted)' }}>
                  {cell.total}
                </span>
              )}
            </div>
            <div className="type-caption" style={{ color: 'var(--color-muted)', marginTop: 2 }}>
              {cell.sub}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
