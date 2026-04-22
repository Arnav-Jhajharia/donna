# Rewriting Project Claw Code

<p align="center">
  <img src="assets/clawd-hero.jpeg" alt="Claw" width="300" />
</p>

<p align="center">
  <strong>Better Harness Tools, not merely storing the archive of leaked Claude Code</strong>
</p>

<p align="center">
  <a href="https://github.com/sponsors/instructkr"><img src="https://img.shields.io/badge/Sponsor-%E2%9D%A4-pink?logo=github&style=for-the-badge" alt="Sponsor on GitHub" /></a>
</p>

> [!IMPORTANT]
> **Rust port is now in progress** on the [`dev/rust`](https://github.com/instructkr/claw-code/tree/dev/rust) branch and is expected to be merged into main today. The Rust implementation aims to deliver a faster, memory-safe harness runtime. Stay tuned — this will be the definitive version of the project.

> If you find this work useful, consider [sponsoring @instructkr on GitHub](https://github.com/sponsors/instructkr) to support continued open-source harness engineering research.

---

## Backstory

At 4 AM on March 31, 2026, I woke up to my phone blowing up with notifications. The Claude Code source had been exposed, and the entire dev community was in a frenzy. My girlfriend in Korea was genuinely worried I might face legal action from Anthropic just for having the code on my machine — so I did what any engineer would do under pressure: I sat down, ported the core features to Python from scratch, and pushed it before the sun came up.

The whole thing was orchestrated end-to-end using [oh-my-codex (OmX)](https://github.com/Yeachan-Heo/oh-my-codex) by [@bellman_ych](https://x.com/bellman_ych) — a workflow layer built on top of OpenAI's Codex ([@OpenAIDevs](https://x.com/OpenAIDevs)). I used `$team` mode for parallel code review and `$ralph` mode for persistent execution loops with architect-level verification. The entire porting session — from reading the original harness structure to producing a working Python tree with tests — was driven through OmX orchestration.

The result is a clean-room Python rewrite that captures the architectural patterns of Claude Code's agent harness without copying any proprietary source. I'm now actively collaborating with [@bellman_ych](https://x.com/bellman_ych) — the creator of OmX himself — to push this further. The basic Python foundation is already in place and functional, but we're just getting started. **Stay tuned — a much more capable version is on the way.**

https://github.com/instructkr/claw-code

![Tweet screenshot](assets/tweet-screenshot.png)

## The Creators Featured in Wall Street Journal For Avid Claude Code Fans

I've been deeply interested in **harness engineering** — studying how agent systems wire tools, orchestrate tasks, and manage runtime context. This isn't a sudden thing. The Wall Street Journal featured my work earlier this month, documenting how I've been one of the most active power users exploring these systems:

> AI startup worker Sigrid Jin, who attended the Seoul dinner, single-handedly used 25 billion of Claude Code tokens last year. At the time, usage limits were looser, allowing early enthusiasts to reach tens of billions of tokens at a very low cost.
>
> Despite his countless hours with Claude Code, Jin isn't faithful to any one AI lab. The tools available have different strengths and weaknesses, he said. Codex is better at reasoning, while Claude Code generates cleaner, more shareable code.
>
> Jin flew to San Francisco in February for Claude Code's first birthday party, where attendees waited in line to compare notes with Cherny. The crowd included a practicing cardiologist from Belgium who had built an app to help patients navigate care, and a California lawyer who made a tool for automating building permit approvals using Claude Code.
>
> "It was basically like a sharing party," Jin said. "There were lawyers, there were doctors, there were dentists. They did not have software engineering backgrounds."
>
> — *The Wall Street Journal*, March 21, 2026, [*"The Trillion Dollar Race to Automate Our Entire Lives"*](https://lnkd.in/gs9td3qd)

![WSJ Feature](assets/wsj-feature.png)

---

## Porting Status

The previous Python porting workspace has been archived.

- `archive/src_porting_workspace_2026-04-20/src/` contains the archived porting workspace
- `archive/tests_porting_workspace_2026-04-20/` contains the archived porting-workspace tests
- `donna_runtime/` contains the active Donna prototype runtime
- `tests/` verifies the active Donna runtime
- the exposed snapshot is no longer part of the tracked repository state

The active working surface is now Donna-first rather than the old porting CLI.

## Why this rewrite exists

I originally studied the exposed codebase to understand its harness, tool wiring, and agent workflow. After spending more time with the legal and ethical questions—and after reading the essay linked below—I did not want the exposed snapshot itself to remain the main tracked source tree.

This repository now focuses on the Donna system prototype instead. The earlier porting work is retained under `archive/` for reference.

## Repository Layout

```text
.
├── donna.py                            # Donna CLI entrypoint
├── donna_runtime/                      # Active Donna runtime package
│   ├── audit.py
│   ├── config.py
│   ├── hooks.py
│   ├── options.py
│   ├── prompt.py
│   ├── runner.py
│   ├── tool_logic.py
│   ├── tools.py
│   └── tracing.py
├── tests/                              # Active Donna verification
├── archive/                            # Archived porting workspace
├── assets/omx/                         # OmX workflow screenshots
├── 2026-03-09-is-legal-the-same-as-legitimate-ai-reimplementation-and-the-erosion-of-copyleft.md
└── README.md
```

## Donna Runtime Overview

The active Donna runtime currently provides:

- **`donna.py`** - CLI entrypoint for running and auditing Donna
- **`donna_runtime/config.py`** - model, messages, and tool policy configuration
- **`donna_runtime/env.py`** - small `.env` loader with no extra dependency
- **`donna_runtime/prompt.py`** - Donna system prompt construction
- **`donna_runtime/runner.py`** - stateless Agent SDK `query()` execution with `resume` support
- **`donna_runtime/session_store.py`** - local user-id to Claude session-id mapping for development
- **`donna_runtime/tool_logic.py`** - SDK-free tool behavior
- **`donna_runtime/tools.py`** - Claude Agent SDK tool wrappers
- **`donna_runtime/hooks.py`** - pre-tool and post-tool hook handling
- **`donna_runtime/tracing.py`** - JSONL trace collection and persistence
- **`donna_runtime/audit.py`** - trace policy checks

## Quickstart

Install runtime dependencies and fill in `.env`:

```bash
python -m pip install -r requirements.txt
```

Audit existing traces without requiring the Agent SDK:

```bash
python3 donna.py --audit-only --trace-file donna_traces.jsonl
```

Run the prototype loop when `claude-agent-sdk` and `ANTHROPIC_API_KEY` are available:

```bash
python3 donna.py --exercise
python3 donna.py --message "how much did I spend this week"
```

Resume a Claude Agent SDK session explicitly:

```bash
python3 donna.py --message "continue where we left off" --session-id <claude-session-id>
```

Or let Donna keep a local development mapping from `user_id` to Claude `session_id`:

```bash
python3 donna.py --user-id arnav --message "how much did I spend this week"
python3 donna.py --user-id arnav --message "what changed since then"
```

For production, store the returned Claude `session_id` in your database per app user. The local `.donna_sessions.json` file is only a development stand-in.

Donna uses the standalone Agent SDK `query()` function for production-shaped requests. Each process handles one prompt, captures `ResultMessage.session_id`, and resumes later with `ClaudeAgentOptions(resume=session_id)`. `ClaudeSDKClient` is still useful for an interactive single-process chat or REPL, but it is not the default shape here because it requires keeping a live async client around per active conversation.

Run verification:

```bash
python3 -m unittest discover -s tests -v
```

## LangSmith Tracing

Donna has optional LangSmith tracing for SDK turns, tool wrappers, and pre/post hook events.

Run a local instrumentation smoke test without credentials:

```bash
python3 donna.py --langsmith-smoke-test --langsmith-project donna-local
```

To post live traces to LangSmith, set credentials and enable tracing:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=<your-langsmith-api-key>
export LANGSMITH_PROJECT=donna-dev
python3 donna.py --message "haha same" --langsmith
```

For local-only tracing around the live SDK loop, use:

```bash
python3 donna.py --message "haha same" --langsmith-local
```

The archived porting CLI can still be inspected under `archive/src_porting_workspace_2026-04-20/src/`, but it is no longer the active source tree.

## Built with `oh-my-codex`

The restructuring and documentation work on this repository was AI-assisted and orchestrated with Yeachan Heo's [oh-my-codex (OmX)](https://github.com/Yeachan-Heo/oh-my-codex), layered on top of Codex.

- **`$team` mode:** used for coordinated parallel review and architectural feedback
- **`$ralph` mode:** used for persistent execution, verification, and completion discipline
- **Codex-driven workflow:** used for porting-workspace cleanup and Donna runtime restructuring

### OmX workflow screenshots

![OmX workflow screenshot 1](assets/omx/omx-readme-review-1.png)

*Ralph/team orchestration view while the README and essay context were being reviewed in terminal panes.*

![OmX workflow screenshot 2](assets/omx/omx-readme-review-2.png)

*Split-pane review and verification flow during the final README wording pass.*

## Community

<p align="center">
  <a href="https://instruct.kr/"><img src="assets/instructkr.png" alt="instructkr" width="400" /></a>
</p>

Join the [**instructkr Discord**](https://instruct.kr/) — the best Korean language model community. Come chat about LLMs, harness engineering, agent workflows, and everything in between.

[![Discord](https://img.shields.io/badge/Join%20Discord-instruct.kr-5865F2?logo=discord&style=for-the-badge)](https://instruct.kr/)

## Star History

This repository became **the fastest GitHub repo in history to surpass 30K stars**, reaching the milestone in just a few hours after publication.

<a href="https://star-history.com/#instructkr/claw-code&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=instructkr/claw-code&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=instructkr/claw-code&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=instructkr/claw-code&type=Date" />
  </picture>
</a>

![Star History Screenshot](assets/star-history.png)

## Ownership / Affiliation Disclaimer

- This repository does **not** claim ownership of the original Claude Code source material.
- This repository is **not affiliated with, endorsed by, or maintained by Anthropic**.
