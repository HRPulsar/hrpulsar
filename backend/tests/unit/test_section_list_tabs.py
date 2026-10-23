"""HRP-823…826 (QA 13.10): the tabs of the four section lists.

Every level opens the caller's own side of the section - ``?tab=mine`` and
``?tab=todo`` (the talent market: ``mine`` / ``appointed``) - answered from
the caller's own employee row whatever their level or read scope: a
division head holding ``manage`` sees only their own there, not their
subtree's. The "To do (N)" count is ``<list path>/todo-count``. Without a
tab every list answers as before.
"""

import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest_asyncio
from app.main import app
from app.modules.assessment.models import (
    PDP,
    Assessment,
    AssessmentGroup,
    AssessmentParticipant,
)
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from app.modules.exam.models import Exam, MassExam
from app.modules.talent_market.models import TalentCandidate, TalentCard
from fastapi.routing import APIRoute

from tests.unit.test_section_gate import _save
from tests.unit.test_work_containers import _user_with_role

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src"


async def _person(db, tenant, code, division_id=None):
    user, token = await _user_with_role(db, tenant, code)
    emp = Employee(
        user_id=user.id, tenant_id=tenant.id, hire_date=date(2026, 1, 15), division_id=division_id
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return SimpleNamespace(user=user, emp=emp, h={"Authorization": f"Bearer {token}"})


@pytest_asyncio.fixture
async def team(db, tenant):
    """A division head - ``manage`` on all four sections by default - and
    one of their people, whom the head's read scope covers."""
    head = await _person(db, tenant, "manager")
    division = Division(tenant_id=tenant.id, name=f"Team {uuid.uuid4().hex[:4]}", manager_id=head.emp.id)
    db.add(division)
    await db.commit()
    member = await _person(db, tenant, "employee", division_id=division.id)
    return SimpleNamespace(head=head, member=member)


def _ids(rows) -> set[str]:
    return {r["id"] for r in rows}


async def test_exam_tabs_answer_for_ones_own_row(auth_client, client, db, tenant, team):
    head, member = team.head, team.member

    def mass(status):
        return MassExam(tenant_id=tenant.id, title=status, initiator_id=head.user.id, status=status)

    sent, done_one, running, draft = mass("sent"), mass("sent"), mass("in_progress"), mass("draft")
    db.add_all([sent, done_one, running, draft])
    await db.commit()

    def exam(m, emp, status):
        return Exam(tenant_id=tenant.id, mass_exam_id=m.id, employee_id=emp.id, status=status)

    own_todo, own_done, own_running = exam(sent, head.emp, "assigned"), exam(done_one, head.emp, "done"), exam(running, head.emp, "in_progress")
    own_draft, theirs = exam(draft, head.emp, "assigned"), exam(sent, member.emp, "assigned")
    db.add_all([own_todo, own_done, own_running, own_draft, theirs])
    await db.commit()

    async def get(path, h):
        r = await client.get(path, headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    # No tab: the read scope as before - the head reads their subtree.
    assert str(theirs.id) in _ids(await get("/api/exams", head.h))
    # My exams: one's own once the mass exam left Draft.
    assert _ids(await get("/api/exams?tab=mine", head.h)) == {str(own_todo.id), str(own_done.id), str(own_running.id)}
    # A tab answers for the caller alone: someone else's employee_id is ignored.
    assert _ids(await get(f"/api/exams?tab=mine&employee_id={member.emp.id}", head.h)) == {
        str(own_todo.id), str(own_done.id), str(own_running.id)
    }
    # To do: one's own still assigned or in progress.
    assert _ids(await get("/api/exams?tab=todo", head.h)) == {str(own_todo.id), str(own_running.id)}
    assert await get("/api/exams/todo-count", head.h) == {"count": 2}

    # The taker's side stays open with the section closed (PERSONAL_PATHS).
    await _save(auth_client, levels={"exams": {"employee": "none"}})
    assert _ids(await get("/api/exams?tab=todo", member.h)) == {str(theirs.id)}
    assert await get("/api/exams/todo-count", member.h) == {"count": 1}
    assert (await client.get("/api/exams?tab=other", headers=member.h)).status_code == 422


async def test_assessment_tabs_answer_for_ones_own_questionnaire(
    client, db, tenant, team, assessment_statuses, assessment_types
):
    head, member = team.head, team.member
    group = AssessmentGroup(tenant_id=tenant.id, title="Mass", initiator_id=head.user.id)
    db.add(group)
    await db.commit()

    def assessment(emp, status, *participants, group_id=None):
        a = Assessment(
            tenant_id=tenant.id,
            employee_id=emp.emp.id,
            type_id=assessment_types["360"].id,
            status_id=assessment_statuses[status].id,
            initiator_id=head.user.id,
            group_id=group_id,
            participants=[
                AssessmentParticipant(user_id=p.user.id, role=role, is_completed=completed)
                for p, role, completed in participants
            ],
        )
        db.add(a)
        return a

    own_sent = assessment(head, "sent", (head, "self", False))
    rating_member = assessment(member, "in_progress", (member, "self", False), (head, "manager", False))
    own_done = assessment(head, "done", (head, "self", True))
    own_draft = assessment(head, "draft", (head, "self", False))
    own_answered = assessment(head, "on_review", (head, "self", True))
    member_only = assessment(member, "sent", (member, "self", False))
    own_in_group = assessment(head, "sent", (head, "self", False), group_id=group.id)
    await db.commit()

    async def ids(path, h):
        r = await client.get(path, headers=h)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert all(i["kind"] == "single" for i in items) or "tab=" not in path
        return {i["assessment"]["id"] for i in items if i["kind"] == "single"}

    # No tab: as before - the head's subtree, the mass one behind its group card.
    assert str(member_only.id) in await ids("/api/assessments-grouped", head.h)
    # My assessments: past Draft, where I take part as Self - mass ones listed one by one.
    assert await ids("/api/assessments-grouped?tab=mine", head.h) == {
        str(a.id) for a in (own_sent, own_done, own_answered, own_in_group)
    }
    # To do: active, any role, my questionnaire not completed.
    assert await ids("/api/assessments-grouped?tab=todo", head.h) == {
        str(a.id) for a in (own_sent, rating_member, own_in_group)
    }
    count = await client.get("/api/assessments-grouped/todo-count", headers=head.h)
    assert count.json() == {"count": 3}
    assert await ids("/api/assessments-grouped?tab=todo", member.h) == {str(rating_member.id), str(member_only.id)}
    assert own_draft.id  # listed nowhere above


async def test_plan_tabs_answer_for_ones_own_plans(client, db, tenant, team):
    head, member = team.head, team.member

    def plan(emp, status):
        p = PDP(tenant_id=tenant.id, title=status, employee_id=emp.emp.id, author_id=head.user.id, status=status)
        db.add(p)
        return p

    todo = [plan(head, s) for s in ("sent", "in_progress", "returned")]
    rest = [plan(head, s) for s in ("review", "done", "cancelled")]
    plan(head, "draft")
    theirs = plan(member, "sent")
    await db.commit()

    async def get(path):
        r = await client.get(path, headers=head.h)
        assert r.status_code == 200, r.text
        return r.json()

    assert str(theirs.id) in _ids(await get("/api/pdp"))
    assert _ids(await get("/api/pdp?tab=mine")) == {str(p.id) for p in todo + rest}
    assert _ids(await get("/api/pdp?tab=todo")) == {str(p.id) for p in todo}
    assert _ids(await get(f"/api/pdp?tab=todo&employee_id={member.emp.id}")) == {str(p.id) for p in todo}
    assert await get("/api/pdp/todo-count") == {"count": 3}


async def test_talent_market_tabs_answer_for_ones_own_candidacies(client, db, tenant, team):
    head, member = team.head, team.member

    def card(status, *candidates):
        c = TalentCard(
            tenant_id=tenant.id,
            title=status,
            card_type="vacancy",
            status=status,
            author_id=member.user.id,
            start_date=date(2026, 1, 1),
        )
        db.add(c)
        for who, cand_status in candidates:
            c.candidates.append(TalentCandidate(employee_id=who.emp.id, status=cand_status))
        return c

    published = card("published", (head, "matched"))
    appointed_draft = card("draft", (head, "appointed"))
    card("draft", (head, "matched"))
    appointed_cancelled = card("cancelled", (head, "appointed"))
    appointed_completed = card("completed", (head, "appointed"))
    card("published", (member, "matched"))
    await db.commit()

    async def ids(tab=""):
        r = await client.post(f"/api/talent-market/search{tab}", json={"limit": 50}, headers=head.h)
        assert r.status_code == 200, r.text
        return _ids(r.json()["items"])

    # I'm a candidate: past Draft with my name on it, or Draft where I am appointed.
    assert await ids("?tab=mine") == {
        str(c.id) for c in (published, appointed_draft, appointed_cancelled, appointed_completed)
    }
    # I'm appointed: appointed, Cancelled aside.
    assert await ids("?tab=appointed") == {str(appointed_draft.id), str(appointed_completed.id)}


async def test_a_tab_never_reaches_into_another_tenant(
    client, db, tenant, team, assessment_statuses, assessment_types
):
    # The head's own items in this tenant - one of each section - against a
    # manager of another workspace naming the head's employee row.
    from app.modules.company.models import Tenant

    head = team.head
    mass = MassExam(tenant_id=tenant.id, title="Sent", initiator_id=head.user.id, status="sent")
    db.add(mass)
    await db.commit()
    db.add_all(
        [
            Exam(tenant_id=tenant.id, mass_exam_id=mass.id, employee_id=head.emp.id, status="assigned"),
            PDP(tenant_id=tenant.id, title="Plan", employee_id=head.emp.id, author_id=head.user.id, status="sent"),
            Assessment(
                tenant_id=tenant.id,
                employee_id=head.emp.id,
                type_id=assessment_types["self"].id,
                status_id=assessment_statuses["sent"].id,
                initiator_id=head.user.id,
                participants=[AssessmentParticipant(user_id=head.user.id, role="self", is_completed=False)],
            ),
        ]
    )
    card = TalentCard(
        tenant_id=tenant.id, title="Card", card_type="vacancy", status="published",
        author_id=head.user.id, start_date=date(2026, 1, 1),
    )
    card.candidates.append(TalentCandidate(employee_id=head.emp.id, status="appointed"))
    db.add(card)
    await db.commit()

    other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(other)
    await db.commit()
    outsider = await _person(db, other, "manager")
    h = outsider.h
    for path in (
        f"/api/exams?tab=todo&employee_id={head.emp.id}",
        f"/api/pdp?tab=todo&employee_id={head.emp.id}",
    ):
        r = await client.get(path, headers=h)
        assert r.status_code == 200 and r.json() == [], path
    r = await client.get("/api/assessments-grouped?tab=todo", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 0
    for tab in ("mine", "appointed"):
        r = await client.post(f"/api/talent-market/search?tab={tab}", json={"limit": 50}, headers=h)
        assert r.status_code == 200 and r.json()["total"] == 0, tab
    for path in ("/api/exams/todo-count", "/api/pdp/todo-count", "/api/assessments-grouped/todo-count"):
        assert (await client.get(path, headers=h)).json() == {"count": 0}, path
    # ...while the head's own counts see them.
    for path in ("/api/exams/todo-count", "/api/pdp/todo-count", "/api/assessments-grouped/todo-count"):
        assert (await client.get(path, headers=head.h)).json() == {"count": 1}, path


def test_the_urls_the_tabs_call_are_the_routers():
    routes = {(r.path, m) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    for path in ("/api/exams/todo-count", "/api/assessments-grouped/todo-count", "/api/pdp/todo-count"):
        assert (path, "GET") in routes, path
    pages = {
        name: (FRONTEND / "app" / "(dashboard)" / name / "page.tsx").read_text()
        for name in ("exams", "assessments", "development", "talent-market")
    }
    assert '"/exams/todo-count"' in pages["exams"]
    assert '"/assessments-grouped/todo-count"' in pages["assessments"]
    assert '"/pdp/todo-count"' in pages["development"]
    # Each page sends its tab to the list it already reads.
    assert "`/exams?tab=${tab}`" in pages["exams"]
    assert 'params.set("tab", tab)' in pages["assessments"]
    assert "`/pdp?tab=${tab}`" in pages["development"]
    assert "`/talent-market/search?tab=${tab}`" in pages["talent-market"]


def test_a_letter_to_the_person_opens_the_tab_that_holds_it():
    # Action-required letters open "To do", closed ones "My ..."; the
    # reviewer's letters open the plan itself - the tabs are one's own, so
    # none of them holds a plan the reviewer does not own (HRP-1048).
    from app.core import email_templates as e

    assert "/exams?tab=todo" in e.render_exam_assigned_email("Exam")[1]
    assert "/exams?tab=mine" in e.render_exam_results_email("Exam", 1, 1)[1]
    assert "/development?tab=todo" in e.render_pdp_sent_email("Ann", pdp_title="Plan")[1]
    assert "/development?tab=todo" in e.render_pdp_returned_email("Ann", "Plan")[1]
    for render in (
        e.render_pdp_review_submitted_email,
        e.render_pdp_done_to_reviewer_email,
        e.render_pdp_cancelled_to_reviewer_email,
    ):
        html = render("Ann", "Plan", pdp_id="p-42")[1]
        assert "/development/p-42" in html, render.__name__
        assert "/development?tab=" not in html, render.__name__
