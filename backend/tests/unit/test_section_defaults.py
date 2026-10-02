"""HRP-820: the default matrix is today's behaviour, pinned."""

from app.core.sections import ROLE_CODES, SECTIONS_BY_CODE

# docs/core/docs/rbac.md, "Section access". Columns: admin, hr, manager,
# recruiter, hiring_manager, employee.
EXPECTED = {
    "employees": ("manage", "view", "manage", "view", "view", "view"),
    "company": ("manage", "view", "manage", "view", "view", "view"),
    "assessments": ("manage", "view", "manage", "view", "view", "view"),
    "development": ("manage", "view", "manage", "view", "view", "view"),
    "exams": ("manage", "view", "manage", "view", "view", "view"),
    "competences": ("manage", "manage", "view", "view", "view", "view"),
    "coverage": ("manage", "manage", "view", "view", "view", "view"),
    "talent-market": ("manage", "view", "manage", "view", "view", "view"),
    "recruitment": ("manage", "manage", "view", "manage", "view", "none"),
    "analytics": ("manage", "manage", "manage", "none", "none", "none"),
    "dictionaries": ("manage", "view", "view", "view", "view", "view"),
    "import": ("manage", "none", "none", "none", "none", "none"),
    "invitations": ("manage", "manage", "manage", "none", "none", "none"),
    "roles": ("manage", "none", "none", "none", "none", "none"),
    "ai-settings": ("manage", "none", "none", "none", "none", "none"),
}


def test_defaults_match_the_documented_matrix():
    assert list(EXPECTED) == list(SECTIONS_BY_CODE)
    for code, row in EXPECTED.items():
        assert SECTIONS_BY_CODE[code].defaults == dict(zip(ROLE_CODES, row, strict=True)), code
