import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, NavTabs, Pill, Section, Stat } from '../../_lib/ui';

interface Ping {
  id: string;
  source: string;
  message_ref: string | null;
  topic_key: string | null;
  fired_at: string | null;
  suppressed_reason: string | null;
  sent: boolean;
}

interface PingsResponse {
  totals: { sent: number; suppressed: number };
  pings: Ping[];
}

export default async function ProactivePage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: PingsResponse;
  try {
    data = await adminFetch<PingsResponse>(
      `${encodeURIComponent(user_id)}/proactive?limit=200`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="proactive" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="proactive" />
      <Section title="Totals">
        <Card>
          <div style={{ display: 'flex', gap: 32 }}>
            <Stat label="sent" value={data.totals.sent} />
            <Stat label="suppressed" value={data.totals.suppressed} />
            <Stat
              label="rate"
              value={
                data.totals.sent + data.totals.suppressed > 0
                  ? `${Math.round(
                      (100 * data.totals.sent) /
                        (data.totals.sent + data.totals.suppressed),
                    )}%`
                  : '—'
              }
            />
          </div>
        </Card>
      </Section>

      <Section
        title={`Last ${data.pings.length} pings`}
        right="newest first"
      >
        <div style={{ display: 'grid', gap: 6 }}>
          {data.pings.map((p) => (
            <Card key={p.id} pad={10}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                }}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      color: '#fff',
                      fontSize: 12,
                      display: 'flex',
                      gap: 8,
                      alignItems: 'center',
                    }}
                  >
                    <span style={{ color: '#888', minWidth: 130 }}>
                      {p.fired_at?.slice(0, 19) || '—'}
                    </span>
                    <Pill color={p.sent ? '#1a6e3c' : '#3a3a3a'}>
                      {p.sent ? 'sent' : 'suppressed'}
                    </Pill>
                    <span style={{ color: '#aaa' }}>{p.source}</span>
                    {p.topic_key && (
                      <span style={{ color: '#666', fontSize: 11 }}>
                        topic={p.topic_key}
                      </span>
                    )}
                  </div>
                  <div style={{ color: '#666', fontSize: 11, marginTop: 4 }}>
                    msg_ref: {p.message_ref || '—'}
                    {p.suppressed_reason
                      ? ` · reason: ${p.suppressed_reason}`
                      : ''}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
