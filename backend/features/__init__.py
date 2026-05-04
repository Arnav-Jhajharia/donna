"""Features primitive — composable units of (attentions + observations +
cron + dashboard cards + hooks + tools + integrations).

See ``backend/features/manifest.py`` for the FEATURE_MANIFEST schema and
``backend/features/registry.py`` for boot-time loading. Reference
manifests live in ``backend/features/library/``.

This module is additive: nothing about pre-feature primitives changes.
All existing rows carry ``feature_id IS NULL`` and keep working.
"""
from __future__ import annotations
