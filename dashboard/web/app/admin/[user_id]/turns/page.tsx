import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, NavTabs, Section } from '../../_lib/ui';

interface Turn {
  turn_id: string;
  system_prompt_head?: string;
  snapshot_ts?: string;
  duration_ms?: number;
  num_turns?: number;
  total_cost_usd?: number;
  tools?: string[];
  terminal_tool?: string;
  session_id?: string;
  end_ts?: string;
  cache_creation?: number;
  cache_read?: number;
}

interface TurnsResponse {
  turns: Turn[];
}

export default async function TurnsPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: TurnsResponse;
  try {
    data = await adminFetch<TurnsResponse>(
      `${encodeURIComponent(user_id)}/turns?limit=30`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="turns" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="turns" />
      <Section
        title={`Last ${data.turns.length} turns`}
        right="prompt + tool list + cost"
      >
        <div style={{ display: 'grid', gap: 8 }}>
          {data.turns.map((t) => (
            <Card key={t.turn_id} pad={12}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: 12,
                }}
              >
                <div>
                  <div style={{ color: '#fff' }}>{t.turn_id}</div>
                  <div style={{ color: '#666', fontSize: 11, marginTop: 2 }}>
                    {(t.end_ts || t.snapshot_ts || '').slice(0, 19)} ·{' '}
                    {t.duration_ms != null ? `${t.duration_ms}ms` : '—'} ·
                    inner_turns={t.num_turns ?? '?'} · cost=$
                    {t.total_cost_usd?.toFixed(5) || '—'}
                  </div>
                </div>
                <div style={{ color: '#888', fontSize: 11, textAlign: 'right' }}>
                  cache_create={t.cache_creation ?? '—'} · cache_read=
                  {t.cache_read ?? '—'}
                </div>
              </div>
              {(t.tools && t.tools.length > 0) && (
                <div
                  style={{
                    marginTop: 8,
                    color: '#9bc',
                    fontSize: 11,
                    fontFamily: 'inherit',
                  }}
                >
                  tools: {t.tools.join(' → ')}
                </div>
              )}
              {t.system_prompt_head && (
                <details style={{ marginTop: 6 }}>
                  <summary
                    style={{ cursor: 'pointer', color: '#888', fontSize: 11 }}
                  >
                    system_prompt head
                  </summary>
                  <pre
                    style={{
                      background: '#000',
                      border: '1px solid #222',
                      borderRadius: 6,
                      padding: 10,
                      fontSize: 11,
                      color: '#9bc',
                      overflow: 'auto',
                      maxHeight: 240,
                      marginTop: 6,
                    }}
                  >
                    {t.system_prompt_head}
                  </pre>
                </details>
              )}
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
