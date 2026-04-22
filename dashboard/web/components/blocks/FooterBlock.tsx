import type { FooterBlock as FooterSpec } from '@/lib/plan';

export default function FooterBlock({ spec }: { spec: FooterSpec }) {
  return (
    <div
      style={{
        textAlign: 'center',
        fontSize: 11,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: 'var(--fg-placeholder)',
        fontWeight: 500,
        padding: '16px 0 8px',
      }}
    >
      {spec.text}
    </div>
  );
}
