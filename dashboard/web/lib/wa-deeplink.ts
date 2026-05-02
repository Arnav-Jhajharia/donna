/**
 * Build a WhatsApp deeplink that opens Donna's chat with a primer text.
 *
 * Reads ``NEXT_PUBLIC_WA_URL`` (canonical wa.me/<donna-number>). Falls
 * back to plain ``https://wa.me/`` which makes the OS show its WhatsApp
 * picker — user chooses Donna chat manually. That's the same fallback
 * the signin page uses, so dev environments without the env set still
 * land somewhere sensible.
 */
const WA_DEEPLINK_DEFAULT = 'https://wa.me/';

export function buildWaUrl(primer: string): string {
  const base = (process.env.NEXT_PUBLIC_WA_URL || WA_DEEPLINK_DEFAULT).replace(
    /\/$/,
    '',
  );
  const sep = base.includes('?') ? '&' : '?';
  return `${base}${sep}text=${encodeURIComponent(primer)}`;
}

/**
 * Choose the right primer for a tally tracker so logging via WhatsApp
 * lands in Donna's NLP pipeline as the right observation type.
 *
 *   "calories"  → "had "          (let user finish: "had chicken rice")
 *   "water"     → "drank water"   (donna can ack and bump count)
 *   "sleep"     → "slept "        ("slept 7 hours")
 *   "spend"     → "spent "        ("spent ₹420 on dinner")
 *   "steps"     → "walked "       ("walked 8000 steps")
 *   default     → "logging "
 */
export function tallyLogPrimer(subject: string): string {
  const s = (subject || '').toLowerCase();
  if (s.includes('calorie') || s.includes('meal') || s.includes('food'))
    return 'had ';
  if (s.includes('water') || s.includes('hydrat')) return 'drank water';
  if (s.includes('sleep') || s.includes('rest')) return 'slept ';
  if (s.includes('spend') || s.includes('expense') || s.includes('money'))
    return 'spent ';
  if (s.includes('step') || s.includes('walk')) return 'walked ';
  if (s.includes('weight')) return 'weighed ';
  if (s.includes('mood') || s.includes('feel')) return 'feeling ';
  if (s.includes('exercise') || s.includes('workout') || s.includes('lift'))
    return 'just trained ';
  return `logging ${s} `;
}
