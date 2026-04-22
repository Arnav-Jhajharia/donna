'use client';

import { motion } from 'framer-motion';
import { ICONS } from '../icons';
import SectionHead from './SectionHead';
import type { SignalTone, TrackerGridBlock as TrackerGridSpec, TrackerItem } from '@/lib/plan';

const TONE_VAR: Record<SignalTone, string> = {
  ink: 'var(--fg-tertiary)',
  rust: 'var(--rust-700)',
  moss: 'var(--moss-700)',
  amber: 'var(--amber-700)',
  oxblood: 'var(--oxblood-700)',
};

const TINT_VAR: Record<TrackerItem['tint'], string> = {
  amber: 'var(--amber-100)',
  moss: 'var(--moss-100)',
  rust: 'var(--rust-100)',
  paper: 'var(--paper-400)',
};

export default function TrackerGridBlock({ spec }: { spec: TrackerGridSpec }) {
  const cols = Math.max(1, Math.min(spec.items.length, 3));
  return (
    <section style={{ margin: '26px 16px 0' }}>
      <SectionHead title={spec.title} />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gap: 10,
          marginTop: 12,
        }}
      >
        {spec.items.map((t) => (
          <TrackerCard key={t.id} item={t} />
        ))}
      </div>
    </section>
  );
}

function TrackerCard({ item }: { item: TrackerItem }) {
  const Icon = ICONS[item.icon];
  const tone = TONE_VAR[item.tone];
  const bg = TINT_VAR[item.tint];

  return (
    <div
      style={{
        background: bg,
        border: '1px solid var(--border-hairline)',
        borderRadius: 12,
        padding: '14px 14px 12px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 11.5, letterSpacing: '-0.005em', color: 'var(--fg-tertiary)', fontWeight: 500 }}>
          {item.title}
        </div>
        <Icon color={tone} />
      </div>
      <div>
        <div
          style={{
            fontFamily: 'var(--font-serif)',
            fontWeight: 500,
            fontSize: 28,
            lineHeight: 1,
            letterSpacing: '-0.02em',
            color: 'var(--fg-primary)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {item.value}
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--fg-muted)', marginTop: 4 }}>{item.unit}</div>
      </div>
      <div style={{ height: 3, background: 'var(--alpha-ink-08)', borderRadius: 2, overflow: 'hidden' }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${item.progress * 100}%` }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.25 }}
          style={{ height: '100%', background: tone }}
        />
      </div>
      <div style={{ fontSize: 12, color: 'var(--fg-tertiary)', lineHeight: 1.4 }}>{item.sub}</div>
    </div>
  );
}
