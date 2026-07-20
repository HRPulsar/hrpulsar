"""Startup monkey-patch machinery shared by the service-wrapper stacks.

Two registries wrap mutating service functions at startup with the same
import → getattr → idempotency-check → setattr loop, and derive the same
``{module:func}`` coverage keys for their "every mutation must be declared"
tests:

* ``app.modules.recruitment.audit_registry`` (core) — audit-log hooks;
* ``ee.billing`` (enterprise, imports core) — credit-billing wrappers.

This module is the single source of that machinery so the loop (or a third
registry) lives in one place. Each registry keeps its own registry map and
its own wrapper builder — only the patch loop and key derivation are shared.

``make_wrapper`` receives the original callable plus the registry ``entry``
tuple (whose first element is always the function name) and returns the
wrapped callable. It is responsible for stamping the idempotency ``marker``
attribute on its wrapper; the loop only *reads* that attribute to skip
already-patched functions (safe re-registration).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any

Entry = Sequence[Any]


def apply_service_patches(
    registry: Mapping[str, Sequence[Entry]],
    *,
    make_wrapper: Callable[[Any, Entry], Any],
    marker: str,
    kind: str,
) -> None:
    """Monkey-patch every declared function with ``make_wrapper``. Idempotent.

    ``registry`` maps ``module_path`` → entries whose first element is the
    function name. ``marker`` is the attribute a wrapper stamps on itself; a
    function already carrying it is skipped. ``kind`` labels the RuntimeError
    raised when a declared function is missing from its module.
    """
    for module_path, entries in registry.items():
        module = importlib.import_module(module_path)
        for entry in entries:
            func_name = entry[0]
            original = getattr(module, func_name, None)
            if original is None:
                raise RuntimeError(
                    f"{kind} registration failed: {module_path}.{func_name} not found"
                )
            if hasattr(original, marker):
                continue
            setattr(module, func_name, make_wrapper(original, entry))


def declared_keys(registry: Mapping[str, Sequence[Entry]]) -> set[str]:
    """All ``module:func`` keys declared in ``registry`` (for coverage tests)."""
    return {
        f"{module_path}:{entry[0]}"
        for module_path, entries in registry.items()
        for entry in entries
    }
