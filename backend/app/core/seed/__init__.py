"""Shared seed logic for populating tenants with demo data.

Used by:
- scripts/seed_demo.py (self-hosted)
- backend/ee/seed_saas.py (SaaS)

Decomposed by step (review [30]): static demo data lives in ``data``,
per-step logic in ``org`` / ``catalog`` / ``competences`` /
``assessments`` / ``pdps`` / ``exams`` / ``talent``, all sharing an
explicit :class:`~app.core.seed.context.SeedContext` instead of function
locals. ``populate.populate_tenant`` orchestrates. This module re-exports
the public surface the seed scripts import.
"""

from .data import (
    CUSTOM_GRADES,
    CUSTOM_SPECS,
    DEMO_PASSWORD,
    DIVISIONS_L1,
    DIVISIONS_L2,
    PEOPLE,
)
from .helpers import now, past_date, past_dt, uid
from .populate import populate_tenant
from .ref_data import fetch_ref_data

__all__ = [
    "CUSTOM_GRADES",
    "CUSTOM_SPECS",
    "DEMO_PASSWORD",
    "DIVISIONS_L1",
    "DIVISIONS_L2",
    "PEOPLE",
    "fetch_ref_data",
    "now",
    "past_date",
    "past_dt",
    "populate_tenant",
    "uid",
]
