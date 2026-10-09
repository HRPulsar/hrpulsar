"""HRP-630 (QA 06.10, tasks 2 and 3): what a hiring manager at ``view`` writes.

Task 2: at ``Recruitment x Hiring manager = view`` the interview questions
are read-only - only their PDF export stays - and on the manager
assessment rounds the hiring manager fills in the sheet they hold as an
internal evaluator and nothing else. The vacancy's own hiring manager can
be named an evaluator on its rounds for that.

Task 3: ``Talent Market x Recruiter / Hiring manager = view`` read every
card, the way ``hr`` does; ``employee`` still reads only its own.
"""

import uuid

from app.modules.company.models import Division
from app.modules.recruitment.models import QuestionSet

from tests.unit.test_recruitment_manager_scope import _headers, _user
from tests.unit.test_recruitment_section_access import (  # noqa: F401
    GATE,
    _refused,
    hiring,
)

CARD = {"title": "HRP-630 probe", "card_type": "talent"}


async def test_the_hiring_manager_reads_and_exports_questions_at_view(client, db, tenant, hiring):  # noqa: F811
    hm = _headers(hiring["hm"])
    cv = hiring["mine_cv"]
    qset = QuestionSet(tenant_id=tenant.id, candidate_vacancy_id=cv.id, name="Set")
    db.add(qset)
    await db.commit()
    for method, path, body in (
        ("POST", f"/api/v1/candidate-vacancies/{cv.id}/question-sets", {}),
        ("POST", f"/api/v1/question-sets/{qset.id}/questions", {"text": "Why?"}),
        ("POST", f"/api/v1/question-sets/{qset.id}/cancel", None),
        ("POST", f"/api/recruitment/candidates/{cv.candidate_id}/vacancies/{cv.vacancy_id}/questions", {}),
    ):
        r = await client.request(method, path, json=body, headers=hm)
        assert _refused(r), f"{method} {path} -> {r.status_code} {r.text}"
    exported = await client.post(f"/api/v1/question-sets/{qset.id}/export-pdf", json={}, headers=hm)
    assert exported.status_code != 403, exported.text
    assert (await client.get(f"/api/v1/candidates/{cv.candidate_id}/question-sets", headers=hm)).status_code == 200


async def test_the_hiring_manager_fills_in_only_their_own_sheet(client, db, tenant, hiring):  # noqa: F811
    recruiter = _headers(await _user(db, tenant, "recruiter"))
    hm_user = hiring["hm"]
    hm = _headers(hm_user)
    created = await client.post(
        f"/api/v1/candidate-vacancies/{hiring['mine_cv'].id}/assessment-rounds",
        json={"type": "final"},
        headers=recruiter,
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    # The vacancy's own hiring manager is on the picker, whatever their role.
    picker = await client.get(f"/api/v1/assessment-rounds/{rid}/eligible-evaluators", headers=recruiter)
    assert str(hm_user.id) in {u["id"] for u in picker.json()}, picker.text
    for user_id in (hm_user.id, (await client.get("/api/auth/me", headers=recruiter)).json()["id"]):
        added = await client.post(
            f"/api/v1/assessment-rounds/{rid}/evaluators", json={"user_id": str(user_id)}, headers=recruiter
        )
        assert added.status_code == 201, added.text
    # A colleague's sheet stays hidden until one's own is in (HRP-373), so
    # each evaluator reads their own.
    async def sheet_of(headers):
        listed = (await client.get(f"/api/v1/assessment-rounds/{rid}/assessments", headers=headers)).json()
        me = (await client.get("/api/auth/me", headers=headers)).json()["id"]
        return next(s["id"] for s in listed if s["evaluator_user_id"] == me)

    own, theirs = await sheet_of(hm), await sheet_of(recruiter)
    competence = uuid.uuid4()
    score = {"score_value": 3, "score_source": "manual"}
    ok = await client.patch(f"/api/v1/assessments/{own}/competence-scores/{competence}", json=score, headers=hm)
    assert ok.status_code == 200, ok.text
    refused = await client.patch(f"/api/v1/assessments/{theirs}/competence-scores/{competence}", json=score, headers=hm)
    assert _refused(refused), refused.text
    assert _refused(await client.post(f"/api/v1/assessments/{theirs}/submit", json={}, headers=hm))
    # Everything else on the round stays read-only.
    assert _refused(await client.patch(f"/api/v1/assessment-rounds/{rid}", json={"action": "complete"}, headers=hm))
    assert _refused(
        await client.post(
            f"/api/v1/candidate-vacancies/{hiring['mine_cv'].id}/assessment-rounds",
            json={"type": "interview"},
            headers=hm,
        )
    )


async def test_a_hiring_manager_of_another_vacancy_is_not_on_the_picker(client, db, tenant, hiring):  # noqa: F811
    recruiter = _headers(await _user(db, tenant, "recruiter"))
    created = await client.post(
        f"/api/v1/candidate-vacancies/{hiring['theirs_cv'].id}/assessment-rounds",
        json={"type": "final"},
        headers=recruiter,
    )
    rid = created.json()["id"]
    picker = await client.get(f"/api/v1/assessment-rounds/{rid}/eligible-evaluators", headers=recruiter)
    assert str(hiring["hm"].id) not in {u["id"] for u in picker.json()}
    added = await client.post(
        f"/api/v1/assessment-rounds/{rid}/evaluators", json={"user_id": str(hiring["hm"].id)}, headers=recruiter
    )
    assert added.status_code == 403 and added.json()["code"] == "evaluator_role_not_eligible", added.text


async def test_the_hiring_roles_read_every_talent_card_at_view(auth_client, client, db, tenant):
    # A draft in a division none of them heads: before, only ``hr`` read it.
    division = Division(tenant_id=tenant.id, name=f"Far {uuid.uuid4().hex[:4]}")
    db.add(division)
    await db.commit()
    card = await auth_client.post("/api/talent-market", json={**CARD, "division_id": str(division.id)})
    assert card.status_code == 201, card.text
    cid = card.json()["id"]
    for code in ("recruiter", "hiring_manager", "hr"):
        h = _headers(await _user(db, tenant, code))
        me = await client.get("/api/auth/me", headers=h)
        assert me.json()["sections"]["talent-market"] == "view", code
        listed = await client.post("/api/talent-market/search", json={}, headers=h)
        assert cid in {c["id"] for c in listed.json()["items"]}, code
        detail = await client.get(f"/api/talent-market/{cid}", headers=h)
        assert detail.status_code == 200, (code, detail.text)
        assert detail.json()["can_manage"] is False, code
        put = await client.put(f"/api/talent-market/{cid}", json={"title": "X"}, headers=h)
        assert put.status_code == 403, code
    employee = _headers(await _user(db, tenant, "employee"))
    listed = await client.post("/api/talent-market/search", json={}, headers=employee)
    assert cid not in {c["id"] for c in listed.json()["items"]}
    assert (await client.get(f"/api/talent-market/{cid}", headers=employee)).status_code == 404
