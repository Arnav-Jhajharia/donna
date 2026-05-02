'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useAttentionSheet } from '@/lib/attention-sheet-context';
import { useAction } from '@/lib/action-context';
import type { ActionVerb } from '@/lib/plan';
import { buildWaUrl, tallyLogPrimer } from '@/lib/wa-deeplink';
import ActionChip from './ActionChip';

/**
 * Bottom-sheet drawer for non-one-shot attentions.
 *
 * The shell is shared across card types (slide-up, drag-down dismiss,
 * Donna-voice header). The body is per-card — a tally page reads
 * differently from an open-loop or a watch. Each card-typed body
 * answers four user-side questions:
 *
 *   1. Where am I right now?
 *   2. What did I log / what did Donna find?
 *   3. What does Donna think?
 *   4. What's the one thing to do next?
 *
 * Engineer-side metadata (cron, status, ticks, evidence rows, copy-id)
 * is not surfaced. That's what /observe/attention is for.
 */

interface AttentionDetail {
  id: string;
  user_id: string;
  card: string | null;
  status: string | null;
  title: string | null;
  description: string | null;
  subject: { name?: string; type?: string } | null;
  cadence: { type?: string; params?: Record<string, unknown> } | null;
  surface_policy: Record<string, unknown> | null;
  current_state: Record<string, unknown>;
  evidence: {
    id: string;
    type: string;
    fields: Record<string, unknown>;
    raw: string;
    event_time: string | null;
  }[];
  ticks: {
    id: string;
    at: string | null;
    rendered_markdown: string | null;
    source_counts: Record<string, unknown>;
  }[];
  history?: { day: string; value: number; count: number }[];
  created_at: string | null;
  last_surfaced_at: string | null;
  last_update_at: string | null;
}

export default function AttentionSheet() {
  const { attentionId, closeSheet } = useAttentionSheet();
  const [data, setData] = useState<AttentionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fire = useAction();

  const refetch = useEffect.bind(null); // typing helper, no-op
  void refetch;

  useEffect(() => {
    if (!attentionId) {
      setData(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const userId =
          new URLSearchParams(window.location.search).get('user_id') || '';
        if (!userId) {
          setError('not signed in');
          return;
        }
        const r = await fetch(
          `/api/dashboard/${encodeURIComponent(userId)}/attention/${encodeURIComponent(attentionId)}`,
          { cache: 'no-store' },
        );
        if (!r.ok) {
          setError(r.status === 404 ? "couldn't find that one" : 'something broke');
          return;
        }
        const json = (await r.json()) as AttentionDetail;
        if (!cancelled) setData(json);
      } catch {
        if (!cancelled) setError("can't reach donna");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const onRefetch = () => void load();
    window.addEventListener('donna:refetch-sheet', onRefetch as EventListener);
    return () => {
      cancelled = true;
      window.removeEventListener(
        'donna:refetch-sheet',
        onRefetch as EventListener,
      );
    };
  }, [attentionId]);

  useEffect(() => {
    if (!attentionId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeSheet();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [attentionId, closeSheet]);

  return (
    <AnimatePresence>
      {attentionId && (
        <>
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={closeSheet}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(20,18,12,0.42)',
              backdropFilter: 'blur(2px)',
              zIndex: 60,
            }}
          />
          <motion.div
            key="sheet"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 32, stiffness: 320 }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={0.18}
            onDragEnd={(_, info) => {
              if (info.offset.y > 80 || info.velocity.y > 600) closeSheet();
            }}
            style={{
              position: 'fixed',
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: 61,
              background: 'var(--paper-50, #fdfcf8)',
              borderTopLeftRadius: 22,
              borderTopRightRadius: 22,
              maxHeight: '88vh',
              overflowY: 'auto',
              boxShadow: '0 -16px 48px rgba(0,0,0,0.18)',
              display: 'flex',
              flexDirection: 'column',
              fontFamily:
                'var(--font-sans, ui-sans-serif, system-ui, sans-serif)',
              color: 'var(--ink-900, #1a1a1a)',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                paddingTop: 8,
                paddingBottom: 4,
                cursor: 'grab',
              }}
            >
              <div
                style={{
                  width: 44,
                  height: 4,
                  borderRadius: 2,
                  background: 'var(--ink-300, #c2bdb1)',
                }}
              />
            </div>

            {loading && !data && (
              <div
                style={{
                  padding: '40px 24px',
                  textAlign: 'center',
                  color: 'var(--ink-500)',
                }}
              >
                opening…
              </div>
            )}
            {error && (
              <div
                style={{
                  padding: '24px',
                  margin: '12px 16px',
                  borderRadius: 10,
                  background: 'var(--paper-100, #f4f2ec)',
                  color: 'var(--ink-700)',
                  fontSize: 14,
                  textAlign: 'center',
                }}
              >
                {error}
              </div>
            )}
            {data && data.card === 'tally' && <TallyBody data={data} fire={fire} />}
            {data && data.card !== 'tally' && (
              <PlaceholderBody data={data} fire={fire} />
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Tally body — the user-friendly page for any tally attention
// ─────────────────────────────────────────────────────────────────────────

function TallyBody({
  data,
  fire,
}: {
  data: AttentionDetail;
  fire: (verb: ActionVerb) => Promise<unknown>;
}) {
  void fire;
  const value = num(data.current_state.value_numeric, num(data.current_state.value, 0));
  const target = num(data.current_state.target, 0);
  const unit = inferUnit(data);
  const meals = humanizeEvidence(data.evidence);
  const history = data.history || [];
  const today = history[history.length - 1];
  const yesterday = history[history.length - 2];
  const donnaRead = composeDonnaRead({ value, target, unit, today, yesterday, meals });
  const subject = data.subject?.name || data.title || 'tally';
  const shownValue = value;

  return (
    <>
      {/* Title block — no status pill, no ID. Just what it is. */}
      <div style={{ padding: '4px 22px 0' }}>
        <div
          style={{
            color: 'var(--ink-500)',
            fontSize: 11,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            fontWeight: 500,
            marginBottom: 6,
          }}
        >
          {humanCardLabel(data.card, subject)}
        </div>
        <h2
          style={{
            fontFamily: 'var(--font-serif, Georgia, serif)',
            fontSize: 26,
            fontWeight: 500,
            margin: 0,
            letterSpacing: '-0.012em',
            lineHeight: 1.2,
          }}
        >
          {data.title || subject}
        </h2>
      </div>

      {/* The big number */}
      <div style={{ padding: '20px 22px 8px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
          <motion.div
            key={shownValue}
            initial={{ opacity: 0.4, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18 }}
            style={{
              fontFamily: 'var(--font-serif, Georgia, serif)',
              fontSize: 64,
              fontWeight: 500,
              lineHeight: 1,
              letterSpacing: '-0.025em',
            }}
          >
            {fmtN(shownValue)}
          </motion.div>
          {target > 0 && (
            <div style={{ color: 'var(--ink-500)', fontSize: 16 }}>
              of {fmtN(target)} {unit}
            </div>
          )}
          {target === 0 && unit && (
            <div style={{ color: 'var(--ink-500)', fontSize: 16 }}>{unit}</div>
          )}
        </div>
        {target > 0 && (
          <div
            style={{
              marginTop: 12,
              height: 6,
              background: 'var(--paper-200, #ece8df)',
              borderRadius: 999,
              overflow: 'hidden',
            }}
          >
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(100, (shownValue / target) * 100)}%` }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              style={{
                height: '100%',
                background: 'var(--moss-600, #6a8458)',
                borderRadius: 999,
              }}
            />
          </div>
        )}
      </div>

      {/* 7-day trend bars */}
      {history.length > 0 && (
        <div style={{ padding: '14px 22px 8px' }}>
          <Trend history={history} target={target} />
        </div>
      )}

      {/* Donna's read */}
      {donnaRead && (
        <div
          style={{
            margin: '10px 22px 4px',
            padding: '14px 16px',
            background: 'var(--paper-100, #f4f2ec)',
            borderRadius: 12,
          }}
        >
          <div
            style={{
              color: 'var(--ink-500)',
              fontSize: 10,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              marginBottom: 6,
            }}
          >
            donna
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.5, color: 'var(--ink-800)' }}>
            {donnaRead}
          </div>
        </div>
      )}

      {/* Meals as prose */}
      {meals.length > 0 ? (
        <div style={{ padding: '18px 22px 8px' }}>
          <div
            style={{
              color: 'var(--ink-500)',
              fontSize: 10,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            today
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {meals.map((m) => (
              <MealLine key={m.id} meal={m} unit={unit} />
            ))}
          </div>
        </div>
      ) : (
        <div
          style={{
            padding: '18px 22px 8px',
            color: 'var(--ink-500)',
            fontSize: 13,
          }}
        >
          nothing logged yet today.
        </div>
      )}

      {/* One CTA — opens WhatsApp with a primer so logging goes through
          Donna's real NLP + estimator pipeline instead of writing a
          context-less +1 observation from the dashboard. */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          alignItems: 'center',
          padding: '18px 22px 28px',
          position: 'sticky',
          bottom: 0,
          background:
            'linear-gradient(to top, var(--paper-50, #fdfcf8) 70%, rgba(253,252,248,0))',
        }}
      >
        <a
          href={buildWaUrl(tallyLogPrimer(subject))}
          target="_blank"
          rel="noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 18px',
            background: 'var(--moss-600, #6a8458)',
            color: 'var(--paper-50, #fdfcf8)',
            borderRadius: 999,
            fontFamily: 'inherit',
            fontSize: 14,
            fontWeight: 500,
            textDecoration: 'none',
            transition: 'transform 120ms, background-color 120ms',
            boxShadow: '0 1px 0 rgba(20,18,12,0.06)',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.background =
              'var(--moss-700, #557045)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.background =
              'var(--moss-600, #6a8458)';
          }}
        >
          <WhatsAppGlyph />
          <span>{primaryCtaLabel(data.card, subject)}</span>
        </a>
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Trend — 7 tiny bars
// ─────────────────────────────────────────────────────────────────────────

function Trend({
  history,
  target,
}: {
  history: { day: string; value: number; count: number }[];
  target: number;
}) {
  const max = Math.max(target || 0, ...history.map((h) => h.value), 1);
  const todayIdx = history.length - 1;
  return (
    <div>
      <div
        style={{
          color: 'var(--ink-500)',
          fontSize: 10,
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          marginBottom: 8,
        }}
      >
        last 7 days
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, 1fr)',
          gap: 6,
          alignItems: 'end',
          height: 56,
        }}
      >
        {history.map((h, i) => {
          const heightPct = max > 0 ? Math.max(4, (h.value / max) * 100) : 4;
          const isToday = i === todayIdx;
          const empty = h.value === 0;
          return (
            <div
              key={h.day}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'flex-end',
                height: '100%',
              }}
            >
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: `${heightPct}%` }}
                transition={{ duration: 0.4, delay: i * 0.04, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  width: '100%',
                  background: empty
                    ? 'var(--paper-200, #ece8df)'
                    : isToday
                      ? 'var(--moss-600, #6a8458)'
                      : 'var(--moss-300, #98b878)',
                  borderRadius: 4,
                  minHeight: 4,
                }}
              />
            </div>
          );
        })}
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, 1fr)',
          gap: 6,
          marginTop: 6,
        }}
      >
        {history.map((h, i) => (
          <div
            key={h.day}
            style={{
              fontSize: 10,
              textAlign: 'center',
              color: i === todayIdx ? 'var(--ink-900)' : 'var(--ink-500)',
              fontWeight: i === todayIdx ? 600 : 400,
              letterSpacing: 0.4,
            }}
          >
            {dayLabel(h.day, i === todayIdx)}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Meal line
// ─────────────────────────────────────────────────────────────────────────

function MealLine({
  meal,
  unit,
}: {
  meal: ReturnType<typeof humanizeEvidence>[number];
  unit: string;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr auto',
        gap: 10,
        alignItems: 'baseline',
        padding: '8px 0',
        borderBottom: '1px solid var(--border-hairline, #e5e1d6)',
      }}
    >
      <div>
        <div style={{ fontSize: 14, color: 'var(--ink-900)', lineHeight: 1.3 }}>
          {meal.headline}
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-500)', marginTop: 2 }}>
          {meal.timeText}
        </div>
      </div>
      {meal.value != null && (
        <div style={{ fontSize: 14, color: 'var(--ink-700)', fontWeight: 500 }}>
          {fmtN(meal.value)}
          <span style={{ color: 'var(--ink-500)', fontSize: 12, marginLeft: 4 }}>
            {unit}
          </span>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Placeholder body for non-tally cards (still better than the engineer view)
// ─────────────────────────────────────────────────────────────────────────

function PlaceholderBody({
  data,
  fire,
}: {
  data: AttentionDetail;
  fire: (verb: ActionVerb) => Promise<unknown>;
}) {
  void fire;
  const subject = data.subject?.name || data.title || 'attention';
  return (
    <div style={{ padding: '8px 22px 28px' }}>
      <div
        style={{
          color: 'var(--ink-500)',
          fontSize: 11,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          fontWeight: 500,
          marginBottom: 6,
        }}
      >
        {humanCardLabel(data.card, subject)}
      </div>
      <h2
        style={{
          fontFamily: 'var(--font-serif, Georgia, serif)',
          fontSize: 24,
          fontWeight: 500,
          margin: '0 0 12px',
          letterSpacing: '-0.012em',
        }}
      >
        {data.title || subject}
      </h2>
      {data.description && (
        <div
          style={{
            fontSize: 14,
            color: 'var(--ink-700)',
            lineHeight: 1.55,
            marginBottom: 16,
          }}
        >
          {data.description}
        </div>
      )}
      <div
        style={{
          padding: '16px',
          background: 'var(--paper-100)',
          borderRadius: 10,
          color: 'var(--ink-500)',
          fontSize: 13,
          textAlign: 'center',
        }}
      >
        the dedicated page for {humanCardLabel(data.card, subject)} is coming next.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Helpers — humanization, formatting
// ─────────────────────────────────────────────────────────────────────────

function num(v: unknown, fallback: number): number {
  if (v == null) return fallback;
  if (typeof v === 'number') return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function fmtN(n: number): string {
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n - Math.round(n)) < 0.01) return String(Math.round(n));
  return n.toFixed(1);
}

function inferUnit(data: AttentionDetail): string {
  const f = data.evidence[0]?.fields || {};
  if (typeof f.unit === 'string') return f.unit;
  if (data.card === 'tally') {
    const subj = (data.subject?.name || data.title || '').toLowerCase();
    if (subj.includes('calorie')) return 'kcal';
    if (subj.includes('water') || subj.includes('hydrat')) return 'glasses';
    if (subj.includes('sleep')) return 'h';
    if (subj.includes('spend') || subj.includes('expense')) return '';
    if (subj.includes('step')) return 'steps';
  }
  return '';
}

function humanCardLabel(card: string | null, subject: string): string {
  switch (card) {
    case 'tally':
      return 'tracker';
    case 'open_loop':
      return 'open loop';
    case 'event_stream':
      return 'watch';
    case 'brief':
      return 'brief';
    case 'prep_doc':
      return 'prep';
    case 'ping':
      return 'ping';
    default:
      return subject;
  }
}

function humanCardLog(card: string | null, subject: string): string {
  if (card === 'tally') {
    const s = subject.toLowerCase();
    if (s.includes('calorie') || s.includes('meal')) return 'meal';
    if (s.includes('water') || s.includes('hydrat')) return 'water';
    if (s.includes('sleep')) return 'sleep';
    if (s.includes('spend') || s.includes('expense')) return 'expense';
    if (s.includes('step')) return 'steps';
  }
  return 'log';
}

function primaryCtaLabel(card: string | null, subject: string): string {
  if (card !== 'tally') return 'log on whatsapp';
  const s = (subject || '').toLowerCase();
  if (s.includes('calorie') || s.includes('meal') || s.includes('food'))
    return 'log a meal';
  if (s.includes('water') || s.includes('hydrat')) return 'log water';
  if (s.includes('sleep')) return 'log sleep';
  if (s.includes('spend') || s.includes('expense')) return 'log spend';
  if (s.includes('step') || s.includes('walk')) return 'log steps';
  if (s.includes('weight')) return 'log weight';
  if (s.includes('workout') || s.includes('exercise')) return 'log workout';
  if (s.includes('mood')) return 'log mood';
  return 'log on whatsapp';
}

function WhatsAppGlyph() {
  // Minimal monochrome WhatsApp mark — paper-colored on moss button.
  return (
    <svg width="14" height="14" viewBox="0 0 32 32" fill="none" aria-hidden>
      <path
        d="M16 3C8.82 3 3 8.82 3 16c0 2.39.66 4.62 1.8 6.54L3 29l6.62-1.74A12.96 12.96 0 0 0 16 29c7.18 0 13-5.82 13-13S23.18 3 16 3Zm0 23.4c-2.06 0-3.97-.6-5.58-1.62l-.4-.24-3.93 1.04 1.05-3.83-.26-.4A10.4 10.4 0 1 1 26.4 16 10.41 10.41 0 0 1 16 26.4Zm5.7-7.78c-.31-.16-1.85-.92-2.13-1.02-.29-.1-.5-.16-.7.16-.21.31-.81 1.02-1 1.23-.18.21-.37.23-.68.08-.31-.16-1.31-.48-2.5-1.54-.92-.82-1.55-1.84-1.73-2.16-.18-.31-.02-.48.13-.63.14-.14.31-.36.47-.55.16-.18.21-.31.31-.52.1-.21.05-.39-.03-.55-.08-.16-.7-1.69-.96-2.31-.25-.6-.51-.52-.7-.53l-.6-.01a1.16 1.16 0 0 0-.84.39c-.29.31-1.1 1.07-1.1 2.62 0 1.55 1.13 3.04 1.29 3.25.16.21 2.22 3.4 5.4 4.76.75.32 1.34.51 1.8.66.76.24 1.45.21 2-.12.61-.36 1.85-1.27 2.11-1.97.26-.7.26-1.31.18-1.45-.08-.13-.29-.21-.6-.36Z"
        fill="currentColor"
      />
    </svg>
  );
}

function humanizeEvidence(evidence: AttentionDetail['evidence']) {
  return evidence
    .slice()
    .sort((a, b) => {
      const ta = a.event_time ? Date.parse(a.event_time) : 0;
      const tb = b.event_time ? Date.parse(b.event_time) : 0;
      return tb - ta;
    })
    .map((e) => {
      const fields = e.fields || {};
      const value =
        num(fields.calories, NaN) ||
        num(fields.amount, NaN) ||
        num(fields.hours, NaN) ||
        num(fields.value, NaN);
      const headline = humanizeRaw(e.raw, e.type, fields);
      return {
        id: e.id,
        headline,
        timeText: e.event_time ? niceTime(e.event_time) : '',
        value: Number.isFinite(value) ? value : null,
      };
    });
}

function humanizeRaw(
  raw: string,
  type: string,
  fields: Record<string, unknown>,
): string {
  const trimmed = (raw || '').trim();
  if (trimmed) {
    // Capitalise first letter; assume the user's voice for the rest.
    return trimmed[0].toUpperCase() + trimmed.slice(1);
  }
  if (typeof fields.item === 'string') return fields.item;
  if (typeof fields.label === 'string') return fields.label;
  return type;
}

function niceTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString([], {
      hour: 'numeric',
      minute: '2-digit',
    });
    if (sameDay) return time.toLowerCase();
    const ago = Math.round((now.getTime() - d.getTime()) / 36e5);
    if (ago < 24) return `${ago}h ago`;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

function dayLabel(day: string, isToday: boolean): string {
  if (isToday) return 'today';
  try {
    const d = new Date(day);
    return d.toLocaleDateString([], { weekday: 'narrow' });
  } catch {
    return '';
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Donna's read — templated for now, replaceable with an LLM call later
// ─────────────────────────────────────────────────────────────────────────

function composeDonnaRead({
  value,
  target,
  unit,
  today,
  yesterday,
  meals,
}: {
  value: number;
  target: number;
  unit: string;
  today: { value: number; count: number } | undefined;
  yesterday: { value: number; count: number } | undefined;
  meals: ReturnType<typeof humanizeEvidence>;
}): string | null {
  if (target > 0) {
    const remaining = target - value;
    const pct = (value / target) * 100;
    if (meals.length === 0) {
      return `nothing logged yet — easy to get behind today.`;
    }
    if (pct >= 100) {
      const over = value - target;
      return `${fmtN(over)} ${unit || ''} over goal. tomorrow's a fresh window.`;
    }
    if (pct >= 80) {
      return `close. ${fmtN(remaining)} ${unit || ''} of room — light something works.`;
    }
    if (pct >= 40) {
      return `${fmtN(remaining)} ${unit || ''} left. plenty of room for a real meal.`;
    }
    return `${fmtN(remaining)} ${unit || ''} under. you're light today — eat something proper.`;
  }
  // No target — talk about momentum vs yesterday
  if (yesterday && yesterday.value > 0) {
    const delta = value - yesterday.value;
    if (delta > 0)
      return `up ${fmtN(delta)} ${unit || ''} from yesterday. nice.`;
    if (delta < 0)
      return `${fmtN(-delta)} ${unit || ''} less than yesterday — slow start.`;
  }
  if (meals.length === 0) return null;
  return `${meals.length} logged today.`;
}
