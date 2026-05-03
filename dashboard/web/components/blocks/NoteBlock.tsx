/**
 * NoteBlock — catalogue archetype #02.
 *
 * Donna's voice on the moment. Sits immediately below the intro; one
 * sentence to a short paragraph. Three flavors:
 *
 *   editorial — borderless, italic kicker, breathing whitespace.
 *               canonical mode for daily notes.
 *   bar       — rust-tinted card with a 2px accent stripe.
 *               for shorter, more pragmatic notes that point at one thing.
 *   confront  — oxblood, italic eyebrow, serif body.
 *               only when kind=confrontation. one per plan, ever.
 */

import TapToTalk from '../TapToTalk';
import type { NoteBlock as NoteSpec } from '@/lib/plan';

export default function NoteBlock({ spec }: { spec: NoteSpec }) {
  const kind = spec.kind ?? 'editorial';
  const eyebrow = spec.eyebrow ?? (kind === 'confront' ? 'a note from me · the hard one' : 'a note from me');
  const actions = spec.actions ?? {};
  // The note IS donna's voice on the moment — when the user taps, they
  // continue that voice in WhatsApp. Truncate long notes for the primer
  // so we don't blow past WhatsApp's URL length comfort.
  const tapPrimer =
    kind === 'confront'
      ? `let's talk about: ${spec.body.slice(0, 200)}`
      : `say more about: ${spec.body.slice(0, 200)}`;

  if (kind === 'bar') {
    return (
      <TapToTalk
        primer={tapPrimer}
        decoration="block"
        style={{
          margin: '14px 16px 0',
          padding: '12px 14px',
          background: 'var(--rust-100)',
          borderLeft: '2px solid var(--rust-700)',
          borderRadius: 2,
        }}
      >
        <Eyebrow tone="var(--rust-700)">{eyebrow}</Eyebrow>
        <div
          style={{
            fontSize: 13.5,
            lineHeight: 1.55,
            color: 'var(--ink-900)',
            marginTop: 5,
          }}
        >
          {spec.body}
        </div>
      </TapToTalk>
    );
  }

  if (kind === 'confront') {
    return (
      <TapToTalk
        primer={tapPrimer}
        decoration="block"
        style={{
          margin: '14px 16px 0',
          padding: '14px 16px',
          background: 'var(--oxblood-100)',
          border: '1px solid rgba(30,26,24,0.08)',
          borderLeft: '3px solid var(--oxblood-700)',
          borderRadius: 6,
        }}
      >
        <Eyebrow tone="var(--oxblood-700)">{eyebrow}</Eyebrow>
        <div
          style={{
            fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
            fontSize: 18,
            fontWeight: 500,
            lineHeight: 1.25,
            color: 'var(--ink-900)',
            marginTop: 6,
            letterSpacing: '-0.01em',
          }}
        >
          {spec.body}
        </div>
      </TapToTalk>
    );
  }

  // editorial — the canonical flavor. Body itself is the tap target;
  // wrapping the whole block (eyebrow + action labels) would nest
  // anchors. The discrete primary/secondary/tertiary action labels
  // below stay independent tap targets.
  return (
    <div style={{ margin: '14px 22px 0' }}>
      <Eyebrow tone="var(--rust-700)">{eyebrow}</Eyebrow>
      <TapToTalk
        primer={tapPrimer}
        decoration="block"
        style={{
          fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
          fontSize: 24,
          fontWeight: 400,
          lineHeight: 1.25,
          letterSpacing: '-0.015em',
          color: 'var(--ink-900)',
          marginTop: 8,
          textWrap: 'pretty' as 'pretty',
        }}
      >
        {spec.body}
      </TapToTalk>
      {(actions.primary || actions.secondary || actions.tertiary) && (
        <div
          style={{
            marginTop: 14,
            paddingTop: 10,
            borderTop: '1px solid rgba(30,26,24,0.08)',
            display: 'flex',
            gap: 18,
          }}
        >
          {actions.primary !== undefined && (
            <TapToTalk
              primer={`noted: ${spec.body.slice(0, 160)}`}
              decoration="label"
              style={{ fontSize: 12, color: 'var(--ink-600)' }}
            >
              {actions.primary || 'noted'}
            </TapToTalk>
          )}
          {actions.secondary !== undefined && (
            <TapToTalk
              primer={`say more about: ${spec.body.slice(0, 160)}`}
              decoration="label"
              style={{ fontSize: 12, color: 'var(--rust-700)', fontWeight: 500 }}
            >
              {actions.secondary || 'say more'}
            </TapToTalk>
          )}
          {actions.tertiary !== undefined && (
            <TapToTalk
              primer={`skip this: ${spec.body.slice(0, 160)}`}
              decoration="label"
              style={{ fontSize: 12, color: 'var(--ink-500)' }}
            >
              {actions.tertiary || 'skip'}
            </TapToTalk>
          )}
        </div>
      )}
    </div>
  );
}

function Eyebrow({ children, tone }: { children: React.ReactNode; tone: string }) {
  return (
    <div
      style={{
        fontSize: 9.5,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: tone,
        fontWeight: 500,
      }}
    >
      {children}
    </div>
  );
}
