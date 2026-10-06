"""HRP-1019: whoever opens an interview reads its interviewers' names.

The page used to resolve them from the interviewer picker's list, which
is an edit control (``manage``) - a caller the section opens to ``view``
saw the Interviewers field empty. The interview now carries each
interviewer's name and position, as the company directory shows them.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest_asyncio
from app.modules.company.models import Division, Tenant
from app.modules.employee.models import Employee
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
    InterviewInterviewer,
    Vacancy,
)

from tests.unit.test_recruitment_manager_scope import _headers, _user


@pytest_asyncio.fixture
async def panel(db, tenant):
    """A vacancy of ``head``'s division with ``hm`` as its hiring manager,
    and an interview of ``olga`` (the legacy primary, no employee row),
    ``ivan`` (a staff engineer) and a user of another tenant."""
    head = await _user(db, tenant, "manager")
    hm = await _user(db, tenant, "hiring_manager")
    olga = await _user(db, tenant, "employee")
    ivan = await _user(db, tenant, "employee")
    head_emp = Employee(user_id=head.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    ivan_emp = Employee(
        user_id=ivan.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1), position_title="Staff Engineer"
    )
    db.add_all([head_emp, ivan_emp])
    await db.commit()
    division = Division(tenant_id=tenant.id, name=f"Div {uuid.uuid4().hex[:4]}", manager_id=head_emp.id)
    db.add(division)
    await db.commit()
    vacancy = Vacancy(tenant_id=tenant.id, title="Engineer", division_id=division.id, hiring_manager_id=hm.id)
    cand = Candidate(tenant_id=tenant.id, full_name="Ada", email=f"ada-{uuid.uuid4().hex[:6]}@example.com")
    db.add_all([vacancy, cand])
    await db.commit()
    cv = CandidateVacancy(tenant_id=tenant.id, candidate_id=cand.id, vacancy_id=vacancy.id)
    db.add(cv)
    await db.commit()
    other_tenant = Tenant(name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}")
    db.add(other_tenant)
    await db.commit()
    foreign = await _user(db, other_tenant, "employee")
    interview = Interview(tenant_id=tenant.id, candidate_vacancy_id=cv.id, interviewer_id=olga.id)
    db.add(interview)
    await db.commit()
    db.add_all([InterviewInterviewer(tenant_id=tenant.id, interview_id=interview.id, user_id=u.id) for u in (ivan, foreign)])
    await db.commit()
    return {"head": head, "hm": hm, "olga": olga, "ivan": ivan, "foreign": foreign, "cv": cv, "interview": interview}


def _assert_names(body: dict, panel: dict) -> None:
    foreign = str(panel["foreign"].id)
    # The ids stay as they were - the edit form and e2e read them.
    assert body["interviewer_ids"][0] == str(panel["olga"].id)
    assert foreign in body["interviewer_ids"]
    assert [b["id"] for b in body["interviewers"]] == [i for i in body["interviewer_ids"] if i != foreign]
    by_id = {b["id"]: b for b in body["interviewers"]}
    assert by_id[str(panel["olga"].id)] == {
        "id": str(panel["olga"].id),
        "full_name": "employee X",
        "position_title": None,
    }
    assert by_id[str(panel["ivan"].id)]["position_title"] == "Staff Engineer"


async def test_view_manage_and_the_hiring_manager_read_the_names(client, db, tenant, panel):
    one = f"/api/recruitment/interviews/{panel['interview'].id}"
    listed = f"/api/recruitment/candidate-vacancies/{panel['cv'].id}/interviews"
    recruiter = await _user(db, tenant, "recruiter")
    for who in (panel["head"], panel["hm"], recruiter):
        h = _headers(who)
        r = await client.get(one, headers=h)
        assert r.status_code == 200, (who.first_name, r.text)
        _assert_names(r.json(), panel)
        r = await client.get(listed, headers=h)
        assert r.status_code == 200, (who.first_name, r.text)
        (row,) = r.json()
        _assert_names(row, panel)
    # The picker's list stays the editors' - the names do not come from it.
    picker = f"/api/recruitment/interviewers?candidate_vacancy_id={panel['cv'].id}"
    assert (await client.get(picker, headers=_headers(panel["head"]))).status_code == 403
