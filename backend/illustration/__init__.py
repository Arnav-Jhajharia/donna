"""Day 1 dashboard top-half illustration generation.

Cache-amortized fal.ai Recraft calls keyed on (city, time_band, weather).
Curated safe per-city descriptors so we never free-form-prompt a place name
through an image model — that path leads straight to stereotype.
"""
