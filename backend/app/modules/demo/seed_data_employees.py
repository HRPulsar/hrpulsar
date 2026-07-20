"""Employee fixtures for the demo seed (HRP-281 — S3).

40 deterministically named cards distributed across the divisions
seeded in S1. Each entry resolves to:

* a ``User`` row (one per employee, unique on (email, tenant_id))
* an ``Employee`` row tied to the user, division and position

Names are picked from an international, PII-safe pool; emails are
``<first>.<last>@demo.example.com`` lowercased, with the apostrophe in
Irish surnames stripped to avoid breaking the unique constraint.

Hire dates are spaced deterministically (1..5 years) so the Employee
list shows a realistic tenure spread without re-randomising on each
seed run.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Name pool — 40 international names, no real customers / employees
# ---------------------------------------------------------------------------

NAME_POOL: list[tuple[str, str]] = [
    ("Adam", "Kovacs"),
    ("Bella", "Martins"),
    ("Carlos", "Mendez"),
    ("Daria", "Volkova"),
    ("Ethan", "Williams"),
    ("Fatima", "Al-Rashid"),
    ("Gabriel", "Santos"),
    ("Hana", "Okafor"),
    ("Ivan", "Petrov"),
    ("Julia", "Schmitt"),
    ("Kenji", "Nakamura"),
    ("Leila", "Karam"),
    ("Marcus", "Johnson"),
    ("Nadia", "Hassan"),
    ("Omar", "Ali"),
    ("Petra", "Nowak"),
    ("Quinn", "O'Connor"),
    ("Rafael", "Costa"),
    ("Sara", "Lindberg"),
    ("Theo", "Bauer"),
    ("Uma", "Patel"),
    ("Victor", "Dubois"),
    ("Wilma", "Hansen"),
    ("Xavier", "Romero"),
    ("Yara", "Saito"),
    ("Zoe", "Caron"),
    ("Aaron", "Park"),
    ("Bianca", "Rossi"),
    ("Cameron", "Brown"),
    ("Diana", "Ovsyannikova"),
    ("Emil", "Krause"),
    ("Farah", "Khoury"),
    ("Greg", "Murphy"),
    ("Hannah", "Adler"),
    ("Igor", "Sokolov"),
    ("Jana", "Vargas"),
    ("Kira", "Tanaka"),
    ("Liam", "O'Sullivan"),
    ("Mira", "Bianchi"),
    ("Noah", "Larsson"),
]


# ---------------------------------------------------------------------------
# Assignments — index in NAME_POOL → (division_key, position_key, status,
#                                     manager_role)
# ---------------------------------------------------------------------------
#
# ``manager_role`` is one of:
#   ``"division_head"`` — this employee becomes the Division.manager_id
#       for their division (one per division).
#   ``"division_deputy"`` — this employee becomes Division.deputy_manager_id.
#   ``None`` — regular contributor.
#
# Headcount distribution:
#   eng-backend     : 6
#   eng-platform    : 5
#   eng-frontend    : 7  (total Engineering = 18)
#   product         : 6
#   design          : 4
#   people          : 5
#   gtm             : 7  (3 AE + 4 SDR)
#
# Status mix: 3 onboarding (recent hires), 1 inactive, 1 on_leave, 35 active.

EMPLOYEE_ASSIGNMENTS: list[dict] = [
    # 0 — Adam Kovacs — Engineering Manager Backend (division_head)
    {"division_key": "eng-backend", "position_key": "p-em-backend", "status": "active", "manager_role": "division_head"},
    # 1 — Bella Martins — Engineering, Backend L4 Staff
    {"division_key": "eng-backend", "position_key": "p-be-l4", "status": "active", "manager_role": "division_deputy"},
    # 2 — Carlos Mendez — Backend L3 Senior
    {"division_key": "eng-backend", "position_key": "p-be-l3", "status": "active", "manager_role": None},
    # 3 — Daria Volkova — Backend L3 Senior
    {"division_key": "eng-backend", "position_key": "p-be-l3", "status": "active", "manager_role": None},
    # 4 — Ethan Williams — Backend L2 Middle
    {"division_key": "eng-backend", "position_key": "p-be-l2", "status": "active", "manager_role": None},
    # 5 — Fatima Al-Rashid — Backend L1 Junior (recent hire)
    {"division_key": "eng-backend", "position_key": "p-be-l1", "status": "active", "manager_role": None, "recent_hire": True},
    # 6 — Gabriel Santos — Engineering Manager Platform (division_head)
    {"division_key": "eng-platform", "position_key": "p-em-platform", "status": "active", "manager_role": "division_head"},
    # 7 — Hana Okafor — Platform, Backend L4 Staff
    {"division_key": "eng-platform", "position_key": "p-be-l4", "status": "active", "manager_role": None},
    # 8 — Ivan Petrov — Platform, Backend L3 Senior
    {"division_key": "eng-platform", "position_key": "p-be-l3", "status": "active", "manager_role": None},
    # 9 — Julia Schmitt — Platform, Backend L3 Senior
    {"division_key": "eng-platform", "position_key": "p-be-l3", "status": "active", "manager_role": None},
    # 10 — Kenji Nakamura — Platform, Backend L2 Middle
    {"division_key": "eng-platform", "position_key": "p-be-l2", "status": "active", "manager_role": None},
    # 11 — Leila Karam — Engineering Manager Frontend (division_head)
    {"division_key": "eng-frontend", "position_key": "p-em-frontend", "status": "active", "manager_role": "division_head"},
    # 12 — Marcus Johnson — Frontend L3 Senior
    {"division_key": "eng-frontend", "position_key": "p-fe-l3", "status": "active", "manager_role": "division_deputy"},
    # 13 — Nadia Hassan — Frontend L3 Senior
    {"division_key": "eng-frontend", "position_key": "p-fe-l3", "status": "active", "manager_role": None},
    # 14 — Omar Ali — Frontend L3 Senior
    {"division_key": "eng-frontend", "position_key": "p-fe-l3", "status": "active", "manager_role": None},
    # 15 — Petra Nowak — Frontend L2 Middle
    {"division_key": "eng-frontend", "position_key": "p-fe-l2", "status": "active", "manager_role": None},
    # 16 — Quinn O'Connor — Frontend L2 Middle (on_leave)
    {"division_key": "eng-frontend", "position_key": "p-fe-l2", "status": "on_leave", "manager_role": None},
    # 17 — Rafael Costa — Frontend L1 Junior (recent hire)
    {"division_key": "eng-frontend", "position_key": "p-fe-l1", "status": "active", "manager_role": None, "recent_hire": True},
    # 18 — Sara Lindberg — Senior PM (division_head Product)
    {"division_key": "product", "position_key": "p-pm-senior", "status": "active", "manager_role": "division_head"},
    # 19 — Theo Bauer — Senior PM
    {"division_key": "product", "position_key": "p-pm-senior", "status": "active", "manager_role": "division_deputy"},
    # 20 — Uma Patel — PM
    {"division_key": "product", "position_key": "p-pm-mid", "status": "active", "manager_role": None},
    # 21 — Victor Dubois — PM
    {"division_key": "product", "position_key": "p-pm-mid", "status": "active", "manager_role": None},
    # 22 — Wilma Hansen — PM
    {"division_key": "product", "position_key": "p-pm-mid", "status": "active", "manager_role": None},
    # 23 — Xavier Romero — PM
    {"division_key": "product", "position_key": "p-pm-mid", "status": "active", "manager_role": None},
    # 24 — Yara Saito — Senior Product Designer (division_head Design)
    {"division_key": "design", "position_key": "p-designer-senior", "status": "active", "manager_role": "division_head"},
    # 25 — Zoe Caron — Senior Product Designer
    {"division_key": "design", "position_key": "p-designer-senior", "status": "active", "manager_role": "division_deputy"},
    # 26 — Aaron Park — Product Designer
    {"division_key": "design", "position_key": "p-designer-mid", "status": "active", "manager_role": None},
    # 27 — Bianca Rossi — Product Designer
    {"division_key": "design", "position_key": "p-designer-mid", "status": "active", "manager_role": None},
    # 28 — Cameron Brown — People Partner (division_head People)
    {"division_key": "people", "position_key": "p-people-partner", "status": "active", "manager_role": "division_head"},
    # 29 — Diana Ovsyannikova — People Partner
    {"division_key": "people", "position_key": "p-people-partner", "status": "active", "manager_role": "division_deputy"},
    # 30 — Emil Krause — Recruiter
    {"division_key": "people", "position_key": "p-recruiter", "status": "active", "manager_role": None},
    # 31 — Farah Khoury — Recruiter
    {"division_key": "people", "position_key": "p-recruiter", "status": "active", "manager_role": None},
    # 32 — Greg Murphy — Recruiter (inactive — former teammate)
    {"division_key": "people", "position_key": "p-recruiter", "status": "inactive", "manager_role": None},
    # 33 — Hannah Adler — Account Executive (division_head GTM)
    {"division_key": "gtm", "position_key": "p-ae", "status": "active", "manager_role": "division_head"},
    # 34 — Igor Sokolov — Account Executive
    {"division_key": "gtm", "position_key": "p-ae", "status": "active", "manager_role": "division_deputy"},
    # 35 — Jana Vargas — Account Executive
    {"division_key": "gtm", "position_key": "p-ae", "status": "active", "manager_role": None},
    # 36 — Kira Tanaka — SDR (recent hire)
    {"division_key": "gtm", "position_key": "p-sdr", "status": "active", "manager_role": None, "recent_hire": True},
    # 37 — Liam O'Sullivan — SDR
    {"division_key": "gtm", "position_key": "p-sdr", "status": "active", "manager_role": None},
    # 38 — Mira Bianchi — SDR
    {"division_key": "gtm", "position_key": "p-sdr", "status": "active", "manager_role": None},
    # 39 — Noah Larsson — SDR
    {"division_key": "gtm", "position_key": "p-sdr", "status": "active", "manager_role": None},
]


# Deterministic hire-date spacing (in days back from "today"). Rows
# flagged ``recent_hire`` land inside the last 90 days; the rest stretch
# out over five years so the tenure column on /employees shows a
# believable spread. EmployeeUpdate.status only accepts active /
# inactive / on_leave / terminated, so the seed keeps the three
# freshly-onboarded cards on ``status=active`` and uses ``recent_hire``
# in the assignment dict purely as a hire-date hint.

def hire_days_back(idx: int, status: str, recent_hire: bool = False) -> int:
    if recent_hire:
        # Recent hires spread over the last 90 days.
        return 30 + (idx * 17) % 60
    if status == "inactive":
        # Inactive rows look like multi-year tenure that ended.
        return 365 * 3 + (idx * 11) % 180
    # Linear-ish spread from ~6 months to ~5 years.
    return 180 + (idx * 47) % 1640


EMPLOYEE_EMAIL_DOMAIN = "demo.example.com"


def email_for(first: str, last: str) -> str:
    """Build a deterministic, unique email per name pool entry."""
    return (
        f"{first}.{last}".replace("'", "").replace(" ", "").lower()
        + f"@{EMPLOYEE_EMAIL_DOMAIN}"
    )
