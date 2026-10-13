"""HRP-693 REDO: the recruitment side of the talent-market bridge.

(a) After the vacancy's competences change, its Internal candidates block
    showed each employee's percentage against the old set: it read the
    stored ``match_score``, which waits for the pool recompute on the worker
    (the block re-reads before it runs) and which the recompute never
    refreshes for a manual pick below the bar. The block now reads the
    percentage the card's own Candidates table shows, judged live.
(b) The card's Details name the vacancy it was posted from, linked for
    whoever may open it in recruitment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.competence.models import Competence, SkillLevel
from app.modules.employee.models import Employee
from app.modules.recruitment import service
from app.modules.recruitment.schemas import (
    VacancyCompetenceSpec,
    VacancyCompetencesUpdate,
)
from app.modules.talent_market import card_service
from app.modules.talent_market.models import TalentCandidate, TalentCard
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp663_internal_candidates import (
    _competence,
    _queued_recompute,
    _vacancy_with_competence,
)
from tests.unit.test_recruitment_manager_scope import _headers, _user
from tests.unit.test_talent_market_service import add_done_assessment

pytestmark = pytest.mark.asyncio


async def _colleague(db: AsyncSession, tenant) -> Employee:
    u = User(
        email=f"pick-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="Manual",
        last_name="Pick",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.flush()
    emp = Employee(user_id=u.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    return emp


async def _scores(auth_client, vacancy_id) -> dict[str, int | None]:
    res = await auth_client.get(
        f"/api/recruitment/vacancies/{vacancy_id}/internal-candidates"
    )
    assert res.status_code == 200, res.text
    return {i["employee_id"]: i["match_score"] for i in res.json()["items"]}


async def _posted_pool(db: AsyncSession, tenant, user, employee):
    """A posted vacancy on its first competence, a second one waiting.

    ``employee`` clears the first competence and falls short on the second;
    ``manual`` the other way round, below the bar on both, and is picked by
    hand onto the pool with the score of the day it was added."""
    vacancy, first_id = await _vacancy_with_competence(db, tenant.id, user.id)
    second_id = await _competence(db, tenant.id)
    level = SkillLevel(tenant_id=tenant.id, title="L", sort_index=0)
    db.add(level)
    await db.commit()
    first = await db.get(Competence, first_id)
    second = await db.get(Competence, second_id)
    manual = await _colleague(db, tenant)
    await add_done_assessment(db, tenant, employee, first, level, 90)
    await add_done_assessment(db, tenant, employee, second, level, 30)
    await add_done_assessment(db, tenant, manual, first, level, 40)
    await add_done_assessment(db, tenant, manual, second, level, 70)

    posted = await service.post_vacancy_to_talent_market(
        db, tenant.id, vacancy["id"], user.id
    )
    card_id = posted["talent_card_id"]
    db.add(
        TalentCandidate(
            card_id=card_id,
            employee_id=manual.id,
            status="not_matched",
            match_score=40,
        )
    )
    await db.commit()
    return vacancy, card_id, manual, second_id


class TestBlockFollowsTheCompetences:
    async def test_new_competences_new_percentages(
        self, db: AsyncSession, tenant, user, employee, auth_client
    ):
        vacancy, card_id, manual, second_id = await _posted_pool(
            db, tenant, user, employee
        )
        assert await _scores(auth_client, vacancy["id"]) == {
            str(employee.id): 90,
            str(manual.id): 40,
        }

        update = VacancyCompetencesUpdate(
            competences=[VacancyCompetenceSpec(competence_id=second_id)]
        )
        # The block re-reads as soon as the save answers, before the
        # worker's recompute of the pool has run.
        with patch(
            "app.modules.talent_market.tasks.recompute_card_candidates_task.delay"
        ):
            await service.set_vacancy_competences(db, tenant.id, vacancy["id"], update)
        expected = {str(employee.id): 30, str(manual.id): 70}
        assert await _scores(auth_client, vacancy["id"]) == expected
        # The card's own Candidates table says the same.
        card = await card_service.get_card_detail(db, tenant.id, card_id)
        assert {str(c["employee_id"]): c["comp_match"] for c in card["candidates"]} == (
            expected
        )

        # Once the worker has run: the auto row below the new bar is
        # pruned, the manual pick stays with its new percentage.
        async with _queued_recompute(db):
            await service.set_vacancy_competences(db, tenant.id, vacancy["id"], update)
        assert await _scores(auth_client, vacancy["id"]) == {str(manual.id): 70}

    async def test_no_required_competences_no_percentage(
        self, db: AsyncSession, tenant, user, employee, auth_client
    ):
        """Review: the stored score outlived a card left without competence
        requirements - the pool's old percentage, and a manual pick's for
        good. The card's table shows none there; only a card matching on
        specializations alone has a score, the stored one."""
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.talent_market.models import (
            TalentCardCompetence,
            TalentCardSpecialization,
        )
        from sqlalchemy import delete

        vacancy, card_id, manual, _ = await _posted_pool(db, tenant, user, employee)
        await db.execute(
            delete(TalentCardCompetence).where(TalentCardCompetence.card_id == card_id)
        )
        await db.commit()
        assert await _scores(auth_client, vacancy["id"]) == {
            str(employee.id): None,
            str(manual.id): None,
        }

        spec = DictionaryItem(
            tenant_id=tenant.id,
            type="specialization",
            title=f"S-{uuid.uuid4().hex[:4]}",
        )
        db.add(spec)
        await db.flush()
        db.add(TalentCardSpecialization(card_id=card_id, specialization_id=spec.id))
        await db.commit()
        assert await _scores(auth_client, vacancy["id"]) == {
            str(employee.id): 90,
            str(manual.id): 40,
        }


class TestDetailsNameTheVacancy:
    async def _posted(self, db: AsyncSession, tenant, user):
        vacancy, _ = await _vacancy_with_competence(db, tenant.id, user.id)
        posted = await service.post_vacancy_to_talent_market(
            db, tenant.id, vacancy["id"], user.id
        )
        return vacancy, posted["talent_card_id"]

    async def test_linked_for_whoever_may_open_it(
        self, db: AsyncSession, tenant, user, auth_client
    ):
        vacancy, card_id = await self._posted(db, tenant, user)
        res = await auth_client.get(f"/api/talent-market/{card_id}")
        assert res.status_code == 200, res.text
        assert res.json()["source_vacancy"] == {
            "id": str(vacancy["id"]),
            "title": vacancy["title"],
            "can_open": True,
        }

    async def test_plain_text_outside_the_hiring_scope(
        self, db: AsyncSession, tenant, user
    ):
        vacancy, card_id = await self._posted(db, tenant, user)
        # A division head of no division the vacancy is in, and nobody at all.
        head = await _user(db, tenant, "manager")
        for viewer in (head, None):
            found = await service.vacancy_behind_card(db, tenant.id, card_id, viewer)
            # No id for a vacancy the viewer may not follow.
            assert found == {"id": None, "title": vacancy["title"], "can_open": False}

    async def test_an_applicant_is_not_told(
        self, client, db: AsyncSession, tenant, user
    ):
        _, card_id = await self._posted(db, tenant, user)
        applicant = await _user(db, tenant, "employee")
        emp = Employee(
            user_id=applicant.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
        )
        db.add(emp)
        await db.flush()
        card = await db.get(TalentCard, card_id)
        card.status = "published"
        card.is_published = True
        db.add(TalentCandidate(card_id=card_id, employee_id=emp.id, status="matched"))
        await db.commit()

        res = await client.get(
            f"/api/talent-market/{card_id}", headers=_headers(applicant)
        )
        assert res.status_code == 200, res.text
        assert res.json()["source_vacancy"] is None

    async def test_a_card_of_the_market_itself_names_none(
        self, db: AsyncSession, tenant, user, auth_client
    ):
        card = TalentCard(
            tenant_id=tenant.id,
            author_id=user.id,
            title="Own",
            card_type="vacancy",
            start_date=date.today(),
        )
        db.add(card)
        await db.commit()
        res = await auth_client.get(f"/api/talent-market/{card.id}")
        assert res.json()["source_vacancy"] is None
