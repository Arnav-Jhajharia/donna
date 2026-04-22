interface Props {
  title: string;
  right?: string;
}

export default function SectionHead({ title, right }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        paddingBottom: 8,
        borderBottom: '1px solid var(--border-hairline)',
      }}
    >
      <h3
        style={{
          margin: 0,
          fontFamily: 'var(--font-serif)',
          fontWeight: 500,
          fontSize: 18,
          letterSpacing: '-0.01em',
          color: 'var(--fg-primary)',
        }}
      >
        {title}
      </h3>
      {right && <span style={{ fontSize: 12, color: 'var(--fg-muted)' }}>{right}</span>}
    </div>
  );
}
