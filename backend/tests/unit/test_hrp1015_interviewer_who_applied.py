"""HRP-1015: an interviewer who has since applied to the vacancy keeps their
name on the interview.

HRP-971 leaves a candidate for a vacancy out of its interviewer picker, but
someone named before they applied stays on the interview - only people
added later are checked. The interview page used to build the names from the
picker's list, so that interviewer showed up nameless. The names now come
with the interview (HRP-1019), whatever the picker offers.
"""

from __future__ import annotations

from app.modules.recruitment.models import Interview, InterviewInterviewer

from tests.unit.test_hrp971_own_candidacy_scope import seat  # noqa: F401 - fixture
from tests.unit.test_recruitment_manager_scope import _headers, _user


async def test_the_interview_names_whom_the_picker_leaves_out(client, db, tenant, seat):  # noqa: F811
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
