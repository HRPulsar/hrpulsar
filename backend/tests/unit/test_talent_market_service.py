import uuid

import pytest
from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCardCompetence
from app.modules.talent_market.schemas import (
    CandidateAdd,
    RequiredCompetenceBulkCreate,
    RequiredCompetenceItem,
    RequiredCompetenceUpdate,
    RequiredSpecializationCreate,
    RequiredSpecializationUpdate,
    RequirementCreate,
    SearchRequest,
    TalentCardCreate,
    TalentCardUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# --------------- helpers ---------------


def _card_create(suffix: str | None = None) -> TalentCardCreate:
    s = suffix or uuid.uuid4().hex[:6]
    return TalentCardCreate(
        title=f"Card {s}", description=f"Desc {s}", card_type="vacancy"
    )


async def _attach_min_competence(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> TalentCardCompetence:
    """Spin up a minimal Competence + SkillLevel and link them to `card_id`.

    Used by tests that need to publish a card under the HRP-87 invariant
    that publish requires at least one Required Competence.
    """
    group = CompetenceGroup(tenant_id=tenant_id, title=f"G-{uuid.uuid4().hex[:6]}")
    db.add(group)
    await db.flush()

    comp = Competence(
        tenant_id=tenant_id, group_id=group.id, title=f"C-{uuid.uuid4().hex[:6]}"
    )
    db.add(comp)
    await db.flush()

    sl = SkillLevel(
        tenant_id=tenant_id,
        title=f"L-{uuid.uuid4().hex[:6]}",
        sort_index=0,
    )
    db.add(sl)
    await db.flush()

    link = TalentCardCompetence(
        card_id=card_id,
        competence_id=comp.id,
        skill_level_id=sl.id,
        match_percent=80,
    )
    db.add(link)
    await db.commit()
    return link


async def _attach_min_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, employee_id: uuid.UUID
):
    """Attach a candidate to satisfy the HRP-150 publish invariant."""
    from app.modules.talent_market.models import TalentCandidate

    cand = TalentCandidate(card_id=card_id, employee_id=employee_id, status="matched")
    db.add(cand)
    await db.commit()
    return cand


# --------------- create_card ---------------


class TestCreateCard:
    async def test_create_card(self, db: AsyncSession, tenant, user):
        data = _card_create()
        result = await service.create_card(db, tenant.id, user.id, data)

        assert result["title"] == data.title
        assert result["description"] == data.description
        assert result["card_type"] == "vacancy"
        assert result["status"] == "draft"
        assert result["is_published"] is False
        assert result["author_id"] == user.id
        assert result["tenant_id"] == tenant.id

    async def test_create_card_project_type(self, db: AsyncSession, tenant, user):
        data = TalentCardCreate(title="Project X", card_type="project")
        result = await service.create_card(db, tenant.id, user.id, data)
        assert result["card_type"] == "project"

    async def test_create_card_talent_type(self, db: AsyncSession, tenant, user):
        data = TalentCardCreate(title="Talent Y", card_type="talent")
        result = await service.create_card(db, tenant.id, user.id, data)
        assert result["card_type"] == "talent"


# --------------- search_cards ---------------


class TestSearchCards:
    async def test_search_empty(self, db: AsyncSession, tenant):
        items, total = await service.search_cards(db, tenant.id, SearchRequest())
        assert items == []
        assert total == 0

    async def test_search_returns_created(self, db: AsyncSession, tenant, user):
        s = uuid.uuid4().hex[:6]
        await service.create_card(db, tenant.id, user.id, _card_create(s))
        await service.create_card(db, tenant.id, user.id, _card_create(s + "b"))

        items, total = await service.search_cards(db, tenant.id, SearchRequest())
        assert total >= 2
        assert len(items) >= 2

    async def test_filter_by_type(self, db: AsyncSession, tenant, user):
        await service.create_card(
            db, tenant.id, user.id, TalentCardCreate(title="V1", card_type="vacancy")
        )
        await service.create_card(
            db, tenant.id, user.id, TalentCardCreate(title="P1", card_type="project")
        )

        vacancies, _ = await service.search_cards(
            db, tenant.id, SearchRequest(card_type="vacancy")
        )
        projects, _ = await service.search_cards(
            db, tenant.id, SearchRequest(card_type="project")
        )

        assert all(c["card_type"] == "vacancy" for c in vacancies)
        assert all(c["card_type"] == "project" for c in projects)

    async def test_filter_by_status(self, db: AsyncSession, tenant, user, employee):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        await _attach_min_candidate(db, tenant.id, card["id"], employee.id)
        await service.publish_card(db, tenant.id, card["id"])

        published, _ = await service.search_cards(
            db, tenant.id, SearchRequest(status="published")
        )
        assert any(c["id"] == card["id"] for c in published)

    async def test_pagination(self, db: AsyncSession, tenant, user):
        for i in range(5):
            await service.create_card(db, tenant.id, user.id, _card_create(f"pg{i}"))

        page1, total = await service.search_cards(
            db, tenant.id, SearchRequest(skip=0, limit=2)
        )
        page2, _ = await service.search_cards(
            db, tenant.id, SearchRequest(skip=2, limit=2)
        )

        assert len(page1) == 2
        assert len(page2) == 2
        assert total >= 5
        assert {c["id"] for c in page1}.isdisjoint({c["id"] for c in page2})

    async def test_tenant_isolation(self, db: AsyncSession, tenant, user):
        await service.create_card(db, tenant.id, user.id, _card_create())
        other_tenant_id = uuid.uuid4()
        items, total = await service.search_cards(db, other_tenant_id, SearchRequest())
        assert total == 0

    async def test_published_only_hides_drafts(
        self, db: AsyncSession, tenant, user, employee
    ):
        draft = await service.create_card(db, tenant.id, user.id, _card_create("d"))
        pub = await service.create_card(db, tenant.id, user.id, _card_create("p"))
        await _attach_min_competence(db, tenant.id, pub["id"])
        await _attach_min_candidate(db, tenant.id, pub["id"], employee.id)
        await service.publish_card(db, tenant.id, pub["id"])

        items, _ = await service.search_cards(
            db, tenant.id, SearchRequest(), published_only=True
        )
        ids = {c["id"] for c in items}
        assert pub["id"] in ids
        assert draft["id"] not in ids

    async def test_assignee_sees_unpublished_card_with_candidate(
        self, db: AsyncSession, tenant, user, employee
    ):
        draft = await service.create_card(db, tenant.id, user.id, _card_create("a"))
        await service.add_candidate(
            db, tenant.id, draft["id"], CandidateAdd(employee_id=employee.id)
        )

        items, total = await service.search_cards(
            db,
            tenant.id,
            SearchRequest(),
            published_only=True,
            assignee_employee_id=employee.id,
        )
        ids = {c["id"] for c in items}
        assert draft["id"] in ids
        assert total >= 1

    async def test_non_assignee_does_not_see_unpublished(
        self, db: AsyncSession, tenant, user, employee
    ):
        draft = await service.create_card(db, tenant.id, user.id, _card_create("n"))
        other_employee_id = uuid.uuid4()

        items, _ = await service.search_cards(
            db,
            tenant.id,
            SearchRequest(),
            published_only=True,
            assignee_employee_id=other_employee_id,
        )
        assert draft["id"] not in {c["id"] for c in items}


# --------------- get_card_detail ---------------


class TestGetCardDetail:
    async def test_get_detail(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        detail = await service.get_card_detail(db, tenant.id, card["id"])

        assert detail["id"] == card["id"]
        assert detail["title"] == card["title"]
        assert detail["specializations"] == []
        assert detail["competences"] == []
        assert detail["requirements"] == []
        assert detail["candidates"] == []

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_card_detail(db, tenant.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.get_card_detail(db, uuid.uuid4(), card["id"])
        assert exc_info.value.status_code == 404


# --------------- update_card ---------------


class TestUpdateCard:
    async def test_update(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        updated = await service.update_card(
            db,
            tenant.id,
            card["id"],
            TalentCardUpdate(title="New Title", description="New Desc"),
        )
        assert updated["title"] == "New Title"
        assert updated["description"] == "New Desc"

    async def test_partial_update(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        original_desc = card["description"]
        updated = await service.update_card(
            db,
            tenant.id,
            card["id"],
            TalentCardUpdate(title="Only Title Changed"),
        )
        assert updated["title"] == "Only Title Changed"
        assert updated["description"] == original_desc

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.update_card(
                db, tenant.id, uuid.uuid4(), TalentCardUpdate(title="x")
            )
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.update_card(
                db, uuid.uuid4(), card["id"], TalentCardUpdate(title="x")
            )
        assert exc_info.value.status_code == 404


# --------------- delete_card ---------------


class TestDeleteCard:
    async def test_delete(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await service.delete_card(db, tenant.id, card["id"])

        with pytest.raises(HTTPException) as exc_info:
            await service.get_card_detail(db, tenant.id, card["id"])
        assert exc_info.value.status_code == 404

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_card(db, tenant.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_card(db, uuid.uuid4(), card["id"])
        assert exc_info.value.status_code == 404


# --------------- publish_card ---------------


class TestPublishCard:
    async def test_publish(self, db: AsyncSession, tenant, user, employee):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        assert card["is_published"] is False

        # HRP-87: publish requires at least one Required Competence.
        await _attach_min_competence(db, tenant.id, card["id"])
        # HRP-150: publish also requires at least one Candidate.
        await _attach_min_candidate(db, tenant.id, card["id"], employee.id)
        published = await service.publish_card(db, tenant.id, card["id"])
        assert published["is_published"] is True
        assert published["status"] == "published"
        assert published["published_at"] is not None

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.publish_card(db, tenant.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.publish_card(db, uuid.uuid4(), card["id"])
        assert exc_info.value.status_code == 404

    async def test_publish_without_required_competences_fails(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-87: empty Required Competences block blocks publish."""
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.publish_card(db, tenant.id, card["id"])
        assert exc_info.value.status_code == 422


# --------------- HRP-87: Required Specialization / Competence ---------------


class TestRequiredBlocks:
    async def _seed_spec_grade_with_competence(
        self, db: AsyncSession, tenant
    ) -> tuple[
        DictionaryItem, DictionaryItem, GradeSpecialization, Competence, SkillLevel
    ]:
        """Materialise a (spec, grade, GradeSpec+CompetenceLink) tuple for tests."""
        spec = DictionaryItem(
            type="specialization",
            tenant_id=tenant.id,
            title=f"Spec-{uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        grade = DictionaryItem(
            type="grade",
            tenant_id=tenant.id,
            title=f"Grade-{uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        db.add_all([spec, grade])
        await db.flush()

        gs = GradeSpecialization(
            tenant_id=tenant.id, grade_id=grade.id, specialization_id=spec.id
        )
        db.add(gs)
        await db.flush()

        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="C")
        db.add(comp)
        sl = SkillLevel(tenant_id=tenant.id, title="L", sort_index=0)
        db.add(sl)
        await db.flush()

        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=sl.id,
            )
        )
        await db.commit()
        return spec, grade, gs, comp, sl

    async def test_add_required_spec_autofills_competences(
        self, db: AsyncSession, tenant, user
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        spec, grade, _gs, comp, sl = await self._seed_spec_grade_with_competence(
            db, tenant
        )

        link = await service.add_required_specialization(
            db,
            tenant.id,
            card["id"],
            RequiredSpecializationCreate(
                specialization_id=spec.id,
                grade_id=grade.id,
                min_experience_years=3,
            ),
        )
        assert link["specialization_id"] == spec.id
        assert link["grade_id"] == grade.id
        assert link["min_experience_years"] == 3

        detail = await service.get_card_detail(db, tenant.id, card["id"])
        assert len(detail["specializations"]) == 1
        # Auto-filled from GradeCompetenceLink — competence appears without
        # any explicit call to add_required_competences.
        assert len(detail["competences"]) == 1
        assert detail["competences"][0]["competence_id"] == comp.id
        assert detail["competences"][0]["skill_level_id"] == sl.id

    async def test_add_required_spec_skips_duplicates_on_repeated_add(
        self, db: AsyncSession, tenant, user
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        spec, grade, _, _, _ = await self._seed_spec_grade_with_competence(db, tenant)
        for _ in range(2):
            await service.add_required_specialization(
                db,
                tenant.id,
                card["id"],
                RequiredSpecializationCreate(
                    specialization_id=spec.id, grade_id=grade.id
                ),
            )
        detail = await service.get_card_detail(db, tenant.id, card["id"])
        # Both Required Specialization rows persist (the user can list the
        # same spec twice with different grades; the dialog doesn't dedupe).
        assert len(detail["specializations"]) == 2
        # …but the auto-filled competence is only attached once.
        assert len(detail["competences"]) == 1

    async def test_add_required_competences_bulk(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        _spec, _grade, _, comp, sl = await self._seed_spec_grade_with_competence(
            db, tenant
        )

        rows = await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)
                ],
            ),
        )
        assert len(rows) == 1
        assert rows[0]["competence_id"] == comp.id
        assert rows[0]["skill_level_id"] == sl.id

    async def test_update_required_competence(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        _spec, _grade, _, comp, sl = await self._seed_spec_grade_with_competence(
            db, tenant
        )
        rows = await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)
                ],
            ),
        )
        updated = await service.update_required_competence(
            db,
            tenant.id,
            card["id"],
            rows[0]["id"],
            RequiredCompetenceUpdate(
                competence_id=comp.id,
                skill_level_id=sl.id,
            ),
        )
        assert updated["competence_id"] == comp.id
        assert updated["skill_level_id"] == sl.id

    async def test_delete_required_specialization(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        spec, grade, _, _, _ = await self._seed_spec_grade_with_competence(db, tenant)
        link = await service.add_required_specialization(
            db,
            tenant.id,
            card["id"],
            RequiredSpecializationCreate(specialization_id=spec.id, grade_id=grade.id),
        )
        await service.delete_required_specialization(
            db, tenant.id, card["id"], link["id"]
        )
        detail = await service.get_card_detail(db, tenant.id, card["id"])
        assert detail["specializations"] == []

    async def test_published_card_is_read_only(
        self, db: AsyncSession, tenant, user, employee
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        await _attach_min_candidate(db, tenant.id, card["id"], employee.id)
        await service.publish_card(db, tenant.id, card["id"])

        with pytest.raises(HTTPException) as exc_info:
            await service.add_required_specialization(
                db,
                tenant.id,
                card["id"],
                RequiredSpecializationCreate(
                    specialization_id=uuid.uuid4(), grade_id=uuid.uuid4()
                ),
            )
        assert exc_info.value.status_code == 409

    async def test_update_spec_validates_grade(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        spec, grade, _, _, _ = await self._seed_spec_grade_with_competence(db, tenant)
        link = await service.add_required_specialization(
            db,
            tenant.id,
            card["id"],
            RequiredSpecializationCreate(specialization_id=spec.id, grade_id=grade.id),
        )
        # Unknown grade id should be rejected with 422 (validation, not RBAC).
        with pytest.raises(HTTPException) as exc_info:
            await service.update_required_specialization(
                db,
                tenant.id,
                card["id"],
                link["id"],
                RequiredSpecializationUpdate(
                    specialization_id=spec.id, grade_id=uuid.uuid4()
                ),
            )
        assert exc_info.value.status_code == 422

    async def test_add_spec_rejects_unconfigured_pair(
        self, db: AsyncSession, tenant, user
    ):
        """An arbitrary (spec, grade) pair without a GradeSpecialization → 422.

        Frontend filters grades via /specializations/{id}/grades so the user
        never picks one — but a direct API caller shouldn't be able to save
        a row that can't auto-fill.
        """
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        spec = DictionaryItem(
            type="specialization",
            tenant_id=tenant.id,
            title="LoneSpec",
            is_active=True,
        )
        unconfigured_grade = DictionaryItem(
            type="grade",
            tenant_id=tenant.id,
            title="LoneGrade",
            is_active=True,
        )
        db.add_all([spec, unconfigured_grade])
        await db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await service.add_required_specialization(
                db,
                tenant.id,
                card["id"],
                RequiredSpecializationCreate(
                    specialization_id=spec.id, grade_id=unconfigured_grade.id
                ),
            )
        assert exc_info.value.status_code == 422

    async def test_required_spec_preserves_zero_min_experience(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-127: 0 is a legitimate, distinct value from ``None`` — the
        service stores it as 0 (the UI then hides the line when value == 0)."""
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        spec, grade, _, _, _ = await self._seed_spec_grade_with_competence(db, tenant)

        link = await service.add_required_specialization(
            db,
            tenant.id,
            card["id"],
            RequiredSpecializationCreate(
                specialization_id=spec.id,
                grade_id=grade.id,
                min_experience_years=0,
            ),
        )
        assert link["min_experience_years"] == 0

        detail = await service.get_card_detail(db, tenant.id, card["id"])
        assert detail["specializations"][0]["min_experience_years"] == 0

    async def test_required_competences_replace_drops_removed(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-128: re-submitting Required Competences without a prior entry
        removes that entry — the dialog is now "set/replace", not "append"."""
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        _spec, _grade, _, comp_a, sl = await self._seed_spec_grade_with_competence(
            db, tenant
        )
        # Seed a second competence so we have something to drop.
        comp_b = Competence(tenant_id=tenant.id, group_id=comp_a.group_id, title="C2")
        db.add(comp_b)
        await db.commit()
        await db.refresh(comp_b)

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(
                        competence_id=comp_a.id, skill_level_id=sl.id
                    ),
                    RequiredCompetenceItem(
                        competence_id=comp_b.id, skill_level_id=sl.id
                    ),
                ],
            ),
        )
        # Re-submit with only comp_a → comp_b must be removed.
        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(
                        competence_id=comp_a.id, skill_level_id=sl.id
                    ),
                ],
            ),
        )
        detail = await service.get_card_detail(db, tenant.id, card["id"])
        ids = {c["competence_id"] for c in detail["competences"]}
        assert ids == {comp_a.id}

    async def test_card_match_percent_default_and_update(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-128: card carries match_percent (default 80, editable on draft)."""
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        assert card["match_percent"] == 80

        updated = await service.update_card(
            db,
            tenant.id,
            card["id"],
            TalentCardUpdate(match_percent=65),
        )
        assert updated["match_percent"] == 65

    async def test_card_match_percent_validation(self, db: AsyncSession, tenant, user):
        """HRP-128: match_percent must be in [50, 100]."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TalentCardCreate(title="t", card_type="vacancy", match_percent=40)
        with pytest.raises(ValidationError):
            TalentCardCreate(title="t", card_type="vacancy", match_percent=120)

    async def test_card_match_percent_locked_after_publish(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-128: published cards reject match_percent edits (parity with
        the requirements-block publish-lock)."""
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        await _attach_min_candidate(db, tenant.id, card["id"], employee.id)
        await service.publish_card(db, tenant.id, card["id"])

        with pytest.raises(HTTPException) as exc_info:
            await service.update_card(
                db,
                tenant.id,
                card["id"],
                TalentCardUpdate(match_percent=70),
            )
        assert exc_info.value.status_code == 409

    async def test_competence_endpoints_reject_published_card(
        self, db: AsyncSession, tenant, user, employee
    ):
        """All three Required-Competence mutation endpoints honour the publish lock."""
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        _spec, _grade, _, comp, sl = await self._seed_spec_grade_with_competence(
            db, tenant
        )
        rows = await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)
                ],
            ),
        )
        await _attach_min_candidate(db, tenant.id, card["id"], employee.id)
        await service.publish_card(db, tenant.id, card["id"])

        # add_required_competences
        with pytest.raises(HTTPException) as exc_info:
            await service.add_required_competences(
                db,
                tenant.id,
                card["id"],
                RequiredCompetenceBulkCreate(
                    items=[
                        RequiredCompetenceItem(
                            competence_id=comp.id, skill_level_id=sl.id
                        )
                    ],
                ),
            )
        assert exc_info.value.status_code == 409
        # update_required_competence
        with pytest.raises(HTTPException) as exc_info:
            await service.update_required_competence(
                db,
                tenant.id,
                card["id"],
                rows[0]["id"],
                RequiredCompetenceUpdate(competence_id=comp.id, skill_level_id=sl.id),
            )
        assert exc_info.value.status_code == 409
        # delete_required_competence
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_required_competence(
                db, tenant.id, card["id"], rows[0]["id"]
            )
        assert exc_info.value.status_code == 409


# --------------- add_requirement ---------------


class TestAddRequirement:
    async def test_add(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        req = await service.add_requirement(
            db,
            tenant.id,
            card["id"],
            RequirementCreate(description="3+ years Python", min_experience_years=3),
        )
        assert req["description"] == "3+ years Python"
        assert req["min_experience_years"] == 3
        assert "id" in req

    async def test_add_no_experience(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        req = await service.add_requirement(
            db,
            tenant.id,
            card["id"],
            RequirementCreate(description="English B2+"),
        )
        assert req["min_experience_years"] is None

    async def test_appears_in_detail(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await service.add_requirement(
            db,
            tenant.id,
            card["id"],
            RequirementCreate(description="Requirement A", min_experience_years=1),
        )
        await service.add_requirement(
            db,
            tenant.id,
            card["id"],
            RequirementCreate(description="Requirement B"),
        )
        detail = await service.get_card_detail(db, tenant.id, card["id"])
        assert len(detail["requirements"]) == 2
        descs = {r["description"] for r in detail["requirements"]}
        assert "Requirement A" in descs
        assert "Requirement B" in descs

    async def test_card_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.add_requirement(
                db,
                tenant.id,
                uuid.uuid4(),
                RequirementCreate(description="x"),
            )
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.add_requirement(
                db,
                uuid.uuid4(),
                card["id"],
                RequirementCreate(description="x"),
            )
        assert exc_info.value.status_code == 404


# --------------- add_candidate ---------------


class TestAddCandidate:
    async def test_add(self, db: AsyncSession, tenant, user, employee):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        cand = await service.add_candidate(
            db,
            tenant.id,
            card["id"],
            CandidateAdd(employee_id=employee.id),
        )
        assert cand["employee_id"] == employee.id
        # HRP-214: status mirrors current qualification. With no Required
        # blocks set the employee can't qualify, so manual picks default
        # to `not_matched`.
        assert cand["status"] == "not_matched"
        # HRP-129: with no Required Competencies the matcher returns None
        # (the spec says % match isn't computed when there's nothing to
        # match against).
        assert cand["match_score"] is None
        assert cand["appointed_at"] is None
        assert "id" in cand

    async def test_appears_in_detail(self, db: AsyncSession, tenant, user, employee):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=employee.id)
        )

        detail = await service.get_card_detail(db, tenant.id, card["id"])
        assert len(detail["candidates"]) == 1
        assert detail["candidates"][0]["employee_id"] == employee.id

    async def test_card_not_found(self, db: AsyncSession, tenant, employee):
        with pytest.raises(HTTPException) as exc_info:
            await service.add_candidate(
                db,
                tenant.id,
                uuid.uuid4(),
                CandidateAdd(employee_id=employee.id),
            )
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant, user, employee):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.add_candidate(
                db,
                uuid.uuid4(),
                card["id"],
                CandidateAdd(employee_id=employee.id),
            )
        assert exc_info.value.status_code == 404

    async def test_add_returns_position_and_status(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-258: add_candidate returns the denormalised position +
        status so the Candidates table can render EmployeeSummaryLine
        without a second round-trip."""
        from app.modules.employee.models import Employee

        emp_row = await db.get(Employee, employee.id)
        emp_row.position_title = "Senior Backend Engineer"
        emp_row.status = "on_leave"
        await db.commit()

        card = await service.create_card(db, tenant.id, user.id, _card_create())
        cand = await service.add_candidate(
            db,
            tenant.id,
            card["id"],
            CandidateAdd(employee_id=employee.id),
        )
        assert cand["position_title"] == "Senior Backend Engineer"
        assert cand["employee_status"] == "on_leave"


# --------------- appoint_candidate ---------------


class TestAppointCandidate:
    async def test_appoint(self, db: AsyncSession, tenant, user, employee):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        cand = await service.add_candidate(
            db,
            tenant.id,
            card["id"],
            CandidateAdd(employee_id=employee.id),
        )

        appointed = await service.appoint_candidate(
            db, tenant.id, card["id"], cand["id"]
        )
        assert appointed["status"] == "appointed"
        assert appointed["appointed_at"] is not None
        assert appointed["employee_id"] == employee.id

    async def test_card_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.appoint_candidate(db, tenant.id, uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_wrong_card(self, db: AsyncSession, tenant, user, employee):
        card1 = await service.create_card(db, tenant.id, user.id, _card_create())
        card2 = await service.create_card(db, tenant.id, user.id, _card_create())
        cand = await service.add_candidate(
            db,
            tenant.id,
            card1["id"],
            CandidateAdd(employee_id=employee.id),
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.appoint_candidate(db, tenant.id, card2["id"], cand["id"])
        assert exc_info.value.status_code == 404

    async def test_candidate_not_found(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.appoint_candidate(db, tenant.id, card["id"], uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_wrong_tenant(self, db: AsyncSession, tenant, user, employee):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        cand = await service.add_candidate(
            db,
            tenant.id,
            card["id"],
            CandidateAdd(employee_id=employee.id),
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.appoint_candidate(db, uuid.uuid4(), card["id"], cand["id"])
        assert exc_info.value.status_code == 404


# --------------- HRP-129: auto-pool matcher ---------------


class TestComputeMatchHRP129:
    """Unit coverage for the rewritten _compute_match_score helper.

    Mirrors the three worked examples Victoria attached to HRP-129:
    full coverage of 4 competences (avg 70%), partial coverage with a
    zero-contribution gap (avg 63%), and zero coverage (None — candidate
    excluded).
    """

    async def _setup(self, db: AsyncSession, tenant, user, competence_count: int):
        from app.modules.talent_market import service as svc
        from app.modules.talent_market.models import TalentCard, TalentCardCompetence

        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        comps = []
        for i in range(competence_count):
            c = Competence(tenant_id=tenant.id, group_id=group.id, title=f"C-{i}")
            db.add(c)
            comps.append(c)
        sl = SkillLevel(tenant_id=tenant.id, title="High", sort_index=0)
        db.add(sl)
        await db.flush()

        card_dict = await svc.create_card(db, tenant.id, user.id, _card_create())
        card = await db.get(TalentCard, card_dict["id"])
        for c in comps:
            db.add(
                TalentCardCompetence(
                    card_id=card.id, competence_id=c.id, skill_level_id=sl.id
                )
            )
        await db.commit()
        return card, comps, sl

    async def _add_done_assessment(
        self,
        db: AsyncSession,
        tenant,
        employee,
        comp,
        skill_level,
        percent: int,
        finished_at=None,
    ):
        """Spin up a `done` Assessment with one AssessmentCompetence and
        one AssessmentResult — the minimum the matcher needs to see."""
        from datetime import datetime, timezone

        from app.modules.assessment.models import (
            Assessment,
            AssessmentCompetence,
            AssessmentResult,
            AssessmentStatus,
            AssessmentType,
        )
        from sqlalchemy import select

        st = (
            await db.execute(
                select(AssessmentStatus).where(AssessmentStatus.code == "done")
            )
        ).scalar_one_or_none()
        if not st:
            st = AssessmentStatus(code="done", title="Done", sequence=6)
            db.add(st)
            await db.flush()
        tp = (
            await db.execute(
                select(AssessmentType).where(AssessmentType.code == "self")
            )
        ).scalar_one_or_none()
        if not tp:
            tp = AssessmentType(code="self", title="Self")
            db.add(tp)
            await db.flush()

        a = Assessment(
            tenant_id=tenant.id,
            employee_id=employee.id,
            type_id=tp.id,
            status_id=st.id,
            initiator_id=employee.user_id,
            finished_at=finished_at or datetime.now(timezone.utc),
        )
        db.add(a)
        await db.flush()
        db.add(
            AssessmentCompetence(
                assessment_id=a.id,
                competence_id=comp.id,
                skill_level_id=skill_level.id,
            )
        )
        db.add(
            AssessmentResult(
                assessment_id=a.id,
                competence_id=comp.id,
                avg_score=percent / 25.0,
                percent=percent,
            )
        )
        await db.commit()
        return a

    async def test_example1_all_four_assessed_avg_70(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Spec example 1: 4 competences with 100/80/70/30 → 70%."""
        card, comps, sl = await self._setup(db, tenant, user, 4)
        for c, pct in zip(comps, [100, 80, 70, 30], strict=False):
            await self._add_done_assessment(db, tenant, employee, c, sl, pct)

        score, basis = await service._compute_match_score(db, card, employee.id)
        assert basis == "competence"
        assert score == 70

    async def test_example2_three_of_four_assessed_avg_63(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Spec example 2: 4 competences with 100/80/70 and one gap → 63%
        (the missing competence contributes 0 so the average is
        (100+80+70+0)/4 = 62.5, rounded half-up to 63)."""
        card, comps, sl = await self._setup(db, tenant, user, 4)
        for c, pct in zip(comps[:3], [100, 80, 70], strict=False):
            await self._add_done_assessment(db, tenant, employee, c, sl, pct)

        score, _ = await service._compute_match_score(db, card, employee.id)
        assert score == 63

    async def test_example3_no_assessments_returns_none(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Spec example 3: not a single done assessment among Required
        Competences → % is not computed, candidate excluded."""
        card, _, _ = await self._setup(db, tenant, user, 4)
        score, basis = await service._compute_match_score(db, card, employee.id)
        assert score is None
        assert basis == "none"

    async def test_skill_level_filter_ignores_lower_level(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-129 (per HRP-90): assessment level *below* the requirement
        is ignored. Levels at-or-above the requirement count."""
        # _setup() seeds the Required Competence at sort_index=0; we make a
        # truly lower-level skill at sort_index = -1 so the assessment falls
        # under the required floor.
        card, comps, _sl_required = await self._setup(db, tenant, user, 1)
        sl_lower = SkillLevel(tenant_id=tenant.id, title="Lower", sort_index=-1)
        db.add(sl_lower)
        await db.flush()
        await self._add_done_assessment(db, tenant, employee, comps[0], sl_lower, 95)

        score, basis = await service._compute_match_score(db, card, employee.id)
        assert score is None
        assert basis == "none"

    async def test_last_passed_assessment_wins(
        self, db: AsyncSession, tenant, user, employee
    ):
        """If several `done` assessments cover the same Required Competence
        at the matching skill_level, the matcher picks the most recently
        finished one — even if its percent is lower."""
        from datetime import datetime, timedelta, timezone

        card, comps, sl = await self._setup(db, tenant, user, 1)
        # Older assessment scored higher than the newer one.
        await self._add_done_assessment(
            db,
            tenant,
            employee,
            comps[0],
            sl,
            95,
            finished_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        await self._add_done_assessment(
            db,
            tenant,
            employee,
            comps[0],
            sl,
            60,
            finished_at=datetime.now(timezone.utc),
        )

        score, _ = await service._compute_match_score(db, card, employee.id)
        assert score == 60


class TestAutoPopulateCandidatesHRP129:
    """auto-populate fires on requirement changes and seeds the Candidates
    block with qualifying employees."""

    async def test_set_required_competences_autocreates_candidate(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.talent_market.models import TalentCardCompetence
        from sqlalchemy import select

        # Card with Match% threshold 70.
        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="Auto-pool", card_type="vacancy", match_percent=70),
        )

        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="Python")
        db.add(comp)
        sl = SkillLevel(tenant_id=tenant.id, title="High", sort_index=0)
        db.add(sl)
        await db.flush()

        # Employee already has a done assessment at 80% — should qualify
        # once the Required Competence is wired up.
        helper = TestComputeMatchHRP129()
        await helper._add_done_assessment(db, tenant, employee, comp, sl, 80)

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)
                ]
            ),
        )

        candidates = (
            (
                await db.execute(
                    select(service.TalentCandidate).where(
                        service.TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(candidates) == 1
        assert candidates[0].employee_id == employee.id
        # HRP-214: auto-pool now stamps `matched` rather than `nominated`.
        assert candidates[0].status == "matched"
        assert candidates[0].match_score == 80
        # Sanity: TalentCardCompetence row was also persisted.
        comp_links = (
            (
                await db.execute(
                    select(TalentCardCompetence).where(
                        TalentCardCompetence.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(comp_links) == 1

    async def test_below_threshold_employee_not_auto_added(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Employee at 60% with a Match% threshold of 80 must not appear
        in the auto-pool — qualification gate."""
        from sqlalchemy import select

        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="Strict", card_type="vacancy", match_percent=80),
        )
        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="Go")
        db.add(comp)
        sl = SkillLevel(tenant_id=tenant.id, title="Mid", sort_index=0)
        db.add(sl)
        await db.flush()

        helper = TestComputeMatchHRP129()
        await helper._add_done_assessment(db, tenant, employee, comp, sl, 60)

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)
                ]
            ),
        )

        candidates = (
            (
                await db.execute(
                    select(service.TalentCandidate).where(
                        service.TalentCandidate.card_id == card["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert candidates == []

    async def test_manual_appointed_candidate_stays_after_recompute(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Appointed candidates are sticky — they survive an auto-pool
        recompute even when they no longer match."""
        from app.modules.talent_market.models import TalentCandidate
        from sqlalchemy import select

        card = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title="Sticky", card_type="vacancy", match_percent=80),
        )
        # Manually appoint the employee.
        cand = await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=employee.id)
        )
        await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])

        # Now wire requirements that the employee can't possibly meet
        # (no assessments) — auto-populate must leave the appointed row alone.
        group = CompetenceGroup(tenant_id=tenant.id, title="G")
        db.add(group)
        await db.flush()
        comp = Competence(tenant_id=tenant.id, group_id=group.id, title="Rust")
        db.add(comp)
        sl = SkillLevel(tenant_id=tenant.id, title="High", sort_index=0)
        db.add(sl)
        await db.flush()

        await service.add_required_competences(
            db,
            tenant.id,
            card["id"],
            RequiredCompetenceBulkCreate(
                items=[
                    RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)
                ]
            ),
        )

        rows = (
            (
                await db.execute(
                    select(TalentCandidate).where(TalentCandidate.card_id == card["id"])
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].status == "appointed"


# --------------- HRP-150: status transitions ---------------


class TestPublishRequiresCandidateHRP150:
    """HRP-150 broadens the publish guard: ≥1 Required Competence (HRP-87)
    *and* ≥1 Candidate."""

    async def test_publish_without_candidates_fails(
        self, db: AsyncSession, tenant, user
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        with pytest.raises(HTTPException) as exc_info:
            await service.publish_card(db, tenant.id, card["id"])
        assert exc_info.value.status_code == 422
        assert "Candidate" in exc_info.value.detail


class TestCompleteCardHRP150:
    async def test_complete_with_appointed_candidate(
        self, db: AsyncSession, tenant, user, employee
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        cand = await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=employee.id)
        )
        await service.publish_card(db, tenant.id, card["id"])
        await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])

        completed = await service.complete_card(db, tenant.id, card["id"])
        assert completed["status"] == "completed"
        assert completed["closed_at"] is not None

    async def test_complete_without_appointed_fails(
        self, db: AsyncSession, tenant, user, employee
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=employee.id)
        )
        await service.publish_card(db, tenant.id, card["id"])

        with pytest.raises(HTTPException) as exc_info:
            await service.complete_card(db, tenant.id, card["id"])
        assert exc_info.value.status_code == 422

    async def test_complete_from_draft_fails(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        with pytest.raises(HTTPException) as exc_info:
            await service.complete_card(db, tenant.id, card["id"])
        assert exc_info.value.status_code == 409


class TestCancelCardHRP150:
    async def test_cancel_from_draft(self, db: AsyncSession, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        cancelled = await service.cancel_card(db, tenant.id, card["id"])
        assert cancelled["status"] == "cancelled"
        assert cancelled["closed_at"] is not None

    async def test_cancel_from_published(
        self, db: AsyncSession, tenant, user, employee
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        await _attach_min_candidate(db, tenant.id, card["id"], employee.id)
        await service.publish_card(db, tenant.id, card["id"])

        cancelled = await service.cancel_card(db, tenant.id, card["id"])
        assert cancelled["status"] == "cancelled"

    async def test_cancel_from_completed_fails(
        self, db: AsyncSession, tenant, user, employee
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        cand = await service.add_candidate(
            db, tenant.id, card["id"], CandidateAdd(employee_id=employee.id)
        )
        await service.publish_card(db, tenant.id, card["id"])
        await service.appoint_candidate(db, tenant.id, card["id"], cand["id"])
        await service.complete_card(db, tenant.id, card["id"])

        with pytest.raises(HTTPException) as exc_info:
            await service.cancel_card(db, tenant.id, card["id"])
        assert exc_info.value.status_code == 409


class TestHRP291TerminalLock:
    """HRP-291: Completed / Cancelled cards reject every mutation —
    requirements, candidate list, appointments and card details."""

    async def _cancelled_from_draft(self, db, tenant, user):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await service.cancel_card(db, tenant.id, card["id"])
        return card

    async def test_cancelled_from_draft_requirements_locked(
        self, db: AsyncSession, tenant, user
    ):
        # A Draft-cancelled card never flipped is_published — the old
        # guard let requirement edits through.
        card = await self._cancelled_from_draft(db, tenant, user)

        with pytest.raises(HTTPException) as exc_info:
            await service.add_required_specialization(
                db,
                tenant.id,
                card["id"],
                RequiredSpecializationCreate(
                    specialization_id=uuid.uuid4(), grade_id=uuid.uuid4()
                ),
            )
        assert exc_info.value.status_code == 409

        with pytest.raises(HTTPException) as exc_info:
            await service.add_required_competences(
                db,
                tenant.id,
                card["id"],
                RequiredCompetenceBulkCreate(
                    items=[
                        RequiredCompetenceItem(
                            competence_id=uuid.uuid4(),
                            skill_level_id=uuid.uuid4(),
                        )
                    ]
                ),
            )
        assert exc_info.value.status_code == 409

    async def test_cancelled_card_candidate_mutations_locked(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.talent_market.schemas import CandidateBulkAdd

        card = await self._cancelled_from_draft(db, tenant, user)

        with pytest.raises(HTTPException) as exc_info:
            await service.add_candidate(
                db, tenant.id, card["id"], CandidateAdd(employee_id=employee.id)
            )
        assert exc_info.value.status_code == 409

        with pytest.raises(HTTPException) as exc_info:
            await service.add_candidates_bulk(
                db,
                tenant.id,
                card["id"],
                CandidateBulkAdd(employee_ids=[employee.id]),
            )
        assert exc_info.value.status_code == 409

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_candidate(db, tenant.id, card["id"], employee.id)
        assert exc_info.value.status_code == 409

        with pytest.raises(HTTPException) as exc_info:
            await service.appoint_candidate(db, tenant.id, card["id"], uuid.uuid4())
        assert exc_info.value.status_code == 409

    async def test_cancelled_card_details_locked(self, db: AsyncSession, tenant, user):
        card = await self._cancelled_from_draft(db, tenant, user)
        with pytest.raises(HTTPException) as exc_info:
            await service.update_card(
                db, tenant.id, card["id"], TalentCardUpdate(title="New title")
            )
        assert exc_info.value.status_code == 409

    async def test_completed_card_appoint_locked(
        self, db: AsyncSession, tenant, user, employee
    ):
        card = await service.create_card(db, tenant.id, user.id, _card_create())
        await _attach_min_competence(db, tenant.id, card["id"])
        cand = await _attach_min_candidate(db, tenant.id, card["id"], employee.id)
        await service.publish_card(db, tenant.id, card["id"])
        appointed = await service.appoint_candidate(db, tenant.id, card["id"], cand.id)
        assert appointed["status"] == "appointed"
        await service.complete_card(db, tenant.id, card["id"])

        with pytest.raises(HTTPException) as exc_info:
            await service.appoint_candidate(db, tenant.id, card["id"], cand.id)
        assert exc_info.value.status_code == 409

        with pytest.raises(HTTPException) as exc_info:
            await service.update_card(
                db, tenant.id, card["id"], TalentCardUpdate(title="Nope")
            )
        assert exc_info.value.status_code == 409

    async def test_cancelled_card_legacy_requirement_and_delete_locked(
        self, db: AsyncSession, tenant, user
    ):
        card = await self._cancelled_from_draft(db, tenant, user)

        with pytest.raises(HTTPException) as exc_info:
            await service.add_requirement(
                db,
                tenant.id,
                card["id"],
                RequirementCreate(description="Legacy row"),
            )
        assert exc_info.value.status_code == 409

        # HRP-148 hides Delete on terminal cards in the UI; the API
        # agrees now.
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_card(db, tenant.id, card["id"])
        assert exc_info.value.status_code == 409
