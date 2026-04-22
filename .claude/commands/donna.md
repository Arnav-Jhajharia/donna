---
description: Send a message to Donna (the agent this repo builds) and return the reply
argument-hint: [message]
allowed-tools: Bash(python donna.py:*)
---

Run Donna with the user's message and show the result.

- If `$ARGUMENTS` is non-empty, pass it as a single `--message`.
- If `$ARGUMENTS` is empty, run `python donna.py --health` instead so the user sees runtime readiness.
- Working directory is the repo root; the script lives at `donna.py`.
- Do not add `--langsmith` or `--no-langsmith` unless the user asked.
- After the run, summarize Donna's reply in 1-2 sentences; do not re-print the full trace.

Execute:

```bash
python donna.py --message "$ARGUMENTS"
```

(Swap to `--health` when `$ARGUMENTS` is empty.)
