'use client';

import { motion } from 'framer-motion';
import { ChevIcon, ICONS } from '../icons';
import SectionHead from './SectionHead';
import type { NudgeGridBlock as NudgeGridSpec, NudgeItem, NudgeVariant } from '@/lib/plan';

interface Palette {
  bg: string;
  iconBg: string;
  tone: string;
}

const PALETTE: Record<Exclude<NudgeVariant, 'featured'>, Palette> = {
  neutral: { bg: 'var(--bg-surface)', iconBg: 'var(--paper-400)', tone: 'var(--fg-primary)' },
  moss:    { bg: 'var(--moss-100)',   iconBg: 'var(--paper-100)', tone: 'var(--moss-700)' },
  amber:   { bg: 'var(--amber-100)',  iconBg: 'var(--paper-100)', tone: 'var(--amber-700)' },
};

export default function NudgeGridBlock({ spec }: { spec: NudgeGridSpec }) {
  return (
    <section style={{ margin: '26px 16px 24px' }}>
      <SectionHead title={spec.title} right={String(spec.items.length)} />
      <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {spec.items.map((n) => (
          <NudgeTile key={n.id} item={n} />
        ))}
      </div>
    </section>
  );
}

function NudgeTile({ item }: { item: NudgeItem }) {
  const Icon = ICONS[item.icon];

  if (item.variant === 'featured') {
    return (
      <div
        style={{
          background: 'var(--rust-700)',
          color: 'var(--paper-100)',
          border: '1px solid var(--rust-900)',
          borderRadius: 10,
          padding: '12px 12px 10px',
          minHeight: 124,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 6,
              background: 'rgba(251,247,245,0.14)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon color="var(--paper-100)" />
          </div>
          <div
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 17,
              fontWeight: 500,
              letterSpacing: '-0.01em',
              marginTop: 10,
              lineHeight: 1.15,
              color: 'var(--paper-100)',
            }}
          >
            {item.title}
          </div>
          <div style={{ fontSize: 12, marginTop: 3, color: 'rgba(251,247,245,0.75)', lineHeight: 1.4 }}>
            {item.meta}
          </div>
        </div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 500,
            color: 'var(--paper-100)',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            marginTop: 8,
            letterSpacing: '-0.005em',
          }}
        >
          {item.cta}
          <ChevIcon size={11} color="var(--paper-100)" />
        </div>
      </div>
    );
  }

  const p = PALETTE[item.variant];
  return (
    <div
      style={{
        background: p.bg,
        border: '1px solid var(--border-hairline)',
        borderRadius: 10,
        padding: '12px 12px 10px',
        minHeight: 124,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}
    >
      <div>
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            background: p.iconBg,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Icon color={p.tone} />
        </div>
        <div
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 17,
            fontWeight: 500,
            letterSpacing: '-0.01em',
            marginTop: 10,
            lineHeight: 1.15,
            color: 'var(--fg-primary)',
          }}
        >
          {item.title}
        </div>
        <div style={{ fontSize: 12, marginTop: 3, color: 'var(--fg-muted)', lineHeight: 1.4 }}>{item.meta}</div>
      </div>
      {item.progress !== undefined && (
        <div style={{ height: 3, background: 'var(--alpha-ink-08)', borderRadius: 2, overflow: 'hidden', marginTop: 8 }}>
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${item.progress * 100}%` }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.35 }}
            style={{ height: '100%', background: p.tone }}
          />
        </div>
      )}
      <div
        style={{
          fontSize: 12,
          fontWeight: 500,
          color: p.tone,
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          marginTop: 8,
          letterSpacing: '-0.005em',
        }}
      >
        {item.cta}
        <ChevIcon size={11} color={p.tone} />
      </div>
    </div>
  );
}
