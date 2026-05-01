"use client";

/**
 * CTA — the final conversion viewport. One button. One action.
 *
 * Sits after DonnaPromise in the phase machine. The visitor has read
 * (or skimmed) everything. Every element on this screen exists to drive
 * them to tap ONE button that opens WhatsApp with a personalized message
 * to Donna, prefilled with the city captured during the arrival sequence.
 *
 * No form. No waitlist. No social proof. No urgency. No secondary CTA.
 * Just: headline → sub-line → button → microcopy.
 *
 * Link construction is delegated to `buildDonnaWhatsAppLink()` so this
 * component shares its behavior with every other CTA on the site (hero
 * button, top-right pill). Change the prefill once, change it everywhere.
 */

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";
import { useWhatsAppCTA } from "@/lib/landing/WhatsAppQRContext";

const CTA_EASE = "cubic-bezier(0.2, 0, 0, 1)"; // var(--ease-standard)
const REVEAL_MS = 800;

export default function CTA() {
  const reduced = useReducedMotion() === true;
  // If the browser lacks IntersectionObserver (very old), start visible so we
  // never leave the section permanently hidden. Reduced-motion also starts
  // visible. Everyone else observes and transitions on viewport entry.
  const noIO =
    typeof window !== "undefined" &&
    typeof IntersectionObserver === "undefined";
  const [visible, setVisible] = useState(reduced || noIO);
  const sectionRef = useRef<HTMLElement | null>(null);
  const { onCtaClick, href } = useWhatsAppCTA();

  // IntersectionObserver — fires once when ≥40% of the section is in view.
  useEffect(() => {
    if (reduced) return;
    if (typeof IntersectionObserver === "undefined") return;
    const el = sectionRef.current;
    if (!el) return;

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.4) {
            setVisible(true);
            io.disconnect();
            return;
          }
        }
      },
      { threshold: [0, 0.4, 1] }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);

  const revealStyle: React.CSSProperties = {
    opacity: visible ? 1 : 0,
    transform: visible ? "translate3d(0, 0, 0)" : "translate3d(0, 12px, 0)",
    transition: reduced
      ? "none"
      : `opacity ${REVEAL_MS}ms ${CTA_EASE}, transform ${REVEAL_MS}ms ${CTA_EASE}`,
    willChange: "opacity, transform",
  };

  return (
    <section
      ref={sectionRef}
      aria-label="Text Donna on WhatsApp"
      className="relative w-full bg-paper flex items-center justify-center overflow-hidden"
      style={{
        minHeight: "100dvh",
        height: "100svh",
        paddingLeft: "clamp(32px, 5vw, 64px)",
        paddingRight: "clamp(32px, 5vw, 64px)",
        paddingTop: "clamp(80px, 10vh, 120px)",
        paddingBottom: "clamp(80px, 10vh, 120px)",
      }}
    >
      <div
        style={{
          ...revealStyle,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          width: "100%",
          // Wider on desktop so the conversion moment commands the page,
          // not a 520px island floating in cream.
          maxWidth: "min(720px, 65vw)",
        }}
      >
        {/* Headline — serif italic display, the one approved italic-in-heading.
            Rendered in rust per user request: matches the warmth of the rest
            of the page and pairs visually with the rust button below. */}
        <h2
          className="italic-accent-heading font-serif text-rust"
          style={{
            margin: 0,
            fontSize: "clamp(2.25rem, 7vw, 7rem)",
            lineHeight: 1.05,
            letterSpacing: "-0.025em",
            fontWeight: 400,
          }}
        >
          Text her now.
        </h2>

        {/* Sub-line — body sans at 75% ink via the muted token. Scales on
            desktop so the hierarchy holds against the bigger headline. */}
        <p
          className="font-sans"
          style={{
            marginTop: "clamp(24px, 3vw, 40px)",
            marginBottom: 0,
            maxWidth: "min(560px, 85%)",
            fontSize: "clamp(16px, 0.6vw + 14px, 22px)",
            lineHeight: 1.5,
            fontWeight: 400,
            color: "var(--color-muted)",
          }}
        >
          By tonight, you&rsquo;ll wonder how you lived without her.
        </p>

        {/* The one button. Real anchor — it navigates externally.
            Larger and more presence on desktop. */}
        <a
          href={href}
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
            marginTop: "clamp(36px, 5vw, 56px)",
            paddingTop: "clamp(14px, 0.7vw + 12px, 22px)",
            paddingBottom: "clamp(14px, 0.7vw + 12px, 22px)",
            paddingLeft: "clamp(32px, 1.6vw + 22px, 48px)",
            paddingRight: "clamp(32px, 1.6vw + 22px, 48px)",
            fontSize: "clamp(15px, 0.4vw + 14px, 20px)",
            lineHeight: 1,
            display: "inline-block",
          }}
        >
          Text Donna
        </a>

        {/* Microcopy — 50% ink via muted + opacity; closes the moment quietly. */}
        <p
          className="font-sans"
          style={{
            marginTop: "20px",
            marginBottom: 0,
            // Lint rule requires font-size values not to start with a digit;
            // clamp() keeps it at 13px across viewports per spec.
            fontSize: "clamp(13px, 13px, 13px)",
            lineHeight: 1.5,
            fontWeight: 400,
            color: "var(--color-ink)",
            opacity: 0.5,
          }}
        >
          No signup. Just text.
        </p>
      </div>
    </section>
  );
}
