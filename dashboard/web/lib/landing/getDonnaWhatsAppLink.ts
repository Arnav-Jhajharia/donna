/**
 * Single source of truth for every CTA on the landing page.
 *
 * All "Get Donna" / "Open WhatsApp" / hero / CTA-section buttons use
 * `useDonnaWhatsAppLink()` (React hook) or `buildDonnaWhatsAppLink()`
 * (plain function). Nobody hardcodes the wa.me link anywhere else.
 *
 * Location flow:
 *  - ArrivalSequence resolves the visitor's city via `lib/arrival.ts`
 *    (browser geolocation → IP fallback), and on success calls
 *    `saveDonnaLocation(city)` to persist it in localStorage under
 *    `donna:location`.
 *  - CTAs call `useDonnaWhatsAppLink()` and receive a reactive URL that
 *    updates if the city lands after the CTA has already mounted
 *    (arrival → hero races: hero can mount before detectCity resolves).
 *  - If the city is missing (detection failed, localStorage blocked,
 *    SSR), the fallback message without location is used.
 *
 * The message is URL-encoded via `encodeURIComponent`, never by hand.
 */

import { useEffect, useState } from "react";

// Singapore: +65 9197 8565. wa.me wants digits only — no +, no spaces.
export const DONNA_WHATSAPP_NUMBER = "6585767653";

const LOCATION_STORAGE_KEY = "donna:location";

/**
 * Persist the visitor's resolved city. Called once by ArrivalSequence
 * after `detectCity` resolves. Silently no-ops on SSR / blocked storage.
 */
export function saveDonnaLocation(city: string | null | undefined): void {
  if (typeof window === "undefined") return;
  if (!city || city.length === 0) return;
  try {
    window.localStorage.setItem(LOCATION_STORAGE_KEY, city);
  } catch {
    // Private mode / quota / disabled — the CTA falls back to the
    // no-location message, which is fine.
  }
  // The `storage` event only fires cross-tab. Emit a same-tab event so any
  // CTA already mounted in this tab (Hero especially) re-reads and refreshes.
  try {
    window.dispatchEvent(new Event("donna:location-updated"));
  } catch {
    /* no-op — older browsers */
  }
}

/**
 * Read the visitor's persisted city. Returns null on SSR, missing key,
 * blocked storage, or empty string.
 */
export function getDonnaLocation(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(LOCATION_STORAGE_KEY);
    return v && v.length > 0 ? v : null;
  } catch {
    return null;
  }
}

/**
 * Build the wa.me URL with a prefilled message. If `location` is
 * undefined (the default), the location is read from localStorage.
 * Pass `null` explicitly to force the no-location fallback.
 *
 * Examples (after URL-decoding):
 *   location = "Singapore" → "Hi Donna. From Singapore. Don't make me regret this."
 *   location = null        → "Hi Donna. Don't make me regret this."
 */
export function buildDonnaWhatsAppLink(
  location?: string | null
): string {
  const loc =
    location === undefined ? getDonnaLocation() : location ?? null;

  const message =
    loc && loc.length > 0
      ? `Hi Donna. From ${loc}. Don't make me regret this.`
      : `Hi Donna. Don't make me regret this.`;

  return `https://wa.me/${DONNA_WHATSAPP_NUMBER}?text=${encodeURIComponent(
    message
  )}`;
}

/**
 * Reactive CTA URL. Reads the location on mount and re-reads when another
 * tab writes the `donna:location` key (the native `storage` event fires
 * cross-tab only, but we also re-read on mount to catch the arrival-window
 * case where detectCity resolves after the CTA has already rendered).
 *
 * For same-tab updates from ArrivalSequence → Hero, we also listen for a
 * custom `donna:location-updated` event that `saveDonnaLocation` dispatches.
 */
export function useDonnaWhatsAppLink(): string {
  const [href, setHref] = useState<string>(() => buildDonnaWhatsAppLink());

  useEffect(() => {
    if (typeof window === "undefined") return;

    const refresh = () => setHref(buildDonnaWhatsAppLink());

    // Handle the race where a CTA renders before arrival resolves the city.
    // Also catches the case where we already have a stale SSR-safe fallback.
    refresh();

    window.addEventListener("storage", refresh);
    window.addEventListener("donna:location-updated", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("donna:location-updated", refresh);
    };
  }, []);

  return href;
}
