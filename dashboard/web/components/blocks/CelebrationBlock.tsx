import type { CelebrationBlock as CelebrationBlockSpec } from '@/lib/plan';

export default function CelebrationBlock({ spec }: { spec: CelebrationBlockSpec }) {
  return (
    <div
      style={{
        margin: '14px 16px 0',
        padding: '14px 16px',
        background: 'var(--moss-100)',
        border: '1px solid rgba(92,107,74,0.18)',
        borderRadius: 10,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          marginBottom: 6,
        }}
      >
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'var(--moss-700)',
            fontWeight: 600,
          }}
        >
          landed
        </div>
        {spec.badge && (
          <div
            style={{
              fontSize: 11,
              color: 'var(--moss-700)',
              background: 'rgba(92,107,74,0.14)',
              padding: '3px 8px',
              borderRadius: 99,
              fontWeight: 500,
              letterSpacing: '-0.005em',
            }}
          >
            {spec.badge}
          </div>
        )}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 18,
          fontWeight: 500,
          lineHeight: 1.22,
          letterSpacing: '-0.015em',
          color: 'var(--fg-primary)',
          marginBottom: 4,
        }}
      >
        {spec.title}
      </div>
      <div style={{ fontSize: 13.5, lineHeight: 1.5, color: 'var(--fg-secondary)' }}>
        {spec.body}
      </div>
    </div>
  );
}
