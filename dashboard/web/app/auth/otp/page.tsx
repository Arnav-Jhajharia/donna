'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { AuthShell } from '@/components/AuthShell';

/**
 * /auth/otp — phone + 6-digit code form for the WhatsApp OTP fallback.
 *
 * The user texts Donna ("send me a code"), receives a 6-digit code on
 * WhatsApp, and types it here with their phone. On success the backend
 * issues a 24-hour session cookie and we redirect to `/`.
 *
 * The page also surfaces the magic-link path as an equal alternative
 * below the form — if the user landed here by mistake or wants the
 * faster route, they can pivot without going back.
 */
export default function AuthOTPPage() {
  const router = useRouter();
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch('/api/auth/verify-otp', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ phone: phone.trim(), code: code.trim() }),
      });
      if (!res.ok) {
        setError('that code did not match. text donna for a new one.');
        return;
      }
      router.replace('/');
    } catch {
      setError('network error. try again in a moment.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      kicker="sign in with otp"
      title="type the code donna sent you."
      body="codes are valid for ten minutes and burn after one use. once verified, this device stays signed in for 24 hours."
      meta="donna · whatsapp"
    >
      <form className="auth-form" onSubmit={onSubmit}>
        <div className="auth-field">
          <label className="auth-field__label" htmlFor="auth-phone">
            phone (with country code)
          </label>
          <input
            id="auth-phone"
            className="auth-input"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+91 …"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            required
          />
        </div>
        <div className="auth-field">
          <label className="auth-field__label" htmlFor="auth-code">
            6-digit code
          </label>
          <input
            id="auth-code"
            className="auth-input auth-input--code"
            type="text"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            autoComplete="one-time-code"
            placeholder="——————"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            required
          />
        </div>
        {error ? <p className="auth-error">{error}</p> : null}
        <button className="auth-button" type="submit" disabled={submitting}>
          {submitting ? 'verifying…' : 'sign in'}
        </button>
      </form>

      <div className="auth-divider">or</div>

      <div className="auth-options" style={{ marginTop: 0 }}>
        <a className="auth-option" href="/auth/expired" style={{ gridColumn: '1 / -1' }}>
          <div className="auth-option__kicker">faster path</div>
          <h2 className="auth-option__title">text donna for a magic link</h2>
          <p className="auth-option__body">
            no code to type. send &ldquo;send my dashboard&rdquo; on whatsapp,
            tap the link, you&apos;re in. session is shorter (5 min) — fine for
            quick checks on the move.
          </p>
          <span className="auth-option__cue">how to →</span>
        </a>
      </div>
    </AuthShell>
  );
}
