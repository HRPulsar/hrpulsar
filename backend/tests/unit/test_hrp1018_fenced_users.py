"""HRP-1018: ``fenced_users`` answers in a fixed number of queries.

It used to ask ``fenced_off_vacancy`` of every user it picked - their
employee row, their candidacy and the matrix, four queries a user. It now
matches the candidacy while picking the users and reads the matrix once,
and must still answer exactly what ``fenced_off_vacancy`` answers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.models import Person
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.recruitment.models import Candidate, CandidateVacancy, Vacancy
from app.modules.recruitment.scope import fenced_off_vacancy, fenced_users
from app.modules.talent_market.models import TalentCandidate, TalentCard
from sqlalchemy import event, update

from tests.unit.test_recruitment_manager_scope import _user
from tests.unit.test_section_gate import _save


async def _apply(db, tenant, vacancy, **candidate):
    cand = Candidate(tenant_id=tenant.id, full_name="C", **candidate)
    db.add(cand)
    await db.commit()
    db.add(CandidateVacancy(tenant_id=tenant.id, candidate_id=cand.id, vacancy_id=vacancy.id))
    await db.commit()


async def _employee(db, tenant, user):
    emp = Employee(user_id=user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    return emp


async def _count(db, tenant, vacancy) -> int:
    db.expunge_all()
    seen: list[str] = []

    def _on_exec(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        seen.append(statement)

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _on_exec)
    try:
        await fenced_users(db, tenant.id, vacancy.id)
    finally:
        event.remove(engine, "before_cursor_execute", _on_exec)
    return len(seen)


async def test_fenced_users_answers_what_fenced_off_vacancy_answers(auth_client, db, tenant):
    vac = Vacancy(tenant_id=tenant.id, title="Seat")
    elsewhere = Vacancy(tenant_id=tenant.id, title="Elsewhere")
    db.add_all([vac, elsewhere])
    await db.commit()
    by_email = await _user(db, tenant, "manager")
    await _apply(db, tenant, vac, email=by_email.email.upper())
    by_person = await _user(db, tenant, "employee")
    person = Person(first_name="P", last_name="Q")
    db.add(person)
    await db.commit()
    await db.execute(update(User).where(User.id == by_person.id).values(person_id=person.id))
    await db.commit()
    await _apply(db, tenant, vac, person_id=person.id)
    # The twin card: one reacted, one only matched.
    card = TalentCard(
        tenant_id=tenant.id,
        title="Seat",
        card_type="vacancy",
        author_id=by_email.id,
        start_date=date(2026, 1, 1),
        status="published",
        is_published=True,
    )
    db.add(card)
    await db.commit()
    vac.talent_card_id = card.id
    await db.commit()
    reacted, matched = await _user(db, tenant, "employee"), await _user(db, tenant, "employee")
    db.add_all(
        [
            TalentCandidate(
                card_id=card.id,
                employee_id=(await _employee(db, tenant, reacted)).id,
                response_at=datetime.now(UTC),
            ),
            TalentCandidate(card_id=card.id, employee_id=(await _employee(db, tenant, matched)).id),
        ]
    )
    await db.commit()
    # Unfenced although candidates: the admin level and the recruiter.
    hr, recruiter = await _user(db, tenant, "hr"), await _user(db, tenant, "recruiter")
    for u in (hr, recruiter):
        await _apply(db, tenant, vac, email=u.email)
    # A candidate on another vacancy only.
    other = await _user(db, tenant, "employee")
    await _apply(db, tenant, elsewhere, email=other.email)
    everyone = [by_email, by_person, reacted, matched, hr, recruiter, other]

    async def _both() -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        one_by_one = {u.id for u in everyone if await fenced_off_vacancy(db, u, vac.id)}
        return {u.id for u in await fenced_users(db, tenant.id, vac.id)}, one_by_one

    batch, one_by_one = await _both()
    assert batch == one_by_one == {by_email.id, by_person.id, reacted.id}
    # HRP-830 REDO: raised to ``manage``, the manager runs hiring on their own
    # divisions only - still fenced off the vacancy they applied to.
    await _save(auth_client, levels={"recruitment": {"manager": "manage"}})
    batch, one_by_one = await _both()
    assert batch == one_by_one == {by_email.id, by_person.id, reacted.id}


async def test_fenced_users_does_not_query_per_candidate(db, tenant):
    vac = Vacancy(tenant_id=tenant.id, title="Seat")
    db.add(vac)
    await db.commit()
    for _ in range(2):
        u = await _user(db, tenant, "employee")
        await _apply(db, tenant, vac, email=u.email)
    few = await _count(db, tenant, vac)
    for _ in range(6):
        u = await _user(db, tenant, "employee")
        await _apply(db, tenant, vac, email=u.email)
    assert len(await fenced_users(db, tenant.id, vac.id)) == 8
    assert await _count(db, tenant, vac) == few
    # The users with their roles, and the matrix once.
    assert few <= 4, few


async def test_no_candidate_user_reads_no_matrix(db, tenant):
    vac = Vacancy(tenant_id=tenant.id, title="Seat")
    db.add(vac)
    await db.commit()
    await _apply(db, tenant, vac, email=f"ext-{uuid.uuid4().hex[:6]}@example.com")
    assert await fenced_users(db, tenant.id, vac.id) == []
    assert await _count(db, tenant, vac) == 1
