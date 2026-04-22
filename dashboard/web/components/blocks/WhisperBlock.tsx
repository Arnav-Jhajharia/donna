import type { WhisperBlock as WhisperBlockSpec } from '@/lib/plan';

export default function WhisperBlock({ spec }: { spec: WhisperBlockSpec }) {
  const loud = spec.level === 'loud';
  return (
    <div
      style={{
        margin: '16px 16px 0',
        padding: loud ? '14px 16px' : '10px 14px',
        background: 'var(--rust-100)',
        borderLeft: '2px solid var(--rust-700)',
        borderRadius: 2,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--rust-700)',
          fontWeight: 500,
          marginBottom: 4,
        }}
      >
        {spec.kicker}
      </div>
      <div
        style={{
          fontSize: loud ? 14 : 13.5,
          lineHeight: 1.5,
          color: 'var(--fg-primary)',
          letterSpacing: '-0.005em',
        }}
      >
        {spec.body}
      </div>
    </div>
  );
}
