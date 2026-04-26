import { adminFetch } from '../../_lib/fetcher';
import { Card, ErrorBox, Json, NavTabs, Section } from '../../_lib/ui';

export default async function RawPage({
  params,
}: {
  params: Promise<{ user_id: string }>;
}) {
  const { user_id } = await params;
  let data: Record<string, unknown>;
  try {
    data = await adminFetch<Record<string, unknown>>(
      `${encodeURIComponent(user_id)}/raw`,
    );
  } catch (err) {
    return (
      <>
        <NavTabs userId={user_id} active="raw" />
        <ErrorBox message={String(err)} />
      </>
    );
  }
  return (
    <>
      <NavTabs userId={user_id} active="raw" />
      <Section title="Raw User row">
        <Card>
          <Json value={data} />
        </Card>
      </Section>
    </>
  );
}
