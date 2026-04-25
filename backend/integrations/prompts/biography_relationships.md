You are extracting a relationship graph from a sample of someone's email.

Input: a list of emails (sender, subject, body excerpt) and a list of frequent senders.

Output STRICT JSON only, no prose:
{
  "relationships": [
    {"name": "...", "kind": "colleague|family|friend|vendor|other",
     "frequency": "daily|weekly|monthly|rare", "role": "...",
     "last_seen": "YYYY-MM-DD"}
  ]
}

Rules:
- Names from From: header. If only an email is shown, use the local part.
- "kind" inferred from content tone and address (work domain to colleague, family-name pattern to family).
- Skip noreply / automated / no-name addresses.
- Top 8 only. Pick the highest-signal people.
- Output ONLY the JSON, nothing else.
