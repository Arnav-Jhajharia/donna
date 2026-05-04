"""Tests for the FeatureManifest registry.

Manifest validation, reserved-type rejection, and round-trip loading of
the system library all happen here. The registry is module-level state
so each test that mutates it must reset via ``reset_registry_for_tests``.
"""
from __future__ import annotations

import pytest


def _hydration_manifest_dict() -> dict:
    """Minimal valid manifest matching the hydration library entry."""
    return {
        "template_id": "hydration_tracker",
        "name": "Hydration",
        "surface": "body",
        "icon": "drop",
        "tone": "moss",
        "config_schema": {
            "target_glasses": {"type": "int", "default": 8},
        },
        "observations": [
            {
                "type": "hydration",
                "owner": "primary",
                "fields_required": {"glasses": {"type": "int"}},
            }
        ],
        "attentions": [
            {
                "card": "tally",
                "subject_type": "habit",
                "cadence": "on_event",
            }
        ],
    }


# -- Manifest validation ----------------------------------------------------


def test_feature_manifest_validates_minimal_ok() -> None:
    from backend.features.manifest import FeatureManifest

    manifest = FeatureManifest.model_validate(_hydration_manifest_dict())

    assert manifest.template_id == "hydration_tracker"
    assert manifest.name == "Hydration"
    assert manifest.primary_observation_types == ("hydration",)


def test_feature_manifest_rejects_empty_ingredients() -> None:
    """Identity-only manifests must fail validation."""
    from backend.features.manifest import FeatureManifest

    raw = {
        "template_id": "empty_feature",
        "name": "Empty",
    }
    with pytest.raises(ValueError, match="at least one of"):
        FeatureManifest.model_validate(raw)


def test_feature_manifest_rejects_blank_name() -> None:
    from backend.features.manifest import FeatureManifest

    raw = _hydration_manifest_dict()
    raw["name"] = "   "
    with pytest.raises(ValueError, match="name must be non-empty"):
        FeatureManifest.model_validate(raw)


def test_feature_manifest_rejects_extra_fields() -> None:
    from backend.features.manifest import FeatureManifest

    raw = _hydration_manifest_dict()
    raw["typo_field"] = "oops"
    with pytest.raises(ValueError):
        FeatureManifest.model_validate(raw)


def test_feature_manifest_template_id_can_be_null() -> None:
    """User-composed features (Phase 3) carry NULL template_id."""
    from backend.features.manifest import FeatureManifest

    raw = _hydration_manifest_dict()
    raw["template_id"] = None
    raw["name"] = "Pushups"
    raw["observations"] = [
        {"type": "pushups", "owner": "primary"}
    ]
    manifest = FeatureManifest.model_validate(raw)
    assert manifest.template_id is None


def test_primary_observation_types_filters_subscribers() -> None:
    """Subscriber observations don't claim ownership."""
    from backend.features.manifest import FeatureManifest

    raw = _hydration_manifest_dict()
    raw["observations"] = [
        {"type": "hydration", "owner": "primary"},
        {"type": "meal", "owner": "subscriber"},
    ]
    manifest = FeatureManifest.model_validate(raw)
    assert manifest.primary_observation_types == ("hydration",)


# -- Registry round-trip ----------------------------------------------------


def test_registry_loads_hydration_from_library() -> None:
    """Boot-time load must surface the hydration manifest."""
    from backend.features.registry import (
        FeatureRegistry,
        reset_registry_for_tests,
    )

    reset_registry_for_tests()
    registry = FeatureRegistry()
    registry.load_library()

    hydration = registry.get_template("hydration_tracker")
    assert hydration is not None
    assert hydration.name == "Hydration"
    assert hydration.primary_observation_types == ("hydration",)


def test_registry_indexes_observation_type_to_owner() -> None:
    from backend.features.registry import FeatureRegistry

    registry = FeatureRegistry()
    registry.load_library()

    match = registry.manifest_for_observation(
        user_id="any-user", obs_type="hydration"
    )
    assert match is not None
    manifest, template_id = match
    assert template_id == "hydration_tracker"
    assert manifest.name == "Hydration"


def test_registry_returns_none_for_unowned_type() -> None:
    from backend.features.registry import FeatureRegistry

    registry = FeatureRegistry()
    registry.load_library()

    assert (
        registry.manifest_for_observation(
            user_id="any", obs_type="unowned_type"
        )
        is None
    )


def test_registry_rejects_reserved_observation_for_user_manifest() -> None:
    """User-composed features cannot claim reserved types."""
    from backend.features.manifest import FeatureManifest
    from backend.features.registry import FeatureRegistry

    raw = _hydration_manifest_dict()
    raw["template_id"] = None
    raw["name"] = "MyHydration"
    manifest = FeatureManifest.model_validate(raw)

    registry = FeatureRegistry()
    with pytest.raises(ValueError, match="reserved"):
        registry.register_user_manifest(user_id="u1", manifest=manifest)


def test_registry_rejects_duplicate_template_id() -> None:
    from backend.features.manifest import FeatureManifest
    from backend.features.registry import FeatureRegistry

    manifest_a = FeatureManifest.model_validate(_hydration_manifest_dict())
    manifest_b = FeatureManifest.model_validate(_hydration_manifest_dict())

    registry = FeatureRegistry()
    registry.register_system_manifest(manifest_a)
    with pytest.raises(ValueError, match="Duplicate template_id"):
        registry.register_system_manifest(manifest_b)


def test_registry_rejects_system_manifest_with_null_template_id() -> None:
    from backend.features.manifest import FeatureManifest
    from backend.features.registry import FeatureRegistry

    raw = _hydration_manifest_dict()
    raw["template_id"] = None
    raw["name"] = "no-id"
    manifest = FeatureManifest.model_validate(raw)

    registry = FeatureRegistry()
    with pytest.raises(ValueError, match="non-NULL template_id"):
        registry.register_system_manifest(manifest)


def test_reserved_observation_types_includes_hydration() -> None:
    from backend.features.registry import RESERVED_OBSERVATION_TYPES

    assert "hydration" in RESERVED_OBSERVATION_TYPES
    assert "meal" in RESERVED_OBSERVATION_TYPES
    assert "sleep" in RESERVED_OBSERVATION_TYPES
    assert "workout" in RESERVED_OBSERVATION_TYPES
