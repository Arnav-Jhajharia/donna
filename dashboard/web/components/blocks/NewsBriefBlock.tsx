'use client';

import { motion } from 'framer-motion';
import { ChevIcon, SparklesIcon } from '../icons';
import SectionHead from './SectionHead';
import { useAction } from '@/lib/action-context';
import type { NewsBriefBlock as NewsBriefSpec, NewsBriefItem } from '@/lib/plan';

/**
 * NewsBriefBlock — Donna surfaces 1–3 cards of curated content.
 * Each card is a single sharp sentence + the source domain. The judge
 * already silenced everything generic; what lands here earned its slot.
 */
export default function NewsBriefBlock({ spec }: { spec: NewsBriefSpec }) {
  return (
    <section style={{ margin: '26px 16px 0' }}>
      <SectionHead title={spec.title} right="picked for you" />
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {spec.items.map((n) => (
          <NewsCard key={n.id} item={n} />
        ))}
      </div>
    </section>
  );
}

function NewsCard({ item }: { item: NewsBriefItem }) {
  const fire = useAction();
  const tappable = Boolean(item.action) || Boolean(item.url);
  const onTap = () => {
    if (item.action) void fire(item.action);
    if (item.url) window.open(item.url, '_blank', 'noopener,noreferrer');
  };
  return (
    <motion.div
      whileTap={tappable ? { scale: 0.99 } : undefined}
      role={tappable ? 'button' : undefined}
      tabIndex={tappable ? 0 : undefined}
      onClick={tappable ? onTap : undefined}
      onKeyDown={
        tappable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onTap();
              }
            }
          : undefined
      }
      style={{
        background: 'var(--paper-50)',
        border: '1px solid var(--border-hairline)',
        borderRadius: 10,
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        cursor: tappable ? 'pointer' : 'default',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 10,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--rust-700)',
          fontWeight: 500,
        }}
      >
        <SparklesIcon size={11} color="var(--rust-700)" />
        {item.tag ?? 'today'}
        <span style={{ color: 'var(--fg-placeholder)' }}>·</span>
        <span style={{ color: 'var(--fg-muted)', textTransform: 'none', letterSpacing: 0 }}>{item.source}</span>
      </div>
      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 15.5,
          fontWeight: 500,
          letterSpacing: '-0.005em',
          lineHeight: 1.35,
          color: 'var(--fg-primary)',
        }}
      >
        {item.headline}
      </div>
      {tappable && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 12,
            color: 'var(--rust-700)',
            fontWeight: 500,
            marginTop: 2,
          }}
        >
          read
          <ChevIcon size={11} color="var(--rust-700)" />
        </div>
      )}
    </motion.div>
  );
}
