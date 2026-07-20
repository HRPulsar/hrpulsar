"""Employee profile completeness service.

Single source of truth for the "is this employee profile filled in" check.
POS6 alerts and any other downstream consumer (Phase IL onboarding banner,
talent-market eligibility, etc.) must call into here so the rule stays
consistent. The full HR profile completeness check lives in Phase IL; this
module currently covers the POS6 anchor fields only.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.employee.models import Employee


@dataclass(frozen=True)
class CompletenessReport:
    is_complete: bool
    missing: tuple[str, ...]


# Anchor fields that drive downstream features (assignments, drill-downs,
# matrix inheritance). Order is stable so callers can show the first miss.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "division_id",
    "position",  # position_id OR position_title
    "hire_date",
)


def report(emp: Employee) -> CompletenessReport:
    """Return what is missing from the employee profile, if anything."""
    missing: list[str] = []
    if emp.division_id is None:
        missing.append("division_id")
    if emp.position_id is None and not emp.position_title:
        missing.append("position")
    if emp.hire_date is None:
        missing.append("hire_date")
    return CompletenessReport(
        is_complete=not missing,
        missing=tuple(missing),
    )


def is_incomplete(emp: Employee) -> bool:
    """Convenience wrapper: True when the profile fails the anchor check."""
    return not report(emp).is_complete
