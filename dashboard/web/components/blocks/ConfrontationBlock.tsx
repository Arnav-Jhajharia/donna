import type { ConfrontationBlock as ConfrontationBlockSpec } from '@/lib/plan';

export default function ConfrontationBlock({ spec }: { spec: ConfrontationBlockSpec }) {
  return (
    <div
      style={{
        margin: '16px 16px 0',
        padding: '16px 18px',
        background: 'var(--oxblood-100)',
        borderLeft: '3px solid var(--oxblood-700)',
        borderRadius: 2,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'var(--oxblood-700)',
          fontWeight: 600,
          marginBottom: 8,
        }}
      >
        honest
      </div>
      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 18,
          fontWeight: 500,
          lineHeight: 1.22,
          letterSpacing: '-0.015em',
          color: 'var(--fg-primary)',
          marginBottom: 8,
        }}
      >
        {spec.title}
      </div>
      <div style={{ fontSize: 13.5, lineHeight: 1.5, color: 'var(--fg-secondary)' }}>
        {spec.body}
      </div>
      {spec.ask && (
        <div
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: '1px solid rgba(139,58,46,0.2)',
            fontSize: 12.5,
            color: 'var(--oxblood-700)',
            fontWeight: 500,
            letterSpacing: '-0.005em',
          }}
        >
          {spec.ask}
        </div>
      )}
    </div>
  );
}
