import { cookies } from 'next/headers';
import DashboardClient from '@/components/DashboardClient';
import LandingPage from '@/components/landing/LandingPage';
import './landing.css';

// Root route. Same path serves two surfaces depending on auth state:
//
//   - `?user_id=` query string: dev escape hatch — render the dashboard
//     directly without a session cookie. The client-side resolveUserId
//     also honors this, but page.tsx runs on the server first and would
//     otherwise drop us on LandingPage before the client mounts. Honor
//     it here so `localhost:3000/?user_id=<uuid>` actually works.
//   - No `donna_session` cookie + no `?user_id=`: public landing page.
//   - Cookie present: render the dashboard client (which fetches the
//     manifest and resolves the user via /api/auth/whoami).
//
// The middleware no longer redirects bare `/` to `/auth/signin`; the
// branch happens here so itsmedonna.com works as a single entry point.
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ user_id?: string }>;
}) {
  const params = await searchParams;
  const userIdOverride = (params.user_id ?? '').trim();
  if (userIdOverride) {
    return <DashboardClient />;
  }

  const cookieStore = await cookies();
  const session = cookieStore.get('donna_session')?.value;

  if (!session) {
    return <LandingPage />;
  }

  return <DashboardClient />;
}
