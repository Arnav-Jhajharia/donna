"""Pydantic schema for FEATURE_MANIFEST.

Every feature — system-shipped or user-composed (Phase 3) — produces one
``FeatureManifest`` instance. The shape is the single source of truth for
install, dashboard cards, scheduling, hooks, tools, recipes, and
integration wiring. No parallel hardcoded tuples.

Identity fields are required; everything else is optional, declared only
if the feature uses that ingredient. A simple tracker uses
``observations`` + ``attentions`` + ``dashboard_cards``. A life planner
uses ``cron`` + ``tools_exposed`` + ``dashboard_cards``. A gratitude
practice uses ``cron`` + ``observations``. Same shape, different
ingredients.

The model is intentionally permissive on field types (e.g. ``config_schema``
default values stay ``Any``) so different feature shapes can express
themselves without per-archetype validators in Phase 1. Validation that
matters in Phase 1:

- Identity is non-empty.
- Reserved observation types belong to system features only.
- At least one ingredient is declared (a manifest with no observations,
  attentions, dashboard_cards, cron, or tools_exposed is meaningless).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictBase(BaseModel):
    """Forbid extra fields so manifest typos surface at boot, not at use."""

    model_config = ConfigDict(extra="forbid")


# -- Per-field config schema -------------------------------------------------


class ConfigSchemaField(_StrictBase):
    """One entry in a feature's ``config_schema``.

    ``type`` mirrors the manifest's prose hint (``int``, ``tuple``,
    ``str``, etc.). Phase 1 doesn't enforce types at runtime — install
    just merges ``default`` with caller-provided overrides. Phase 2
    lifecycle tools will validate against ``type`` + bounds.
    """

    type: str
    default: Any = None
    description: str | None = None
    min: float | None = None
    max: float | None = None


# -- Integrations -----------------------------------------------------------


class IntegrationDecl(_StrictBase):
    """A toolkit the feature needs (Gmail, Calendar, GitHub, ...).

    ``required=True`` blocks install if the user hasn't connected the
    toolkit. ``watches`` is the list of Composio trigger slugs the
    feature subscribes to. Phase 1 only checks presence on install;
    fan-out to feature hooks is Phase 4.
    """

    app: str
    required: bool = True
    watches: list[str] = Field(default_factory=list)


# -- Observations -----------------------------------------------------------


class ObservationDecl(_StrictBase):
    """An observation type the feature owns.

    ``owner='primary'`` claims the type — writes through ``log_observation``
    that match this type will tag rows with the owning feature id.
    ``owner='subscriber'`` (Phase 2+) hooks into someone else's writes
    without owning the schema.

    ``fields_required`` / ``fields_optional`` are the structured payload
    the feature expects (for the hydration tracker:
    ``{"glasses": {"type": "int", "min": 0, "max": 30}}``). Validation
    in Phase 1 is best-effort and never blocks a write.
    """

    type: str
    owner: Literal["primary", "subscriber"] = "primary"
    fields_required: dict[str, Any] = Field(default_factory=dict)
    fields_optional: dict[str, Any] = Field(default_factory=dict)
    aggregation: dict[str, str] = Field(default_factory=dict)
    extractor_hint: str | None = None


# -- Attentions -------------------------------------------------------------


class AttentionDecl(_StrictBase):
    """Spawn-time spec for an attention created on feature install.

    Loose enough to back five different feature shapes:
    - ``cadence='on_event'`` for tally cards (re-evaluate on every
      observation of the right type)
    - ``cadence_template='every_N_minutes'`` for cadenced pings whose N
      lives in the feature's ``config`` (``cadence_param_key`` names the
      key — e.g. ``remind_every_min``).

    Phase 2 will materialise these into real ``donna.attention.schema``
    AttentionSpec rows; Phase 1 stores them on the Feature row's
    ``state.attention_specs`` for later promotion.
    """

    card: str
    subject_type: str
    cadence: str | None = None
    cadence_template: str | None = None
    cadence_param_key: str | None = None
    extractor_hint: str | None = None
    title: str | None = None
    description: str | None = None


# -- Dashboard --------------------------------------------------------------


class DashboardCardDecl(_StrictBase):
    """A dashboard surface the feature claims declaratively.

    ``archetype`` is the c-tracker / c-streak / c-prep / c-decision /
    c-reflection / c-read slug the renderer keys off. ``render_when`` is
    a string expression evaluated at compose time (Phase 2). ``fill``
    contains placeholder strings (``{state.today_count}``) that hydrate
    from the Feature row's state + config without an LLM call.
    """

    archetype: str
    variant: str | None = None
    domain: str | None = None
    render_when: str | None = None
    priority: int = 10
    fill: dict[str, Any] = Field(default_factory=dict)


# -- Hooks ------------------------------------------------------------------


class HookDecl(_StrictBase):
    """One subscription to the post-turn pipeline.

    ``event`` is a slug like ``post_observation`` or ``post_turn``;
    ``handler`` is the dotted-path or short slug the dispatcher resolves
    to a Python callable. Phase 1 stores these for later registration
    (Phase 4); they are not invoked yet.
    """

    event: str
    handler: str


# -- Cron -------------------------------------------------------------------


class CronDecl(_StrictBase):
    """A scheduled job materialised into ``donna_schedule`` on install.

    ``schedule`` is a 5-field cron string in the user's timezone when
    ``tz_aware=True``. ``handler`` is resolved at fire time.

    Phase 1 materialises the *next* fire as a ``DonnaSchedule`` row
    tagged with ``feature_id``; recurrence wiring (subsequent fires)
    lives in the existing schedule worker once ``recurrence`` is set.
    """

    name: str
    schedule: str
    tz_aware: bool = True
    handler: str
    recurrence: str | None = None


# -- Onboarding -------------------------------------------------------------


class OnboardingDecl(_StrictBase):
    """How Donna offers / installs this feature in the playbook.

    ``install_kind`` controls the offer flow; ``default_active_for`` is a
    list of persona tags ("health-conscious", "founder") the matcher
    consults when proposing.
    """

    ask: str | None = None
    default_active_for: list[str] = Field(default_factory=list)
    install_kind: Literal["auto", "user_confirms", "donna_proposes"] = (
        "user_confirms"
    )


# -- Recipe -----------------------------------------------------------------


class RecipeDecl(_StrictBase):
    """Recipe-bank entry surfaced in the dashboard mosaic."""

    id: str
    title: str
    primer: str
    provides: tuple[str, ...] = Field(default_factory=tuple)
    requires: tuple[str, ...] = Field(default_factory=tuple)
    body: str | None = None


# -- Top-level manifest -----------------------------------------------------


class FeatureManifest(_StrictBase):
    """Single source of truth for one feature.

    Identity (``template_id`` may be NULL for user-composed features in
    Phase 3, ``name`` always required), surface metadata, and the
    declarative ingredients. Phase 1 consumers:
    - registry.py: load + validate.
    - install.py: spawn attentions, materialise cron, write Feature row.
    - log_observation: auto-tag rows with feature_id when type matches.
    """

    # Identity
    template_id: str | None
    name: str
    description: str | None = None
    surface: str | None = None
    icon: str | None = None
    tone: str | None = None
    manifest_version: str = "1.0"

    # Per-user settings
    config_schema: dict[str, ConfigSchemaField] = Field(default_factory=dict)

    # Ingredients
    integrations: list[IntegrationDecl] = Field(default_factory=list)
    observations: list[ObservationDecl] = Field(default_factory=list)
    attentions: list[AttentionDecl] = Field(default_factory=list)
    dashboard_cards: list[DashboardCardDecl] = Field(default_factory=list)
    tools_required: list[str] = Field(default_factory=list)
    tools_exposed: list[str] = Field(default_factory=list)
    hooks: list[HookDecl] = Field(default_factory=list)
    cron: list[CronDecl] = Field(default_factory=list)
    onboarding: OnboardingDecl | None = None
    recipe: RecipeDecl | None = None

    @model_validator(mode="after")
    def _at_least_one_ingredient(self) -> "FeatureManifest":
        """A manifest with no ingredients is meaningless.

        At least one of {observations, attentions, dashboard_cards,
        cron, tools_exposed} must be non-empty. Identity-only manifests
        are rejected at boot rather than silently installing into
        nothing.
        """
        ingredients = (
            self.observations,
            self.attentions,
            self.dashboard_cards,
            self.cron,
            self.tools_exposed,
        )
        if not any(ingredients):
            raise ValueError(
                "FeatureManifest must declare at least one of "
                "observations, attentions, dashboard_cards, cron, "
                "tools_exposed"
            )
        return self

    @model_validator(mode="after")
    def _name_non_empty(self) -> "FeatureManifest":
        if not self.name or not self.name.strip():
            raise ValueError("FeatureManifest.name must be non-empty")
        return self

    @property
    def primary_observation_types(self) -> tuple[str, ...]:
        """Observation types this feature claims as primary owner.

        Used by ``log_observation`` to auto-tag writes with the feature
        id when an active feature claims the incoming type.
        """
        return tuple(
            obs.type for obs in self.observations if obs.owner == "primary"
        )
