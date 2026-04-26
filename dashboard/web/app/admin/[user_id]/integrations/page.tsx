import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, NavTabs, Pill, Section } from '../../_lib/ui';

interface LocalRow {
  provider: string;
  product: string;
  status: string;
  composio_connection_id: string | null;
  connected_at: string | null;
  last_synced_at: string | null;
  redirect_url: string | null;
  redirect_url_issued_at: string | null;
  last_error: string | null;
  updated_at: string | null;
}

interface ComposioRow {
  id?: string;
  status?: string;
  toolkit?: string;
  created_at?: string;
  error?: string;
}

interface IntegRes {
  local: LocalRow[];
  composio: ComposioRow[];
}

const STATUS_COLOR: Record<string, string> = {
  connected: '#1a6e3c',
  pending: '#7a5a16',
  revoked: '#7a1a1a',
  ACTIVE: '#1a6e3c',
  INITIATED: '#7a5a16',
  EXPIRED: '#7a1a1a',
};

export default async function IntegPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: IntegRes;
  try {
    data = await adminFetch<IntegRes>(
      `${encodeURIComponent(user_id)}/integrations`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="integrations" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="integrations" />
      <Section
        title={`Local DB (${data.local.length})`}
        right="source of truth for [INTEGRATIONS] block in prompts"
      >
        <div style={{ display: 'grid', gap: 6 }}>
          {data.local.map((r) => (
            <Card key={`${r.provider}_${r.product}`} pad={10}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  fontSize: 12,
                }}
              >
                <Pill color={STATUS_COLOR[r.status] || '#444'}>{r.status}</Pill>
                <span style={{ color: '#fff' }}>
                  {r.provider}_{r.product}
                </span>
                <span style={{ color: '#888', fontSize: 11 }}>
                  conn={r.composio_connection_id || '—'}
                </span>
                <span style={{ color: '#666', marginLeft: 'auto' }}>
                  updated {r.updated_at?.slice(0, 16) || '—'}
                </span>
              </div>
              {r.redirect_url && (
                <div
                  style={{
                    color: '#666',
                    fontSize: 11,
                    marginTop: 4,
                    overflowWrap: 'anywhere',
                  }}
                >
                  cached redirect_url: {r.redirect_url} (issued{' '}
                  {r.redirect_url_issued_at?.slice(0, 16) || '—'})
                </div>
              )}
              {r.last_error && (
                <div style={{ color: '#f88', fontSize: 11, marginTop: 4 }}>
                  err: {r.last_error}
                </div>
              )}
            </Card>
          ))}
        </div>
      </Section>

      <Section
        title={`Composio truth (${data.composio.length})`}
        right="live API call · drift = bug"
      >
        <div style={{ display: 'grid', gap: 6 }}>
          {data.composio.map((r, i) => (
            <Card key={`${r.id || i}`} pad={10}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  fontSize: 12,
                }}
              >
                {r.status && (
                  <Pill color={STATUS_COLOR[r.status] || '#444'}>
                    {r.status}
                  </Pill>
                )}
                <span style={{ color: '#fff' }}>{r.toolkit || '?'}</span>
                <span style={{ color: '#888', fontSize: 11 }}>
                  id={r.id || '—'}
                </span>
                {r.created_at && (
                  <span style={{ color: '#666', marginLeft: 'auto' }}>
                    {r.created_at}
                  </span>
                )}
                {r.error && (
                  <span style={{ color: '#f88' }}>err: {r.error}</span>
                )}
              </div>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
