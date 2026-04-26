import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, NavTabs, Pill, Section } from '../../_lib/ui';

interface Msg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  wa_message_id: string | null;
  is_proactive: boolean | null;
  created_at: string | null;
}

interface ChatRes {
  messages: Msg[];
}

export default async function ChatPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: ChatRes;
  try {
    data = await adminFetch<ChatRes>(
      `${encodeURIComponent(user_id)}/chat?limit=200`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="chat" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="chat" />
      <Section
        title={`Last ${data.messages.length} messages`}
        right="newest first"
      >
        <div style={{ display: 'grid', gap: 4 }}>
          {data.messages.map((m) => (
            <Card key={m.id} pad={10}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 12,
                }}
              >
                <span style={{ color: '#666', minWidth: 130 }}>
                  {m.created_at?.slice(0, 19) || '—'}
                </span>
                <Pill color={m.role === 'user' ? '#1a4e6e' : '#1a6e3c'}>
                  {m.role}
                </Pill>
                {m.is_proactive && <Pill color="#7a5a16">proactive</Pill>}
                <span style={{ color: '#666', fontSize: 10 }}>
                  {m.wa_message_id || ''}
                </span>
              </div>
              <div
                style={{
                  color: '#eee',
                  fontSize: 13,
                  marginTop: 6,
                  whiteSpace: 'pre-wrap',
                  overflowWrap: 'anywhere',
                }}
              >
                {m.content}
              </div>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
