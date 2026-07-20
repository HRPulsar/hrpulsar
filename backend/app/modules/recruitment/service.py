"""Delegating namespace for the recruitment services (project-review #7).

The original god-service was split into cohesive modules — the M-5 split
(R4d) moved interview / consent / report logic out, and the project-review
pass split the remainder into ``common`` / ``vacancy_service`` /
``vacancy_profile_service`` / ``candidate_service`` / ``assessment_service``.

This module keeps the historical ``service.<name>`` surface working:
routers, tests and lazy importers such as ``auth.register`` resolve
attributes through :func:`__getattr__` below. Lookup is delegated at call
time (not at import time) so that any wrapping installed by
``register_billing`` / ``register_audit_hooks`` on the canonical module is
also visible through this namespace. Do NOT re-export names eagerly here —
an import-time binding would freeze the unwrapped function.
"""

_SPLIT_MODULES = (
    "app.modules.recruitment.common",
    "app.modules.recruitment.vacancy_service",
    "app.modules.recruitment.vacancy_profile_service",
    "app.modules.recruitment.candidate_service",
    "app.modules.recruitment.assessment_service",
    "app.modules.recruitment.interview_service",
    "app.modules.recruitment.consent_service",
    "app.modules.recruitment.report_service",
)


def __getattr__(name: str):  # PEP 562
    import importlib

    for module_path in _SPLIT_MODULES:
        module = importlib.import_module(module_path)
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(
        f"module 'app.modules.recruitment.service' has no attribute {name!r}"
    )
