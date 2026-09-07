"""Internal candidates in recruitment (HRP-663) + the talent-market bridge (HRP-667).

Two facts the product could not state before:

* a candidate who already works here is marked as such everywhere a
  recruiter looks at candidates, not only in the global list; and
* a vacancy can be posted to the internal talent market, which is what
  produces the "who inside already fits" shortlist.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import Person
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.recruitment import service
from app.modules.recruitment.models import Candidate, VacancyCompetence
from app.modules.recruitment.schemas import (
    CandidateCanonicalPatch,
    CandidateManualCreate,
    CandidateVacancyCreate,
    VacancyCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@contextlib.asynccontextmanager
async def _queued_recompute(db: AsyncSession):
    """Capture ``recompute_card_candidates_task.delay`` and run it inline.

    HRP-705 moved the pool recompute off the request onto Celery. The
    worker would open its own session, which a unit test does not have, so
    the mock records the arguments and the body runs on the test session
    once the block exits. ``calls`` is exposed so a test can assert what
    the save queued.
    """
    from app.modules.talent_market.matching import _auto_populate_candidates

    with patch(
        "app.modules.talent_market.tasks.recompute_card_candidates_task.delay"
    ) as delay:
        yield delay
    for call in delay.call_args_list:
        tenant_id_str, card_id_str = call.args
        await _auto_populate_candidates(
            db, uuid.UUID(tenant_id_str), uuid.UUID(card_id_str)
        )


async def _make_vacancy(db: AsyncSession, tenant_id, user_id) -> dict:
    await service.seed_default_recruitment_stages(db, tenant_id)
    await db.commit()
    return await service.create_vacancy(
        db,
        tenant_id,
        user_id,
        VacancyCreate(title=f"V-{uuid.uuid4().hex[:6]}"),
    )


async def _make_internal_candidate(db: AsyncSession, tenant_id) -> Candidate:
    """A Person → User → Employee chain, plus the Candidate row on it."""
    person = Person(first_name="Inside", last_name="Hire")
    db.add(person)
    await db.flush()
    u = User(
        email=f"inside-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Inside",
        last_name="Hire",
        tenant_id=tenant_id,
        person_id=person.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    db.add(
        Employee(
            user_id=u.id,
            tenant_id=tenant_id,
            position_title="Engineer",
            hire_date=date(2024, 1, 15),
            status="active",
        )
    )
    candidate = Candidate(
        tenant_id=tenant_id,
        person_id=person.id,
        full_name="Inside Hire",
        email=u.email,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)
    return candidate


class TestIsEmployeeReachesEveryCandidateSurface:
    async def test_vacancy_table_and_card_flag_the_employee(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        internal = await _make_internal_candidate(db, tenant.id)
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=internal.id, vacancy_id=vacancy["id"]),
        )
        external = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="Outside Hire", email="outside@example.com"
            ),
        )

        rows, _ = await service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy["id"]
        )
        by_name = {r["candidate_name"]: r for r in rows}
        assert by_name["Inside Hire"]["is_employee"] is True
        # The guard that matters: a NULL person_id must not be swept up by
        # the bulk IN(...) lookup.
        assert by_name["Outside Hire"]["is_employee"] is False

        card = await service.get_candidate_full_card(db, tenant.id, internal.id)
        assert card["is_employee"] is True
        outside = await service.get_candidate_full_card(db, tenant.id, external["id"])
        assert outside["is_employee"] is False

    async def test_patch_and_manual_add_keep_the_flag_on_the_body(
        self, db: AsyncSession, tenant, user
    ):
        """Every candidate body the card merges has to carry the flag.

        The card does ``setCard({...prev, ...response})`` after a save, so
        a body without ``is_employee`` reads as ``false`` and drops the
        badge until the page is reloaded.
        """
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        internal = await _make_internal_candidate(db, tenant.id)
        # Manual add, "link the existing row" branch — the dialog opens the
        # card straight from this body.
        linked = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="Inside Hire",
                email=internal.email,
                link_candidate_id=internal.id,
            ),
        )
        assert linked["is_employee"] is True

        # The personal block: a plain field edit.
        patched = await service.patch_candidate(
            db,
            tenant.id,
            internal.id,
            CandidateCanonicalPatch(current_position="Staff Engineer"),
        )
        assert patched["is_employee"] is True

        # The parsed-resume editor: same endpoint, same body, same badge.
        reparsed = await service.patch_candidate(
            db,
            tenant.id,
            internal.id,
            CandidateCanonicalPatch(
                parsed_resume_jsonb={"experience": [{"position": "Engineer"}]}
            ),
        )
        assert reparsed["is_employee"] is True

        external = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(
                full_name="Outside Hire", email="outside-patch@example.com"
            ),
        )
        assert external["is_employee"] is False
        outside_patched = await service.patch_candidate(
            db,
            tenant.id,
            external["id"],
            CandidateCanonicalPatch(current_position="Contractor"),
        )
        assert outside_patched["is_employee"] is False

    async def test_bulk_lookup_matches_the_single_row_helper(
        self, db: AsyncSession, tenant
    ):
        from app.modules.recruitment.candidate_service import (
            _check_is_employee,
            _employee_person_ids,
        )

        internal = await _make_internal_candidate(db, tenant.id)
        assert await _employee_person_ids(
            db, tenant.id, [internal.person_id, None]
        ) == {internal.person_id}
        assert await _check_is_employee(db, tenant.id, internal.person_id) is True
        assert await _check_is_employee(db, tenant.id, None) is False


async def _seed_pair(db: AsyncSession, tenant_id, spec, *, grade_title: str):
    """A configured (spec, grade) pair wired to one competence."""
    from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization

    grade = DictionaryItem(
        type="grade", tenant_id=tenant_id, title=grade_title, is_active=True
    )
    db.add(grade)
    await db.flush()
    gs = GradeSpecialization(
        tenant_id=tenant_id, grade_id=grade.id, specialization_id=spec.id
    )
    db.add(gs)
    group = CompetenceGroup(tenant_id=tenant_id, title=f"G-{uuid.uuid4().hex[:4]}")
    db.add(group)
    await db.flush()
    comp = Competence(
        tenant_id=tenant_id, group_id=group.id, title=f"C-{uuid.uuid4().hex[:4]}"
    )
    sl = SkillLevel(
        tenant_id=tenant_id, title=f"L-{uuid.uuid4().hex[:4]}", sort_index=0
    )
    db.add_all([comp, sl])
    await db.flush()
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()
    return grade, comp


class TestTalentMarketBridge:
    async def test_refuses_without_library_competences(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        with pytest.raises(AppError) as exc:
            await service.post_vacancy_to_talent_market(
                db, tenant.id, vacancy["id"], user.id
            )
        assert exc.value.code == "vacancy_has_no_library_competences"

    async def test_posts_once_and_links_the_card(self, db: AsyncSession, tenant, user):
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.talent_market.models import TalentCard, TalentCardCompetence
        from sqlalchemy import select

        vacancy = await _make_vacancy(db, tenant.id, user.id)
        group = CompetenceGroup(tenant_id=tenant.id, title="Engineering")
        db.add(group)
        await db.flush()
        competence = Competence(tenant_id=tenant.id, group_id=group.id, title="Python")
        db.add(competence)
        await db.flush()
        db.add(
            VacancyCompetence(
                tenant_id=tenant.id,
                vacancy_id=vacancy["id"],
                competence_id=competence.id,
                skill_level_ids=[],
            )
        )
        await db.commit()

        before = await service.get_vacancy_internal_candidates(
            db, tenant.id, vacancy["id"]
        )
        assert before["talent_card_id"] is None
        assert before["has_library_competences"] is True

        posted = await service.post_vacancy_to_talent_market(
            db, tenant.id, vacancy["id"], user.id
        )
        card_id = posted["talent_card_id"]
        assert card_id is not None
        card = await db.get(TalentCard, card_id)
        assert card is not None
        # Draft, never published: publishing mails every matched employee
        # and that stays the talent market's own decision.
        assert card.card_type == "vacancy"
        assert card.status == "draft"
        copied = (
            (
                await db.execute(
                    select(TalentCardCompetence).where(
                        TalentCardCompetence.card_id == card_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [c.competence_id for c in copied] == [competence.id]

        with pytest.raises(AppError) as exc:
            await service.post_vacancy_to_talent_market(
                db, tenant.id, vacancy["id"], user.id
            )
        assert exc.value.code == "vacancy_already_in_talent_market"

    async def test_carries_spec_grade_and_keeps_them_through_an_edit(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-683: the card gets an Experience axis, and editing it later
        no longer wipes what the bridge copied off the vacancy."""
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.recruitment.models import (
            vacancy_grades_table,
            vacancy_specializations_table,
        )
        from app.modules.talent_market import service as tm_service
        from app.modules.talent_market.models import TalentCardSpecialization
        from app.modules.talent_market.schemas import RequiredSpecializationUpdate
        from sqlalchemy import insert, select

        vacancy = await _make_vacancy(db, tenant.id, user.id)
        spec = DictionaryItem(
            type="specialization",
            tenant_id=tenant.id,
            title="Backend",
            is_active=True,
        )
        db.add(spec)
        await db.flush()
        middle, mid_comp = await _seed_pair(db, tenant.id, spec, grade_title="Middle")
        senior, sr_comp = await _seed_pair(db, tenant.id, spec, grade_title="Senior")
        # Only Middle is on the vacancy; Senior exists to edit into later.
        await db.execute(
            insert(vacancy_specializations_table),
            [{"vacancy_id": vacancy["id"], "specialization_id": spec.id}],
        )
        await db.execute(
            insert(vacancy_grades_table),
            [{"vacancy_id": vacancy["id"], "grade_id": middle.id}],
        )

        # The vacancy asks for a competence the ladder does not imply — it
        # is the one that used to vanish on the first spec edit.
        group = CompetenceGroup(tenant_id=tenant.id, title="Extra")
        db.add(group)
        await db.flush()
        own = Competence(tenant_id=tenant.id, group_id=group.id, title="Kubernetes")
        db.add(own)
        await db.flush()
        db.add(
            VacancyCompetence(
                tenant_id=tenant.id,
                vacancy_id=vacancy["id"],
                competence_id=own.id,
                skill_level_ids=[],
            )
        )
        await db.commit()

        posted = await service.post_vacancy_to_talent_market(
            db, tenant.id, vacancy["id"], user.id
        )
        card_id = posted["talent_card_id"]
        spec_rows = (
            (
                await db.execute(
                    select(TalentCardSpecialization).where(
                        TalentCardSpecialization.card_id == card_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [(r.specialization_id, r.grade_id) for r in spec_rows] == [
            (spec.id, middle.id)
        ]
        # No tenure floor exists on a vacancy to copy.
        assert spec_rows[0].min_experience_years is None

        await tm_service.update_required_specialization(
            db,
            tenant.id,
            card_id,
            spec_rows[0].id,
            RequiredSpecializationUpdate(specialization_id=spec.id, grade_id=senior.id),
        )
        detail = await tm_service.get_card_detail(db, tenant.id, card_id)
        ids = {c["competence_id"] for c in detail["competences"]}
        # Copied requirement survives; Senior's competence joins it; the
        # Middle pair implied nothing that was ever written to this card.
        assert own.id in ids
        assert sr_comp.id in ids
        assert mid_comp.id not in ids

    async def test_failure_mid_bridge_leaves_no_orphan_card(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        """A crash between card construction and the vacancy back-link
        rolls the card back too. The delegated ``create_card`` version
        committed the card on its own, stranding an unlinked draft."""
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.talent_market import models as tm_models
        from sqlalchemy import func, select

        vacancy = await _make_vacancy(db, tenant.id, user.id)
        group = CompetenceGroup(tenant_id=tenant.id, title="Engineering")
        db.add(group)
        await db.flush()
        competence = Competence(tenant_id=tenant.id, group_id=group.id, title="Python")
        db.add(competence)
        await db.flush()
        db.add(
            VacancyCompetence(
                tenant_id=tenant.id,
                vacancy_id=vacancy["id"],
                competence_id=competence.id,
                skill_level_ids=[],
            )
        )
        await db.commit()

        # Pin plain values: rollback expires the ORM instances and a
        # lazy refresh outside a greenlet context raises MissingGreenlet.
        tenant_id, user_id, vacancy_id = tenant.id, user.id, vacancy["id"]

        def boom(self, *args, **kwargs):
            raise RuntimeError("mid-bridge crash")

        monkeypatch.setattr(tm_models.TalentCardCompetence, "__init__", boom)
        with pytest.raises(RuntimeError):
            await service.post_vacancy_to_talent_market(
                db, tenant_id, vacancy_id, user_id
            )
        await db.rollback()

        orphan_count = (
            await db.execute(
                select(func.count(tm_models.TalentCard.id)).where(
                    tm_models.TalentCard.tenant_id == tenant_id
                )
            )
        ).scalar()
        assert orphan_count == 0
        after = await service.get_vacancy_internal_candidates(db, tenant_id, vacancy_id)
        assert after["talent_card_id"] is None

    async def test_matcher_failure_rolls_the_posting_back(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        """HRP-654 review: the card and back-link commit before the
        matcher runs, so a matcher crash used to strand a posted-but-empty
        card that every retry answered 409 for — with the only repair
        endpoint behind roles the recruiter does not have."""
        from app.modules.talent_market import matching

        vacancy, _ = await _vacancy_with_competence(db, tenant.id, user.id)
        tenant_id, user_id, vacancy_id = tenant.id, user.id, vacancy["id"]

        async def boom(*args, **kwargs):
            raise RuntimeError("matcher blew up")

        monkeypatch.setattr(matching, "_auto_populate_candidates", boom)
        with pytest.raises(RuntimeError, match="matcher blew up"):
            await service.post_vacancy_to_talent_market(
                db, tenant_id, vacancy_id, user_id
            )

        after = await service.get_vacancy_internal_candidates(db, tenant_id, vacancy_id)
        assert after["talent_card_id"] is None

        # And the retry starts clean once the matcher works again.
        monkeypatch.undo()
        posted = await service.post_vacancy_to_talent_market(
            db, tenant_id, vacancy_id, user_id
        )
        assert posted["talent_card_id"] is not None


async def _competence(db: AsyncSession, tenant_id) -> uuid.UUID:
    """One library competence, ready to hang on a vacancy."""
    from app.modules.competence.models import Competence, CompetenceGroup

    group = CompetenceGroup(tenant_id=tenant_id, title=f"G-{uuid.uuid4().hex[:4]}")
    db.add(group)
    await db.flush()
    comp = Competence(
        tenant_id=tenant_id, group_id=group.id, title=f"C-{uuid.uuid4().hex[:4]}"
    )
    db.add(comp)
    await db.flush()
    return comp.id


async def _vacancy_with_competence(db: AsyncSession, tenant_id, user_id):
    vacancy = await _make_vacancy(db, tenant_id, user_id)
    competence_id = await _competence(db, tenant_id)
    db.add(
        VacancyCompetence(
            tenant_id=tenant_id,
            vacancy_id=vacancy["id"],
            competence_id=competence_id,
            skill_level_ids=[],
        )
    )
    await db.commit()
    return vacancy, competence_id


class TestInternalSearchSwitch:
    """HRP-678: the recruiter's per-vacancy opt-out of the internal search."""

    async def test_new_vacancies_are_searchable(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        # The read schema carries the switch, or the form cannot show it.
        assert vacancy["internal_search_allowed"] is True
        payload = await service.get_vacancy_internal_candidates(
            db, tenant.id, vacancy["id"]
        )
        assert payload["internal_search_allowed"] is True

    async def test_switch_off_refuses_the_post_and_back_on_allows_it(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.schemas import VacancyUpdate

        vacancy, _ = await _vacancy_with_competence(db, tenant.id, user.id)
        await service.update_vacancy(
            db, tenant.id, vacancy["id"], VacancyUpdate(internal_search_allowed=False)
        )

        payload = await service.get_vacancy_internal_candidates(
            db, tenant.id, vacancy["id"]
        )
        # The block needs the reason, not only a dead button.
        assert payload["internal_search_allowed"] is False
        assert payload["has_library_competences"] is True

        with pytest.raises(AppError) as exc:
            await service.post_vacancy_to_talent_market(
                db, tenant.id, vacancy["id"], user.id
            )
        assert exc.value.code == "vacancy_internal_search_disabled"
        assert exc.value.status_code == 422
        # Refused, not half-done: no card was minted on the way out.
        assert (
            await service.get_vacancy_internal_candidates(db, tenant.id, vacancy["id"])
        )["talent_card_id"] is None

        await service.update_vacancy(
            db, tenant.id, vacancy["id"], VacancyUpdate(internal_search_allowed=True)
        )
        posted = await service.post_vacancy_to_talent_market(
            db, tenant.id, vacancy["id"], user.id
        )
        assert posted["talent_card_id"] is not None
        assert posted["internal_search_allowed"] is True


class TestVacancyCompetenceSyncKeepsTheCardInStep:
    """HRP-693: editing the requisition edits its internal twin."""

    async def test_clearing_competences_while_posted_is_refused(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-654 review: a posted card synced to zero competences flips
        the matcher to spec-only mode and pools the whole specialization —
        the exact state the bridge refuses to create in the first place."""
        from app.modules.recruitment.schemas import VacancyCompetencesUpdate

        vacancy, competence_id = await _vacancy_with_competence(db, tenant.id, user.id)
        # Pin plain values: the raised path rolls the session back and a
        # lazy refresh outside a greenlet context blows up (same trick as
        # test_failure_mid_bridge_leaves_no_orphan_card).
        tenant_id, vacancy_id = tenant.id, vacancy["id"]
        await service.post_vacancy_to_talent_market(db, tenant_id, vacancy_id, user.id)

        with pytest.raises(AppError) as exc:
            await service.set_vacancy_competences(
                db,
                tenant_id,
                vacancy_id,
                VacancyCompetencesUpdate(competences=[]),
            )
        assert exc.value.code == "vacancy_competences_required_while_posted"
        assert exc.value.status_code == 422
        await db.rollback()

        # The vacancy (and therefore the card) keeps its old requirement.
        rows = await service.list_vacancy_competences(db, tenant_id, vacancy_id)
        assert [r["competence_id"] for r in rows] == [competence_id]

    async def test_card_and_pool_follow_the_new_competence_set(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.employee.models import Employee
        from app.modules.recruitment.schemas import (
            VacancyCompetenceSpec,
            VacancyCompetencesUpdate,
        )
        from app.modules.talent_market.models import (
            TalentCandidate,
            TalentCardCompetence,
        )
        from sqlalchemy import select

        vacancy, first = await _vacancy_with_competence(db, tenant.id, user.id)
        posted = await service.post_vacancy_to_talent_market(
            db, tenant.id, vacancy["id"], user.id
        )
        card_id = posted["talent_card_id"]

        # Two pool rows the recompute must treat differently: an auto
        # `matched` row that no longer qualifies is pruned, a manual
        # `not_matched` pick stays and keeps its badge signal.
        candidate = await _make_internal_candidate(db, tenant.id)
        employee = (
            (await db.execute(select(Employee).where(Employee.tenant_id == tenant.id)))
            .scalars()
            .first()
        )
        assert employee is not None and candidate is not None
        db.add(
            TalentCandidate(card_id=card_id, employee_id=employee.id, status="matched")
        )
        await db.commit()

        second = await _competence(db, tenant.id)
        await db.commit()
        async with _queued_recompute(db) as delay:
            await service.set_vacancy_competences(
                db,
                tenant.id,
                vacancy["id"],
                VacancyCompetencesUpdate(
                    competences=[VacancyCompetenceSpec(competence_id=second)]
                ),
            )
            # HRP-705: the requirements sync stayed in the request, the
            # roster scan is queued for the card that was just synced.
            delay.assert_called_once_with(str(tenant.id), str(card_id))

        on_card = {
            r.competence_id
            for r in (
                await db.execute(
                    select(TalentCardCompetence).where(
                        TalentCardCompetence.card_id == card_id
                    )
                )
            )
            .scalars()
            .all()
        }
        assert on_card == {second}
        assert first not in on_card

        # The pool was recomputed, not left pointing at the old question.
        pool = (
            (
                await db.execute(
                    select(TalentCandidate).where(TalentCandidate.card_id == card_id)
                )
            )
            .scalars()
            .all()
        )
        assert [r.employee_id for r in pool if r.status == "matched"] == []

        # A manual pick below the bar survives and reaches the UI with the
        # status the badge reads.
        db.add(
            TalentCandidate(
                card_id=card_id, employee_id=employee.id, status="not_matched"
            )
        )
        await db.commit()
        rows = (
            await service.get_vacancy_internal_candidates(db, tenant.id, vacancy["id"])
        )["items"]
        assert [r["status"] for r in rows] == ["not_matched"]
        assert rows[0]["match_score"] is None

    async def test_a_vacancy_without_a_card_touches_no_talent_market_rows(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.schemas import (
            VacancyCompetenceSpec,
            VacancyCompetencesUpdate,
        )
        from app.modules.talent_market.models import TalentCard
        from sqlalchemy import func, select

        vacancy, _ = await _vacancy_with_competence(db, tenant.id, user.id)
        competence_id = await _competence(db, tenant.id)
        await db.commit()
        async with _queued_recompute(db) as delay:
            await service.set_vacancy_competences(
                db,
                tenant.id,
                vacancy["id"],
                VacancyCompetencesUpdate(
                    competences=[VacancyCompetenceSpec(competence_id=competence_id)]
                ),
            )
        # HRP-705: nothing to recompute, so nothing is queued either.
        delay.assert_not_called()
        cards = (
            await db.execute(
                select(func.count(TalentCard.id)).where(
                    TalentCard.tenant_id == tenant.id
                )
            )
        ).scalar()
        assert cards == 0

    async def test_switch_off_freezes_the_card_sync(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-678 gates the sync too: an excluded vacancy is never
        re-matched, its card keeps the last state instead of being
        rebuilt behind the switch (review fix on 5738fefd)."""
        from app.modules.recruitment.models import Vacancy
        from app.modules.recruitment.schemas import (
            VacancyCompetenceSpec,
            VacancyCompetencesUpdate,
        )
        from app.modules.talent_market.models import TalentCardCompetence
        from sqlalchemy import select

        vacancy, first = await _vacancy_with_competence(db, tenant.id, user.id)
        posted = await service.post_vacancy_to_talent_market(
            db, tenant.id, vacancy["id"], user.id
        )
        card_id = posted["talent_card_id"]

        row = await db.get(Vacancy, vacancy["id"])
        assert row is not None
        row.internal_search_allowed = False
        await db.commit()

        second = await _competence(db, tenant.id)
        await db.commit()
        await service.set_vacancy_competences(
            db,
            tenant.id,
            vacancy["id"],
            VacancyCompetencesUpdate(
                competences=[VacancyCompetenceSpec(competence_id=second)]
            ),
        )

        on_card = {
            r.competence_id
            for r in (
                await db.execute(
                    select(TalentCardCompetence).where(
                        TalentCardCompetence.card_id == card_id
                    )
                )
            )
            .scalars()
            .all()
        }
        # The card still carries the set it was posted with.
        assert on_card == {first}


class TestVacancyCanStartExcluded:
    """HRP-678: the create form carries the switch, not only the edit form."""

    async def test_create_honours_the_switch(self, db: AsyncSession, tenant, user):
        await service.seed_default_recruitment_stages(db, tenant.id)
        await db.commit()
        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(title="Sensitive backfill", internal_search_allowed=False),
        )
        assert vacancy["internal_search_allowed"] is False
        with pytest.raises(AppError) as exc:
            await service.post_vacancy_to_talent_market(
                db, tenant.id, vacancy["id"], user.id
            )
        assert exc.value.code == "vacancy_internal_search_disabled"


class TestRecomputeTaskBody:
    """HRP-705: the Celery task itself, not a stand-in for it.

    ``_queued_recompute`` above re-implements the task body (it calls
    ``_auto_populate_candidates`` directly) so the save tests can keep
    asserting on the pool. That leaves the real body -- the UUID parsing,
    the session ``_run`` opens, the commit -- executed by nothing. This
    runs it.
    """

    async def test_task_rebuilds_the_pool_on_its_own_session(
        self, db: AsyncSession, session_factory, tenant, user
    ):
        from app.modules.talent_market.models import TalentCandidate, TalentCard
        from app.modules.talent_market.tasks import recompute_card_candidates_task
        from sqlalchemy import select

        vacancy, _ = await _vacancy_with_competence(db, tenant.id, user.id)
        posted = await service.post_vacancy_to_talent_market(
            db, tenant.id, vacancy["id"], user.id
        )
        card_id = posted["talent_card_id"]

        # An employee who does not clear the bar, parked in the pool as
        # `matched`: a recompute that really runs has to prune them.
        await _make_internal_candidate(db, tenant.id)
        employee = (
            (await db.execute(select(Employee).where(Employee.tenant_id == tenant.id)))
            .scalars()
            .first()
        )
        assert employee is not None
        db.add(
            TalentCandidate(card_id=card_id, employee_id=employee.id, status="matched")
        )
        card = await db.get(TalentCard, card_id)
        assert card is not None
        card.last_matched_at = None
        await db.commit()

        # Call the real task. Only the engine construction is swapped for
        # the test factory -- `_run`, the session it opens, the UUID
        # parsing and the commit are the task's own code. The coroutine is
        # awaited out here because the shipped runner uses asyncio.run,
        # which cannot nest inside the test's running loop.
        captured: dict = {}

        def _fake_runner(coro_factory):
            captured["coro"] = coro_factory(session_factory)

        with patch(
            "app.modules.talent_market.tasks._run_with_async_session", _fake_runner
        ):
            recompute_card_candidates_task(str(tenant.id), str(card_id))
        assert "coro" in captured, "the task never handed its body to the runner"
        await captured["coro"]

        # Drop this session's snapshot and its cached objects, so what the
        # worker session committed is what gets read back.
        await db.rollback()
        db.expire_all()

        pool = (
            (
                await db.execute(
                    select(TalentCandidate).where(TalentCandidate.card_id == card_id)
                )
            )
            .scalars()
            .all()
        )
        assert [r.employee_id for r in pool if r.status == "matched"] == []
        refreshed = await db.get(TalentCard, card_id)
        assert refreshed is not None
        assert refreshed.last_matched_at is not None


# ---------------------------------------------------------------------------
# HRP-711 — the shortlist becomes the pipeline
# ---------------------------------------------------------------------------


async def _employee_with_profile(
    db: AsyncSession, tenant_id, *, with_person: bool = True
):
    """An employee whose profile has something to say on a resume.

    One spell of current employment, one previous employer, a degree, a
    certificate and a required competence — one row per section of the
    HRP-711 mapping table, so a dropped section fails loudly.
    """
    from app.modules.company.models import Division
    from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.employee.models import (
        Course,
        Education,
        PreviousEmployment,
        WorkExperience,
    )
    from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
    from app.modules.position.models import Position as PositionModel

    suffix = uuid.uuid4().hex[:8]
    person = None
    if with_person:
        person = Person(first_name="Vova", last_name="Probelov")
        db.add(person)
        await db.flush()
    u = User(
        email=f"vova-{suffix}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Vova",
        last_name="Probelov",
        tenant_id=tenant_id,
        person_id=person.id if person else None,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()

    spec = DictionaryItem(
        type="specialization", tenant_id=tenant_id, title=f"Sales-{suffix}"
    )
    grade = DictionaryItem(type="grade", tenant_id=tenant_id, title=f"Junior-{suffix}")
    division = Division(tenant_id=tenant_id, name="Go-to-Market")
    db.add_all([spec, grade, division])
    await db.flush()
    position = PositionModel(
        tenant_id=tenant_id,
        title=f"SDR-{suffix}",
        specialization_id=spec.id,
        grade_id=grade.id,
    )
    db.add(position)
    await db.flush()
    gs = GradeSpecialization(
        tenant_id=tenant_id, grade_id=grade.id, specialization_id=spec.id
    )
    group = CompetenceGroup(tenant_id=tenant_id, title=f"Sales-{suffix}")
    db.add_all([gs, group])
    await db.flush()
    comp = Competence(tenant_id=tenant_id, group_id=group.id, title="Product knowledge")
    level = SkillLevel(tenant_id=tenant_id, title="Basic", sort_index=0)
    db.add_all([comp, level])
    await db.flush()
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=level.id,
        )
    )

    employee = Employee(
        user_id=u.id,
        tenant_id=tenant_id,
        division_id=division.id,
        position_id=position.id,
        position_title="Sales Development Representative",
        hire_date=date(2023, 3, 1),
        status="active",
    )
    db.add(employee)
    await db.flush()
    db.add_all(
        [
            WorkExperience(
                tenant_id=tenant_id,
                employee_id=employee.id,
                division_id=division.id,
                position_id=position.id,
                description="Outbound prospecting",
                start_date=date(2023, 3, 1),
            ),
            PreviousEmployment(
                tenant_id=tenant_id,
                employee_id=employee.id,
                company_name="Old Corp",
                position="Support agent",
                description="First line",
                start_date=date(2021, 1, 1),
                end_date=date(2023, 1, 31),
            ),
            Education(
                tenant_id=tenant_id,
                employee_id=employee.id,
                institution="State University",
                degree="BSc",
                field_of_study="Economics",
                start_date=date(2016, 9, 1),
                end_date=date(2020, 6, 30),
            ),
            Course(
                tenant_id=tenant_id,
                employee_id=employee.id,
                title="SPIN Selling",
                provider="Sales Academy",
                completed_date=date(2024, 4, 1),
            ),
        ]
    )
    await db.commit()
    await db.refresh(employee)
    return employee


async def _posted_vacancy_with_roster(db: AsyncSession, tenant_id, user_id, employee):
    """A vacancy posted to the talent market, with this employee on it."""
    from app.modules.talent_market.models import TalentCandidate

    vacancy, _ = await _vacancy_with_competence(db, tenant_id, user_id)
    posted = await service.post_vacancy_to_talent_market(
        db, tenant_id, vacancy["id"], user_id
    )
    card_id = posted["talent_card_id"]
    db.add(
        TalentCandidate(card_id=card_id, employee_id=employee.id, status="not_matched")
    )
    await db.commit()
    return vacancy, card_id


class TestAddInternalCandidateToVacancy:
    """HRP-711: the Add action under the Internal candidates block."""

    async def test_roster_employee_lands_in_the_pipeline_with_the_chip(
        self, db: AsyncSession, tenant, user
    ):
        employee = await _employee_with_profile(db, tenant.id)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)

        added = await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, vacancy["id"], employee.id
        )
        assert added["is_employee"] is True
        assert added["source"] == "internal"
        assert added["candidate_vacancy_id"] is not None
        assert added["current_position"] == "Sales Development Representative"

        # The chip has to burn in the vacancy table and on the card, not
        # only in the body the button got back.
        rows, _ = await service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy["id"]
        )
        assert [r["is_employee"] for r in rows if r["candidate_id"] == added["id"]] == [
            True
        ]
        card = await service.get_candidate_full_card(db, tenant.id, added["id"])
        assert card["is_employee"] is True

        # And the block now knows the row is done, so it can link instead
        # of offering the button again.
        block = await service.get_vacancy_internal_candidates(
            db, tenant.id, vacancy["id"]
        )
        mine = [i for i in block["items"] if i["employee_id"] == employee.id]
        assert [i["candidate_id"] for i in mine] == [added["id"]]

    async def test_the_profile_becomes_the_resume(self, db: AsyncSession, tenant, user):
        """The ticket's mapping table, section by section."""
        employee = await _employee_with_profile(db, tenant.id)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)
        added = await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, vacancy["id"], employee.id
        )
        parsed = added["parsed_resume_jsonb"]

        # Experience: current employment first (it is still open), then
        # the previous employer. The company on the current spell is us.
        assert [e["company"] for e in parsed["experience"]] == [
            tenant.name,
            "Old Corp",
        ]
        current = parsed["experience"][0]
        assert current["end_date"] is None
        assert current["start_date"] == "2023-03-01"
        assert "Go-to-Market" in (current["description"] or "")
        assert "Outbound prospecting" in (current["description"] or "")
        assert parsed["experience"][1]["position"] == "Support agent"

        assert parsed["education"] == [
            {
                "institution": "State University",
                "degree": "BSc",
                "field": "Economics",
                "start_date": "2016-09-01",
                "end_date": "2020-06-30",
            }
        ]
        assert parsed["certificates"] == [
            {
                "name": "SPIN Selling",
                "issuer": "Sales Academy",
                "issued_at": "2024-04-01",
            }
        ]
        # Competences of the current position, with the level spelled out.
        assert parsed["skills"] == ["Product knowledge — Basic"]
        assert parsed["contacts"]["email"] == added["email"]
        # Never invented — the profile has no summary to give.
        assert parsed["summary"] is None
        assert parsed["years_of_experience"] == added["years_of_experience"]
        assert added["years_of_experience"] and added["years_of_experience"] >= 2

    async def test_adding_twice_is_a_conflict(self, db: AsyncSession, tenant, user):
        employee = await _employee_with_profile(db, tenant.id)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)
        await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, vacancy["id"], employee.id
        )
        with pytest.raises(AppError) as exc:
            await service.add_internal_candidate_to_vacancy(
                db, tenant.id, user.id, vacancy["id"], employee.id
            )
        assert exc.value.code == "candidate_already_attached_to_vacancy"
        assert exc.value.status_code == 409

    async def test_an_employee_off_the_roster_is_refused(
        self, db: AsyncSession, tenant, user
    ):
        """The endpoint takes an employee id; only the shortlist may pass.

        Without this it would be a directory read that a requisition has
        no business granting.
        """
        employee = await _employee_with_profile(db, tenant.id)
        stranger = await _employee_with_profile(db, tenant.id)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)
        with pytest.raises(AppError) as exc:
            await service.add_internal_candidate_to_vacancy(
                db, tenant.id, user.id, vacancy["id"], stranger.id
            )
        assert exc.value.code == "recruitment_internal_candidate_not_found"
        assert exc.value.status_code == 404

        # A vacancy that was never posted has no shortlist at all.
        unposted = await _make_vacancy(db, tenant.id, user.id)
        with pytest.raises(AppError) as exc:
            await service.add_internal_candidate_to_vacancy(
                db, tenant.id, user.id, unposted["id"], employee.id
            )
        assert exc.value.code == "recruitment_internal_candidate_not_found"

    async def test_backfills_the_person_and_reuses_the_candidate(
        self, db: AsyncSession, tenant, user
    ):
        """No Person on the user row is the case that silently broke the chip.

        ``_employee_person_ids`` resolves the chip through
        ``User.person_id``; a candidate created without it would sit in
        the pipeline looking like an external hire.
        """
        employee = await _employee_with_profile(db, tenant.id, with_person=False)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)
        first = await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, vacancy["id"], employee.id
        )
        assert first["is_employee"] is True
        refreshed_user = await db.get(User, employee.user_id)
        assert refreshed_user is not None
        assert refreshed_user.person_id is not None

        # Second vacancy, same colleague: one Candidate row, two links.
        second_vacancy, _ = await _posted_vacancy_with_roster(
            db, tenant.id, user.id, employee
        )
        second = await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, second_vacancy["id"], employee.id
        )
        assert second["id"] == first["id"]
        assert second["candidate_vacancy_id"] != first["candidate_vacancy_id"]


class TestAddInternalCandidateRouteParity:
    async def test_the_block_calls_a_url_the_router_mounts(self):
        import re
        from pathlib import Path

        from app.main import app

        block = (
            Path(__file__).resolve().parents[3]
            / "frontend"
            / "src"
            / "components"
            / "recruitment"
            / "internal-candidates-block.tsx"
        )
        if not block.exists():
            pytest.skip("frontend tree not present")

        def collapse(path: str) -> str:
            return re.sub(r"\$?\{[^}]*\}", "{}", path).rstrip("/")

        referenced = {
            "/api" + collapse(u)
            for u in re.findall(
                r"/recruitment/vacancies/\$\{[^}]+\}/internal-candidates[^`\"'?]*",
                block.read_text(encoding="utf-8"),
            )
        }
        mounted = {
            collapse(getattr(r, "path", ""))
            for r in app.routes
            if "internal-candidates" in getattr(r, "path", "")
        }
        assert referenced, "the block stopped calling the internal-candidates URLs"
        assert referenced <= mounted, referenced - mounted


class TestAddInternalCandidateReviewFollowUps:
    """HRP-711 review: the archived twin, and a chip that agrees with itself."""

    async def test_archived_candidate_is_a_conflict_not_a_crash(
        self, db: AsyncSession, tenant, user
    ):
        """``uq_candidate_person_tenant`` has no ``archived_at`` in it.

        Archiving keeps ``person_id``, and the shortlist (which filters
        archived rows out) starts offering Add again — so the second add
        used to reach the create branch and die on the constraint.
        """
        employee = await _employee_with_profile(db, tenant.id)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)
        added = await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, vacancy["id"], employee.id
        )
        await service.archive_candidate(db, tenant.id, added["id"])

        # The block no longer knows about the row, so the button is back.
        block = await service.get_vacancy_internal_candidates(
            db, tenant.id, vacancy["id"]
        )
        assert [i["candidate_id"] for i in block["items"]] == [None]

        with pytest.raises(AppError) as exc:
            await service.add_internal_candidate_to_vacancy(
                db, tenant.id, user.id, vacancy["id"], employee.id
            )
        assert exc.value.code == "candidate_archived"
        assert exc.value.status_code == 409
        # The recruiter is told which row is in the way.
        assert exc.value.detail_extra["existing_candidate_id"] == str(added["id"])

    async def test_the_chip_agrees_across_every_list(
        self, db: AsyncSession, tenant, user
    ):
        """``is_employee`` on the body must match what the lists compute.

        The body used to hardcode True while ``_employee_person_ids``
        resolves the flag through ``User.person_id`` — a reused row that
        kept a foreign Person would have shown the chip once and never
        again.
        """
        employee = await _employee_with_profile(db, tenant.id)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)
        added = await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, vacancy["id"], employee.id
        )
        assert added["is_employee"] is True

        items, _ = await service.list_candidates(db, tenant.id, limit=100)
        mine = [c for c in items if c["id"] == added["id"]]
        assert [c["is_employee"] for c in mine] == [True]

    async def test_an_email_twin_with_a_loose_person_is_rebound(
        self, db: AsyncSession, tenant, user
    ):
        """A demo tenant mints a fresh Person for every manual candidate.

        That row matches on email but carries a Person nobody signs in
        as. Reused untouched it stayed invisible to the chip and to the
        shortlist, which kept offering an Add that could only 409.
        """
        employee = await _employee_with_profile(db, tenant.id)
        vacancy, _ = await _posted_vacancy_with_roster(db, tenant.id, user.id, employee)
        emp_user = await db.get(User, employee.user_id)
        assert emp_user is not None

        loose = Person(first_name="Vova", last_name="Probelov")
        db.add(loose)
        await db.flush()
        twin = Candidate(
            tenant_id=tenant.id,
            person_id=loose.id,
            full_name="Vova Probelov",
            email=emp_user.email,
        )
        db.add(twin)
        await db.commit()

        added = await service.add_internal_candidate_to_vacancy(
            db, tenant.id, user.id, vacancy["id"], employee.id
        )
        assert added["id"] == twin.id
        assert added["is_employee"] is True
        # And the shortlist can now find it, so the row stops offering Add.
        block = await service.get_vacancy_internal_candidates(
            db, tenant.id, vacancy["id"]
        )
        assert [i["candidate_id"] for i in block["items"]] == [twin.id]
