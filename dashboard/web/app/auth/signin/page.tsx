/**
 * /auth/signin — the welcome surface, and a real first introduction to
 * Donna.
 *
 * Donna lives on WhatsApp. Most people landing here have never met her.
 * The page tells them, in her voice, who she is and what they're doing.
 * One ink-toned CTA opens the WhatsApp thread with "send my dashboard"
 * pre-filled. A small secondary line offers the OTP path.
 *
 * No green button, no card rack, no "pick option A or B". Editorial
 * layout, paper canvas, italic rust accent on her name. It should feel
 * like opening a letter, not signing up for a service.
 */
const WA_DEEPLINK_DEFAULT = 'https://wa.me/';
const WA_PREFILL = 'send my dashboard';

function buildWaUrl(): string {
  // NEXT_PUBLIC_WA_URL is set on Vercel as the canonical wa.me/<number>.
  const base = (process.env.NEXT_PUBLIC_WA_URL || WA_DEEPLINK_DEFAULT).replace(
    /\/$/,
    '',
  );
  const sep = base.includes('?') ? '&' : '?';
  return `${base}${sep}text=${encodeURIComponent(WA_PREFILL)}`;
}

export default async function AuthSigninPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  const rawReason = params.reason;
  const reason = Array.isArray(rawReason) ? rawReason[0] : rawReason ?? null;
  const expired = reason === 'expired';

  const waUrl = buildWaUrl();

  return (
    <main className="signin-page">
      <article className="signin-frame">
        <SigninGlyph />

        <span className="signin-kicker">
          {expired ? 'session ended' : 'meet donna'}
        </span>

        <h1 className="signin-headline">
          {expired ? (
            <>
              welcome <em>back.</em>
            </>
          ) : (
            <>
              hi. i&apos;m <em>donna.</em>
            </>
          )}
        </h1>

        {expired ? (
          <p className="signin-lede">
            it&apos;s been a minute. tap below, say &ldquo;send my dashboard&rdquo;,
            and i&apos;ll drop you a fresh link.
          </p>
        ) : (
          <div className="signin-prose">
            <p>
              your personal assistant on whatsapp. i remember what you share,
              hold threads, notice what&apos;s becoming important, and reach
              out before things slip.
            </p>
            <p>
              this dashboard is the calmer half — a paper-toned read of your
              day that updates as i learn what matters to you. you can keep
              texting me; nothing changes there.
            </p>
            <p className="signin-prose__quiet">
              tap below, say &ldquo;send my dashboard&rdquo;, and i&apos;ll
              meet you here.
            </p>
          </div>
        )}

        <a
          className="signin-cta"
          href={waUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          <span>open the whatsapp thread</span>
          <span className="signin-cta__arrow" aria-hidden>
            →
          </span>
        </a>

        <a className="signin-otp" href="/auth/otp">
          or sign in with a 6-digit code
        </a>

        <footer className="signin-meta">
          <span>once you&apos;re in, this device stays signed in for 30 days.</span>
        </footer>
      </article>
    </main>
  );
}

function SigninGlyph() {
  // Single-weight rust line drawing — a crescent over a horizon line.
  // Same glyph the rest of /auth uses so signin feels continuous with
  // /auth/otp + /auth/expired.
  return (
    <svg
      className="signin-glyph"
      width="56"
      height="56"
      viewBox="0 0 56 56"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M34 12a16 16 0 1 0 9 26 14 14 0 0 1-9-26z" />
      <path d="M8 46h40" opacity="0.45" />
    </svg>
  );
}
