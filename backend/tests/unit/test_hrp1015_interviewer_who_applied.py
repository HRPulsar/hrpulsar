"""HRP-1015: an interviewer who has since applied to the vacancy keeps their
name on the interview.

HRP-971 leaves a candidate for a vacancy out of its interviewer picker, but
someone named before they applied stays on the interview - only people
added later are checked. The interview page used to build the names from the
picker's list, so that interviewer showed up nameless. The names now come
with the interview (HRP-1019), whatever the picker offers.
"""

# ruff: noqa: F811 - ``seat`` is a pytest fixture imported by name
from __future__ import annotations

import uuid

from app.modules.recruitment.models import Interview, InterviewInterviewer, Vacancy

from tests.unit.test_hrp971_own_candidacy_scope import (  # noqa: F401 - seat is a fixture
    _candidacy,
    _seat_card,
    seat,
)
from tests.unit.test_recruitment_manager_scope import _headers, _user


async def test_the_interview_names_whom_the_picker_leaves_out(client, db, tenant, seat):
    deputy = seat["deputy"]
    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=seat["rival_cv"].id,
        interviewer_id=seat["head"].id,
    )
    db.add(interview)
    await db.commit()
    db.add(
        InterviewInterviewer(
            tenant_id=tenant.id, interview_id=interview.id, user_id=deputy.id
        )
    )
    await db.commit()
    h = _headers(await _user(db, tenant, "recruiter"))

    picker = await client.get(
        f"/api/recruitment/interviewers?candidate_vacancy_id={seat['rival_cv'].id}",
        headers=h,
    )
    assert picker.status_code == 200, picker.text
    assert str(deputy.id) not in {p["id"] for p in picker.json()}

    r = await client.get(f"/api/recruitment/interviews/{interview.id}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["interviewer_ids"] == [str(seat["head"].id), str(deputy.id)]
    assert [(b["id"], b["full_name"]) for b in body["interviewers"]] == [
        (str(seat["head"].id), f"{seat['head'].first_name} {seat['head'].last_name}"),
        (str(deputy.id), f"{deputy.first_name} {deputy.last_name}"),
    ]


# HRP-1015 REDO: the picker of an interview being edited keeps its own
# interviewers - the fence only decides who may be added.


async def _interview(db, tenant, cv, *interviewers):
    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        interviewer_id=interviewers[0].id,
    )
    db.add(interview)
    await db.commit()
    db.add_all(
        InterviewInterviewer(
            tenant_id=tenant.id, interview_id=interview.id, user_id=u.id
        )
        for u in interviewers
    )
    await db.commit()
    return interview


async def _picker(client, h, cv, interview=None) -> set[str]:
    url = f"/api/recruitment/interviewers?candidate_vacancy_id={cv.id}"
    if interview is not None:
        url += f"&interview_id={interview.id}"
    r = await client.get(url, headers=h)
    assert r.status_code == 200, r.text
    return {p["id"] for p in r.json()}


async def test_editing_lists_an_interviewer_who_has_since_applied(
    client, db, tenant, seat
):
    """The deputy sits on the rival's interview, then applies to the vacancy
    (``own_cv``): the edit window lists and ticks them, a new one does not."""
    head, deputy = seat["head"], seat["deputy"]
    interview = await _interview(db, tenant, seat["rival_cv"], head, deputy)
    h = _headers(await _user(db, tenant, "recruiter"))

    assert str(deputy.id) in await _picker(client, h, seat["rival_cv"], interview)
    assert str(deputy.id) not in await _picker(client, h, seat["rival_cv"])


async def test_a_candidate_never_on_the_interview_is_still_not_offered(
    client, db, tenant, seat
):
    """QA's guard: a candidate of the vacancy first is no interviewer to add,
    in the edit window of an interview they are not on either."""
    interview = await _interview(db, tenant, seat["rival_cv"], seat["head"])
    h = _headers(await _user(db, tenant, "recruiter"))

    listed = await _picker(client, h, seat["rival_cv"], interview)

    assert str(seat["deputy"].id) not in listed
    assert str(seat["head"].id) in listed


async def test_another_candidacys_interview_lifts_no_fence(client, db, tenant, seat):
    """The deputy's place on an interview of another vacancy says nothing
    about this one."""
    elsewhere = await _interview(db, tenant, seat["other_cv"], seat["deputy"])
    h = _headers(await _user(db, tenant, "recruiter"))

    assert str(seat["deputy"].id) not in await _picker(
        client, h, seat["rival_cv"], elsewhere
    )


async def test_the_talent_market_twin_path_keeps_its_interviewer(
    client, db, tenant, seat
):
    """QA steps 6-8: the interviewer joins the shortlist of the vacancy's
    talent-market card (a reaction fences them, no candidacy needed); the
    edit window still lists them, a new interview does not offer them."""
    card, col_emp = await _seat_card(db, tenant, seat, deputy_reacted=True)
    opening = Vacancy(
        tenant_id=tenant.id,
        title="Deputy of Mine",
        division_id=seat["mine"].id,
        talent_card_id=card.id,
    )
    db.add(opening)
    await db.commit()
    _cand, cv = await _candidacy(
        db, tenant, opening, email=f"x-{uuid.uuid4().hex[:6]}@example.com"
    )
    interview = await _interview(db, tenant, cv, seat["deputy"])
    h = _headers(await _user(db, tenant, "recruiter"))

    assert str(seat["deputy"].id) in await _picker(client, h, cv, interview)
    without = await _picker(client, h, cv)
    assert str(seat["deputy"].id) not in without
    assert str(col_emp.user_id) in without  # on the shortlist, never reacted
