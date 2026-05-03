"use client";

/**
 * DonnaPromise — the section IS the paper.
 *
 * No heading, no folded-letter prop, no desk metaphor. The viewport itself
 * is a single warm parchment surface with torn deckled edges on the left
 * and right (top and bottom flush to the viewport). The reader isn't looking
 * at a letter on a desk — they're looking at the page.
 *
 * Architecture:
 *  - Full-bleed SVG fills the viewport. A clipped path shapes the parchment
 *    with flat top/bottom and wobbled left/right "torn" edges. The rest of
 *    the viewport (a thin slice outside the torn edges) falls back to the
 *    site's bg-paper so the letter reads as paper inside paper.
 *  - The paper texture (radial warm-light gradient, fractalNoise grain,
 *    fractalNoise stains, edge vignette, fibers, nicks) is the same vocab
 *    from the earlier design; only the SHAPE changed from A5 to full-bleed.
 *  - Letter body fades in paragraph-by-paragraph on mount.
 *    prefers-reduced-motion jumps to final.
 *
 * Brand notes:
 *  - EB Garamond (font-serif) for body. Caveat (font-signature) for signature.
 *  - Paper-texture RGBs live inside the SVG render layer only — the paper
 *    is a rendered surface, not a brand UI color.
 */

import { useEffect, useState } from "react";
import { useReducedMotion } from "framer-motion";
import GetDonnaCTA from "./GetDonnaCTA";
import { useIsDesktop } from "@/lib/landing/useIsDesktop";

const LETTER_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

// Locked copy. Do not combine, do not punctuate further.
const PARAGRAPHS: string[] = [
  "I know.",
  "Before you tell me anything \u2014 you want to know where it goes.",
  "Nowhere. Just me.",
  "I don\u2019t read your other chats. I don\u2019t learn from yours.",
  "I don\u2019t take autonomous actions.",
  "This stays between us.",
];

// ─── Seeded RNG ──────────────────────────────────────────────────────────
function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return (s & 0xffffffff) / 0x100000000;
  };
}

// ─── Paper shape ─────────────────────────────────────────────────────────
//
// Build a full-viewport paper shape with flat top/bottom and torn deckled
// left/right edges. viewBox = 1000 × 1000, preserveAspectRatio="none" so
// it stretches to fit any section dimensions.
//
// Torn edges wobble between 0 and ~TEAR_AMP inward from each side.
type Shape = {
  d: string;
  fibers: Array<[number, number, number, number]>;
  W: number;
  H: number;
};

function buildPaperShape(): Shape {
  const W = 1000;
  const H = 1000;
  const TEAR_AMP = 28; // max depth of a tear into the paper
  const STEPS = 70; // vertical resolution of the torn edges
  const rand = seeded(17);

  // Per-side wobble: base inset + jitter + occasional deeper nicks.
  const makeEdge = (sign: 1 | -1): Array<[number, number]> => {
    const pts: Array<[number, number]> = [];
    for (let i = 0; i <= STEPS; i++) {
      const y = (i / STEPS) * H;
      const smallJitter = (rand() - 0.5) * TEAR_AMP * 0.85;
      const deepNick =
        rand() < 0.07 ? (rand() - 0.5) * TEAR_AMP * 1.8 : 0;
      const x0 = sign === 1 ? 0 : W;
      const inset = smallJitter + deepNick;
      // sign=1 (left edge): x hovers around 0 to +TEAR_AMP.
      // sign=-1 (right edge): x hovers around W to W - TEAR_AMP.
      pts.push([x0 + sign * Math.max(0, inset + TEAR_AMP * 0.5), y]);
    }
    return pts;
  };

  const leftEdge = makeEdge(1);
  const rightEdge = makeEdge(-1);

  // Build path: start top-left, trace down the left edge, across the
  // bottom (flat), up the right edge (reverse), across the top (flat).
  const parts: string[] = [];
  parts.push(`M ${leftEdge[0][0].toFixed(2)} 0`);
  for (let i = 1; i < leftEdge.length; i++) {
    parts.push(`L ${leftEdge[i][0].toFixed(2)} ${leftEdge[i][1].toFixed(2)}`);
  }
  // Flat bottom
  parts.push(`L ${rightEdge[rightEdge.length - 1][0].toFixed(2)} ${H}`);
  for (let i = rightEdge.length - 2; i >= 0; i--) {
    parts.push(`L ${rightEdge[i][0].toFixed(2)} ${rightEdge[i][1].toFixed(2)}`);
  }
  // Flat top back to start
  parts.push(`L ${leftEdge[0][0].toFixed(2)} 0`);
  parts.push("Z");

  // Small hair-fibers sticking out of the torn edges for texture.
  const fibers: Array<[number, number, number, number]> = [];
  const pushFibers = (edge: Array<[number, number]>, outward: 1 | -1) => {
    for (let i = 0; i < edge.length - 1; i++) {
      if (rand() < 0.32) {
        const [x, y] = edge[i];
        const len = 1.2 + rand() * 3.0;
        fibers.push([x, y, x + outward * len, y + (rand() - 0.5) * 2]);
      }
    }
  };
  pushFibers(leftEdge, -1);
  pushFibers(rightEdge, 1);

  return { d: parts.join(" "), fibers, W, H };
}

// Gesture hijack tuning — matches ProofSection's delta-accumulator model
// for scroll-feel consistency. One scroll = one advance (to the CTA phase).
// The arm delay covers ~half the unroll; if the user scrolls early they
// jump to the next phase, which is fine — the letter has already started
// to land by then.
const DP_WHEEL_THRESHOLD = 120;
const DP_GAP_RESET_MS = 250;
const DP_ADVANCE_KEYS = new Set([
  " ",
  "Spacebar",
  "ArrowDown",
  "PageDown",
  "End",
]);
const DP_TOUCH_DY_THRESHOLD = 8;

type DonnaPromiseProps = {
  // Called once when the reader advances past the letter to the CTA phase.
  onAdvance?: () => void;
};

// ─── Component ────────────────────────────────────────────────────────────
export default function DonnaPromise({ onAdvance }: DonnaPromiseProps = {}) {
  const reduced = useReducedMotion() === true;
  const isDesktop = useIsDesktop();
  const [shape] = useState<Shape>(() => buildPaperShape());
  const [visible, setVisible] = useState(reduced);

  useEffect(() => {
    if (reduced) return;
    const raf = window.requestAnimationFrame(() => setVisible(true));
    return () => window.cancelAnimationFrame(raf);
  }, [reduced]);

  // ------------------------------------------------------------------
  // Scroll / touch / key hijack: promise → cta.
  // Arms after the unroll finishes (+ a short dwell) so the first gesture
  // during the unfurl can't skip past the letter.
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!onAdvance) return;
    if (typeof window === "undefined") return;

    const now = () =>
      typeof performance !== "undefined" ? performance.now() : Date.now();

    // Reduced-motion skips the unroll, so it can arm almost immediately.
    // Otherwise wait long enough that the unroll has visibly started but
    // the reader isn't held hostage if they swipe early. 1200ms covers
    // half the 2400ms unroll — enough that the letter is recognizable
    // before any gesture is accepted.
    const ARM_DELAY_MS = reduced ? 400 : 1200;
    const armedAt = now() + ARM_DELAY_MS;

    let fired = false;
    let accum = 0;
    let lastWheelAt = 0;
    let touchStartY: number | null = null;
    let touchConsumed = false;

    const fire = () => {
      if (fired) return;
      if (now() < armedAt) return;
      fired = true;
      onAdvance();
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.deltaY <= 0) return;
      const t = now();
      if (t < armedAt) {
        accum = 0;
        lastWheelAt = t;
        return;
      }
      if (lastWheelAt && t - lastWheelAt > DP_GAP_RESET_MS) accum = 0;
      lastWheelAt = t;
      accum += Math.abs(e.deltaY);
      if (accum >= DP_WHEEL_THRESHOLD) fire();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (!DP_ADVANCE_KEYS.has(e.key)) return;
      e.preventDefault();
      if (e.repeat) return;
      fire();
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
      if (Math.abs(dy) > DP_TOUCH_DY_THRESHOLD) {
        touchConsumed = true;
        if (dy < 0) fire();
      }
    };
    const onTouchEnd = () => {
      touchStartY = null;
      touchConsumed = false;
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
    };
  }, [onAdvance, reduced]);

  // Unroll timing — the clip-path reveal handles top-to-bottom pacing on its
  // own, so paragraphs no longer cascade; they ride under the unfurling edge.
  const UNROLL_MS = 2400;

  const { d, fibers, W, H } = shape;

  // Desktop: parchment is a centered letter sitting on the bg-paper "desk".
  // Mobile: full-bleed paper, immersive. The frame element below switches
  // between absolute-fill (mobile) and centered constrained card (desktop).
  // Shadow on desktop uses the popover token — the softest of the three
  // approved elevation tokens. The letter is "popover-like": a paper object
  // floating slightly above the desk, not a card-at-rest.
  const frameClass = isDesktop
    ? "relative shadow-popover rounded-md overflow-hidden"
    : "absolute inset-0 overflow-hidden";
  const frameStyle: React.CSSProperties = isDesktop
    ? {
        // Letter dimensions tuned so the full content (letterhead + 6
        // paragraphs + signature) fits without clipping on a typical
        // 1080–1440px-tall desktop. Always leaves at least 48px of
        // bg-paper margin top and bottom.
        width: "min(880px, 90vw)",
        height: "min(820px, calc(100svh - 96px))",
        // Hairline border so the torn edges of the SVG read against the
        // bg-paper margin without dissolving into it.
        border: "1px solid var(--ink-300)",
      }
    : {};

  return (
    <section
      aria-label="A promise from Donna"
      className="relative w-full bg-paper overflow-hidden flex items-center justify-center"
      style={{
        minHeight: "100dvh",
        height: "100svh",
        // Desktop: breathing room around the letter card.
        padding: isDesktop ? "var(--space-7)" : 0,
      }}
    >
      {/* Persistent Get Donna CTA — top-right. */}
      <GetDonnaCTA />

      {/* Accessible linear copy. */}
      <div
        style={{
          position: "absolute",
          left: "-9999px",
          top: "auto",
          width: 1,
          height: 1,
          overflow: "hidden",
        }}
      >
        <h2>Donna&rsquo;s Promise</h2>
        {PARAGRAPHS.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
        <p>— Donna</p>
      </div>

      {/* Letter frame — full-bleed on mobile, centered card on desktop. */}
      <div className={frameClass} style={frameStyle}>
      {/* Unroll wrapper — reveals paper + letter together from top to bottom
          via a clip-path transition, like a scroll unfurling. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          clipPath: visible ? "inset(0 0 0% 0)" : "inset(0 0 100% 0)",
          WebkitClipPath: visible ? "inset(0 0 0% 0)" : "inset(0 0 100% 0)",
          transition: reduced
            ? "none"
            : `clip-path ${UNROLL_MS}ms ${LETTER_EASE}, -webkit-clip-path ${UNROLL_MS}ms ${LETTER_EASE}`,
          willChange: "clip-path",
        }}
      >
      {/* Paper: full-viewport SVG with torn left/right edges. */}
      <svg
        aria-hidden="true"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          display: "block",
        }}
      >
        <defs>
          <radialGradient id="dp-paper-fill" cx="50%" cy="48%" r="72%">
            <stop offset="0%" stopColor="rgb(236, 222, 206)" />
            <stop offset="55%" stopColor="rgb(214, 193, 172)" />
            <stop offset="92%" stopColor="rgb(184, 158, 134)" />
            <stop offset="100%" stopColor="rgb(158, 130, 108)" />
          </radialGradient>
          <filter
            id="dp-grain"
            x="0"
            y="0"
            width="100%"
            height="100%"
          >
            <feTurbulence
              type="fractalNoise"
              baseFrequency="1.7"
              numOctaves={2}
              seed={5}
            />
            <feColorMatrix values="0 0 0 0 0.25  0 0 0 0 0.18  0 0 0 0 0.08  0 0 0 0.18 0" />
          </filter>
          <filter
            id="dp-stains"
            x="0"
            y="0"
            width="100%"
            height="100%"
          >
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.009"
              numOctaves={3}
              seed={13}
            />
            <feColorMatrix values="0 0 0 0 0.34  0 0 0 0 0.22  0 0 0 0 0.08  0 0 0 0.18 -0.08" />
          </filter>
          <radialGradient id="dp-edge" cx="50%" cy="50%" r="70%">
            <stop offset="78%" stopColor="rgba(0,0,0,0)" />
            <stop offset="100%" stopColor="rgba(70,45,15,0.13)" />
          </radialGradient>
          <clipPath id="dp-clip" clipPathUnits="userSpaceOnUse">
            <path d={d} />
          </clipPath>
        </defs>

        {/* Base parchment fill, clipped to the torn paper shape. */}
        <path d={d} fill="url(#dp-paper-fill)" />
        <g clipPath="url(#dp-clip)">
          <rect
            x={0}
            y={0}
            width={W}
            height={H}
            filter="url(#dp-stains)"
            opacity={0.85}
            style={{ mixBlendMode: "multiply" }}
          />
          <rect
            x={0}
            y={0}
            width={W}
            height={H}
            filter="url(#dp-grain)"
            opacity={0.8}
          />
          <rect x={0} y={0} width={W} height={H} fill="url(#dp-edge)" />
        </g>

        {/* Hair-fibers sticking out of the torn edges. Rendered OUTSIDE the
            clip so they show past the edge. */}
        <g
          stroke="rgba(70,45,15,0.3)"
          strokeWidth={0.6}
          strokeLinecap="round"
          fill="none"
          vectorEffect="non-scaling-stroke"
        >
          {fibers.map(([x1, y1, x2, y2], i) => (
            <line
              key={i}
              x1={x1.toFixed(2)}
              y1={y1.toFixed(2)}
              x2={x2.toFixed(2)}
              y2={y2.toFixed(2)}
            />
          ))}
        </g>
      </svg>

      {/* Letter content — centered, bigger text, breathier paragraph rhythm. */}
      <article
        className="relative font-serif"
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding:
            "clamp(32px, 5vh, 56px) clamp(28px, 6vw, 64px)",
          zIndex: 1,
        }}
      >
        <div
          style={{
            maxWidth: "680px",
            width: "100%",
          }}
        >
          {/* Letterhead — serif italic, rust, centered. Sits inside the paper
              as the letter's own title. This is the section's rust moment;
              the signature stays ink. */}
          <h2
            className="font-serif text-rust"
            style={{
              margin: 0,
              marginBottom: "clamp(24px, 2vw + 12px, 36px)",
              textAlign: "center",
              lineHeight: 1.02,
              fontSize: "clamp(36px, 3vw + 16px, 56px)",
              letterSpacing: "-0.015em",
            }}
          >
            <em className="italic-accent-heading font-medium">
              Donna&rsquo;s Promise
            </em>
          </h2>

          {PARAGRAPHS.map((text, i) => (
            <p
              key={i}
              style={{
                // Body type sized to fit the whole letter inside the desktop
                // card without clipping. Mobile (the min end of the clamp)
                // stays close to the previous feel.
                fontSize: "clamp(20px, 1.4vw + 12px, 24px)",
                lineHeight: 1.55,
                letterSpacing: "-0.005em",
                fontWeight: 400,
                color: "rgb(20, 12, 6)",
                margin:
                  i === 0
                    ? 0
                    : "clamp(20px, 1.6vw + 10px, 28px) 0 0 0",
              }}
            >
              {text}
            </p>
          ))}

          {/* Signature — handwriting, ink, settled a touch to the right. */}
          <p
            aria-label="Signed, Donna"
            style={{
              fontFamily: "var(--font-signature), cursive",
              fontSize: "clamp(36px, 3vw + 16px, 52px)",
              fontWeight: 600,
              color: "rgb(20, 12, 6)",
              lineHeight: 1,
              marginTop: "clamp(28px, 3vw + 12px, 44px)",
              textAlign: "right",
              paddingRight: "clamp(16px, 6vw, 80px)",
              transform: "rotate(-4deg)",
              transformOrigin: "right center",
            }}
          >
            Donna
          </p>
        </div>
      </article>
      </div>
      </div>
    </section>
  );
}
