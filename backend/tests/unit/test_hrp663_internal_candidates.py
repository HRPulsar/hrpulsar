"""Internal candidates in recruitment (HRP-663) + the talent-market bridge (HRP-667).

Two facts the product could not state before:

* a candidate who already works here is marked as such everywhere a
  recruiter looks at candidates, not only in the global list; and
* a vacancy can be posted to the internal talent market, which is what
  produces the "who inside already fits" shortlist.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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
        await service.set_vacancy_competences(
            db,
            tenant.id,
            vacancy["id"],
            VacancyCompetencesUpdate(
                competences=[VacancyCompetenceSpec(competence_id=competence_id)]
            ),
        )
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
