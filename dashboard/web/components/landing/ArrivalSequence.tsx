"use client";

/**
 * ArrivalSequence — the first screen a visitor sees on the Donna landing site.
 *
 * Six short lines land one after the other, centered in the viewport.
 * Lines 1–5 fade in, hold, and fade out. The final line holds and becomes
 * the rust moment for the screen (one italic rust accent inside a heading).
 *
 * Everything else — location, time — resolves on the client without blocking
 * first paint. If detection fails, the copy falls back to neutral.
 *
 * Decorative by design: the sequence is wrapped in `aria-hidden`, the page
 * has an sr-only H1, and a skip link jumps straight to the main landmark.
 *
 * Interaction: tap anywhere to skip to the held final state.
 *
 * Motion rules:
 *  - 400 / 1800 / 400 + 200 gap between lines, 1500ms post-hold before exit.
 *  - `prefers-reduced-motion: reduce` → render only the final line, no fades.
 *  - No layout shift: all lines share one grid cell, so the container height
 *    is always the tallest line's height.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Accent } from "@/components/landing";
import { describeTime, detectCity } from "@/lib/landing/arrival";
import { saveDonnaLocation } from "@/lib/landing/getDonnaWhatsAppLink";

const FADE_IN_MS = 400;
const HOLD_MS = 1800;
const FADE_OUT_MS = 400;
const GAP_MS = 200;
const FINAL_HOLD_MS = 1500;

// Scroll-to-advance tuning.
//
// SCROLL_COOLDOWN_MS — minimum interval between accepted advances. Must exceed
//   typical trackpad inertia (~500–700ms) or a single flick registers twice.
// GESTURE_QUIET_MS  — if a wheel event arrives while we're still locked, extend
//   the lock by this much so the momentum tail of one gesture doesn't trigger
//   a second advance the moment the cooldown expires.
const SCROLL_COOLDOWN_MS = 700;
const GESTURE_QUIET_MS = 150;
// Minimum vertical touch delta before a swipe counts as an advance.
const TOUCH_DY_THRESHOLD = 8;
// Keys that would normally scroll the page; consume them and advance instead.
const ADVANCE_KEYS = new Set([
  " ",
  "Spacebar",
  "ArrowDown",
  "ArrowUp",
  "PageDown",
  "PageUp",
  "End",
  "Home",
]);

const FADE_IN_SEC = FADE_IN_MS / 1000;
const FADE_OUT_SEC = FADE_OUT_MS / 1000;

// The design system's standard ease (see tokens.css --ease-standard).
const EASE_STANDARD: [number, number, number, number] = [0.2, 0, 0, 1];

type Line = { id: string; node: React.ReactNode };

function buildLines(city: string | null, now: Date): Line[] {
  const place = city ?? "somewhere in the world";
  const locationPhrase =
    city === null ? `You\u2019re ${place}.` : `You\u2019re in ${place}.`;

  return [
    { id: "location", node: <>{locationPhrase}</> },
    { id: "time", node: <>{describeTime(now)}</> },
    { id: "tomorrow", node: <>You said &ldquo;tomorrow&rdquo; yesterday.</> },
    {
      id: "todo",
      node: <>Last week&rsquo;s to-do list is still this week&rsquo;s to-do list.</>,
    },
    {
      id: "reply",
      node: (
        <>
          You still haven&rsquo;t replied to the person you said you would two
          days back.
        </>
      ),
    },
    {
      id: "final",
      node: (
        <>
          Wondering what to <Accent>do</Accent>?
        </>
      ),
    },
  ];
}

type Props = {
  onComplete?: () => void;
};

export default function ArrivalSequence({ onComplete }: Props) {
  const reduceMotion = useReducedMotion() === true;

  const [city, setCity] = useState<string | null>(null);
  const [cityReady, setCityReady] = useState(false);
  const [idx, setIdx] = useState(0);
  const [opaque, setOpaque] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [done, setDone] = useState(false);

  // Freeze the arrival timestamp so the time line doesn't shift during the
  // sequence itself. Using useState with a lazy initializer is safer than a
  // ref for render-time access — the value is stable across renders without
  // tripping the react-hooks/refs rule.
  const [arrivalNow] = useState<Date>(() => new Date());

  // Detect the visitor's city, then flip `cityReady`. The first line is
  // gated on this flag — no flash of "somewhere in the world" before the
  // real city lands. If detection hangs or fails, a short timeout flips
  // the flag anyway so the sequence can't stall.
  useEffect(() => {
    const ctrl = new AbortController();
    const CITY_TIMEOUT_MS = 1200;
    const fallbackTimer = window.setTimeout(() => {
      setCityReady(true);
    }, CITY_TIMEOUT_MS);

    detectCity(ctrl.signal)
      .then((resolved) => {
        if (resolved) {
          setCity(resolved);
          // Persist for every CTA on the site — single source of truth.
          saveDonnaLocation(resolved);
        }
        setCityReady(true);
        window.clearTimeout(fallbackTimer);
      })
      .catch(() => {
        setCityReady(true);
        window.clearTimeout(fallbackTimer);
      });

    return () => {
      ctrl.abort();
      window.clearTimeout(fallbackTimer);
    };
  }, []);

  const lines = useMemo(() => buildLines(city, arrivalNow), [city, arrivalNow]);
  const total = lines.length;
  const finalIdx = total - 1;

  // Skip-to-final or reduced-motion: jump straight to the held final line.
  // The setState calls here are intentional — they translate a prop/event
  // flip into the visible state. Using an initializer would race the SSR /
  // hydration mismatch from useReducedMotion's null→bool transition.
  useEffect(() => {
    if (!reduceMotion && !skipped) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIdx(finalIdx);
    setOpaque(true);
    const t = window.setTimeout(() => setDone(true), FINAL_HOLD_MS);
    return () => window.clearTimeout(t);
  }, [reduceMotion, skipped, finalIdx]);

  // Pending timers from the timed path — held in refs so scrollAdvance()
  // can cancel them and run its own fade-out → advance sequence cleanly.
  const tOutRef = useRef<number | null>(null);
  const tNextRef = useRef<number | null>(null);
  const tDoneRef = useRef<number | null>(null);

  const clearTimedTimers = useCallback(() => {
    if (tOutRef.current !== null) {
      window.clearTimeout(tOutRef.current);
      tOutRef.current = null;
    }
    if (tNextRef.current !== null) {
      window.clearTimeout(tNextRef.current);
      tNextRef.current = null;
    }
    if (tDoneRef.current !== null) {
      window.clearTimeout(tDoneRef.current);
      tDoneRef.current = null;
    }
  }, []);

  // Main sequence: fade in → hold → fade out → gap → advance.
  // Gate the very first line on `cityReady` so the fallback copy never flashes
  // before the resolved city. Subsequent lines don't depend on city, so they
  // run as soon as their idx is active.
  useEffect(() => {
    if (reduceMotion || skipped) return;
    if (idx === 0 && !cityReady) return;

    const raf = window.requestAnimationFrame(() => setOpaque(true));
    const isFinal = idx === finalIdx;

    if (isFinal) {
      tDoneRef.current = window.setTimeout(() => {
        tDoneRef.current = null;
        setDone(true);
      }, FADE_IN_MS + FINAL_HOLD_MS);
      return () => {
        window.cancelAnimationFrame(raf);
        clearTimedTimers();
      };
    }

    tOutRef.current = window.setTimeout(() => {
      tOutRef.current = null;
      setOpaque(false);
    }, FADE_IN_MS + HOLD_MS);
    tNextRef.current = window.setTimeout(() => {
      tNextRef.current = null;
      setIdx((i) => i + 1);
    }, FADE_IN_MS + HOLD_MS + FADE_OUT_MS + GAP_MS);

    return () => {
      window.cancelAnimationFrame(raf);
      clearTimedTimers();
    };
  }, [idx, finalIdx, reduceMotion, skipped, cityReady, clearTimedTimers]);

  // Emit the completion signal exactly once.
  const emittedRef = useRef(false);
  useEffect(() => {
    if (done && !emittedRef.current) {
      emittedRef.current = true;
      onComplete?.();
    }
  }, [done, onComplete]);

  // ------------------------------------------------------------------
  // Scroll / touch / key hijack
  // ------------------------------------------------------------------
  // Any scroll-ish gesture during the arrival is consumed by the overlay
  // and used to advance one line. If the user doesn't gesture at all, the
  // timed sequence above still advances them through. The final line's
  // advance dismisses the overlay rather than waiting out FINAL_HOLD_MS.
  //
  // We also pin <body> to overflow:hidden as a belt-and-braces guard
  // against trackpad inertia / momentum events we didn't catch.
  // ------------------------------------------------------------------
  const lockedUntilRef = useRef(0);
  const scrollAdvTimerRef = useRef<number | null>(null);
  // Exposed by the gesture-hijack effect so the click/tap handler can run
  // the same one-line-at-a-time advance as scroll/keyboard. Without this,
  // tap would have to setState({skipped: true}) which jumps to the final
  // line — the user explicitly does not want that.
  const advanceRef = useRef<(() => void) | null>(null);
  const idxRef = useRef(idx);
  useEffect(() => {
    idxRef.current = idx;
  }, [idx]);

  useEffect(() => {
    if (done) return;
    if (typeof window === "undefined") return;

    // Runs the same visual beat as the timed path:
    //   fade out current (FADE_OUT_MS) → gap (GAP_MS) → bump idx.
    // The idx effect re-runs on the bump, rAF flips opaque back on, the new
    // line fades in. One consistent animation for both timed and scroll.
    const scrollAdvance = () => {
      clearTimedTimers();
      if (scrollAdvTimerRef.current !== null) {
        window.clearTimeout(scrollAdvTimerRef.current);
        scrollAdvTimerRef.current = null;
      }
      if (idxRef.current >= finalIdx) {
        // Final line — no line to advance to; dismiss.
        setDone(true);
        return;
      }
      setOpaque(false);
      scrollAdvTimerRef.current = window.setTimeout(() => {
        scrollAdvTimerRef.current = null;
        setIdx(idxRef.current + 1);
      }, FADE_OUT_MS + GAP_MS);
    };

    // Gesture-aware gate. A single trackpad flick fires a long stream of
    // wheel events; we ignore them all after the first, and extend the
    // lock while events keep arriving. That way hard-flick and soft-flick
    // both produce exactly one advance.
    const advance = () => {
      const now =
        typeof performance !== "undefined" ? performance.now() : Date.now();
      if (now < lockedUntilRef.current) {
        // Still inside the current gesture's tail — push the lock out so a
        // momentum event right at the boundary can't fire again.
        lockedUntilRef.current = Math.max(
          lockedUntilRef.current,
          now + GESTURE_QUIET_MS
        );
        return;
      }
      lockedUntilRef.current = now + SCROLL_COOLDOWN_MS;
      scrollAdvance();
    };
    advanceRef.current = advance;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      advance();
    };

    let touchStartY: number | null = null;
    let touchConsumed = false;
    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 0) return;
      touchStartY = e.touches[0].clientY;
      touchConsumed = false;
    };
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      if (touchConsumed || touchStartY === null) return;
      if (e.touches.length === 0) return;
      const dy = e.touches[0].clientY - touchStartY;
      if (Math.abs(dy) > TOUCH_DY_THRESHOLD) {
        touchConsumed = true;
        advance();
      }
    };
    const onTouchEnd = () => {
      touchStartY = null;
      touchConsumed = false;
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (!ADVANCE_KEYS.has(e.key)) return;
      e.preventDefault();
      // Ignore OS auto-repeat so holding the key down doesn't blast through
      // lines faster than the cooldown allows. One keypress = one advance.
      if (e.repeat) return;
      advance();
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("keydown", onKeyDown);

    // body-overflow is owned by page.tsx for the whole landing experience;
    // we don't toggle it here.
    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("keydown", onKeyDown);
      advanceRef.current = null;
      if (scrollAdvTimerRef.current !== null) {
        window.clearTimeout(scrollAdvTimerRef.current);
        scrollAdvTimerRef.current = null;
      }
    };
  }, [done, finalIdx, clearTimedTimers]);

  // Tap / click on the arrival overlay = one advance (same as scroll). The
  // earlier behavior set `skipped=true`, which jumped straight to the final
  // line — taps now step through one line at a time, matching scroll/keys.
  // Reduced-motion users still get a one-tap-to-final via the skipped
  // shortcut, since the timed sequence is bypassed for them anyway.
  const handleSkip = useCallback(() => {
    if (done) return;
    if (reduceMotion) {
      if (!skipped) setSkipped(true);
      return;
    }
    advanceRef.current?.();
  }, [reduceMotion, skipped, done]);

  // The skip link fast-forwards past the held final state entirely — keyboard
  // users should not have to wait for any hold timer.
  const handleSkipToContent = useCallback(() => {
    if (emittedRef.current) return;
    emittedRef.current = true;
    setDone(true);
    onComplete?.();
  }, [onComplete]);

  return (
    <section
      onClick={handleSkip}
      className="relative flex min-h-screen w-full cursor-default select-none items-center justify-center bg-paper px-5 py-8 text-ink"
    >
      {/* Skip link — revealed on keyboard focus. Jumps past the arrival. */}
      <a
        href="#main-content"
        onClick={(e) => {
          e.stopPropagation();
          handleSkipToContent();
        }}
        className="sr-only no-underline focus:not-sr-only focus:fixed focus:left-5 focus:top-5 focus:z-10 focus:rounded-sm focus:bg-surface focus:px-4 focus:py-3 focus:font-sans focus:text-small focus:text-ink focus:no-underline"
      >
        Skip to main content
      </a>

      {/* Page-level heading for assistive tech only. */}
      <h1 className="sr-only">Donna — your assistant on WhatsApp</h1>

      {/* Decorative text sequence. Not announced. Container width scales
          up on desktop so the longest lines (e.g. "You still haven't
          replied to the person you said you would two days back.") have
          room to breathe at the larger desktop type. */}
      <div
        aria-hidden="true"
        className="relative grid w-full"
        style={{ maxWidth: "min(960px, 90vw)" }}
      >
        {lines.map((line, i) => {
          const visible = !reduceMotion
            ? i === idx && opaque
            : i === finalIdx;

          return (
            <motion.p
              key={line.id}
              initial={false}
              animate={{ opacity: visible ? 1 : 0 }}
              transition={{
                duration: visible ? FADE_IN_SEC : FADE_OUT_SEC,
                ease: EASE_STANDARD,
              }}
              className="font-serif text-center text-ink"
              style={{
                gridArea: "1 / 1",
                // Mobile keeps ~text-h2 (32px); desktop scales up so the
                // editorial copy carries on a 27" display instead of
                // sitting in the middle as a small block.
                fontSize: "clamp(28px, 2.4vw + 18px, 56px)",
                lineHeight: 1.2,
                letterSpacing: "-0.015em",
                fontWeight: 400,
              }}
            >
              {line.node}
            </motion.p>
          );
        })}
      </div>
    </section>
  );
}
