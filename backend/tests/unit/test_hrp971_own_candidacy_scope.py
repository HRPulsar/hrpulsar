"""HRP-971: a vacancy one is a candidate on is out of one's hiring scope.

A deputy head applying for their head's seat reached the vacancy through
their managed subtree and with it everything hanging off it: their own
AI verdict and round sheets, their rivals' resumes and scores, and - as a
``manager`` running rounds - a round to score a rival or themselves. The
fence takes the whole vacancy below the admin level and the recruiter
(HRP-830 REDO: ``manage`` alone no longer lifts it), for good, whatever
else reaches it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from app.models import Person
from app.modules.auth.models import User
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.recruitment import notifications
from app.modules.recruitment.manager_assessment_models import AssessmentRound
from app.modules.recruitment.models import (
    AssessmentInvite,
    Candidate,
    CandidateQuestion,
    CandidateVacancy,
    Interview,
    QuestionSet,
    Vacancy,
)
from app.modules.recruitment.scope import fenced_off_vacancy, fenced_off_vacancy_sync
from app.modules.talent_market import common
from app.modules.talent_market.models import TalentCandidate, TalentCard
from sqlalchemy import update

from tests.unit.test_recruitment_manager_scope import _headers, _user
from tests.unit.test_recruitment_section_access import SCOPE, _refused
from tests.unit.test_section_gate import _save


async def _candidacy(db, tenant, vacancy, **candidate):
    cand = Candidate(tenant_id=tenant.id, full_name=candidate.pop("full_name", "C"), **candidate)
    db.add(cand)
    await db.commit()
    cv = CandidateVacancy(tenant_id=tenant.id, candidate_id=cand.id, vacancy_id=vacancy.id)
    db.add(cv)
    await db.commit()
    return cand, cv


@pytest_asyncio.fixture
async def seat(db, tenant):
    """``mine`` headed by ``head`` with ``deputy`` as deputy; the head's
    seat opens as vacancy ``seat``, the deputy applies (matched by email,
    in another case) and a rival applies to it and to ``other``, a second
    vacancy of the same division the deputy is not on."""
    head = await _user(db, tenant, "manager")
    deputy = await _user(db, tenant, "manager")
    head_emp = Employee(user_id=head.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    dep_emp = Employee(user_id=deputy.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add_all([head_emp, dep_emp])
    await db.commit()
    mine = Division(
        tenant_id=tenant.id,
        name=f"Mine {uuid.uuid4().hex[:4]}",
        manager_id=head_emp.id,
        deputy_manager_id=dep_emp.id,
    )
    db.add(mine)
    await db.commit()
    seat_vac = Vacancy(tenant_id=tenant.id, title="Head of Mine", division_id=mine.id)
    other = Vacancy(tenant_id=tenant.id, title="Analyst", division_id=mine.id)
    db.add_all([seat_vac, other])
    await db.commit()
    own, own_cv = await _candidacy(db, tenant, seat_vac, email=deputy.email.upper())
    rival, rival_cv = await _candidacy(db, tenant, seat_vac, email=f"r-{uuid.uuid4().hex[:6]}@example.com")
    other_cv = CandidateVacancy(tenant_id=tenant.id, candidate_id=rival.id, vacancy_id=other.id)
    db.add(other_cv)
    await db.commit()
    return {
        "head": head,
        "deputy": deputy,
        "mine": mine,
        "dep_emp": dep_emp,
        "seat": seat_vac,
        "other": other,
        "own": own,
        "own_cv": own_cv,
        "rival": rival,
        "rival_cv": rival_cv,
        "other_cv": other_cv,
    }


async def test_the_deputy_loses_the_vacancy_they_apply_to(client, seat):
    h = _headers(seat["deputy"])
    listed = await client.get("/api/recruitment/vacancies", headers=h)
    assert listed.status_code == 200, listed.text
    assert {v["id"] for v in listed.json()["items"]} == {str(seat["other"].id)}
    assert _refused(await client.get(f"/api/recruitment/vacancies/{seat['seat'].id}", headers=h), SCOPE)
    table = f"/api/recruitment/vacancies/{seat['seat'].id}/candidates/enriched"
    assert _refused(await client.get(table, headers=h), SCOPE)
    assert _refused(await client.get(f"/api/recruitment/candidates/{seat['own'].id}", headers=h), SCOPE)
    # The rival stays readable through the vacancy the deputy runs, minus
    # the application to the seat.
    card = await client.get(f"/api/recruitment/candidates/{seat['rival'].id}/vacancies", headers=h)
    assert card.status_code == 200, card.text
    assert {a["vacancy_id"] for a in card.json()} == {str(seat["other"].id)}


async def test_the_deputy_cannot_open_a_round_on_the_seat(client, seat):
    h = _headers(seat["deputy"])
    for cv in ("own_cv", "rival_cv"):
        rounds = f"/api/v1/candidate-vacancies/{seat[cv].id}/assessment-rounds"
        assert _refused(await client.post(rounds, json={"type": "pre_interview"}, headers=h), SCOPE)
    other = f"/api/v1/candidate-vacancies/{seat['other_cv'].id}/assessment-rounds"
    created = await client.post(other, json={"type": "pre_interview"}, headers=h)
    assert created.status_code == 201, created.text


async def test_the_fence_outranks_owner_and_hiring_manager_and_outlives_the_vacancy(client, db, seat):
    await db.execute(
        update(Vacancy)
        .where(Vacancy.id == seat["seat"].id)
        .values(owner_id=seat["deputy"].id, hiring_manager_id=seat["deputy"].id, status="closed")
    )
    await db.execute(update(CandidateVacancy).where(CandidateVacancy.id == seat["own_cv"].id).values(status="rejected"))
    await db.commit()
    h = _headers(seat["deputy"])
    assert _refused(await client.get(f"/api/recruitment/vacancies/{seat['seat'].id}", headers=h), SCOPE)
    # Named hiring manager or not, the role that runs rounds reaches the
    # scope check and stops there.
    rounds = f"/api/v1/candidate-vacancies/{seat['own_cv'].id}/assessment-rounds"
    assert _refused(await client.post(rounds, json={"type": "pre_interview"}, headers=h), SCOPE)


async def test_the_person_matches_as_well_as_the_email(client, db, seat):
    person = Person(first_name="Dep", last_name="Uty")
    db.add(person)
    await db.commit()
    await db.execute(update(Candidate).where(Candidate.id == seat["own"].id).values(email=None, person_id=person.id))
    await db.commit()
    h = _headers(seat["deputy"])
    # Before the account is linked to the Person nothing matches it any more.
    assert (await client.get(f"/api/recruitment/vacancies/{seat['seat'].id}", headers=h)).status_code == 200
    await db.execute(update(User).where(User.id == seat["deputy"].id).values(person_id=person.id))
    await db.commit()
    assert _refused(await client.get(f"/api/recruitment/vacancies/{seat['seat'].id}", headers=h), SCOPE)


async def test_the_head_and_whoever_runs_hiring_keep_the_vacancy(auth_client, client, db, tenant, seat):
    for h in (_headers(seat["head"]), _headers(await _user(db, tenant, "recruiter"))):
        r = await client.get(f"/api/recruitment/vacancies/{seat['seat'].id}", headers=h)
        assert r.status_code == 200, r.text
    assert (await auth_client.get(f"/api/recruitment/vacancies/{seat['seat'].id}")).status_code == 200
    # HRP-830 REDO: ``manage`` alone no longer unfences - raised to it, the
    # deputy runs hiring on their divisions, still not on the seat they want.
    await _save(auth_client, levels={"recruitment": {"manager": "manage"}})
    r = await client.get(f"/api/recruitment/vacancies/{seat['seat'].id}", headers=_headers(seat["deputy"]))
    assert r.status_code == 403, r.text


async def test_mail_about_the_seat_skips_the_candidate(db, seat):
    assert await fenced_off_vacancy(db, seat["deputy"], seat["seat"].id)
    assert not await fenced_off_vacancy(db, seat["deputy"], seat["other"].id)
    assert not await fenced_off_vacancy(db, seat["head"], seat["seat"].id)


async def test_a_rival_reached_elsewhere_hands_over_no_seat_questions(client, db, tenant, seat):
    # Review of HRP-971: the candidate-keyed lists answered every vacancy
    # of the rival when called without ``vacancy_id`` - the seat's answer
    # keys included.
    for vac, cv in ((seat["seat"], seat["rival_cv"]), (seat["other"], seat["other_cv"])):
        db.add(
            CandidateQuestion(
                tenant_id=tenant.id,
                candidate_id=seat["rival"].id,
                vacancy_id=vac.id,
                question_text=f"Q {vac.title}",
                good_answer="g",
                acceptable_answer="a",
                poor_answer="p",
            )
        )
        db.add(QuestionSet(tenant_id=tenant.id, candidate_vacancy_id=cv.id, name=f"S {vac.title}"))
    await db.commit()
    h = _headers(seat["deputy"])
    questions = await client.get(f"/api/recruitment/candidates/{seat['rival'].id}/questions", headers=h)
    assert questions.status_code == 200, questions.text
    assert [q["question_text"] for q in questions.json()] == ["Q Analyst"]
    sets = await client.get(f"/api/v1/candidates/{seat['rival'].id}/question-sets", headers=h)
    assert sets.status_code == 200, sets.text
    assert [s["name"] for s in sets.json()] == ["S Analyst"]


async def test_the_mail_about_the_seat_skips_the_candidate_on_both_paths(db, seat, monkeypatch):
    captured: list = []

    async def _dispatch(db_, **kwargs):
        captured.extend(kwargs["recipients"])
        return len(kwargs["recipients"])

    class _Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    async def _recipients(db_, tenant_id, data):
        return [seat["deputy"], seat["head"]]

    monkeypatch.setattr(notifications, "_async_dispatch", _dispatch)
    monkeypatch.setattr("app.database.async_session", _Session)
    data = {"tenant_id": str(seat["seat"].tenant_id), "vacancy_id": str(seat["seat"].id)}
    await notifications._async_handle(
        "recruitment.candidate.attached", data, resolve_recipients=_recipients
    )
    assert [u.id for u in captured] == [seat["head"].id]
    # The Celery twin answers the same.
    assert await db.run_sync(lambda s: fenced_off_vacancy_sync(s, seat["deputy"], seat["seat"].id))
    assert not await db.run_sync(lambda s: fenced_off_vacancy_sync(s, seat["head"], seat["seat"].id))


async def test_the_admin_level_is_never_fenced_off_its_mail(auth_client, db, tenant, seat):
    # Lowered to ``view``, hr is still the admin level and reads the whole
    # workspace - so it is not fenced either.
    await _save(auth_client, levels={"recruitment": {"hr": "view"}})
    hr = await _user(db, tenant, "hr")
    await _candidacy(db, tenant, seat["seat"], email=hr.email)
    assert not await fenced_off_vacancy(db, hr, seat["seat"].id)
    assert not await db.run_sync(lambda s: fenced_off_vacancy_sync(s, hr, seat["seat"].id))


async def _seat_card(db, tenant, seat, *, deputy_reacted: bool):
    """The seat posted to the talent market: a published card of ``mine``
    with the deputy and a colleague on its shortlist."""
    card = TalentCard(
        tenant_id=tenant.id,
        title="Head of Mine",
        card_type="vacancy",
        author_id=seat["head"].id,
        division_id=seat["mine"].id,
        start_date=date(2026, 1, 1),
        status="published",
        is_published=True,
    )
    db.add(card)
    await db.commit()
    colleague = await _user(db, tenant, "employee")
    col_emp = Employee(user_id=colleague.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(col_emp)
    await db.commit()
    reacted = datetime.now(UTC) if deputy_reacted else None
    db.add_all(
        [
            TalentCandidate(card_id=card.id, employee_id=seat["dep_emp"].id, response_at=reacted),
            TalentCandidate(card_id=card.id, employee_id=col_emp.id),
        ]
    )
    await db.commit()
    return card, col_emp


async def test_a_head_who_applied_reads_the_market_card_as_an_applicant(client, db, tenant, seat):
    card, col_emp = await _seat_card(db, tenant, seat, deputy_reacted=True)
    h = _headers(seat["deputy"])
    detail = await client.get(f"/api/talent-market/{card.id}", headers=h)
    assert detail.status_code == 200, detail.text
    assert [c["is_me"] for c in detail.json()["candidates"]] == [True]
    assert detail.json()["can_manage"] is False
    for method, path in (
        ("post", f"/api/talent-market/{card.id}/recompute"),
        ("get", f"/api/talent-market/{card.id}/candidate-pool"),
        ("delete", f"/api/talent-market/{card.id}/candidates/{col_emp.id}"),
    ):
        assert (await getattr(client, method)(path, headers=h)).status_code == 403, path
    breakdown = f"/api/talent-market/{card.id}/candidates/{{}}/breakdown"
    assert (await client.get(breakdown.format(col_emp.id), headers=h)).status_code == 403
    assert (await client.get(breakdown.format(seat["dep_emp"].id), headers=h)).status_code == 200
    # The head keeps running the card.
    head_view = await client.get(f"/api/talent-market/{card.id}", headers=_headers(seat["head"]))
    assert len(head_view.json()["candidates"]) == 2 and head_view.json()["can_manage"] is True


async def test_the_twin_of_a_fenced_vacancy_is_fenced_without_a_reaction(client, db, tenant, seat):
    card, _ = await _seat_card(db, tenant, seat, deputy_reacted=False)
    h = _headers(seat["deputy"])
    # Matched but not applied: a division head runs the card as before.
    assert len((await client.get(f"/api/talent-market/{card.id}", headers=h)).json()["candidates"]) == 2
    await db.execute(update(Vacancy).where(Vacancy.id == seat["seat"].id).values(talent_card_id=card.id))
    await db.commit()
    detail = await client.get(f"/api/talent-market/{card.id}", headers=h)
    assert [c["is_me"] for c in detail.json()["candidates"]] == [True]
    assert (await client.post(f"/api/talent-market/{card.id}/recompute", headers=h)).status_code == 403


async def test_the_twin_stays_fenced_for_a_head_raised_to_manage(auth_client, client, db, tenant, seat):
    # HRP-830 REDO review: ``manage`` on recruitment no longer unfences the
    # vacancy, so its twin card must not open either - read and list alike.
    from app.modules.talent_market.scope import competes_on_card

    card, _ = await _seat_card(db, tenant, seat, deputy_reacted=False)
    await db.execute(update(Vacancy).where(Vacancy.id == seat["seat"].id).values(talent_card_id=card.id))
    await db.commit()
    await _save(auth_client, levels={"recruitment": {"manager": "manage"}})
    h = _headers(seat["deputy"])
    assert _refused(await client.get(f"/api/recruitment/vacancies/{seat['seat'].id}", headers=h), SCOPE)
    detail = await client.get(f"/api/talent-market/{card.id}", headers=h)
    assert [c["is_me"] for c in detail.json()["candidates"]] == [True]
    assert (await client.post(f"/api/talent-market/{card.id}/recompute", headers=h)).status_code == 403
    assert await competes_on_card(db, seat["deputy"], card.id)
    assert not await competes_on_card(db, await _user(db, tenant, "recruiter"), card.id)


async def test_a_reaction_to_the_twin_card_fences_the_vacancy_before_any_candidacy(client, db, tenant, seat):
    # Second review of HRP-971: reacting on the talent market creates no
    # candidacy, so the recruitment fence has to read the reaction itself -
    # otherwise the deputy reads the vacancy, its internal shortlist and its
    # external rivals until a recruiter moves them into the pipeline.
    card, _ = await _seat_card(db, tenant, seat, deputy_reacted=True)
    opening = Vacancy(tenant_id=tenant.id, title="Deputy of Mine", division_id=seat["mine"].id, talent_card_id=card.id)
    db.add(opening)
    await db.commit()
    h = _headers(seat["deputy"])
    assert _refused(await client.get(f"/api/recruitment/vacancies/{opening.id}", headers=h), SCOPE)
    assert _refused(await client.get(f"/api/recruitment/vacancies/{opening.id}/internal-candidates", headers=h), SCOPE)
    assert (await client.get(f"/api/recruitment/vacancies/{opening.id}", headers=_headers(seat["head"]))).status_code == 200


async def test_interview_mail_is_fenced_on_the_request_path_and_in_celery(db, tenant, seat, monkeypatch):
    interview = Interview(tenant_id=tenant.id, candidate_vacancy_id=seat["rival_cv"].id, interviewer_id=seat["deputy"].id)
    db.add(interview)
    await db.commit()
    data = {"tenant_id": str(tenant.id), "interview_id": str(interview.id)}
    captured: list = []

    async def _dispatch(db_, **kwargs):
        captured.extend(kwargs["recipients"])
        return len(kwargs["recipients"])

    class _Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    async def _recipients(db_, tenant_id, data_):
        return [seat["deputy"], seat["head"]]

    monkeypatch.setattr(notifications, "_async_dispatch", _dispatch)
    monkeypatch.setattr("app.database.async_session", _Session)
    await notifications._async_handle("recruitment.interview.scheduled", data, resolve_recipients=_recipients)
    assert [u.id for u in captured] == [seat["head"].id]

    class _Stop(Exception):
        pass

    def _locales(recipients, default):
        captured[:] = recipients
        raise _Stop

    monkeypatch.setattr(notifications, "_recipient_locales", _locales)
    with pytest.raises(_Stop):
        await db.run_sync(
            lambda s: notifications.notify_sync(
                s,
                event="recruitment.interview.transcript_ready",
                tenant_id=tenant.id,
                context={"interview_id": str(interview.id)},
                recipient_ids=[seat["deputy"].id, seat["head"].id],
            )
        )
    assert [u.id for u in captured] == [seat["head"].id]


async def test_a_draft_twin_is_neither_listed_nor_read_by_the_head_who_competes(client, db, tenant, seat):
    draft = TalentCard(
        tenant_id=tenant.id,
        title="Head of Mine (draft)",
        card_type="vacancy",
        author_id=seat["head"].id,
        division_id=seat["mine"].id,
        start_date=date(2026, 1, 1),
    )
    db.add(draft)
    await db.commit()
    h = _headers(seat["deputy"])
    listed = await client.post("/api/talent-market/search", json={}, headers=h)
    assert str(draft.id) in {c["id"] for c in listed.json()["items"]}
    await db.execute(update(Vacancy).where(Vacancy.id == seat["seat"].id).values(talent_card_id=draft.id))
    await db.commit()
    listed = await client.post("/api/talent-market/search", json={}, headers=h)
    assert str(draft.id) not in {c["id"] for c in listed.json()["items"]}
    assert (await client.get(f"/api/talent-market/{draft.id}", headers=h)).status_code == 404
    # Published, it is still not theirs to browse: an applicant reads the
    # cards their name is on, and the deputy is not on this one.
    await db.execute(
        update(TalentCard).where(TalentCard.id == draft.id).values(status="published", is_published=True)
    )
    await db.commit()
    listed = await client.post("/api/talent-market/search", json={}, headers=h)
    assert str(draft.id) not in {c["id"] for c in listed.json()["items"]}
    assert (await client.get(f"/api/talent-market/{draft.id}", headers=h)).status_code == 404


async def test_card_letters_skip_a_manager_who_competes_on_the_card(client, db, tenant, seat, monkeypatch):
    # The deputy heads the colleague's team and reacted to the seat: the
    # letters about the colleague on that card - reacted, appointed,
    # cancelled, a plan asked for - would name a rival and their outcome.
    card, col_emp = await _seat_card(db, tenant, seat, deputy_reacted=True)
    team = Division(tenant_id=tenant.id, name=f"Team {uuid.uuid4().hex[:4]}", manager_id=seat["dep_emp"].id)
    db.add(team)
    await db.commit()
    col_emp.division_id = team.id
    await db.commit()
    assert await common.resolve_manager_user(db, col_emp, card.id) is None
    elsewhere = TalentCard(
        tenant_id=tenant.id,
        title="Analyst",
        card_type="vacancy",
        author_id=seat["head"].id,
        division_id=seat["mine"].id,
        start_date=date(2026, 1, 1),
    )
    db.add(elsewhere)
    await db.commit()
    manager = await common.resolve_manager_user(db, col_emp, elsewhere.id)
    assert manager is not None and manager.id == seat["deputy"].id
    # Their own head is still themselves: the plan request keeps saying
    # "you manage this division yourself", not "nobody manages it".
    seat["dep_emp"].division_id = team.id
    await db.commit()
    own_head = await common.resolve_manager_user(db, seat["dep_emp"], card.id)
    assert own_head is not None and own_head.id == seat["deputy"].id

    sent: list[str] = []
    monkeypatch.setattr("app.core.email.enqueue_email", lambda to, *a, **k: sent.append(to))
    colleague = await db.get(User, col_emp.user_id)
    r = await client.post(f"/api/talent-market/{card.id}/react", headers=_headers(colleague))
    assert r.status_code == 200, r.text
    assert seat["deputy"].email not in sent


async def test_nobody_fenced_off_the_vacancy_interviews_or_evaluates_on_it(auth_client, db, tenant, seat):
    # The deputy applied to the seat: they may not sit in the rival's
    # interview or score them, nor be handed an evaluator link to either.
    deputy, head = str(seat["deputy"].id), str(seat["head"].id)
    rival_cv = seat["rival_cv"].id

    def refused(r):
        return r.status_code == 422 and r.json()["code"] == "assignee_fenced_off"

    picker = "/api/recruitment/interviewers"
    listed = {p["id"] for p in (await auth_client.get(f"{picker}?candidate_vacancy_id={rival_cv}")).json()}
    assert head in listed and deputy not in listed
    # The rival's other vacancy is not the deputy's: the deputy is offered.
    other = seat["other_cv"].id
    assert deputy in {p["id"] for p in (await auth_client.get(f"{picker}?candidate_vacancy_id={other}")).json()}

    interviews = f"/api/recruitment/candidate-vacancies/{rival_cv}/interviews"
    assert refused(await auth_client.post(interviews, json={"interviewers": [head, deputy]}))
    made = await auth_client.post(interviews, json={"interviewers": [head]})
    assert made.status_code == 201, made.text
    edit = f"/api/recruitment/interviews/{made.json()['id']}"
    assert refused(await auth_client.put(edit, json={"interviewers": [head, deputy]}))
    assert (await auth_client.put(edit, json={"title": "Round 1"})).status_code == 200

    rnd = AssessmentRound(tenant_id=tenant.id, candidate_vacancy_id=rival_cv, type="pre_interview")
    db.add(rnd)
    await db.commit()
    eligible = await auth_client.get(f"/api/v1/assessment-rounds/{rnd.id}/eligible-evaluators")
    assert {head} <= {p["id"] for p in eligible.json()} and deputy not in {p["id"] for p in eligible.json()}
    evaluators = f"/api/v1/assessment-rounds/{rnd.id}/evaluators"
    assert refused(await auth_client.post(evaluators, json={"user_id": deputy}))

    # A token link opens the sheet past the matrix: no candidate on the
    # vacancy - fenced or not - is invited to evaluate on it.
    invites = f"/api/recruitment/candidate-vacancies/{rival_cv}/invites"
    assert refused(await auth_client.post(invites, json={"email": seat["deputy"].email}))
    assert refused(await auth_client.post(invites, json={"email": seat["rival"].email.upper()}))
    batch = f"/api/v1/candidate-vacancies/{rival_cv}/manager-assessment-invites"
    r = await auth_client.post(batch, json={"invitees": [{"email": seat["rival"].email, "name": "Rival"}]})
    assert refused(r), r.text
    # Nor sent again to one who applied after the link went out.
    sent = AssessmentInvite(
        tenant_id=tenant.id,
        candidate_vacancy_id=rival_cv,
        token=uuid.uuid4().hex,
        email=seat["deputy"].email,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(sent)
    await db.commit()
    assert refused(await auth_client.post(f"/api/v1/manager-assessment-invites/{sent.id}/resend"))
    # Review 01.10: nor extended, and the link already out stops opening
    # the rival's sheet - the fence used to be asked on send and resend only.
    assert refused(await auth_client.post(f"/api/v1/manager-assessment-invites/{sent.id}/extend", json={"additional_days": 3}))
    r = await auth_client.get(f"/api/v1/public/assessments/{sent.token}")
    assert r.status_code == 410 and r.json()["code"] == "invitation_revoked", r.text


async def test_the_evaluation_notice_skips_an_owner_fenced_off_the_vacancy(db, tenant, seat):
    # Review 01.10: the notice picked one recipient - the owner - and the
    # fence then dropped them, so nobody heard of the submitted sheet.
    from app.modules.recruitment.manager_assessment_public import _notified_owner_id

    vacancy = seat["seat"]
    vacancy.owner_id = seat["deputy"].id
    vacancy.hiring_manager_id = seat["head"].id
    await db.commit()
    invite = AssessmentInvite(
        tenant_id=tenant.id,
        candidate_vacancy_id=seat["rival_cv"].id,
        token=uuid.uuid4().hex,
        email=f"ext-{uuid.uuid4().hex[:6]}@example.com",
        status="submitted",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    assert await _notified_owner_id(db, vacancy, invite) == seat["head"].id
