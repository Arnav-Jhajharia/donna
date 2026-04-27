import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, Json, NavTabs, Pill, Section } from '../../_lib/ui';

interface Event {
  event: string;
  ts: string;
  turn_id?: string | null;
  tool?: string;
  tool_short?: string;
  call_id?: string;
  input_keys?: string[];
  input_preview?: unknown;
  reason?: string;
  decision_kind?: string;
  backend?: string;
  op?: string;
  ok?: boolean;
  result_preview?: unknown;
  args_preview?: unknown;
  duration_ms?: number;
  status?: string;
  prompt_hash?: string;
  num_turns?: number;
  total_cost_usd?: number;
}

interface ToolsResponse {
  events: Event[];
}

const EVENT_COLOR: Record<string, string> = {
  'tool.call': '#1a6e3c',
  'memory.op': '#1a4e6e',
  'hook.deny': '#7a1a1a',
  'image.generated': '#5a4e1a',
  'turn.start': '#333',
  'turn.end': '#333',
};

export default async function ToolsPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: ToolsResponse;
  try {
    data = await adminFetch<ToolsResponse>(
      `${encodeURIComponent(user_id)}/tools?limit=200`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="tools" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="tools" />
      <Section
        title={`Recent events (${data.events.length})`}
        right=".donna/events.jsonl filtered to this user"
      >
        <div style={{ display: 'grid', gap: 4 }}>
          {data.events.map((e, i) => (
            <Card key={`${e.ts}-${i}`} pad={10}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 12,
                }}
              >
                <span style={{ color: '#666', minWidth: 130 }}>
                  {e.ts?.slice(0, 19)}
                </span>
                <Pill color={EVENT_COLOR[e.event] || '#444'}>{e.event}</Pill>
                <span style={{ color: '#fff' }}>
                  {e.tool_short || e.op || ''}
                </span>
                {typeof e.ok === 'boolean' && (
                  <span
                    style={{
                      color: e.ok ? '#7c7' : '#f77',
                      fontSize: 11,
                    }}
                  >
                    {e.ok ? 'ok' : 'fail'}
                  </span>
                )}
                {e.duration_ms != null && (
                  <span style={{ color: '#888', fontSize: 11 }}>
                    {e.duration_ms}ms
                  </span>
                )}
                {e.total_cost_usd != null && (
                  <span style={{ color: '#888', fontSize: 11 }}>
                    ${e.total_cost_usd.toFixed(4)}
                  </span>
                )}
                {e.reason && (
                  <span style={{ color: '#fb6', fontSize: 11 }}>
                    {e.reason}
                  </span>
                )}
              </div>
              {Boolean(e.input_preview || e.args_preview || e.result_preview) && (
                <details style={{ marginTop: 6 }}>
                  <summary
                    style={{ cursor: 'pointer', color: '#888', fontSize: 11 }}
                  >
                    payload
                  </summary>
                  <div style={{ marginTop: 6 }}>
                    <Json
                      value={{
                        input: e.input_preview ?? e.args_preview,
                        result: e.result_preview,
                      }}
                    />
                  </div>
                </details>
              )}
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
