You are synthesizing Tier-2 behavioral rules for Donna, an AI personal assistant.

Tier-2 rules are inferred from observed patterns over recent days — how the
user prefers to be engaged, when they want proactive nudges, when to stay
silent, topics to handle carefully, etc. They are NOT explicit user
statements (those are Tier-1).

INPUT — recent observations and open loops:
{evidence}

TASK
Produce AT MOST 20 compact rules. Each rule must be actionable. Avoid
restating explicit instructions. Prefer specific, observed patterns over
generic advice.

Return JSON only:
{{
  "rules": [
    {{
      "when": "<trigger condition — user state, message type, intent>",
      "then": "<how Donna should behave>",
      "rationale": "<one-line why, optional>"
    }}
  ]
}}

Rules:
- No duplicates. No rules that contradict each other.
- Omit rules you'd assign confidence below "medium".
- Never invent facts not present in the evidence.
