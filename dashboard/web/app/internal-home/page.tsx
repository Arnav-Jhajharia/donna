import Link from 'next/link';

/**
 * Internal-host landing page. Lives only on the internal subdomain
 * (e.g. `internal.donna.app`); the user host's middleware blocks this
 * route as 404. Acts as a navigation aid for staff tools.
 *
 * Reachable via the middleware redirect on `/` when the request hits
 * an internal host. Behind HTTP Basic auth (ADMIN_USER + ADMIN_PASSWORD).
 */

interface InternalLink {
  href: string;
  label: string;
  blurb: string;
}

const LINKS: InternalLink[] = [
  {
    href: '/observe',
    label: 'observe',
    blurb: 'turn-by-turn telemetry. tool calls, hook denies, latencies, prompt snapshots.',
  },
  {
    href: '/observe/attention',
    label: 'observe.attention',
    blurb: 'attention runtime. live cards, ticks, proactive messages, pending schedule queue.',
  },
  {
    href: '/admin',
    label: 'admin',
    blurb: 'user inspector. integrations, attentions, memory, calendar, raw state.',
  },
  {
    href: '/moments',
    label: 'moments',
    blurb: 'showcase gallery — 18 hand-built dashboard plans rendered side by side.',
  },
  {
    href: '/generator',
    label: 'generator',
    blurb: 'rule-based composer demo. takes a synthetic context, builds a plan live.',
  },
  {
    href: '/expansion',
    label: 'expansion',
    blurb: 'experimental block archetypes not yet in the production renderer.',
  },
];

export default function InternalHomePage() {
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: 'var(--space-7) var(--space-5)',
        background: 'var(--bg-canvas, #f8f6f1)',
      }}
    >
      <div style={{ width: '100%', maxWidth: 560 }}>
        <header style={{ marginBottom: 'var(--space-7)' }}>
          <span
            style={{
              fontSize: 11,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: 'var(--ink-500, #6b6b6b)',
              fontWeight: 500,
            }}
          >
            internal
          </span>
          <h1
            style={{
              fontFamily: 'var(--font-serif, Georgia, serif)',
              fontWeight: 500,
              fontSize: 32,
              lineHeight: 1.2,
              margin: '6px 0 0 0',
              color: 'var(--ink-900, #1a1a1a)',
            }}
          >
            staff surface.
          </h1>
          <p
            style={{
              fontSize: 14,
              lineHeight: 1.55,
              color: 'var(--ink-600, #4a4a4a)',
              margin: '12px 0 0 0',
              maxWidth: 460,
            }}
          >
            tools for staff. not the user product. user dashboard lives
            on the public domain.
          </p>
        </header>

        <ul
          style={{
            listStyle: 'none',
            padding: 0,
            margin: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-3, 12px)',
          }}
        >
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                style={{
                  display: 'block',
                  padding: '16px 20px',
                  borderRadius: 8,
                  border: '1px solid var(--border-hairline, #e5e1d6)',
                  background: 'var(--paper-50, #fdfcf8)',
                  textDecoration: 'none',
                  color: 'inherit',
                  transition: 'border-color 120ms',
                }}
              >
                <div
                  style={{
                    fontFamily: 'var(--font-serif, Georgia, serif)',
                    fontSize: 18,
                    fontWeight: 500,
                    color: 'var(--rust-700, #8b4513)',
                    marginBottom: 4,
                  }}
                >
                  /{link.label}
                </div>
                <div
                  style={{
                    fontSize: 13,
                    lineHeight: 1.5,
                    color: 'var(--ink-600, #4a4a4a)',
                  }}
                >
                  {link.blurb}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
