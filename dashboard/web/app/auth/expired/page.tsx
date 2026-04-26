import { redirect } from 'next/navigation';

/**
 * Legacy URL — kept so any magic link minted before we renamed the
 * canonical signin surface still lands somewhere sensible. Forwards to
 * /auth/signin?reason=expired which renders the same content with the
 * "link expired" copy variant.
 */
export default function AuthExpiredLegacyRedirect() {
  redirect('/auth/signin?reason=expired');
}
