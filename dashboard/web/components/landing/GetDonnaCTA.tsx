"use client";

/**
 * GetDonnaCTA — persistent rust pill that lives in the top-right corner
 * of every screen AFTER the hero (ProofSection, DonnaPromise). The hero
 * already has its own centered CTA; arrival has none.
 *
 * All CTAs on the site route through `buildDonnaWhatsAppLink()` — same
 * prefilled message, same phone number, same location pulled from the
 * arrival-resolved localStorage entry. No hardcoding anywhere.
 *
 * Brand notes:
 *  - bg-rust + text-paper (the approved primary button pair).
 *  - rounded-full pill, matching the hero's CTA geometry but a step smaller
 *    so it reads as a secondary persistent offer, not the hero moment.
 *  - Design-system rule: "one rust moment per screen." This pill IS the
 *    rust moment on the screens where it appears — smaller existing rust
 *    accents (tagline full-stop, Promise letterhead) are still in play on
 *    those screens and will trigger the dev-only rust-budget warning. That
 *    tradeoff is intentional: a persistent conversion affordance outweighs
 *    the one-accent purity rule on post-hero screens.
 */

import { useWhatsAppCTA } from "@/lib/landing/WhatsAppQRContext";

type Props = {
  label?: string;
};

export default function GetDonnaCTA({ label = "Text Donna" }: Props) {
  const { onCtaClick, href } = useWhatsAppCTA();

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={onCtaClick}
      aria-label="Open WhatsApp to message Donna"
      className={[
        "font-sans text-button font-medium no-underline",
        "bg-rust text-paper",
        "rounded-full",
        "transition-colors duration-fast ease-standard",
        "hover:bg-rust-900",
        "focus:outline-none focus:ring-focus focus:ring-rust focus:ring-offset-2 focus:ring-offset-paper",
      ].join(" ")}
      style={{
        position: "absolute",
        top: "clamp(16px, 2.5vh, 28px)",
        right: "clamp(16px, 2.5vw, 32px)",
        // Slightly smaller padding than the hero CTA so the persistent pill
        // reads as secondary rather than competing with the hero button.
        paddingLeft: "clamp(16px, 1.4vw + 10px, 22px)",
        paddingTop: "clamp(10px, 1vh + 4px, 14px)",
        paddingRight: "clamp(16px, 1.4vw + 10px, 22px)",
        paddingBottom: "clamp(10px, 1vh + 4px, 14px)",
        zIndex: 50,
        display: "inline-block",
      }}
    >
      {label}
    </a>
  );
}
