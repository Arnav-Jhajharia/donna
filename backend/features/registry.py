"""Feature manifest registry.

Walks ``backend.features.library`` at boot, validates each module's
``FEATURE_MANIFEST`` against ``FeatureManifest``, and builds two lookup
tables:

- ``template_id -> FeatureManifest`` for install / lifecycle tools.
- ``(user_id, type) -> (FeatureManifest, owner_template_id)`` for
  observation-type ownership lookup. The map is per-user because Phase 3
  user-composed features land in the same registry but are scoped to one
  user.

Reserved observation types are claimed by system features only. A
user-composed feature attempting to register a reserved type at install
time is rejected with a clear error. (Phase 3 enforcement; Phase 1 only
exposes the list and the rejection helper.)
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Iterator

from backend.features.manifest import FeatureManifest

logger = logging.getLogger(__name__)


# Observation types claimed by system features. User-composed features
# (Phase 3) cannot register these; they must extend the existing system
# feature instead.
RESERVED_OBSERVATION_TYPES: frozenset[str] = frozenset(
    {
        "hydration",
        "meal",
        "sleep",
        "mood",
        "gratitude",
        "read",
        "workout",
        "expense",
        "fitness",
        "habit",
    }
)


class FeatureRegistry:
    """In-memory registry of validated FeatureManifest instances.

    The registry is built once at startup via ``load_library()``. The
    same instance is shared across the process. User-composed features
    (Phase 3) will be added at install time via
    ``register_user_manifest()``; today only system features land here.
    """

    def __init__(self) -> None:
        self._by_template: dict[str, FeatureManifest] = {}
        # (user_id_or_wildcard, observation_type) -> (manifest, template_id)
        # System manifests use "*" as the user_id wildcard. Phase 3 will
        # store user-scoped entries with the actual user_id.
        self._by_observation: dict[
            tuple[str, str], tuple[FeatureManifest, str]
        ] = {}

    # -- Loading --------------------------------------------------------

    def load_library(self) -> None:
        """Walk ``backend.features.library`` and register each manifest.

        Raises ``ValueError`` if any module's ``FEATURE_MANIFEST`` fails
        validation; failure to load one feature must surface at boot
        rather than silently degrade the catalogue.
        """
        from backend.features import library as library_pkg

        for module_name in _iter_library_modules(library_pkg):
            module = importlib.import_module(module_name)
            raw = getattr(module, "FEATURE_MANIFEST", None)
            if raw is None:
                logger.warning(
                    "feature library module %s exports no FEATURE_MANIFEST",
                    module_name,
                )
                continue
            manifest = FeatureManifest.model_validate(raw)
            self.register_system_manifest(manifest)

    # -- Registration ---------------------------------------------------

    def register_system_manifest(self, manifest: FeatureManifest) -> None:
        """Register a system manifest (template_id non-NULL).

        System manifests are global — they apply to every user — so we
        index observation types under the ``"*"`` wildcard user_id.
        """
        if manifest.template_id is None:
            raise ValueError(
                "System manifests must have a non-NULL template_id; got NULL "
                f"for name={manifest.name!r}"
            )
        if manifest.template_id in self._by_template:
            existing = self._by_template[manifest.template_id]
            raise ValueError(
                f"Duplicate template_id {manifest.template_id!r}: "
                f"{existing.name!r} vs {manifest.name!r}"
            )
        self._by_template[manifest.template_id] = manifest
        for obs_type in manifest.primary_observation_types:
            key = ("*", obs_type)
            if key in self._by_observation:
                other_manifest, other_template = self._by_observation[key]
                raise ValueError(
                    f"observation type {obs_type!r} already claimed by "
                    f"system feature {other_template!r}; "
                    f"refusing to add {manifest.template_id!r}"
                )
            self._by_observation[key] = (manifest, manifest.template_id)

    def register_user_manifest(
        self, *, user_id: str, manifest: FeatureManifest
    ) -> None:
        """Register a user-composed manifest (Phase 3 hook).

        Rejected if the manifest claims a reserved observation type.
        Reserved types belong to system features; user-composed features
        must use a different name or subscribe to the existing one.
        """
        for obs_type in manifest.primary_observation_types:
            if obs_type in RESERVED_OBSERVATION_TYPES:
                raise ValueError(
                    f"observation type {obs_type!r} is reserved for system "
                    "features; user-composed features cannot claim it"
                )
            key = (user_id, obs_type)
            self._by_observation[key] = (
                manifest,
                manifest.template_id or "user_composed",
            )

    # -- Lookup ---------------------------------------------------------

    def get_template(self, template_id: str) -> FeatureManifest | None:
        return self._by_template.get(template_id)

    def all_templates(self) -> tuple[FeatureManifest, ...]:
        return tuple(self._by_template.values())

    def template_ids(self) -> tuple[str, ...]:
        return tuple(self._by_template.keys())

    def manifest_for_observation(
        self, *, user_id: str, obs_type: str
    ) -> tuple[FeatureManifest, str] | None:
        """Resolve an observation type to its owning manifest.

        Checks user-scoped entries first (Phase 3), then falls back to
        the global system catalogue. Returns ``(manifest, template_id)``
        or ``None`` if the type is unowned (free-form observation).
        """
        scoped = self._by_observation.get((user_id, obs_type))
        if scoped is not None:
            return scoped
        return self._by_observation.get(("*", obs_type))

    # -- Helpers --------------------------------------------------------

    def reserved_observation_types(self) -> frozenset[str]:
        return RESERVED_OBSERVATION_TYPES

    def is_reserved(self, obs_type: str) -> bool:
        return obs_type in RESERVED_OBSERVATION_TYPES

    def reset(self) -> None:
        """Test-only: drop everything and start fresh."""
        self._by_template.clear()
        self._by_observation.clear()


# -- Module-level singleton --------------------------------------------------


_registry: FeatureRegistry | None = None


def get_registry() -> FeatureRegistry:
    """Return the lazily-initialised process-global registry.

    First call walks the library; subsequent calls return the cached
    instance. Tests that mutate the registry should call ``reset()``
    or build their own instance via ``FeatureRegistry()``.
    """
    global _registry
    if _registry is None:
        _registry = FeatureRegistry()
        _registry.load_library()
    return _registry


def reset_registry_for_tests() -> None:
    """Drop the module-level singleton so the next ``get_registry``
    call rebuilds from the library. Tests-only entry point."""
    global _registry
    _registry = None


# -- Internals ---------------------------------------------------------------


def _iter_library_modules(library_pkg: object) -> Iterator[str]:
    """Yield fully-qualified module names under ``backend.features.library``."""
    path = getattr(library_pkg, "__path__", None)
    if path is None:
        return
    pkg_name = library_pkg.__name__  # type: ignore[attr-defined]
    for module_info in pkgutil.iter_modules(path):
        if module_info.ispkg:
            continue
        if module_info.name.startswith("_"):
            continue
        yield f"{pkg_name}.{module_info.name}"
