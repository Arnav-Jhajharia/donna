'use client';

/**
 * Intro — the fixed top region. Sits naked on the canvas: no border,
 * no radius, no shadow. Holds the date kicker, the greeting (with optional
 * italic accent), the place/weather line, and an optional illustration slot.
 *
 * Distinct from Frame on purpose — see system.html §6. The dashboard's
 * shape is "intro region + rows of frames". Treating Intro as a Frame
 * would lose the editorial breathing room at the top.
 */

import type { ReactNode } from 'react';

export interface IntroProps {
  /** "friday · 18 april" — uppercase tracking label. */
  kicker: string;
  /** "good morning, " — plain text before the accent. */
  greetingPrefix?: string;
  /** Italic rust accent within the greeting (usually a name). */
  accent?: string;
  /** Optional trailing punctuation after the accent: "." */
  greetingSuffix?: string;
  /** Full greeting if you don't want to use prefix/accent split. */
  greeting?: string;
  /** "mumbai · 29° · slight haze, cooler by the sea" */
  place?: string;
  /** Optional illustration — single-weight rust line drawing. */
  illustration?: ReactNode;
}

export function Intro({
  kicker,
  greetingPrefix,
  accent,
  greetingSuffix,
  greeting,
  place,
  illustration,
}: IntroProps) {
  return (
    <div className="intro">
      <p className="intro__kicker">{kicker}</p>
      <h2 className="intro__greet">
        {greeting ? (
          greeting
        ) : (
          <>
            {greetingPrefix}
            {accent && <em>{accent}</em>}
            {greetingSuffix}
          </>
        )}
      </h2>
      {place && <p className="intro__place">{place}</p>}
      {illustration && <div className="intro__illo">{illustration}</div>}
    </div>
  );
}
