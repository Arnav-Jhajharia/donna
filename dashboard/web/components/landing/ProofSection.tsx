"use client";

/**
 * ProofSection — nine-state scroll-controlled chat reveal.
 *
 * Flow:
 *   Hero ends → user scrolls → ProofSection enters view, pins, hijacks scroll.
 *   From there, each gesture (wheel, touch swipe, arrow/space/page key)
 *   advances exactly one state. Nine states in total:
 *
 *     1  P1 S1  first message only (user: "Mom's birthday next week.")
 *     2  P1 S2  user message persists; Donna's reply lands staggered
 *     3  P1 S3  chat persists in place; tagline "She gets you." appears below
 *     4  P2 S1  pillar 2 first message (user)
 *     5  P2 S2  + Donna's replies
 *     6  P2 S3  + tagline "She connects the dots."
 *     7  P3 S1  pillar 3 first message (Donna initiates)
 *     8  P3 S2  + Donna's second message
 *     9  P3 S3  + tagline "She reaches out to you."
 *
 *   After state 9, one more scroll releases the hijack so the page can
 *   resume native scrolling past this section (currently nothing follows).
 *
 * Gesture gating mirrors ArrivalSequence — 700ms cooldown per accepted
 * advance, plus a gesture-quiet extension so trackpad inertia can't sneak
 * a second advance at the tail of a flick. One gesture, one state.
 *
 * Design-system mappings (locked):
 *   Instrument Serif italic → EB Garamond italic via font-serif +
 *                              italic-accent-heading.
 *   DM Sans               → Red Hat Text via font-sans.
 *   #7B5544 accent        → text-rust / var(--color-rust).
 *   #1E1A18 text          → text-ink.
 *   #FBF7F5 page cream    → bg-paper.
 *   Donna bubble white    → CSS keyword "white" (no palette token exists).
 *   Donna bubble lift     → .donna-bubble-lift class in globals.css.
 */

import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useReducedMotion } from "framer-motion";
import GetDonnaCTA from "./GetDonnaCTA";

const CHAT_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

// Paper grain. Inline SVG fractal noise tiled at 180px. Sits at ~3.5% opacity
// on top of the cream background — warms the surface without reading as
// texture on first glance.
const GRAIN_DATA_URI =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>" +
      "<filter id='n'>" +
      "<feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/>" +
      "<feColorMatrix values='0 0 0 0 0.12 0 0 0 0 0.10 0 0 0 0 0.09 0 0 0 1 0'/>" +
      "</filter>" +
      "<rect width='100%' height='100%' filter='url(#n)'/>" +
      "</svg>"
  );

// Gesture hijack tuning — delta-accumulator model.
//   WHEEL_THRESHOLD: total downward deltaY that must accumulate before one
//     advance fires. A standard mouse-wheel notch ships ~100px in a single
//     event, so one notch = instant advance. A trackpad sends small deltas
//     (~3–10px) continuously, so a short swipe crosses the threshold in a
//     few events.
//   COOLDOWN_MS:     after firing, further deltas are discarded for this long
//     so a single flick's inertia tail doesn't double-advance. The accumulator
//     resets at the same time. Short enough (450ms) that *continuous* scrolling
//     still keeps advancing roughly every half-second — which is what users
//     expect from holding down a scroll gesture.
//   GAP_RESET_MS:    if the user pauses this long between wheel events, we
//     treat the next event as a fresh gesture and reset the accumulator so
//     stale partial-progress doesn't linger for minutes.
const WHEEL_THRESHOLD = 120;
const COOLDOWN_MS = 900;
const GAP_RESET_MS = 250;
const TOUCH_DY_THRESHOLD = 8;
// Forward-only: ArrowUp / PageUp / Home are not accepted (no back-scroll).
const ADVANCE_KEYS = new Set([
  " ",
  "Spacebar",
  "ArrowDown",
  "PageDown",
  "End",
]);

const APOS = "\u2019";
const EM_DASH = "\u2014";

type Sender = "YOU" | "DONNA";
type Message = { sender: Sender; body: ReactNode };
type Pillar = { tagline: string; messages: Message[] };

const PILLARS: Pillar[] = [
  {
    tagline: "She gets you.",
    messages: [
      { sender: "YOU", body: <>Mom{APOS}s birthday next week.</> },
      {
        sender: "DONNA",
        body: (
          <>
            She has three trips this year. A passport cover with her initials{" "}
            {EM_DASH} you always get her something personal.
          </>
        ),
      },
      {
        sender: "DONNA",
        body: <>She{APOS}ll remember you at every airport.</>,
      },
    ],
  },
  {
    tagline: "She connects the dots.",
    messages: [
      {
        sender: "YOU",
        body: <>Movie tonight with Clara?</>,
      },
      {
        sender: "DONNA",
        body: (
          <>
            <em className="italic-accent-inline">La La Land.</em> Clara walked
            out of <em className="italic-accent-inline">John Wick</em>{" "}
            {EM_DASH} skip anything violent.
          </>
        ),
      },
      {
        sender: "DONNA",
        body: (
          <>
            She{APOS}ll love it. You{APOS}ll pretend you didn{APOS}t cry.
          </>
        ),
      },
    ],
  },
  {
    // Pillar 3 — Donna initiates. No YOU message. State 1 reveals her first
    // turn; state 2 reveals her second.
    tagline: "She reaches out to you.",
    messages: [
      {
        sender: "DONNA",
        body: (
          <>
            Dubai in 9 days. UAE added visa rules last month {EM_DASH} you
            {APOS}ll need 5 working days.
          </>
        ),
      },
      {
        sender: "DONNA",
        body: <>Apply today.</>,
      },
    ],
  },
];

const SUB_STATES_PER_PILLAR = 3;
const TOTAL_STATES = PILLARS.length * SUB_STATES_PER_PILLAR;

/* =====================================================================
 * Message — a single chat line, rendered as type only. No bubble, no
 * label, no timestamp, no avatar, no alignment difference. YOU vs DONNA
 * differentiate purely through size + opacity:
 *
 *   YOU    →  smaller, 55% ink (quieter, a memory)
 *   DONNA  →  larger,  100% ink (clear, present voice)
 *
 * Both share the same left edge. Visibility is opacity-gated so layout
 * stays stable as states advance.
 * =================================================================== */

function Message({
  sender,
  body,
  visible,
  delay,
  marginTop,
  reduced,
}: {
  sender: Sender;
  body: ReactNode;
  visible: boolean;
  delay: number;
  marginTop: string;
  reduced: boolean;
}) {
  const isUser = sender === "YOU";
  const transition = reduced
    ? "none"
    : `opacity 600ms ${CHAT_EASE} ${delay}ms, transform 600ms ${CHAT_EASE} ${delay}ms`;

  return (
    <p
      // YOU: DM Sans, muted warm-gray, body size.
      // DONNA: EB Garamond roman at 400, ink, larger body.
      // Centered text in the new stacked layout — auto margins keep the
      // narrower YOU line and the wider DONNA line both visually centered.
      className={isUser ? "font-sans" : "font-serif"}
      style={{
        // Desktop type ceilings raised so the conversation has presence
        // on a wide screen instead of disappearing into negative space.
        // Mobile (the min end of each clamp) stays unchanged.
        fontSize: isUser
          ? "clamp(18px, 1.6vw + 12.5px, 28px)"
          : "clamp(24px, 3.2vw + 12px, 44px)",
        lineHeight: isUser ? 1.5 : 1.35,
        letterSpacing: isUser ? undefined : "-0.005em",
        fontWeight: 400,
        // YOU: warm brown (rust-500 tint), not gray — the sender's voice is
        // a quiet but warm memory, not a washed-out neutral.
        // DONNA: full ink, clear and present.
        color: isUser ? "var(--rust-500)" : "var(--color-ink)",
        maxWidth: isUser ? "560px" : "880px",
        marginLeft: 0,
        marginRight: 0,
        marginTop,
        opacity: visible ? 1 : 0,
        transform: visible
          ? "translate3d(0, 0, 0)"
          : "translate3d(0, 12px, 0)",
        transition,
        willChange: "opacity, transform",
      }}
    >
      {body}
    </p>
  );
}

/* =====================================================================
 * PillarStage — editorial chat + tagline.
 *
 * Desktop: split layout. Chat left, tagline right. ≥120px of negative
 * space between the chat column's right edge and the tagline.
 * Mobile: stacked. Chat on top, tagline beneath, ≥72px between them.
 *
 * Reveal states:
 *   1  only first message visible
 *   2  all messages visible (staggered reveal of the new ones)
 *   3  all messages + tagline
 *
 * Between-message rhythm:
 *   YOU → DONNA : 20px mobile / 28px desktop
 *   DONNA→ DONNA: 24px mobile / 36px desktop
 * =================================================================== */

function PillarStage({
  pillar,
  subState,
  reduced,
}: {
  pillar: Pillar;
  subState: number;
  reduced: boolean;
}) {
  const FIRST_BATCH = 1;

  const messageVisible = (i: number) => {
    if (subState <= 0) return false;
    if (subState === 1) return i < FIRST_BATCH;
    return true;
  };

  const showTagline = subState >= 3;

  const taglineTransition = reduced
    ? "none"
    : `opacity 900ms ${CHAT_EASE} 250ms, transform 900ms ${CHAT_EASE} 250ms`;

  // Gap between a given message and the one above it. Scaled up on
  // desktop to keep proportional rhythm with the bigger DONNA type
  // (44px cap) — a 28px gap under a 44px line reads as too cramped.
  const gapFor = (i: number): string => {
    if (i === 0) return "0px";
    const prev = pillar.messages[i - 1];
    const curr = pillar.messages[i];
    if (prev.sender === "DONNA" && curr.sender === "DONNA") {
      // 24px mobile → ~56px desktop.
      return "clamp(24px, 2vw + 16px, 56px)";
    }
    // Default (YOU→DONNA, YOU→YOU, DONNA→YOU): 20px mobile → ~40px desktop.
    return "clamp(20px, 1.5vw + 12px, 40px)";
  };

  return (
    <div
      // Stacked vertically on every viewport: conversation reads first
      // (top), tagline lands as the payoff below it (bottom). Left-aligned
      // editorial layout — both the conversation and the payoff sit on
      // the same left rail, centered vertically with a clear gap between
      // conversation and payoff.
      className="flex h-full w-full flex-col items-start justify-center"
      style={{
        gap: "clamp(48px, 7vh, 88px)",
        paddingLeft: "clamp(24px, 6vw, 120px)",
        paddingRight: "clamp(24px, 6vw, 120px)",
      }}
    >
      {/* Chat column — left-aligned text block, conversation reads top→bottom.
          Wider cap on desktop so the conversation commands the viewport
          rather than floating in a 640px island on a 1920px screen. */}
      <div
        role="log"
        aria-live="polite"
        className="flex flex-col items-start text-left"
        style={{
          maxWidth: "min(900px, 90vw)",
          width: "100%",
        }}
      >
        {pillar.messages.map((m, i) => {
          const newIdx = Math.max(0, i - FIRST_BATCH);
          const delay = i < FIRST_BATCH ? 0 : newIdx * 220;
          return (
            <Message
              key={i}
              sender={m.sender}
              body={m.body}
              visible={messageVisible(i)}
              delay={delay}
              marginTop={gapFor(i)}
              reduced={reduced}
            />
          );
        })}
      </div>

      {/* Tagline — the editorial payoff, sits centered beneath the
          conversation. Always-mounted so the layout doesn't jump when it
          fades in at sub-state 3. */}
      <Tagline
        text={pillar.tagline}
        visible={showTagline}
        transition={taglineTransition}
      />
    </div>
  );
}

/* =====================================================================
 * Tagline — renders body + a rust-colored final stop.
 * Splits on the last "." so the accent is always the concluding
 * punctuation, never a mid-sentence period.
 * =================================================================== */

function Tagline({
  text,
  visible,
  transition,
}: {
  text: string;
  visible: boolean;
  transition: string;
}) {
  return (
    <h2
      className="italic-accent-heading font-serif text-ink"
      style={{
        // True display size on desktop — the tagline is the editorial
        // payoff and should command the page width, not sit in a 640px
        // pocket. Mobile (clamp min) stays at 44px.
        fontSize: "clamp(44px, 9vw, 152px)",
        lineHeight: 0.92,
        letterSpacing: "-0.03em",
        fontWeight: 400,
        maxWidth: "min(1100px, 90vw)",
        textAlign: "left",
        opacity: visible ? 1 : 0,
        transform: visible
          ? "translate3d(0, 0, 0)"
          : "translate3d(0, 16px, 0)",
        transition,
        willChange: "opacity, transform",
      }}
    >
      {text}
    </h2>
  );
}

/* =====================================================================
 * ProofSection — orchestrator.
 * =================================================================== */

type ProofSectionProps = {
  // Called once when the user advances past the final state (state 9).
  // The parent uses this to transition to the next phase (DonnaPromise).
  onComplete?: () => void;
};

export default function ProofSection({ onComplete }: ProofSectionProps = {}) {
  const reduced = useReducedMotion() === true;

  // 1..TOTAL_STATES. The component is mounted only when the proof phase is
  // entered (see page.tsx), so state 1 is always the first thing the user
  // sees in this phase: pillar 1, user's first message only.
  const [state, setState] = useState(1);

  const pillarIdx = Math.floor((state - 1) / SUB_STATES_PER_PILLAR);
  const subState = ((state - 1) % SUB_STATES_PER_PILLAR) + 1;
  const activePillar = PILLARS[pillarIdx] ?? PILLARS[0];

  /* ----- Reduced-motion: jump straight to the end. -----
   * Intentional setState-in-effect — useReducedMotion resolves null→bool
   * post-hydration, so initializing useState from it would race SSR.
   */
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (reduced) setState(TOTAL_STATES);
  }, [reduced]);

  /* ----- Scroll hijack. Runs for the lifetime of the component (until
   * state reaches TOTAL_STATES, after which further gestures are simply
   * swallowed — no back-scroll, no runaway). body-overflow is locked at
   * the page level; we only manage gesture listeners here.
   * ---------------------------------------------------------------- */
  useEffect(() => {
    if (reduced) return;
    if (typeof window === "undefined") return;

    const now = () =>
      typeof performance !== "undefined" ? performance.now() : Date.now();

    // Arm the listener slightly after mount so trackpad inertia from the
    // hero-advance gesture can't trigger the first state advance.
    const PROOF_ARM_MS = 350;
    let armedAt = now() + PROOF_ARM_MS;
    // Scroll accumulator. Each downward wheel event adds to `accum`; when it
    // crosses WHEEL_THRESHOLD we fire one advance and reset.
    let accum = 0;
    let lastWheelAt = 0;
    let touchStartY: number | null = null;
    let touchConsumed = false;

    let completed = false;
    const tryAdvance = () => {
      const t = now();
      if (t < armedAt) return;
      armedAt = t + COOLDOWN_MS;
      accum = 0;
      setState((s) => {
        if (s < TOTAL_STATES) return s + 1;
        // Already on the final state — one more gesture hands off to the
        // next phase (DonnaPromise). Fire onComplete once.
        if (!completed) {
          completed = true;
          onComplete?.();
        }
        return s;
      });
    };

    const onWheel = (e: WheelEvent) => {
      // Always swallow — body overflow is locked by the parent anyway, but
      // preventDefault kills any residual native scrolling attempts.
      e.preventDefault();

      // Ignore up-scrolls entirely (no back-scroll by design).
      if (e.deltaY <= 0) return;

      const t = now();
      // In cooldown window — discard everything so inertia can't add up into
      // a second advance. Keep accumulator at 0.
      if (t < armedAt) {
        accum = 0;
        lastWheelAt = t;
        return;
      }
      // If the user paused, drop any stale partial progress so the next flick
      // starts fresh rather than triggering immediately.
      if (lastWheelAt && t - lastWheelAt > GAP_RESET_MS) {
        accum = 0;
      }
      lastWheelAt = t;

      accum += Math.abs(e.deltaY);
      if (accum >= WHEEL_THRESHOLD) {
        tryAdvance();
      }
    };
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
        // Finger moving up (dy < 0) = page-down gesture = advance.
        if (dy < 0) tryAdvance();
      }
    };
    const onTouchEnd = () => {
      touchStartY = null;
      touchConsumed = false;
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (!ADVANCE_KEYS.has(e.key)) return;
      e.preventDefault();
      if (e.repeat) return;
      tryAdvance();
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [reduced, onComplete]);

  /* ----- Pillar cross-fade when advancing from one pillar to the next ----- */
  const pillarOpacity = (i: number) => (pillarIdx === i ? 1 : 0);
  const pillarTransition = reduced
    ? "none"
    : `opacity 500ms ${CHAT_EASE}`;

  const ariaLabel = useMemo(
    () => activePillar.tagline,
    [activePillar.tagline]
  );

  return (
    <section
      aria-label={ariaLabel}
      className="relative w-full bg-paper overflow-hidden"
      style={{ height: "100svh" }}
    >
      {/* Persistent Get Donna CTA — top-right, every pillar screen. */}
      <GetDonnaCTA />

      {/* Paper-grain overlay — warms the cream without announcing itself.
          Decorative, non-interactive, behind all content. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: `url("${GRAIN_DATA_URI}")`,
          backgroundRepeat: "repeat",
          backgroundSize: "180px 180px",
          opacity: 0.035,
          mixBlendMode: "multiply",
          zIndex: 0,
        }}
      />

      {/* Stack all three pillar stages — only the active one is opaque.
          Keeping them mounted avoids bubble-remount flicker. */}
      {PILLARS.map((p, i) => {
        const isActive = pillarIdx === i;
        return (
          <div
            key={i}
            aria-hidden={!isActive}
            className="absolute inset-0 flex items-center justify-center"
            style={{
              opacity: pillarOpacity(i),
              transition: pillarTransition,
              pointerEvents: isActive ? "auto" : "none",
              willChange: "opacity",
              zIndex: 1,
            }}
          >
            <PillarStage
              pillar={p}
              subState={isActive ? subState : 0}
              reduced={reduced}
            />
          </div>
        );
      })}
    </section>
  );
}
