"""Deterministic seed corpus for the memory stress test.

Pure data generators live here. The CLI and async writers live in
``scripts/seed_stress_corpus.py``. Each module exposes one ``build_*``
function that returns immutable rows from a fixed anchor datetime and a
seeded ``random.Random`` instance — so every run reproduces bit-for-bit.
"""
