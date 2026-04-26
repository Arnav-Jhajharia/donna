"""Research-grade eval questions for the web pipeline.

Each question is chosen to require real synthesis across multiple sources
(i.e., one search snippet won't cut it). Avoid questions with a definitive
answer in training data — we want to see the pipeline actually fetching
and reasoning over fresh pages.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    rationale: str


QUESTIONS: tuple[EvalQuestion, ...] = (
    EvalQuestion(
        id="q1_compare",
        question=(
            "compare Poke and Limitless AI hardware as of 2026 — "
            "form factor, privacy stance, and which one is better suited "
            "for a founder on back-to-back pitches"
        ),
        rationale="Requires pulling from both companies' sites + third-party reviews and contrasting them.",
    ),
    EvalQuestion(
        id="q2_state_of",
        question=(
            "what is the current state of Claude Agent SDK vs LangGraph "
            "for building stateful conversational agents — where each is "
            "winning and where each is losing"
        ),
        rationale="Evolving landscape; no single source covers both; needs synthesis.",
    ),
    EvalQuestion(
        id="q3_tradeoffs",
        question=(
            "what are the tradeoffs between Exa and Tavily for a custom "
            "deep-research pipeline — features, pricing, and reliability"
        ),
        rationale="Directly relevant; needs pricing + feature comparison + reliability anecdotes.",
    ),
    EvalQuestion(
        id="q4_freshness",
        question=(
            "what has OpenAI shipped in the last 30 days and what "
            "does the pattern tell us about their roadmap"
        ),
        rationale="Freshness-sensitive; tests recency filter + synthesis.",
    ),
    EvalQuestion(
        id="q5_ambiguous",
        question=(
            "is it worth switching a small startup from Linear to Height "
            "right now — what do teams that switched report"
        ),
        rationale="Ambiguous, opinion-heavy; tests whether the pipeline handles 'weak signals' well.",
    ),
)
