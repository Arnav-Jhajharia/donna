import { adminFetch } from '../_lib/fetcher';
import {
  Card,
  ErrorBox,
  Json,
  NavTabs,
  Pill,
  Section,
  Stat,
} from '../_lib/ui';

interface IntegrationRow {
  provider: string;
  product: string;
  status: string;
  composio_connection_id: string | null;
  connected_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
}

interface OverviewResponse {
  user: {
    id: string;
    phone: string;
    name: string | null;
    timezone: string | null;
    wake_time: string | null;
    sleep_time: string | null;
    is_sandbox: boolean | null;
    created_at: string | null;
    last_active_at: string | null;
  };
  integrations: IntegrationRow[];
  bootstrap_runs: Record<string, unknown>;
  notified_integrations: Record<string, unknown>;
  biography_summary: {
    keys: string[];
    overview: string;
    evidence_window: unknown;
    last_bootstrapped_at: string | null;
  };
  counts: Record<string, number>;
}

const STATUS_COLOR: Record<string, string> = {
  connected: '#1a6e3c',
  pending: '#7a5a16',
  revoked: '#7a1a1a',
  error: '#7a1a1a',
};

export default async function OverviewPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: OverviewResponse;
  try {
    data = await adminFetch<OverviewResponse>(
      `${encodeURIComponent(user_id)}/overview`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="overview" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  const u = data.user;
  return (
    <>
      <NavTabs userId={user_id} active="overview" />
      <Section title="User">
        <Card>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
            <Stat label="name" value={u.name || '—'} />
            <Stat label="phone" value={u.phone} />
            <Stat label="timezone" value={u.timezone || '—'} />
            <Stat label="sandbox" value={u.is_sandbox ? 'yes' : 'no'} />
            <Stat label="wake" value={u.wake_time || '—'} />
            <Stat label="sleep" value={u.sleep_time || '—'} />
            <Stat label="created" value={u.created_at?.slice(0, 16) || '—'} />
            <Stat label="last active" value={u.last_active_at?.slice(0, 16) || '—'} />
          </div>
          <div style={{ marginTop: 12, color: '#555', fontSize: 11 }}>
            id: {u.id}
          </div>
        </Card>
      </Section>

      <Section title="Counts">
        <Card>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(5, 1fr)',
              gap: 16,
            }}
          >
            {Object.entries(data.counts).map(([k, v]) => (
              <Stat key={k} label={k.replace(/_/g, ' ')} value={v} />
            ))}
          </div>
        </Card>
      </Section>

      <Section title={`Integrations (${data.integrations.length})`}>
        <div style={{ display: 'grid', gap: 8 }}>
          {data.integrations.length === 0 ? (
            <Card>
              <div style={{ color: '#666' }}>none</div>
            </Card>
          ) : (
            data.integrations.map((r) => (
              <Card key={`${r.provider}_${r.product}`} pad={12}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                  }}
                >
                  <div>
                    <div style={{ color: '#fff', fontSize: 14 }}>
                      {r.provider}_{r.product}
                    </div>
                    <div style={{ color: '#666', fontSize: 11, marginTop: 4 }}>
                      conn={r.composio_connection_id || '—'}
                      {' · '}
                      synced={r.last_synced_at?.slice(0, 16) || '—'}
                      {r.last_error ? ` · err=${r.last_error.slice(0, 80)}` : ''}
                    </div>
                  </div>
                  <Pill color={STATUS_COLOR[r.status] || '#444'}>
                    {r.status}
                  </Pill>
                </div>
              </Card>
            ))
          )}
        </div>
      </Section>

      <Section title="Bootstrap runs">
        <Card>
          {Object.keys(data.bootstrap_runs).length === 0 ? (
            <div style={{ color: '#666' }}>never run</div>
          ) : (
            <Json value={data.bootstrap_runs} />
          )}
        </Card>
      </Section>

      <Section title="Biography summary">
        <Card>
          {data.biography_summary.keys.length === 0 ? (
            <div style={{ color: '#666' }}>not synthesized yet</div>
          ) : (
            <>
              <div style={{ color: '#aaa', fontSize: 13, marginBottom: 8 }}>
                {data.biography_summary.overview || '(empty overview)'}
              </div>
              <div style={{ color: '#666', fontSize: 11 }}>
                keys: {data.biography_summary.keys.join(', ')} · last:{' '}
                {data.biography_summary.last_bootstrapped_at?.slice(0, 16) || '—'}
              </div>
            </>
          )}
        </Card>
      </Section>

      <Section title="Notified integrations (dedup map)">
        <Card>
          {Object.keys(data.notified_integrations).length === 0 ? (
            <div style={{ color: '#666' }}>none</div>
          ) : (
            <Json value={data.notified_integrations} />
          )}
        </Card>
      </Section>
    </>
  );
}
