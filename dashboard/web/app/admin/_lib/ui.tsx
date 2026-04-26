import { ReactNode } from 'react';

export function Section({
  title,
  children,
  right,
}: {
  title: string;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section style={{ marginBottom: 28 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <h2
          style={{
            fontSize: 14,
            color: '#aaa',
            textTransform: 'uppercase',
            letterSpacing: 1.2,
            margin: 0,
          }}
        >
          {title}
        </h2>
        {right ? <div style={{ fontSize: 12, color: '#666' }}>{right}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Card({
  children,
  pad = 16,
}: {
  children: ReactNode;
  pad?: number;
}) {
  return (
    <div
      style={{
        background: '#111',
        border: '1px solid #222',
        borderRadius: 8,
        padding: pad,
      }}
    >
      {children}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: '#666', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{ fontSize: 18, color: '#fff', marginTop: 4 }}>{value}</div>
    </div>
  );
}

export function Pill({
  children,
  color = '#444',
}: {
  children: ReactNode;
  color?: string;
}) {
  return (
    <span
      style={{
        background: color,
        color: '#fff',
        fontSize: 11,
        padding: '2px 8px',
        borderRadius: 4,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
      }}
    >
      {children}
    </span>
  );
}

export function Json({ value }: { value: unknown }) {
  return (
    <pre
      style={{
        background: '#000',
        border: '1px solid #222',
        borderRadius: 6,
        padding: 12,
        fontSize: 12,
        color: '#9bc',
        overflow: 'auto',
        maxHeight: 400,
        margin: 0,
      }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function NavTabs({
  userId,
  active,
}: {
  userId: string;
  active: string;
}) {
  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'integrations', label: 'Integrations' },
    { key: 'proactive', label: 'Pings' },
    { key: 'tools', label: 'Tools' },
    { key: 'turns', label: 'Turns' },
    { key: 'memory', label: 'Memory' },
    { key: 'email', label: 'Email' },
    { key: 'calendar', label: 'Calendar' },
    { key: 'attentions', label: 'Attentions' },
    { key: 'chat', label: 'Chat' },
    { key: 'raw', label: 'Raw' },
  ];
  return (
    <nav
      style={{
        display: 'flex',
        gap: 4,
        flexWrap: 'wrap',
        marginBottom: 20,
        paddingBottom: 12,
        borderBottom: '1px solid #222',
      }}
    >
      {tabs.map((t) => (
        <a
          key={t.key}
          href={`/admin/${encodeURIComponent(userId)}/${
            t.key === 'overview' ? '' : t.key
          }`}
          style={{
            padding: '6px 12px',
            fontSize: 12,
            color: active === t.key ? '#fff' : '#888',
            background: active === t.key ? '#1a1a1a' : 'transparent',
            border: '1px solid #222',
            borderRadius: 4,
            textDecoration: 'none',
          }}
        >
          {t.label}
        </a>
      ))}
    </nav>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div
      style={{
        background: '#2a0e0e',
        border: '1px solid #5a1f1f',
        color: '#fbb',
        padding: 12,
        borderRadius: 6,
        fontSize: 13,
        whiteSpace: 'pre-wrap',
      }}
    >
      error: {message}
    </div>
  );
}
