import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, Json, NavTabs, Pill, Section } from '../../_lib/ui';

interface Attention {
  id: string | null;
  title: string | null;
  card_type: string | null;
  state: string | null;
  created_at: string | null;
  raw: string | null;
}

interface AttRes {
  attentions: Attention[];
  error?: string;
}

export default async function AttPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: AttRes;
  try {
    data = await adminFetch<AttRes>(
      `${encodeURIComponent(user_id)}/attentions`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="attentions" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="attentions" />
      {data.error && <ErrorBox message={data.error} />}
      <Section
        title={`Attentions (${data.attentions.length})`}
        right="proposed / shadow / live / accepted / dismissed"
      >
        <div style={{ display: 'grid', gap: 6 }}>
          {data.attentions.length === 0 ? (
            <Card>
              <div style={{ color: '#666' }}>none</div>
            </Card>
          ) : (
            data.attentions.map((a, i) => (
              <Card key={a.id || i} pad={10}>
                <div
                  style={{
                    display: 'flex',
                    gap: 12,
                    fontSize: 12,
                    alignItems: 'center',
                  }}
                >
                  <Pill color="#1a4e6e">{a.card_type || '?'}</Pill>
                  <Pill color="#444">{a.state || '?'}</Pill>
                  <span style={{ color: '#fff' }}>
                    {a.title || '(untitled)'}
                  </span>
                  <span style={{ color: '#666', marginLeft: 'auto', fontSize: 11 }}>
                    {a.created_at?.slice(0, 16) || '—'}
                  </span>
                </div>
                {a.raw && (
                  <details style={{ marginTop: 6 }}>
                    <summary
                      style={{ cursor: 'pointer', color: '#666', fontSize: 11 }}
                    >
                      raw
                    </summary>
                    <div style={{ marginTop: 6 }}>
                      <Json value={a.raw} />
                    </div>
                  </details>
                )}
              </Card>
            ))
          )}
        </div>
      </Section>
    </>
  );
}
