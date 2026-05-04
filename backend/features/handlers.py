"""Registry of feature cron + hook handlers.

A feature manifest declares ``cron[*].handler`` and ``hooks[*].handler`` as
string names. Phase 4 wires real callables into these names via
``register_cron_handler`` / ``register_hook_handler``. Until then, the
registry is a gating mechanism: ``_materialise_cron`` in install refuses
to schedule a cron row whose handler isn't registered, because the
schedule worker would otherwise fall through to a literal "reminder"
WhatsApp text — the worst possible Phase 1 user experience.

The registry is intentionally module-level (process-wide). Phase 4 will
add a per-user dispatcher that walks active features and fires their
hooks; that dispatcher reads from the same registry.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

CronHandler = Callable[..., Awaitable[Any]]
HookHandler = Callable[..., Awaitable[Any]]


_CRON_HANDLERS: dict[str, CronHandler] = {}
_HOOK_HANDLERS: dict[str, HookHandler] = {}


def register_cron_handler(name: str, fn: CronHandler) -> None:
    """Register a cron handler. Re-registration overrides (handy in tests)."""
    if not name:
        raise ValueError("cron handler name must be non-empty")
    _CRON_HANDLERS[name] = fn


def register_hook_handler(name: str, fn: HookHandler) -> None:
    """Register a post_observation / post_turn hook handler."""
    if not name:
        raise ValueError("hook handler name must be non-empty")
    _HOOK_HANDLERS[name] = fn


def is_cron_handler_registered(name: str | None) -> bool:
    return bool(name) and name in _CRON_HANDLERS


def is_hook_handler_registered(name: str | None) -> bool:
    return bool(name) and name in _HOOK_HANDLERS


def get_cron_handler(name: str) -> CronHandler | None:
    return _CRON_HANDLERS.get(name)


def get_hook_handler(name: str) -> HookHandler | None:
    return _HOOK_HANDLERS.get(name)


def registered_cron_handlers() -> tuple[str, ...]:
    return tuple(sorted(_CRON_HANDLERS))


def registered_hook_handlers() -> tuple[str, ...]:
    return tuple(sorted(_HOOK_HANDLERS))


def _reset_for_tests() -> None:
    """Test-only helper: clear both registries between tests."""
    _CRON_HANDLERS.clear()
    _HOOK_HANDLERS.clear()
