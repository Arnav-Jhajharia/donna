import type { ThesisBlock as ThesisBlockSpec } from '@/lib/plan';

export default function ThesisBlock({ spec }: { spec: ThesisBlockSpec }) {
  return (
    <div style={{ margin: '20px 16px 4px', padding: '2px 6px' }}>
      {spec.kicker && (
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--fg-placeholder)',
            fontWeight: 500,
            marginBottom: 8,
          }}
        >
          {spec.kicker}
        </div>
      )}
      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontStyle: 'italic',
          fontWeight: 400,
          fontSize: 22,
          lineHeight: 1.28,
          letterSpacing: '-0.015em',
          color: 'var(--fg-primary)',
        }}
      >
        {spec.sentence}
      </div>
    </div>
  );
}
