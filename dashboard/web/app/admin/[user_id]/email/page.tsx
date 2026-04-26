import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, NavTabs, Pill, Section } from '../../_lib/ui';

interface Email {
  id: string;
  gmail_message_id: string;
  thread_id: string;
  from_address: string | null;
  from_name: string | null;
  to_addresses: string[] | null;
  subject: string | null;
  snippet: string | null;
  body_text: string | null;
  labels: string[] | null;
  is_important: boolean | null;
  is_starred: boolean | null;
  is_sent: boolean | null;
  ingest_depth: string | null;
  internal_date: string | null;
  ingested_at: string | null;
}
interface EmailRes {
  emails: Email[];
}

export default async function EmailPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: EmailRes;
  try {
    data = await adminFetch<EmailRes>(
      `${encodeURIComponent(user_id)}/email?limit=100`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="email" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="email" />
      <Section
        title={`Last ${data.emails.length} emails (mirror)`}
        right="newest first · click for body"
      >
        <div style={{ display: 'grid', gap: 6 }}>
          {data.emails.map((e) => (
            <Card key={e.id} pad={10}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 12,
                }}
              >
                <span style={{ color: '#888', minWidth: 130 }}>
                  {e.internal_date?.slice(0, 16) || '—'}
                </span>
                {e.is_important && <Pill color="#7a5a16">important</Pill>}
                {e.is_starred && <Pill color="#5a4e1a">starred</Pill>}
                {e.is_sent && <Pill color="#444">sent</Pill>}
                <span style={{ color: '#fff', flex: 1, minWidth: 0 }}>
                  <span style={{ color: '#bbb' }}>
                    {e.from_name || e.from_address || '—'}
                  </span>{' '}
                  → {e.subject || '(no subject)'}
                </span>
                <span style={{ color: '#666', fontSize: 11 }}>
                  {e.ingest_depth}
                </span>
              </div>
              <div style={{ color: '#666', fontSize: 11, marginTop: 4 }}>
                {e.snippet?.slice(0, 200) || '—'}
              </div>
              {e.body_text && (
                <details style={{ marginTop: 6 }}>
                  <summary
                    style={{ cursor: 'pointer', color: '#888', fontSize: 11 }}
                  >
                    body
                  </summary>
                  <pre
                    style={{
                      background: '#000',
                      border: '1px solid #222',
                      borderRadius: 6,
                      padding: 10,
                      fontSize: 11,
                      color: '#bbb',
                      overflow: 'auto',
                      maxHeight: 300,
                      marginTop: 6,
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {e.body_text}
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
