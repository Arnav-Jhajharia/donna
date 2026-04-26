import Link from 'next/link';
import { adminFetch } from './_lib/fetcher';
import { Card, ErrorBox, Section, Stat } from './_lib/ui';

interface AdminUser {
  id: string;
  phone: string;
  name: string | null;
  timezone: string | null;
  is_sandbox: boolean | null;
  created_at: string | null;
  last_active_at: string | null;
  integrations: number;
  proactive_pings: number;
  emails: number;
  chat_messages: number;
}

interface UsersResponse {
  users: AdminUser[];
}

export default async function AdminUsersPage() {
  let data: UsersResponse;
  try {
    data = await adminFetch<UsersResponse>('users?limit=100');
  } catch (err) {
    return <ErrorBox message={String(err)} />;
  }
  return (
    <Section
      title={`Users (${data.users.length})`}
      right="ordered by last activity"
    >
      <div style={{ display: 'grid', gap: 12 }}>
        {data.users.map((u) => (
          <Link
            key={u.id}
            href={`/admin/${encodeURIComponent(u.id)}`}
            style={{ textDecoration: 'none' }}
          >
            <Card>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 16,
                }}
              >
                <div>
                  <div style={{ color: '#fff', fontSize: 14 }}>
                    {u.name || '(unnamed)'} · {u.phone}
                  </div>
                  <div
                    style={{ color: '#666', fontSize: 11, marginTop: 4 }}
                  >
                    {u.id} · tz={u.timezone || '?'} · last_active={u.last_active_at || '—'}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 24 }}>
                  <Stat label="integ" value={u.integrations} />
                  <Stat label="pings" value={u.proactive_pings} />
                  <Stat label="emails" value={u.emails} />
                  <Stat label="chats" value={u.chat_messages} />
                </div>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </Section>
  );
}
