"""HRP-630: writing into a neighbouring division's hiring is refused too.

HRP-629 closed *reading* hiring outside the caller's own division, but
left 24 mutating routes taking ``manager`` / ``hiring_manager`` without
asking whose vacancy it is: candidate stage changes, assessment rounds,
questions, evaluator invites. Read closed, write open is the worst of
the two states, so every one of them now carries the matching scope
guard.

Each route is driven twice. Against the neighbouring division the guard
must refuse — that is the bug this file reproduces. Against the
manager's own division the assertion is only that the guard did *not*
refuse: what the handler then answers (201, 409, 422 for a stub body) is
that route's own business and not what is under test here. That
weaker-looking assertion is exactly what catches a guard pointed at the
wrong table — ``assert_in_scope`` is fail-closed, so a resolver that
looks the id up in the wrong model refuses the owner too. See
``PATCH /recruitment/assessments/{assessment_id}``, which is keyed like
the manager-assessment sheets but stores a ``HumanAssessment``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.recruitment.manager_assessment_models import (
    AssessmentRound,
    RecruitmentAssessment,
)
from app.modules.recruitment.models import (
    AssessmentInvite,
    Candidate,
    CandidateQuestion,
    CandidateVacancy,
    HumanAssessment,
    Question,
    QuestionSet,
    Vacancy,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _user(db: AsyncSession, tenant, *codes: str) -> User:
    """A user carrying every role in ``codes``.

    The hiring-manager routes and the manager-assessment routes have
    disjoint ``require_role`` sets, and ``require_role`` answers 403 as
    well — one caller holding both roles keeps that 403 out of the way,
    so a refusal in this file can only have come from the scope guard.
    """
    u = User(
        email=f"{codes[0]}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name=codes[0],
        last_name="X",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    for code in codes:
        role = (
            (await db.execute(select(Role).where(Role.code == code))).scalars().first()
        )
        if role is None:
            role = Role(name=code.title(), code=code, is_system=True)
            db.add(role)
            await db.commit()
            await db.refresh(role)
        await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    return (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == u.id)
        )
    ).scalar_one()


def _headers(u: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(u.id), str(u.tenant_id))}"
    }


def _refused(resp) -> bool:
    """True when the recruitment scope guard turned the call away."""
    return resp.status_code == 403 and "outside_recruitment_scope" in resp.text


@pytest_asyncio.fixture
async def hiring(db: AsyncSession, tenant):
    """Two divisions, and one of every mutable hiring resource in each.

    ``mine`` is managed by ``mgr_user``; ``theirs`` is the neighbouring
    department. Both vacancies are owned by the recruiter and name no
    hiring manager, so the only way into ``mine`` is the division
    subtree.
    """
    mgr_user = await _user(db, tenant, "manager", "hiring_manager")
    rec_user = await _user(db, tenant, "recruiter")
    admin_user = await _user(db, tenant, "admin")

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

    out: dict = {
        "mgr_user": mgr_user,
        "rec_user": rec_user,
        "admin_user": admin_user,
    }
    for key, division in (("mine", mine), ("theirs", theirs)):
        vac = Vacancy(
            tenant_id=tenant.id,
            title=f"{key} role {uuid.uuid4().hex[:4]}",
            division_id=division.id,
            owner_id=rec_user.id,
        )
        cand = Candidate(
            tenant_id=tenant.id,
            full_name=f"{key} candidate",
            email=f"{key}-{uuid.uuid4().hex[:6]}@example.com",
        )
        db.add_all([vac, cand])
        await db.commit()
        await db.refresh(vac)
        await db.refresh(cand)

        cv = CandidateVacancy(
            tenant_id=tenant.id, candidate_id=cand.id, vacancy_id=vac.id
        )
        cq = CandidateQuestion(
            tenant_id=tenant.id,
            candidate_id=cand.id,
            vacancy_id=vac.id,
            question_text="Tell me about a rollback you owned",
            good_answer="g",
            acceptable_answer="a",
            poor_answer="p",
        )
        db.add_all([cv, cq])
        await db.commit()
        await db.refresh(cv)
        await db.refresh(cq)

        qset = QuestionSet(
            tenant_id=tenant.id, candidate_vacancy_id=cv.id, name=f"{key} set"
        )
        human = HumanAssessment(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv.id,
            competence_id=uuid.uuid4(),
            evaluator_id=rec_user.id,
            score=3.0,
        )
        rnd = AssessmentRound(
            tenant_id=tenant.id, candidate_vacancy_id=cv.id, type="pre_interview"
        )
        # Seeded already revoked: revoke/resend/extend then answer from
        # the invite's own state instead of mailing anyone, and the only
        # thing left to observe is whether the guard let the call in.
        invite = AssessmentInvite(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv.id,
            token=uuid.uuid4().hex,
            email=f"eval-{uuid.uuid4().hex[:6]}@example.com",
            status="revoked",
            revoked_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add_all([qset, human, rnd, invite])
        await db.commit()
        for row in (qset, human, rnd, invite):
            await db.refresh(row)

        question = Question(
            tenant_id=tenant.id, question_set_id=qset.id, text=f"{key} question"
        )
        sheet = RecruitmentAssessment(
            tenant_id=tenant.id, round_id=rnd.id, evaluator_user_id=rec_user.id
        )
        db.add_all([question, sheet])
        await db.commit()
        await db.refresh(question)
        await db.refresh(sheet)

        out[key] = {
            "vacancy": vac.id,
            "candidate": cand.id,
            "cv": cv.id,
            "cq": cq.id,
            "qset": qset.id,
            "question": question.id,
            "human": human.id,
            "round": rnd.id,
            "sheet": sheet.id,
            "invite": invite.id,
        }
    return out


def _routes(s: dict) -> list[tuple[str, str, dict | None]]:
    """The 24 mutating routes of HRP-630, keyed into one side's resources.

    Bodies are deliberately stubs: the guard runs as a dependency, ahead
    of body validation, so an unscoped caller is refused before the
    payload is ever looked at.
    """
    competence, other = uuid.uuid4(), uuid.uuid4()
    return [
        # -- gated on hiring_manager (14) ------------------------------
        (
            "POST",
            f"/api/recruitment/candidates/{s['candidate']}"
            f"/vacancies/{s['vacancy']}/questions",
            {},
        ),
        ("PUT", f"/api/recruitment/questions/{s['cq']}", {}),
        (
            "POST",
            f"/api/recruitment/candidates/{s['candidate']}"
            f"/vacancies/{s['vacancy']}/questions/pdf",
            {},
        ),
        ("PATCH", f"/api/recruitment/candidate-vacancies/{s['cv']}/status", {}),
        ("PATCH", f"/api/recruitment/candidate-vacancies/{s['cv']}", {}),
        ("POST", f"/api/recruitment/candidate-vacancies/{s['cv']}/assessments", {}),
        ("PATCH", f"/api/recruitment/assessments/{s['human']}", {}),
        (
            "POST",
            f"/api/recruitment/candidate-vacancies/{s['cv']}/assessments"
            f"/{competence}/evaluators/{other}/revert",
            {},
        ),
        ("POST", f"/api/v1/candidate-vacancies/{s['cv']}/question-sets", {}),
        ("POST", f"/api/v1/question-sets/{s['qset']}/questions", {}),
        ("PATCH", f"/api/v1/questions/{s['question']}", {}),
        ("POST", f"/api/v1/question-sets/{s['qset']}/export-pdf", {}),
        # Deletes run last on their resource so the routes above still
        # have a row to aim at.
        ("DELETE", f"/api/recruitment/questions/{s['cq']}", None),
        ("DELETE", f"/api/v1/questions/{s['question']}", None),
        # -- gated on manager (10) -------------------------------------
        ("POST", f"/api/v1/candidate-vacancies/{s['cv']}/assessment-rounds", {}),
        ("PATCH", f"/api/v1/assessment-rounds/{s['round']}", {}),
        ("POST", f"/api/v1/assessment-rounds/{s['round']}/evaluators", {}),
        (
            "PATCH",
            f"/api/v1/assessments/{s['sheet']}/competence-scores/{competence}",
            {},
        ),
        ("PATCH", f"/api/v1/assessments/{s['sheet']}/indicator-scores/{other}", {}),
        ("POST", f"/api/v1/assessments/{s['sheet']}/submit", {}),
        (
            "POST",
            f"/api/v1/candidate-vacancies/{s['cv']}/manager-assessment-invites",
            {"invitees": []},
        ),
        ("POST", f"/api/v1/manager-assessment-invites/{s['invite']}/revoke", {}),
        ("POST", f"/api/v1/manager-assessment-invites/{s['invite']}/resend", {}),
        ("POST", f"/api/v1/manager-assessment-invites/{s['invite']}/extend", {}),
    ]


async def _call(client: AsyncClient, method, path, body, headers):
    if body is None:
        return await client.request(method, path, headers=headers)
    return await client.request(method, path, json=body, headers=headers)


class TestMutationScope:
    async def test_all_twenty_four_routes_are_covered(self, hiring):
        """The count the ticket is written around; a route dropped from
        the table would otherwise go untested in silence."""
        assert len(_routes(hiring["mine"])) == 24

    async def test_writing_into_a_neighbouring_division_is_refused(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["mgr_user"])
        for method, path, body in _routes(hiring["theirs"]):
            resp = await _call(client, method, path, body, h)
            assert _refused(resp), f"{method} {path} -> {resp.status_code} {resp.text}"

    async def test_the_managers_own_division_still_goes_through(
        self, client: AsyncClient, hiring
    ):
        h = _headers(hiring["mgr_user"])
        for method, path, body in _routes(hiring["mine"]):
            resp = await _call(client, method, path, body, h)
            assert not _refused(resp), f"{method} {path} -> {resp.text}"

    async def test_admin_is_not_scoped(self, client: AsyncClient, hiring):
        """``admin`` is in ``FULL_RECRUITMENT_ROLES`` — the whole tenant
        stays reachable, including the division nobody made them head of."""
        h = _headers(hiring["admin_user"])
        for method, path, body in _routes(hiring["theirs"]):
            resp = await _call(client, method, path, body, h)
            assert not _refused(resp), f"{method} {path} -> {resp.text}"

    async def test_a_named_hiring_manager_reaches_the_other_division(
        self, db: AsyncSession, client: AsyncClient, hiring
    ):
        """Scope is the vacancy's, not the division's alone: naming the
        caller on the neighbouring vacancy opens its mutations too."""
        vac = await db.get(Vacancy, hiring["theirs"]["vacancy"])
        assert vac is not None
        vac.hiring_manager_id = hiring["mgr_user"].id
        await db.commit()
        h = _headers(hiring["mgr_user"])
        for method, path, body in _routes(hiring["theirs"]):
            resp = await _call(client, method, path, body, h)
            assert not _refused(resp), f"{method} {path} -> {resp.text}"
