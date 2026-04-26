# Attention subsystem — issue punch list

Fresh audit of `donna/attention/` done 2026-04-24. 14 primary issues + 6 extras. Work through one-by-one; check off as fixed.

---

## Timezone / temporal

- [~] **1. Cron cadence doesn't require `timezone`.** _(deferred 2026-04-24 — timezone will be supplied by the scheduler at eval time from `users.timezone`; spec stays tz-free.)_
  - `schema.py:99-103` validates `cron` / `interval_seconds` exist but not TZ.
  - Gold library crons (`"0 9 * * *"`, `"0 18 * * 5"`) are TZ-naive.
  - DST correctness relies on the scheduler resolving `users.timezone` per eval — see `docs/timezone-audit.md` rec #1.

- [~] **2. `_parse_reminder` bakes offset into ISO string but spec has no TZ field.** _(deferred 2026-04-24 — same reason as #1: scheduler resolves tz at eval. ONE_SHOT offset locks the absolute moment correctly.)_
  - `author.py:245, 259, 270, 274`.

- [x] **3. Date-of-month silently skips short months.** _(done 2026-04-24)_
  - `schema.py::Cadence._validate_cadence_params` now accepts `monthly_day: int 1..31 | "last"` + `hour` + optional `minute` as a third SCHEDULED shape.
  - `author.py::_parse_reminder` routes days 29..31 and "last of every month" through the new shape; days 1..28 keep cron (no regression).
  - Scheduler (TBD) must clamp `monthly_day in {29,30,31}` to last-day-of-month when the month is short; `"last"` always fires last day.
  - Tests: `test_schema.py::test_cadence_monthly_day_*` + `test_author.py::test_parse_reminder_day_*`, `test_parse_reminder_last_*`.

- [x] **4. Same-day "at 6pm" rolls to tomorrow silently.** _(done 2026-04-24)_
  - `_parse_reminder` now detects `\btoday\b` and raises `ReminderInPastError` if `"today"` is explicit and the target time has already passed.
  - Added optional `now: datetime | None = None` kwarg to `_parse_reminder` for deterministic testing.
  - `author_spec` catches `ReminderInPastError` in the ping short-circuit → falls through to LLM path for clarification.
  - Kept silent roll-to-tomorrow when no day-token is present (pragmatic default).
  - Tests: `test_parse_reminder_today_explicit_past_raises`, `test_parse_reminder_today_explicit_future_ok`, `test_parse_reminder_no_token_past_rolls_to_tomorrow`, `test_parse_reminder_tomorrow_explicit_adds_a_day`.

- [x] **5. Nothing-parsed fallback is `now + 1h`.** _(done 2026-04-24)_
  - New `UnparseableReminderError(ValueError)` raised when no time/recurrence branch matches.
  - `author_spec` ping short-circuit catches it and falls through to the LLM path, which can elicit "when?" via `user_elicitation`.
  - Tests: `test_parse_reminder_no_time_raises`, `test_author_ping_shortcircuit_falls_through_on_unparseable`.

## Non-US / non-EN terminology

- [ ] **6. `_DOMAIN_HINTS` is US/EN-only.**
  - `normalize.py:106-119` — no entries for `rbi, iras, ica, hdb, mcst, ep, sgx, nifty, sensex, pan, aadhaar, tds, gst, hra, dbs, ocbc, uob, cpf, medisave, esi, epf`.
  - SG/India intents collapse to `domain="work"` on heuristic fallback.
  - Fix sketch: extend hint maps with regional lexicons; keep them as a separate module for ease of expansion.

- [ ] **7. `DomainTag` enum missing critical non-US buckets.**
  - `vocabulary.py:104-121` — no `TAX, REGULATORY, IMMIGRATION, BANKING, HOUSING, UTILITIES, BILLS, INSURANCE, COMPLIANCE`.
  - RBI/IRAS/ICA/HDB/MCST shoehorn into `FINANCE`/`WORK`/`REMINDER`.
  - Fix sketch: add the missing tags; re-tag gold; update prompt vocabulary block.

- [ ] **8. `WebGoogleNewsParams.country` defaults to `"US"`.**
  - `vocabulary.py:205`.
  - Authored specs on ambiguous queries silently bias to US outlets.
  - Fix sketch: default `None` (provider default) or derive from user country; never hardcode US.

- [ ] **9. Currency-agnostic thresholds hard-coded.**
  - `"month_to_date_sgd > 400"`, `"amount_usd >= 10_000_000"` — no `currency` spec field.
  - Fix sketch: add `SurfacePolicy.currency: str | None`; surface-rule parser must resolve thresholds via that.

- [ ] **10. `subject_pattern` / `title_pattern` are English-only.**
  - Gold: `"receipt|invoice|subscription|renewal"` — misses "tax invoice", "e-invoice", "GST summary", "credit note", hindi/chinese/tamil variants.
  - Fix sketch: build a receipt/invoice lexicon module with locale selectors; referenced by authored regex patterns.

## Retrieval / robustness

- [ ] **11. TF-IDF tokenizer drops unicode.**
  - `retrieve.py:17` — `_TOKEN_RE = [a-z0-9]+`.
  - Devanagari/chinese/tamil intents tokenize to empty. No synonym expansion.
  - Fix sketch: broaden regex to `\w+` under `re.UNICODE`; add small synonym map (`watch↔monitor↔track↔keep tabs on`); activate Voyage path when key present.

- [ ] **12. `_fallback_from_retrieval` silently returns top gold verbatim.**
  - `author.py:563-576` — confidence 0.4 but title/description are the gold's, not the user's.
  - Fix sketch: on fallback, synthesize a minimal spec (ping or generic event_stream) using the user's raw text for title/description; attach the gold id as retrieval hint only.

## Defensive / UX

- [ ] **13. CalendarFetcher silently falls back to fixture.**
  - `dry_run.py:47-60` — preview lies when live fetch fails.
  - Fix sketch: include `live: bool` per `SourcePreview`; surface in markdown header ("live" vs "fixture").

- [ ] **14. `_reminder_domain_tags` swallows unknown domains.**
  - `author.py:304-311` — except branch returns `[REMINDER]` only.
  - Combined with #6, most SG/India reminders end up single-tag.
  - Fix sketch: add an explicit fallback chain (heuristic → `work` → `reminder`) and log unknown domains for hint-map expansion.

---

## Extras (not in the 14, worth addressing eventually)

- [ ] Gold library is 22; README says 15. Retrieval `k=3` default is tight against a larger library.
- [ ] Ping `trigger_at` stringly-typed in `params: dict[str, Any]`. No datetime validation. Compounds #2.
- [ ] `_ping_spec` has dead defensive code (`hasattr(normalized.signals, "domain_tag_or_reminder")` always False).
- [ ] `flight_prep` gold spec uses `location: "destination"` as a literal placeholder — failure mode dressed as a gold example.
- [ ] No lunar/regional calendar support (diwali, CNY eve, eid, lunar new year).
- [ ] No query expansion in retrieval.

---

## Order of work

Timezone first (1→5) because they block correct scheduling. Then terminology (6→10) to unblock SG/India coverage. Retrieval (11→12) and defensive/UX (13→14) last. Extras opportunistically.

Prior work: `docs/timezone-audit.md` already covers the operational timezone drift problem end-to-end and overlaps with #1, #2; the fixes here should reference that doc rather than duplicate it.
