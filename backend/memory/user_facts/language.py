"""Lightweight language detector — English/Hindi/Hinglish markers only.

The lingua-language-detector dep from backend-v2 is optional here — if it is
not installed we fall back to marker-only heuristics.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from lingua import Language, LanguageDetectorBuilder

    _detector = (
        LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.HINDI)
        .with_preloaded_language_models()
        .build()
    )
    _LINGUA_AVAILABLE = True
except ImportError:
    _detector = None
    _LINGUA_AVAILABLE = False


_MIN_CHARS = 4
_HINGLISH_MARKERS = {
    "bhai", "yaar", "kya", "hai", "nahi", "mera", "tera", "bhi",
    "accha", "theek", "chalo", "bolo", "karo", "hona", "kal",
    "dena", "lena", "raha", "rahi", "kaisa", "kaisi",
}


def detect_language(text: str) -> str | None:
    if not text or len(text.strip()) < _MIN_CHARS:
        return None
    words = {w.strip(".,!?;:").lower() for w in text.split()}
    if words & _HINGLISH_MARKERS:
        return "en-hi"
    if not _LINGUA_AVAILABLE:
        return None
    try:
        lang = _detector.detect_language_of(text)
    except Exception:
        logger.exception("language detection failed")
        return None
    if lang is None:
        return None
    if lang == Language.ENGLISH:
        return "en"
    if lang == Language.HINDI:
        return "hi"
    return None
