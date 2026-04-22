interface Props {
  initial: string;
}

export default function TopBar({ initial }: Props) {
  return (
    <div
      style={{
        padding: '8px 22px 14px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-serif)',
          fontStyle: 'italic',
          fontWeight: 500,
          fontSize: 22,
          letterSpacing: '-0.015em',
          color: 'var(--fg-primary)',
          display: 'inline-flex',
          alignItems: 'baseline',
          gap: 2,
        }}
      >
        donna
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: 999,
            background: 'var(--rust-700)',
            display: 'inline-block',
            marginLeft: 2,
            transform: 'translateY(-1px)',
          }}
        />
      </span>
      <div
        style={{
          width: 30,
          height: 30,
          borderRadius: 999,
          background: 'var(--bg-surface)',
          color: 'var(--fg-tertiary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 13,
          fontWeight: 500,
          border: '1px solid var(--border-hairline)',
        }}
      >
        {initial}
      </div>
    </div>
  );
}
