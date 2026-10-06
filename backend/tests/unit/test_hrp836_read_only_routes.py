"""HRP-836 review: every mutating hiring route honours the vacancy status.

The read-only check used to live in a handful of routers; the rest of the
writes (profile, competences, attachments, funnel, candidate attach and
stage moves, questions, manager sheets, interview upload) went through on
a paused / closed / cancelled vacancy. The guard now sits in the services,
so each route below has to answer ``vacancy_status_read_only`` for every
status that freezes its surface.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError
from app.modules.recruitment import service, vacancy_service
from app.modules.recruitment.common import vacancy_locks
from app.modules.recruitment.manager_assessment_models import (
    AssessmentRound,
    RecruitmentAssessment,
)
from app.modules.recruitment.models import (
    CandidateQuestion,
    CandidateVacancy,
    Question,
    QuestionSet,
    Vacancy,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    CandidateVacancyPatch,
    CandidateVacancyStatusUpdate,
    InterviewCreate,
    VacancyCloseData,
    VacancyCreate,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(db: AsyncSession, tenant, user) -> dict:
    await vacancy_service.seed_default_recruitment_stages(db, tenant.id)
    v = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    vacancy_id = uuid.UUID(str(v["id"]))
    cand = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="C", last_name="D", email=f"{uuid.uuid4().hex[:8]}@x.com"
        ),
    )
    candidate_id = uuid.UUID(str(cand["id"]))
    spare = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="S", last_name="P", email=f"{uuid.uuid4().hex[:8]}@x.com"
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(candidate_id=candidate_id, vacancy_id=vacancy_id),
    )
    cv_id = uuid.UUID(str(cv["id"]))
    interview = await service.create_interview(
        db, tenant.id, user.id, cv_id, InterviewCreate(notes="x")
    )
    stages = await service.get_effective_vacancy_stages(db, tenant.id, vacancy_id)

    cq = CandidateQuestion(
        tenant_id=tenant.id,
        candidate_id=candidate_id,
        vacancy_id=vacancy_id,
        question_text="q",
        good_answer="g",
        acceptable_answer="a",
        poor_answer="p",
    )
    qset = QuestionSet(tenant_id=tenant.id, candidate_vacancy_id=cv_id, name="set")
    rnd = AssessmentRound(
        tenant_id=tenant.id, candidate_vacancy_id=cv_id, type="pre_interview"
    )
    db.add_all([cq, qset, rnd])
    await db.commit()
    question = Question(tenant_id=tenant.id, question_set_id=qset.id, text="q")
    sheet = RecruitmentAssessment(
        tenant_id=tenant.id, round_id=rnd.id, evaluator_user_id=user.id
    )
    db.add_all([question, sheet])
    await db.commit()
    return {
        "vacancy": vacancy_id,
        "candidate": candidate_id,
        "spare": uuid.UUID(str(spare["id"])),
        "cv": cv_id,
        "interview": uuid.UUID(str(interview["id"])),
        "stage": stages[0]["id"],
        "cq": cq.id,
        "qset": qset.id,
        "question": question.id,
        "sheet": sheet.id,
    }


def _routes(s: dict) -> list[tuple[str, str, str, dict]]:
    """(surface, method, path, request kwargs). Bodies are valid enough to
    clear request validation, so the answer is the service's own."""
    v, cv, i = s["vacancy"], s["cv"], s["interview"]
    any_id = str(uuid.uuid4())
    part = {"upload_id": "u", "part_number": 1}
    return [
        ("vacancy", "POST", f"/recruitment/vacancies/{v}/profile/generate", {}),
        (
            "vacancy",
            "POST",
            f"/recruitment/vacancies/{v}/profile/sessions/apply",
            {"json": {"session_id": any_id, "profile_data": {}}},
        ),
        (
            "vacancy",
            "PUT",
            f"/recruitment/vacancies/{v}/profile",
            {"json": {"profile_data": {}}},
        ),
        ("vacancy", "PATCH", f"/recruitment/vacancies/{v}/competences", {"json": {}}),
        (
            "vacancy",
            "POST",
            f"/recruitment/vacancies/{v}/internal-candidates/{any_id}/add",
            {},
        ),
        ("vacancy", "POST", f"/recruitment/vacancies/{v}/talent-card", {}),
        (
            "vacancy",
            "POST",
            f"/recruitment/vacancies/{v}/attachments",
            {"files": {"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}},
        ),
        ("vacancy", "DELETE", f"/recruitment/vacancies/{v}/attachments/{any_id}", {}),
        (
            "vacancy",
            "POST",
            f"/recruitment/vacancies/{v}/stages",
            {"json": {"name": "Extra", "code": "extra"}},
        ),
        ("vacancy", "PUT", f"/recruitment/vacancies/{v}/funnel-stages", {"json": {}}),
        (
            "vacancy",
            "POST",
            "/recruitment/candidate-vacancies",
            {"json": {"candidate_id": str(s["spare"]), "vacancy_id": str(v)}},
        ),
        (
            "vacancy",
            "POST",
            f"/recruitment/vacancies/{v}/candidates",
            {"json": {"full_name": "New One", "email": "new-one@x.com"}},
        ),
        (
            "vacancy",
            "POST",
            f"/recruitment/vacancies/{v}/candidates/from-parsed",
            {"json": {}},
        ),
        ("vacancy", "POST", f"/recruitment/vacancies/{v}/resumes/bulk-upload", {}),
        (
            "vacancy",
            "PATCH",
            f"/recruitment/candidate-vacancies/{cv}/status",
            {"json": {"stage_id": str(s["stage"])}},
        ),
        (
            "vacancy",
            "PATCH",
            f"/recruitment/candidate-vacancies/{cv}",
            {"json": {"stage_id": str(s["stage"])}},
        ),
        ("vacancy", "DELETE", f"/recruitment/candidate-vacancies/{cv}", {}),
        (
            "questions",
            "POST",
            f"/recruitment/candidates/{s['candidate']}/vacancies/{v}/generate-questions",
            {},
        ),
        (
            "questions",
            "POST",
            f"/recruitment/candidates/{s['candidate']}/vacancies/{v}/questions",
            {"json": {"question_text": "new"}},
        ),
        ("questions", "PUT", f"/recruitment/questions/{s['cq']}", {"json": {}}),
        ("questions", "DELETE", f"/recruitment/questions/{s['cq']}", {}),
        (
            "questions",
            "POST",
            f"/v1/question-sets/{s['qset']}/questions",
            {"json": {"text": "new"}},
        ),
        ("questions", "PATCH", f"/v1/questions/{s['question']}", {"json": {}}),
        ("questions", "DELETE", f"/v1/questions/{s['question']}", {}),
        (
            "manager_assessments",
            "PATCH",
            f"/v1/assessments/{s['sheet']}/competence-scores/{any_id}",
            {"json": {}},
        ),
        (
            "manager_assessments",
            "PATCH",
            f"/v1/assessments/{s['sheet']}/indicator-scores/{any_id}",
            {"json": {"competence_id": any_id}},
        ),
        ("manager_assessments", "POST", f"/v1/assessments/{s['sheet']}/submit", {}),
        (
            "manager_assessments",
            "POST",
            f"/v1/candidate-vacancies/{cv}/manager-assessment-invites",
            {"json": {"invitees": [{"email": "ev@x.com", "name": "Eva"}]}},
        ),
        (
            "interviews",
            "PATCH",
            f"/recruitment/interviews/{i}/upload/u",
            {"json": {"part_number": 1, "etag": "e", "size": 1}},
        ),
        (
            "interviews",
            "POST",
            f"/recruitment/interviews/{i}/upload/part-url",
            {"json": part},
        ),
        (
            "interviews",
            "POST",
            f"/recruitment/interviews/{i}/upload/complete",
            {"json": {"upload_id": "u", "parts": [{"part_number": 1, "etag": "e"}]}},
        ),
    ]


@pytest.mark.parametrize("vacancy_status", ["paused", "closed", "cancelled"])
async def test_mutating_routes_refused_on_a_frozen_vacancy(
    db: AsyncSession, tenant, user, auth_client: AsyncClient, vacancy_status
) -> None:
    seeded = await _seed(db, tenant, user)
    row = await db.get(Vacancy, seeded["vacancy"])
    row.status = vacancy_status
    await db.commit()

    checked, missed = 0, []
    for surface, method, path, kwargs in _routes(seeded):
        if not vacancy_locks(vacancy_status, surface):
            continue
        checked += 1
        resp = await auth_client.request(method, "/api" + path, **kwargs)
        if resp.status_code != 409 or "vacancy_status_read_only" not in resp.text:
            missed.append(f"{method} {path} -> {resp.status_code} {resp.text[:200]}")
    assert checked
    assert not missed, "\n".join(missed)


async def test_no_hire_close_keeps_the_candidate_out_of_hired(
    db: AsyncSession, tenant, user
) -> None:
    seeded = await _seed(db, tenant, user)
    stages = {
        s["code"]: s["id"]
        for s in await service.get_effective_vacancy_stages(
            db, tenant.id, seeded["vacancy"]
        )
    }
    await service.close_vacancy(
        db, tenant.id, seeded["vacancy"], VacancyCloseData(resolution="closed_no_hire")
    )

    with pytest.raises(AppError) as exc:
        await service.patch_candidate_vacancy(
            db,
            tenant.id,
            seeded["cv"],
            CandidateVacancyPatch(stage_id=stages["hired"]),
        )
    assert exc.value.code == "vacancy_status_read_only"
    with pytest.raises(AppError) as exc:
        await service.change_candidate_status(
            db,
            tenant.id,
            seeded["cv"],
            CandidateVacancyStatusUpdate(stage_id=stages["hired"]),
        )
    assert exc.value.code == "vacancy_status_read_only"

    cv = await db.get(CandidateVacancy, seeded["cv"])
    await db.refresh(cv)
    assert cv.stage_id != stages["hired"]
