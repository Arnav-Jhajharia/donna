import Link from 'next/link';
import DashboardRenderer from '@/components/DashboardRenderer';
import { getPlan } from '@/lib/getPlan';

export default function Page() {
  const plan = getPlan('aarav', new Date());

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: 'var(--space-5) 0',
      }}
    >
      <nav
        style={{
          width: '100%',
          maxWidth: 440,
          display: 'flex',
          gap: 16,
          padding: '0 20px 20px',
          justifyContent: 'flex-end',
          fontSize: 11,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          fontWeight: 500,
        }}
      >
        <Link href="/moments" style={{ color: 'var(--rust-700)', textDecoration: 'none' }}>
          moments →
        </Link>
        <Link href="/generator" style={{ color: 'var(--rust-700)', textDecoration: 'none' }}>
          generator →
        </Link>
      </nav>
      <div
        style={{
          width: '100%',
          maxWidth: 440,
          background: 'var(--bg-canvas)',
          borderLeft: '1px solid var(--border-hairline)',
          borderRight: '1px solid var(--border-hairline)',
          overflow: 'hidden',
        }}
      >
        <DashboardRenderer plan={plan} />
      </div>
    </main>
  );
}
