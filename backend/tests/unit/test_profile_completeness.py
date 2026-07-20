"""Unit tests for the employee profile completeness service (POS6)."""

from datetime import date

from app.modules.employee.models import Employee
from app.modules.employee.profile_completeness import (
    is_incomplete,
    report,
)


def _emp(**overrides) -> Employee:
    fields = {
        "division_id": "00000000-0000-0000-0000-000000000001",
        "position_id": "00000000-0000-0000-0000-000000000002",
        "position_title": "Backend",
        "hire_date": date(2025, 1, 1),
    }
    fields.update(overrides)
    e = Employee()
    for k, v in fields.items():
        setattr(e, k, v)
    return e


def test_complete_profile():
    rep = report(_emp())
    assert rep.is_complete
    assert rep.missing == ()
    assert is_incomplete(_emp()) is False


def test_division_missing_marks_incomplete():
    rep = report(_emp(division_id=None))
    assert not rep.is_complete
    assert "division_id" in rep.missing


def test_position_id_missing_but_title_present_is_complete():
    """Inviting flow can store a free-text title before resolving the FK."""
    rep = report(_emp(position_id=None, position_title="Backend"))
    assert rep.is_complete


def test_position_id_and_title_both_missing_is_incomplete():
    rep = report(_emp(position_id=None, position_title=None))
    assert not rep.is_complete
    assert "position" in rep.missing


def test_hire_date_missing_marks_incomplete():
    rep = report(_emp(hire_date=None))
    assert not rep.is_complete
    assert "hire_date" in rep.missing


def test_multiple_missing_collected_in_order():
    rep = report(_emp(division_id=None, hire_date=None))
    assert rep.missing == ("division_id", "hire_date")
