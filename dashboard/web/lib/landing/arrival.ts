/**
 * Arrival-sequence utilities.
 *
 * Kept tiny and dependency-free — the arrival section is load-path critical
 * and must not add weight. Location uses IP lookup only, so the browser never
 * asks for precise location permission. Time is read from the visitor's device.
 */

/**
 * Human-language hour-of-day hint, paired with a formatted local time.
 * Deliberately quiet — Donna does not perform warmth, does not exclaim.
 */
export function describeTime(now: Date): string {
  const h = now.getHours();
  const m = now.getMinutes();
  const ampm = h >= 12 ? "pm" : "am";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  const timeStr = `${hour12}:${String(m).padStart(2, "0")} ${ampm}`;

  let suffix: string;
  if (h < 5) suffix = "You should be asleep.";
  else if (h < 9) suffix = "Early start.";
  else if (h < 12) suffix = "The day's already moving.";
  else if (h < 17) suffix = "Afternoon's slipping.";
  else if (h < 21) suffix = "Evening already.";
  else suffix = "Late again.";

  return `It's ${timeStr}. ${suffix}`;
}

/**
 * Best-effort city name for the current visitor.
 *
 * Uses IP-based geolocation via ipapi.co (no key, free tier). Returns `null`
 * if lookup fails — caller renders the fallback copy.
 */
export async function detectCity(signal?: AbortSignal): Promise<string | null> {
  const fromIp = await tryIpLookup(signal);
  if (fromIp) return fromIp;

  return null;
}

async function tryIpLookup(signal?: AbortSignal): Promise<string | null> {
  try {
    const res = await fetch("https://ipapi.co/json/", { signal });
    if (!res.ok) return null;
    const data: { city?: string } = await res.json();
    return typeof data.city === "string" && data.city.length > 0
      ? data.city
      : null;
  } catch {
    return null;
  }
}
