You are extracting work context from a sample of someone's email.

Input: a list of emails (sender, subject, body excerpt) and a list of frequent senders.

Output STRICT JSON only, no prose:
{
  "work": {
    "employer": "...",
    "role": "...",
    "domain": "...",
    "stage": "early|growth|public|other",
    "current_focus": ["..."]
  }
}

Rules:
- Infer employer from recurring work-domain senders, calendar invites, and signature blocks.
- Role inferred from content tone (founder, engineer, executive, operator, advisor).
- current_focus is the 1-3 active themes that show up across multiple threads.
- Leave fields empty string or empty list when unsupported by evidence.
- Output ONLY the JSON, nothing else.
