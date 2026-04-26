import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, Json, NavTabs, Section } from '../../_lib/ui';

interface CalRes {
  events: Record<string, unknown>[];
}

export default async function CalendarPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: CalRes;
  try {
    data = await adminFetch<CalRes>(
      `${encodeURIComponent(user_id)}/calendar`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="calendar" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="calendar" />
      <Section
        title={`Calendar entries (${data.events.length})`}
        right="ordered by start_time asc"
      >
        <div style={{ display: 'grid', gap: 6 }}>
          {data.events.map((e, i) => (
            <Card key={(e.id as string) || i} pad={10}>
              <div
                style={{
                  display: 'flex',
                  gap: 12,
                  fontSize: 12,
                  alignItems: 'center',
                }}
              >
                <span style={{ color: '#888', minWidth: 130 }}>
                  {(e.start_time as string)?.slice(0, 16) || '—'}
                </span>
                <span style={{ color: '#fff' }}>
                  {(e.title as string) || '(untitled)'}
                </span>
                {e.location ? (
                  <span style={{ color: '#888', fontSize: 11 }}>
                    @ {e.location as string}
                  </span>
                ) : null}
              </div>
              <details style={{ marginTop: 6 }}>
                <summary
                  style={{ cursor: 'pointer', color: '#666', fontSize: 11 }}
                >
                  raw
                </summary>
                <div style={{ marginTop: 6 }}>
                  <Json value={e} />
                </div>
              </details>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
