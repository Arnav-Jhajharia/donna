'use client';

import { motion } from 'framer-motion';
import { ChevIcon } from '../icons';
import SectionHead from './SectionHead';
import { useAction } from '@/lib/action-context';
import type { RelationshipBlock as RelationshipSpec, RelationshipItem } from '@/lib/plan';

export default function RelationshipBlock({ spec }: { spec: RelationshipSpec }) {
  return (
    <section style={{ margin: '26px 16px 0' }}>
      <SectionHead title={spec.title} right={`${spec.items.length} on your mind`} />
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {spec.items.map((p) => (
          <PersonRow key={p.id} person={p} />
        ))}
      </div>
    </section>
  );
}

function PersonRow({ person }: { person: RelationshipItem }) {
  const fire = useAction();
  const tappable = Boolean(person.action);
  const onTap = () => {
    if (person.action) void fire(person.action);
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
        display: 'grid',
        gridTemplateColumns: '38px 1fr auto',
        gap: 12,
        padding: '10px 12px',
        background: 'var(--paper-50)',
        border: '1px solid var(--border-hairline)',
        borderRadius: 10,
        alignItems: 'center',
        cursor: tappable ? 'pointer' : 'default',
      }}
    >
      <div
        style={{
          width: 38,
          height: 38,
          borderRadius: 999,
          background: 'var(--paper-300)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'var(--font-serif)',
          fontWeight: 500,
          fontSize: 16,
          color: 'var(--rust-700)',
          letterSpacing: '-0.01em',
        }}
      >
        {person.initial}
      </div>
      <div>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 6,
            fontFamily: 'var(--font-serif)',
            fontSize: 16,
            fontWeight: 500,
            color: 'var(--fg-primary)',
            letterSpacing: '-0.005em',
            lineHeight: 1.2,
          }}
        >
          {person.name}
          {person.role && (
            <span
              style={{
                fontFamily: 'var(--font-sans)',
                fontStyle: 'normal',
                fontSize: 11,
                fontWeight: 400,
                color: 'var(--fg-muted)',
              }}
            >
              · {person.role}
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 2 }}>
          {person.lastTouch}
          {person.nudge && (
            <>
              {' '}
              <span style={{ color: 'var(--rust-700)', fontWeight: 500 }}>· {person.nudge}</span>
            </>
          )}
        </div>
      </div>
      {tappable && <ChevIcon size={13} color="var(--fg-placeholder)" />}
    </motion.div>
  );
}
