"use client";

/**
 * Hero — second screen, mounts after ArrivalSequence completes.
 *
 * Layout 1 (locked):
 *   - Full-bleed looping video behind everything.
 *   - Top caption directly on the video (no pill).
 *   - Headline + sub-line clustered above the bottom.
 *   - Rust CTA pill below that.
 *
 * The video luminance varies across the loop, so two legibility scrims
 * (top and bottom) darken the edges enough that brand-paper text reads on
 * every frame. A soft text-shadow on each text element is the belt-and-braces.
 *
 * Gradients are normally forbidden by the design system — the scrims here
 * are decorative legibility aids, not brand surfaces, and were explicitly
 * spec'd. They never sit on a card, panel, or button.
 *
 * Text appears instantly at full opacity. Only the video fades in on mount
 * (800ms ease-standard) so there's no white-frame flash while bytes stream.
 */

import { useEffect, useRef } from "react";
import { Wordmark } from "@/components/landing";
import { useWhatsAppCTA } from "@/lib/landing/WhatsAppQRContext";
import { useIsDesktop } from "@/lib/landing/useIsDesktop";

type Props = {
  topCaption?: string;
  headline?: string;
  subline?: string;
  ctaLabel?: string;
  // Called once when the user makes any scroll-ish downward gesture while
  // the hero is the active phase. The parent advances to the proof phase.
  onAdvance?: () => void;
};

const ADVANCE_KEYS = new Set([
  " ",
  "Spacebar",
  "ArrowDown",
  "PageDown",
  "End",
]);
// Arm window — tuned to absorb the entire trackpad-inertia tail from the
// arrival's last gesture (typically 400–700ms of decaying wheel events).
// 250ms was too short and the hero was getting dismissed instantly; 600ms
// is enough to let the user actually land on the hero before scroll counts.
const HERO_ARM_MS = 600;
const HERO_TOUCH_DY_THRESHOLD = 8;

// Soft shadow to carry brand-paper text across variable-luminance frames.
// Not a box-shadow (forbidden on cards) — purely typographic.
const TEXT_SHADOW = "0 2px 20px rgba(0,0,0,0.4)";

// Legibility scrims. Top is shorter + lighter, bottom carries headline + CTA.
const SCRIM_TOP = "linear-gradient(to bottom, rgba(0,0,0,0.4), rgba(0,0,0,0))";
const SCRIM_BOTTOM = "linear-gradient(to top, rgba(0,0,0,0.4), rgba(0,0,0,0))";

export default function Hero({
  topCaption = "You\u2019ve seen her before.",
  headline = "Now meet yours.",
  subline = "On WhatsApp. Already three steps ahead.",
  ctaLabel = "Text Donna",
  onAdvance,
}: Props) {
  // Reactive — if arrival resolves the city after Hero has mounted, the
  // provider's hook refreshes the href on the `donna:location-updated`
  // event. On desktop the click handler intercepts and opens the QR modal;
  // on mobile it's a no-op so the native wa.me navigation runs.
  const { onCtaClick, href: ctaHref } = useWhatsAppCTA();
  const isDesktop = useIsDesktop();
  const videoRef = useRef<HTMLVideoElement>(null);
  // Desktop gets the wide cinematic 16:9 (hero-desktop). Mobile keeps the
  // original portrait-friendly hero1 framing. Both videos and their poster
  // JPGs are served from Cloudinary with q_auto,f_auto so each browser
  // gets the best codec (WebM in Chrome, MP4 in Safari) at an
  // appropriate quality level. This keeps git + Vercel deploys lean.
  const CLOUDINARY = "https://res.cloudinary.com/djwprq1uj";
  const videoSrc = isDesktop
    ? `${CLOUDINARY}/video/upload/q_auto,f_auto/hero-desktop_apspgi`
    : `${CLOUDINARY}/video/upload/q_auto,f_auto/hero1_czjxs1`;
  const posterSrc = isDesktop
    ? `${CLOUDINARY}/image/upload/q_auto,f_auto/hero-desktop-poster_b2yclw`
    : `${CLOUDINARY}/image/upload/q_auto,f_auto/hero1-poster_ulx2ik`;

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;

    // When the source switches between mobile/desktop after a viewport
    // resize, re-load so the new src takes over from the buffered old one.
    v.load();

    // Reduced motion: freeze the first frame rather than looping.
    if (
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      v.pause();
    }
  }, [videoSrc]);

  // ------------------------------------------------------------------
  // Hero → Proof hijack. One downward gesture advances; upward gestures
  // are swallowed (no back-scroll). The listener arms HERO_ARM_MS after
  // mount so trackpad inertia from the arrival dismiss can't trigger it.
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!onAdvance) return;
    if (typeof window === "undefined") return;

    const armedAt =
      (typeof performance !== "undefined" ? performance.now() : Date.now()) +
      HERO_ARM_MS;
    let fired = false;
    let touchStartY: number | null = null;
    let touchConsumed = false;

    const fire = () => {
      const now =
        typeof performance !== "undefined" ? performance.now() : Date.now();
      if (now < armedAt) return;
      if (fired) return;
      fired = true;
      onAdvance();
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.deltaY > 0) fire();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (!ADVANCE_KEYS.has(e.key)) return;
      e.preventDefault();
      if (e.repeat) return;
      fire();
    };
    const onTouchStart = (e: TouchEvent) => {
      touchStartY = e.touches[0]?.clientY ?? null;
      touchConsumed = false;
    };
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      if (touchConsumed || touchStartY === null) return;
      const y = e.touches[0]?.clientY ?? touchStartY;
      const dy = y - touchStartY;
      if (Math.abs(dy) > HERO_TOUCH_DY_THRESHOLD) {
        touchConsumed = true;
        // Only a downward swipe (finger moving up → dy < 0) advances.
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
  }, [onAdvance]);

  return (
    <section
      className="relative w-full overflow-hidden bg-ink text-paper"
      style={{ height: "100svh", minHeight: "100dvh" }}
      aria-label="Donna"
    >
      {/* Full-bleed looping video. Decorative. */}
      <video
        ref={videoRef}
        aria-hidden="true"
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        src={videoSrc}
        poster={posterSrc}
        // `key` ensures React swaps the underlying element when the src
        // flips between desktop and mobile — without this, some browsers
        // hold the old buffered frames and you see a flash.
        key={videoSrc}
        className="absolute inset-0 h-full w-full object-cover"
        // The poster is shown by the <video> element until canplay fires,
        // so we no longer need the opacity-fade-on-ready trick — the swap
        // from poster JPG to live frames is seamless on its own.
      />

      {/* Top legibility scrim — carries the top caption. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0"
        style={{ height: "25%", background: SCRIM_TOP }}
      />

      {/* Bottom legibility scrim — carries headline, sub-line, CTA. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0"
        style={{ height: "35%", background: SCRIM_BOTTOM }}
      />

      {/* Top caption — plain text on the video. Scales up on desktop so
          it doesn't read as a tiny mobile caption blown up. */}
      <p
        className="absolute left-1/2 -translate-x-1/2 w-full px-5 text-center font-sans text-paper"
        style={{
          top: "8%",
          fontSize: "clamp(14px, 0.6vw + 12px, 18px)",
          lineHeight: 1.5,
          textShadow: TEXT_SHADOW,
        }}
      >
        {topCaption}
      </p>

      {/* Headline + sub-line cluster. Centered horizontally, ~35% from bottom. */}
      <div
        className="absolute left-1/2 -translate-x-1/2 w-full px-5 text-center"
        style={{ bottom: "26%", maxWidth: "min(960px, 90vw)" }}
      >
        <h1
          className="font-serif text-paper"
          style={{
            fontSize: "clamp(40px, 7vw, 96px)",
            lineHeight: 1.05,
            letterSpacing: "-0.02em",
            fontWeight: 400,
            textShadow: TEXT_SHADOW,
          }}
        >
          {headline}
        </h1>
        {/* Brand wordmark — the name gets its own beat. Wordmark sizes are
            quantized in the design system, so we wrap with a transform-scale
            that lifts the desktop presence without minting a new size token.
            56px (cover) is the baseline; on desktop we scale to ~1.5x. */}
        <div
          className="mt-3 flex justify-center"
          style={{
            textShadow: TEXT_SHADOW,
            transform: isDesktop ? "scale(1.5)" : undefined,
            transformOrigin: "center top",
            paddingBottom: isDesktop ? "clamp(12px, 1.5vw, 24px)" : 0,
          }}
        >
          <Wordmark color="paper" size="cover" />
        </div>
        <p
          className="mt-3 font-sans text-paper"
          style={{
            fontSize: "clamp(18px, 0.6vw + 16px, 24px)",
            lineHeight: 1.5,
            textShadow: TEXT_SHADOW,
          }}
        >
          {subline}
        </p>
      </div>

      {/* CTA — the rust moment for the hero. Scales up on desktop so it
          reads as a proper editorial button, not a phone pill. */}
      <div
        className="absolute left-1/2 -translate-x-1/2 w-full px-5 flex justify-center"
        style={{ bottom: "18%" }}
      >
        <a
          href={ctaHref}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onCtaClick}
          aria-label="Open WhatsApp to message Donna"
          className={[
            "font-sans font-medium no-underline",
            "bg-rust text-paper",
            "rounded-full",
            "transition-colors duration-fast ease-standard",
            "hover:bg-rust-900",
            "focus:outline-none focus:ring-focus focus:ring-rust focus:ring-offset-2 focus:ring-offset-paper",
          ].join(" ")}
          style={{
            paddingTop: "clamp(14px, 0.6vw + 12px, 20px)",
            paddingBottom: "clamp(14px, 0.6vw + 12px, 20px)",
            paddingLeft: "clamp(24px, 1.4vw + 18px, 40px)",
            paddingRight: "clamp(24px, 1.4vw + 18px, 40px)",
            fontSize: "clamp(15px, 0.4vw + 14px, 18px)",
            lineHeight: 1,
            display: "inline-block",
          }}
        >
          {ctaLabel}
        </a>
      </div>
    </section>
  );
}
