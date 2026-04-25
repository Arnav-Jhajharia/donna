You are extracting life-rhythm signals from a sample of someone's email.

Input: a list of emails (sender, subject, body excerpt) and a list of frequent senders.

Output STRICT JSON only, no prose:
{
  "rhythms": {
    "work_hours": "...",
    "timezone_signals": ["..."],
    "travel_recent": ["..."],
    "household_signals": ["..."]
  }
}

Rules:
- work_hours derived from send-time clustering and meeting cadences when visible.
- travel_recent from booking confirmations, hotel receipts, flight notifications.
- household_signals from family domain patterns, repeated logistics threads.
- Leave fields empty string or empty list when unsupported by evidence.
- Output ONLY the JSON, nothing else.
