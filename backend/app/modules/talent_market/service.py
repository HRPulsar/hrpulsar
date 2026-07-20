"""Delegating namespace for the talent-market services (project-review #20).

The original god-service was split into cohesive modules: ``common``
(read-model converters + lifecycle email dispatch), ``card_service``
(card CRUD / search / publish / complete / cancel), ``matching`` (the
candidate matching engine), ``candidate_service`` (pool listing / attach /
appoint / remove / reactions) and ``requirement_service`` (requirements,
required specializations and competences).

This module keeps the historical ``service.<name>`` surface working:
the router and tests resolve attributes through :func:`__getattr__` below.
Lookup is delegated at call time (not at import time) so that any wrapping
installed by ``register_billing`` on the canonical module is also visible
through this namespace. Do NOT re-export names eagerly here — an
import-time binding would freeze the unwrapped function.
"""

_SPLIT_MODULES = (
    "app.modules.talent_market.common",
    "app.modules.talent_market.card_service",
    "app.modules.talent_market.matching",
    "app.modules.talent_market.candidate_service",
    "app.modules.talent_market.requirement_service",
)


def __getattr__(name: str):  # PEP 562
    import importlib

    for module_path in _SPLIT_MODULES:
        module = importlib.import_module(module_path)
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(
        f"module 'app.modules.talent_market.service' has no attribute {name!r}"
    )
