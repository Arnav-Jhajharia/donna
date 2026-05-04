"""System-shipped feature manifests.

Each module in this package exports ``FEATURE_MANIFEST`` — a dict that
validates against ``backend.features.manifest.FeatureManifest`` at boot.
The registry walks this package once at startup; new system features
land here as a single new file.

Phase 1 contains exactly one manifest (``hydration``). Phase 1.5 adds
``gratitude`` and ``inbox_brief``; Phase 2 adds ``person_watcher`` and
``life_planner``.
"""
from __future__ import annotations
