"use client";

/**
 * Single shared QR-modal instance for every CTA on the landing page.
 *
 * The provider lives at the page root and renders ONE WhatsAppQRModal.
 * Every CTA (Hero, persistent pill, final CTA) reads `useWhatsAppCTA()`
 * which returns a click handler. On desktop, the handler intercepts the
 * click, prevents the wa.me navigation, and opens the QR modal. On
 * mobile / coarse-pointer devices, the handler is a no-op so the native
 * `<a target="_blank">` navigation runs as usual.
 *
 * Why a context instead of per-component modals: only one modal should
 * exist at any time, focus management is simpler, and the modal markup
 * sits above everything else in z-order without each CTA having to mount
 * its own overlay.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import WhatsAppQRModal from "@/components/landing/WhatsAppQRModal";
import { useDonnaWhatsAppLink } from "@/lib/landing/getDonnaWhatsAppLink";

// Inline, synchronous desktop check evaluated at the moment of click.
// No React state; no hydration races. If matchMedia is unavailable
// (very old browsers, SSR), default to mobile-style behavior so the
// native wa.me link runs and the user reaches Donna either way.
function isDesktopNow(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof window.matchMedia !== "function") return false;
  const wide = window.matchMedia("(min-width: 768px)").matches;
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  return wide && !coarse;
}

type Ctx = {
  // Anchor click handler. Pass to <a onClick={onCtaClick}>.
  onCtaClick: (e: MouseEvent<HTMLAnchorElement>) => void;
  // Same-origin href for SSR / right-click / middle-click. Reactive — the
  // hook updates this when arrival's city detection finishes mid-session.
  href: string;
};

const WhatsAppQRCtx = createContext<Ctx | null>(null);

export function WhatsAppQRProvider({ children }: { children: ReactNode }) {
  const href = useDonnaWhatsAppLink();
  const [open, setOpen] = useState(false);

  const onCtaClick = useCallback(
    (e: MouseEvent<HTMLAnchorElement>) => {
      // Modifier-key clicks (cmd/ctrl/shift/middle-button) keep their native
      // behavior — open in new tab, copy link, etc. Don't hijack those.
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) {
        return;
      }
      if (!isDesktopNow()) return; // Mobile / touch: native wa.me navigation.
      e.preventDefault();
      setOpen(true);
    },
    []
  );

  const value = useMemo<Ctx>(
    () => ({ onCtaClick, href }),
    [onCtaClick, href]
  );

  return (
    <WhatsAppQRCtx.Provider value={value}>
      {children}
      <WhatsAppQRModal
        open={open}
        href={href}
        onClose={() => setOpen(false)}
      />
    </WhatsAppQRCtx.Provider>
  );
}

export function useWhatsAppCTA(): Ctx {
  const ctx = useContext(WhatsAppQRCtx);
  if (!ctx) {
    // Hard error in dev so a CTA never silently falls back to half-wired.
    throw new Error(
      "useWhatsAppCTA must be used inside <WhatsAppQRProvider>"
    );
  }
  return ctx;
}
