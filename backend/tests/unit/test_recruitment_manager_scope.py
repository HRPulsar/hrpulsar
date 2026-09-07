"""HRP-629: a division head reads hiring for their own division only.

HRP-615 stopped rank-and-file employees from reading candidate PII, but
left ``manager`` reading the whole workspace — and ``company.service``
hands that role to every division head automatically. Hiring for a
neighbouring department is now closed: a vacancy is visible when it sits
in the caller's managed subtree, names them as hiring manager, or was
created by them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
    CandidateVacancy,
    ConsolidatedReport,
    Interview,
    Vacancy,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _user(db: AsyncSession, tenant, code: str) -> User:
    result = await db.execute(select(Role).where(Role.code == code))
    role = result.scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    u = User(
        email=f"{code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name=code,
        last_name="X",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


def _headers(u: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(u.id), str(u.tenant_id))}"
    }


@pytest_asyncio.fixture
async def hiring(db: AsyncSession, tenant):
    """Two divisions, one vacancy each, one candidate each.

    ``mine`` is managed by the manager; ``theirs`` is a neighbouring
    department they have nothing to do with.
    """
    mgr_user = await _user(db, tenant, "manager")
    rec_user = await _user(db, tenant, "recruiter")

    mgr_emp = Employee(
        user_id=mgr_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
    )
    db.add(mgr_emp)
    await db.commit()
    await db.refresh(mgr_emp)

    mine = Division(
        tenant_id=tenant.id, name=f"Mine {uuid.uuid4().hex[:4]}", manager_id=mgr_emp.id
    )
    theirs = Division(tenant_id=tenant.id, name=f"Theirs {uuid.uuid4().hex[:4]}")
    db.add_all([mine, theirs])
    await db.commit()
    await db.refresh(mine)
    await db.refresh(theirs)

    out: dict = {"mgr_user": mgr_user, "rec_user": rec_user, "mgr_emp": mgr_emp}
    for key, division in (("mine", mine), ("theirs", theirs)):
        vac = Vacancy(
            tenant_id=tenant.id,
            title=f"{key} role {uuid.uuid4().hex[:4]}",
            division_id=division.id,
            owner_id=rec_user.id,
        )
        db.add(vac)
        await db.commit()
        await db.refresh(vac)
        cand = Candidate(
            tenant_id=tenant.id,
            full_name=f"{key} candidate",
            email=f"{key}-{uuid.uuid4().hex[:6]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        cv = CandidateVacancy(
            tenant_id=tenant.id, candidate_id=cand.id, vacancy_id=vac.id
        )
        db.add(cv)
        await db.commit()
        await db.refresh(cv)
        out[f"{key}_vacancy"] = vac
        out[f"{key}_candidate"] = cand
        out[f"{key}_cv"] = cv
    return out


class TestManagerHiringScope:
    async def test_manager_reads_own_division_vacancy(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["mgr_user"])
        for path in (
            f"/api/recruitment/vacancies/{hiring['mine_vacancy'].id}",
            f"/api/recruitment/vacancies/{hiring['mine_vacancy'].id}/candidates",
            f"/api/recruitment/candidates/{hiring['mine_candidate'].id}/resumes",
            f"/api/recruitment/candidate-vacancies/{hiring['mine_cv'].id}",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 200, f"{path} -> {resp.status_code} {resp.text}"

    async def test_manager_refused_on_a_neighbouring_division(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["mgr_user"])
        for path in (
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}",
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}/candidates",
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}/reports",
            f"/api/recruitment/candidates/{hiring['theirs_candidate'].id}",
            f"/api/recruitment/candidates/{hiring['theirs_candidate'].id}/resumes",
            f"/api/recruitment/candidates/{hiring['theirs_candidate'].id}/card",
            f"/api/recruitment/candidate-vacancies/{hiring['theirs_cv'].id}",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 403, f"{path} -> {resp.status_code}"

    async def test_lists_only_show_the_managed_division(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["mgr_user"])
        vacancies = (await client.get("/api/recruitment/vacancies", headers=h)).json()
        assert [v["id"] for v in vacancies["items"]] == [str(hiring["mine_vacancy"].id)]
        assert vacancies["total"] == 1

        candidates = (await client.get("/api/recruitment/candidates", headers=h)).json()
        assert [c["id"] for c in candidates["items"]] == [
            str(hiring["mine_candidate"].id)
        ]
        assert candidates["total"] == 1

    async def test_recruiter_still_sees_the_whole_workspace(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["rec_user"])
        resp = await client.get(
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}", headers=h
        )
        assert resp.status_code == 200
        listing = (await client.get("/api/recruitment/vacancies", headers=h)).json()
        ids = {v["id"] for v in listing["items"]}
        assert {str(hiring["mine_vacancy"].id), str(hiring["theirs_vacancy"].id)} <= ids

    async def test_named_hiring_manager_reaches_another_division(
        self, db: AsyncSession, client: AsyncClient, hiring
    ):
        theirs = hiring["theirs_vacancy"]
        theirs.hiring_manager_id = hiring["mgr_user"].id
        await db.commit()
        resp = await client.get(
            f"/api/recruitment/vacancies/{theirs.id}",
            headers=_headers(hiring["mgr_user"]),
        )
        assert resp.status_code == 200

    async def test_creator_keeps_a_vacancy_with_no_division(
        self, db: AsyncSession, client: AsyncClient, tenant, hiring
    ):
        orphan = Vacancy(
            tenant_id=tenant.id,
            title=f"Orphan {uuid.uuid4().hex[:4]}",
            owner_id=hiring["mgr_user"].id,
        )
        db.add(orphan)
        await db.commit()
        await db.refresh(orphan)
        resp = await client.get(
            f"/api/recruitment/vacancies/{orphan.id}",
            headers=_headers(hiring["mgr_user"]),
        )
        assert resp.status_code == 200

    async def test_hiring_manager_is_scoped_like_a_manager(
        self, db: AsyncSession, client: AsyncClient, tenant, hiring
    ):
        """The role is not grantable yet (HRP-618), but the rule is the same."""
        hm = await _user(db, tenant, "hiring_manager")
        h = _headers(hm)
        theirs = await client.get(
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}", headers=h
        )
        assert theirs.status_code == 403

        hiring["theirs_vacancy"].hiring_manager_id = hm.id
        await db.commit()
        named = await client.get(
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}", headers=h
        )
        assert named.status_code == 200

    async def test_resume_interview_and_report_follow_the_vacancy(
        self, db: AsyncSession, client: AsyncClient, tenant, hiring
    ):
        """The three heaviest payloads, one per resolver that had no test."""
        resume = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=hiring["theirs_candidate"].id,
            file_type="resume",
            original_filename="cv.pdf",
            mime_type="application/pdf",
            file_size=1024,
        )
        interview = Interview(
            tenant_id=tenant.id, candidate_vacancy_id=hiring["theirs_cv"].id
        )
        report = ConsolidatedReport(
            tenant_id=tenant.id, vacancy_id=hiring["theirs_vacancy"].id
        )
        db.add_all([resume, interview, report])
        await db.commit()
        for row in (resume, interview, report):
            await db.refresh(row)

        h = _headers(hiring["mgr_user"])
        for path in (
            f"/api/recruitment/resumes/{resume.id}/download",
            f"/api/recruitment/interviews/{interview.id}",
            f"/api/recruitment/interviews/{interview.id}/media-url",
            f"/api/recruitment/reports/{report.id}",
            f"/api/recruitment/reports/{report.id}/preview",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 403, f"{path} -> {resp.status_code}"

        # ...and the recruiter, who is unrestricted, is not blocked by them.
        rec = _headers(hiring["rec_user"])
        resp = await client.get(f"/api/recruitment/reports/{report.id}", headers=rec)
        assert resp.status_code != 403

    async def test_narrowing_a_list_to_a_foreign_vacancy_is_refused(
        self, client: AsyncClient, hiring
    ):
        """``?vacancy_id=`` is a way in too — the roster it filters to is
        exactly what the scope hides."""
        h = _headers(hiring["mgr_user"])
        for path in (
            f"/api/recruitment/candidates?vacancy_id={hiring['theirs_vacancy'].id}",
            f"/api/recruitment/reports?vacancy_id={hiring['theirs_vacancy'].id}",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 403, f"{path} -> {resp.status_code}"

        own = await client.get(
            f"/api/recruitment/candidates?vacancy_id={hiring['mine_vacancy'].id}",
            headers=h,
        )
        assert own.status_code == 200

    async def test_an_application_to_another_division_stays_hidden(
        self, db: AsyncSession, client: AsyncClient, hiring
    ):
        """One candidate, two applications — the manager sees only theirs."""
        extra = CandidateVacancy(
            tenant_id=hiring["mine_vacancy"].tenant_id,
            candidate_id=hiring["mine_candidate"].id,
            vacancy_id=hiring["theirs_vacancy"].id,
        )
        db.add(extra)
        await db.commit()

        h = _headers(hiring["mgr_user"])
        card = (
            await client.get(
                f"/api/recruitment/candidates/{hiring['mine_candidate'].id}/card",
                headers=h,
            )
        ).json()
        assert [a["vacancy_id"] for a in card["vacancy_applications"]] == [
            str(hiring["mine_vacancy"].id)
        ]

        links = (
            await client.get(
                f"/api/recruitment/candidates/{hiring['mine_candidate'].id}/vacancies",
                headers=h,
            )
        ).json()
        assert [link["vacancy_id"] for link in links] == [
            str(hiring["mine_vacancy"].id)
        ]


class TestManagerReadsTheAssessmentMatrix:
    """HRP-694: the matrix explains the card a manager already reads.

    The candidate card and its divergence badge are open to
    ``RECRUITMENT_VIEWER_ROLES``, but the matrix behind them used to be
    ``admin / recruiter / hr / hiring_manager`` — so the Manager vs AI
    block rendered empty for a division head. Reads are level with the
    card now; writing a score is still recruiter work.
    """

    async def test_manager_reads_the_matrix_of_its_own_vacancy(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["mgr_user"])
        vacancy_id = hiring["mine_vacancy"].id
        for path in (
            f"/api/recruitment/vacancies/{vacancy_id}/assessment-matrix",
            f"/api/recruitment/vacancies/{vacancy_id}/assessment-matrix/export.xlsx",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 200, f"{path} -> {resp.status_code} {resp.text}"

        # The cell drill-down is a subset of one matrix cell — same gate.
        cell = await client.get(
            f"/api/recruitment/vacancies/{vacancy_id}/assessment-matrix"
            f"/cells/{hiring['mine_cv'].id}/{uuid.uuid4()}",
            headers=h,
        )
        assert cell.status_code != 403, cell.text

    async def test_matrix_of_a_neighbouring_division_stays_refused(
        self, client: AsyncClient, hiring
    ):
        """Role opens the door, scope still says which room."""
        resp = await client.get(
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}"
            "/assessment-matrix",
            headers=_headers(hiring["mgr_user"]),
        )
        assert resp.status_code == 403

    async def test_manager_still_cannot_write_a_score(
        self, client: AsyncClient, hiring
    ):
        """The write endpoints behind the same matrix are untouched."""
        h = _headers(hiring["mgr_user"])
        cv_id = hiring["mine_cv"].id
        competence_id = uuid.uuid4()

        created = await client.post(
            f"/api/recruitment/candidate-vacancies/{cv_id}/assessments",
            headers=h,
            json={"competence_id": str(competence_id), "score": 4},
        )
        assert created.status_code == 403, created.text

        updated = await client.patch(
            f"/api/recruitment/assessments/{uuid.uuid4()}",
            headers=h,
            json={"score": 4},
        )
        assert updated.status_code == 403, updated.text

        reverted = await client.post(
            f"/api/recruitment/candidate-vacancies/{cv_id}/assessments"
            f"/{competence_id}/evaluators/{uuid.uuid4()}/revert",
            headers=h,
            json={"audit_event_id": str(uuid.uuid4())},
        )
        assert reverted.status_code == 403, reverted.text


class TestInternalShortlistIsScopedByTheVacancy:
    """HRP-703: the shortlist is scoped by the requisition, not the viewer.

    The decision on HRP-678: internal matching is a legitimate-interest
    read the employer already makes for its own staffing, so whoever may
    open a vacancy sees its whole internal shortlist. The HRP-149 profile
    scope that narrows the talent market's directory browsing is
    deliberately NOT applied here -- it protects looking colleagues up,
    not a requisition's own match results, and the recruiting roles that
    reach this endpoint are not talent-market viewers at all.

    Privacy is controlled per requisition instead: ``internal_search_allowed``
    decides whether anyone is matched, ``vacancy_scope`` decides who may
    open the vacancy. Reversing the call means filtering ``items`` through
    ``can_view_profile``; this test is what would go red.
    """

    async def _employee(self, db: AsyncSession, tenant, division_id, name: str):
        u = User(
            email=f"tm-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("x"),
            first_name=name,
            last_name="Match",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        emp = Employee(
            user_id=u.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 1),
            division_id=division_id,
            position_title="Engineer",
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)
        return emp

    async def test_manager_sees_matches_from_every_division(
        self, db: AsyncSession, client: AsyncClient, tenant, hiring
    ):
        from app.modules.talent_market.models import TalentCandidate, TalentCard

        vacancy = hiring["theirs_vacancy"]
        # The manager manages "mine" and is admitted to this neighbouring
        # requisition by being named its hiring manager -- the only gate.
        vacancy.hiring_manager_id = hiring["mgr_user"].id

        card = TalentCard(
            tenant_id=tenant.id,
            author_id=hiring["rec_user"].id,
            title="Twin",
            card_type="vacancy",
            start_date=date.today(),
        )
        db.add(card)
        await db.commit()
        await db.refresh(card)
        vacancy.talent_card_id = card.id
        await db.commit()

        mine_emp = await self._employee(
            db, tenant, hiring["mine_vacancy"].division_id, "Insider"
        )
        theirs_emp = await self._employee(db, tenant, vacancy.division_id, "Outsider")
        db.add_all(
            [
                TalentCandidate(
                    card_id=card.id,
                    employee_id=mine_emp.id,
                    status="matched",
                    match_score=80,
                ),
                TalentCandidate(
                    card_id=card.id,
                    employee_id=theirs_emp.id,
                    status="matched",
                    match_score=60,
                ),
            ]
        )
        await db.commit()

        resp = await client.get(
            f"/api/recruitment/vacancies/{vacancy.id}/internal-candidates",
            headers=_headers(hiring["mgr_user"]),
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert {i["employee_id"] for i in payload["items"]} == {
            str(mine_emp.id),
            str(theirs_emp.id),
        }
        # Names and scores come through for both, including the employee
        # from a division this manager does not manage.
        by_id = {i["employee_id"]: i for i in payload["items"]}
        assert by_id[str(theirs_emp.id)]["employee_name"] == "Outsider Match"
        assert by_id[str(theirs_emp.id)]["match_score"] == 60

    async def test_a_manager_outside_the_vacancy_is_still_refused(
        self, client: AsyncClient, hiring
    ):
        """The gate that does apply: no access to the vacancy, no shortlist."""
        resp = await client.get(
            f"/api/recruitment/vacancies/{hiring['theirs_vacancy'].id}"
            "/internal-candidates",
            headers=_headers(hiring["mgr_user"]),
        )
        assert resp.status_code == 403, resp.text
class TestManagerReadsTheVersionsPanelAndQuestions:
    """HRP-701: the two GETs HRP-694 left on the narrow role tuple.

    A manager opens the fullscreen canvas (matrix and canvas both admit
    them since HRP-694), but the Versions panel and the Questions tab were
    still ``admin / recruiter / hr / hiring_manager`` — both swallow a 403
    into an empty state, so the panels simply rendered blank.
    """

    async def test_manager_reads_both_panels_of_its_own_vacancy(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["mgr_user"])
        vacancy_id = hiring["mine_vacancy"].id
        for path in (
            f"/api/recruitment/vacancies/{vacancy_id}/assessment-history",
            f"/api/recruitment/vacancies/{vacancy_id}/question-sets",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 200, f"{path} -> {resp.status_code} {resp.text}"

    async def test_a_neighbouring_division_stays_refused(
        self, client: AsyncClient, hiring
    ):
        """Role opens the door, ``vacancy_scope`` still says which room."""
        h = _headers(hiring["mgr_user"])
        vacancy_id = hiring["theirs_vacancy"].id
        for path in (
            f"/api/recruitment/vacancies/{vacancy_id}/assessment-history",
            f"/api/recruitment/vacancies/{vacancy_id}/question-sets",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 403, f"{path} -> {resp.status_code}"

    async def test_employee_is_still_refused(
        self, db: AsyncSession, client: AsyncClient, tenant, hiring
    ):
        """Widening stopped at the recruitment roles — not company-wide."""
        h = _headers(await _user(db, tenant, "employee"))
        vacancy_id = hiring["mine_vacancy"].id
        for path in (
            f"/api/recruitment/vacancies/{vacancy_id}/assessment-history",
            f"/api/recruitment/vacancies/{vacancy_id}/question-sets",
        ):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 403, f"{path} -> {resp.status_code}"
