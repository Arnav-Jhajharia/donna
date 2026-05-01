"use client";

import { useEffect, useState } from "react";

/**
 * Best-effort "is this a desktop visitor" check.
 *
 * Definition: viewport ≥ 768px AND the primary pointer is NOT coarse
 * (i.e. not a touchscreen-first device). That correctly classifies:
 *  - Windows / Mac laptops (mouse or trackpad)        → desktop  ✓
 *  - Desktops                                          → desktop  ✓
 *  - iPhones / Androids                                → mobile   ✓
 *  - iPads / Android tablets (touch-primary)           → mobile   ✓
 *  - Hybrid Windows laptop with touch screen, mouse in
 *    use → pointer:fine wins → desktop                 → desktop  ✓
 *
 * The earlier version also required `(pointer: fine)` AND `(hover: hover)`
 * which can fail on hybrids; we now use the inverse — explicitly excluding
 * `pointer: coarse` — which is more reliable across browsers.
 *
 * SSR safety: returns false until the client mount runs. Components that
 * branch on this should accept a one-frame initial mobile-like render and
 * swap to desktop on the next tick. With Hero's `key={videoSrc}` that
 * remount is clean.
 */
const VIEWPORT_MQ = "(min-width: 768px)";
const COARSE_PTR_MQ = "(pointer: coarse)";

function evaluate(): boolean {
  if (typeof window === "undefined") return false;
  const viewportOk = window.matchMedia(VIEWPORT_MQ).matches;
  const isCoarse = window.matchMedia(COARSE_PTR_MQ).matches;
  return viewportOk && !isCoarse;
}

export function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const sync = () => setIsDesktop(evaluate());
    sync();

    const viewport = window.matchMedia(VIEWPORT_MQ);
    const pointer = window.matchMedia(COARSE_PTR_MQ);

    const add = (mq: MediaQueryList) => {
      if (typeof mq.addEventListener === "function") {
        mq.addEventListener("change", sync);
      } else {
        // Older Safari fallback.
        mq.addListener(sync);
      }
    };
    const remove = (mq: MediaQueryList) => {
      if (typeof mq.removeEventListener === "function") {
        mq.removeEventListener("change", sync);
      } else {
        mq.removeListener(sync);
      }
    };

    add(viewport);
    add(pointer);
    return () => {
      remove(viewport);
      remove(pointer);
    };
  }, []);

  return isDesktop;
}
