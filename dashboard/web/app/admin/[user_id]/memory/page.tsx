import { adminFetch } from '../../_lib/fetcher';
import {
  Card,
  ErrorBox,
  Json,
  NavTabs,
  Pill,
  Section,
} from '../../_lib/ui';

interface OpenLoop {
  id: string;
  content: string;
  status: string;
  due_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}
interface Observation {
  id: string;
  type: string;
  fields: unknown;
  tags: unknown;
  raw: string | null;
  confidence: number | null;
  event_time: string | null;
  created_at: string | null;
}

async function safeFetch<T>(path: string): Promise<T | { error: string }> {
  try {
    return await adminFetch<T>(path);
  } catch (err) {
    return { error: String(err) };
  }
}

export default async function MemoryPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  const enc = encodeURIComponent(user_id);
  const [biographyRes, profileRes, loopsRes, obsRes, smRes, gRes, factsRes] =
    await Promise.all([
      safeFetch<{ biography: Record<string, unknown> }>(`${enc}/memory/biography`),
      safeFetch<{ living_profile: Record<string, unknown> }>(`${enc}/memory/profile`),
      safeFetch<{ open_loops: OpenLoop[] }>(`${enc}/memory/open_loops`),
      safeFetch<{ observations: Observation[] }>(`${enc}/memory/observations`),
      safeFetch<{ supermemory: unknown[]; error?: string }>(`${enc}/memory/supermemory`),
      safeFetch<{ graphiti: unknown[]; error?: string }>(`${enc}/memory/graphiti`),
      safeFetch<{ user_facts: unknown[]; note?: string }>(`${enc}/memory/user_facts`),
    ]);

  const renderError = (r: unknown) =>
    r && typeof r === 'object' && 'error' in r
      ? (r as { error: string }).error
      : null;

  return (
    <>
      <NavTabs userId={user_id} active="memory" />

      <Section title="Biography (synthesized from email)">
        {renderError(biographyRes) ? (
          <ErrorBox message={renderError(biographyRes)!} />
        ) : (
          <Card>
            <Json
              value={(biographyRes as { biography: unknown }).biography}
            />
          </Card>
        )}
      </Section>

      <Section title="Open loops">
        {renderError(loopsRes) ? (
          <ErrorBox message={renderError(loopsRes)!} />
        ) : (
          <div style={{ display: 'grid', gap: 6 }}>
            {(loopsRes as { open_loops: OpenLoop[] }).open_loops.length ===
            0 ? (
              <Card>
                <div style={{ color: '#666' }}>none</div>
              </Card>
            ) : (
              (loopsRes as { open_loops: OpenLoop[] }).open_loops.map((l) => (
                <Card key={l.id} pad={10}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      gap: 12,
                      alignItems: 'center',
                    }}
                  >
                    <div style={{ color: '#fff', fontSize: 13 }}>
                      {l.content}
                    </div>
                    <Pill color={l.status === 'active' ? '#1a6e3c' : '#444'}>
                      {l.status}
                    </Pill>
                  </div>
                  <div style={{ color: '#666', fontSize: 11, marginTop: 4 }}>
                    due: {l.due_at?.slice(0, 16) || '—'} · created:{' '}
                    {l.created_at?.slice(0, 16) || '—'}
                  </div>
                </Card>
              ))
            )}
          </div>
        )}
      </Section>

      <Section title={`Observations`}>
        {renderError(obsRes) ? (
          <ErrorBox message={renderError(obsRes)!} />
        ) : (
          <div style={{ display: 'grid', gap: 6 }}>
            {(obsRes as { observations: Observation[] }).observations.length ===
            0 ? (
              <Card>
                <div style={{ color: '#666' }}>none</div>
              </Card>
            ) : (
              (obsRes as { observations: Observation[] }).observations
                .slice(0, 100)
                .map((o) => (
                  <Card key={o.id} pad={10}>
                    <div
                      style={{
                        display: 'flex',
                        gap: 12,
                        alignItems: 'center',
                        fontSize: 12,
                      }}
                    >
                      <Pill color="#1a4e6e">{o.type}</Pill>
                      <span style={{ color: '#fff' }}>
                        {JSON.stringify(o.fields).slice(0, 200)}
                      </span>
                      <span
                        style={{ color: '#666', marginLeft: 'auto', fontSize: 11 }}
                      >
                        {o.event_time?.slice(0, 16) || '—'}
                      </span>
                    </div>
                  </Card>
                ))
            )}
          </div>
        )}
      </Section>

      <Section title="Supermemory chunks">
        {renderError(smRes) || (smRes as { error?: string }).error ? (
          <ErrorBox
            message={
              renderError(smRes) || (smRes as { error?: string }).error || ''
            }
          />
        ) : (
          <Card>
            <Json value={(smRes as { supermemory: unknown[] }).supermemory} />
          </Card>
        )}
      </Section>

      <Section title="Graphiti entities + edges">
        {renderError(gRes) || (gRes as { error?: string }).error ? (
          <ErrorBox
            message={
              renderError(gRes) || (gRes as { error?: string }).error || ''
            }
          />
        ) : (
          <Card>
            <Json value={(gRes as { graphiti: unknown[] }).graphiti} />
          </Card>
        )}
      </Section>

      <Section title="User facts">
        {renderError(factsRes) ? (
          <ErrorBox message={renderError(factsRes)!} />
        ) : (
          <Card>
            <Json value={(factsRes as { user_facts: unknown[] }).user_facts} />
            {(factsRes as { note?: string }).note && (
              <div style={{ color: '#888', fontSize: 11, marginTop: 8 }}>
                {(factsRes as { note: string }).note}
              </div>
            )}
          </Card>
        )}
      </Section>

      <Section title="Full living_profile">
        {renderError(profileRes) ? (
          <ErrorBox message={renderError(profileRes)!} />
        ) : (
          <Card>
            <Json
              value={
                (profileRes as { living_profile: unknown }).living_profile
              }
            />
          </Card>
        )}
      </Section>
    </>
  );
}
