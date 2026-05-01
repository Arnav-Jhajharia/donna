import { cookies } from 'next/headers';
import DashboardClient from '@/components/DashboardClient';
import LandingPage from '@/components/landing/LandingPage';
import './landing.css';

// Root route. Same path serves two surfaces depending on auth state:
//
//   - No `donna_session` cookie: render the public landing page.
//   - Cookie present: render the dashboard client (which fetches the
//     manifest and resolves the user via /api/auth/whoami).
//
// The middleware no longer redirects bare `/` to `/auth/signin`; the
// branch happens here so itsmedonna.com works as a single entry point.
export default async function Page() {
  const cookieStore = await cookies();
  const session = cookieStore.get('donna_session')?.value;

  if (!session) {
    return <LandingPage />;
  }

  return <DashboardClient />;
}
