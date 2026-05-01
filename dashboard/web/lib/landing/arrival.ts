/**
 * Arrival-sequence utilities.
 *
 * Kept tiny and dependency-free — the arrival section is load-path critical
 * and must not add weight. Both location and time detection are client-side.
 */

const GEO_TIMEOUT_MS = 2500;

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
 * Order of attempts:
 *  1. Browser Geolocation API → BigDataCloud reverse-geocode-client (no key).
 *     Skipped entirely if the permission is already "denied" so we don't loop.
 *  2. IP-based geolocation via ipapi.co (no key, free tier).
 *
 * Returns `null` if both paths fail — caller renders the fallback copy.
 */
export async function detectCity(signal?: AbortSignal): Promise<string | null> {
  const fromBrowser = await tryBrowserGeo(signal);
  if (fromBrowser) return fromBrowser;

  const fromIp = await tryIpLookup(signal);
  if (fromIp) return fromIp;

  return null;
}

async function tryBrowserGeo(signal?: AbortSignal): Promise<string | null> {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
    return null;
  }

  // If permission is explicitly denied, don't bother the user again.
  try {
    if ("permissions" in navigator && navigator.permissions?.query) {
      const perm = await navigator.permissions.query({
        name: "geolocation" as PermissionName,
      });
      if (perm.state === "denied") return null;
    }
  } catch {
    // Permissions API unavailable — proceed.
  }

  const coords = await new Promise<GeolocationCoordinates | null>((resolve) => {
    let settled = false;
    const finish = (value: GeolocationCoordinates | null) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const fallbackTimer = setTimeout(() => finish(null), GEO_TIMEOUT_MS);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(fallbackTimer);
        finish(pos.coords);
      },
      () => {
        clearTimeout(fallbackTimer);
        finish(null);
      },
      { timeout: GEO_TIMEOUT_MS, maximumAge: 10 * 60 * 1000 }
    );
  });

  if (!coords) return null;
  if (signal?.aborted) return null;

  try {
    const url =
      "https://api.bigdatacloud.net/data/reverse-geocode-client?" +
      `latitude=${coords.latitude}&longitude=${coords.longitude}&localityLanguage=en`;
    const res = await fetch(url, { signal });
    if (!res.ok) return null;
    const data: {
      city?: string;
      locality?: string;
      principalSubdivision?: string;
    } = await res.json();
    const city = data.city || data.locality || data.principalSubdivision;
    return typeof city === "string" && city.length > 0 ? city : null;
  } catch {
    return null;
  }
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
