import Link from 'next/link';
import { ReactNode } from 'react';

interface AdminLayoutProps {
  children: ReactNode;
}

/**
 * Wrapping layout for /admin/*. Auth is enforced one layer up by the
 * edge middleware (HTTP Basic against ADMIN_PASSWORD). Inside the
 * tree, every page can assume the request is authenticated.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#0a0a0a',
        color: '#e6e6e6',
        fontFamily:
          'ui-monospace, "SF Mono", Menlo, Monaco, Consolas, monospace',
      }}
    >
      <header
        style={{
          padding: '12px 20px',
          borderBottom: '1px solid #222',
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          fontSize: 13,
        }}
      >
        <Link
          href="/admin"
          style={{ color: '#fff', fontWeight: 600, textDecoration: 'none' }}
        >
          donna · admin
        </Link>
        <span style={{ color: '#555' }}>read-only observability</span>
      </header>
      <main style={{ padding: 20, maxWidth: 1400, margin: '0 auto' }}>
        {children}
      </main>
    </div>
  );
}
