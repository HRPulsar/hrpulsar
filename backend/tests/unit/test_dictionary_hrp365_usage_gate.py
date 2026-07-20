"""HRP-365: the delete usage-gate sees every FK on dictionary_items.

The manual enumeration missed Talent Market card requirements, vacancy
spec/grade and recommended grades — a spec delete silently CASCADE-wiped
published card requirements. The generic metadata walk in
``_collect_generic_refs`` now blocks on any non-exempt reference.
"""

import pytest
from app.modules.dictionary import service
from app.modules.dictionary.schemas import DictionaryItemCreate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

GENERIC = "This item has connections with other object(s). It can't be deleted"


async def _spec(db: AsyncSession, tenant, title="HRP365 Spec") -> dict:
    return await service.create_item(
        db, tenant.id, "specialization", DictionaryItemCreate(title=title)
    )


async def _grade(db: AsyncSession, tenant, title="HRP365 Grade") -> dict:
    return await service.create_item(
        db, tenant.id, "grade", DictionaryItemCreate(title=title)
    )


async def _talent_card(db: AsyncSession, tenant, user):
    from datetime import date

    from app.modules.talent_market.models import TalentCard

    card = TalentCard(
        tenant_id=tenant.id,
        title="HRP365 card",
        card_type="talent",
        author_id=user.id,
        start_date=date(2026, 1, 1),
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


class TestTalentMarketRefsBlockDelete:
    async def test_card_specialization_blocks_spec_delete(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.talent_market.models import TalentCardSpecialization

        spec = await _spec(db, tenant)
        card = await _talent_card(db, tenant, user)
        db.add(
            TalentCardSpecialization(
                card_id=card.id, specialization_id=spec["id"]
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, spec["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["message"] == GENERIC
        others = exc.value.detail["counts"]["others"]
        assert others.get("talent_card_specializations.specialization_id") == 1

    async def test_card_grade_blocks_grade_delete(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.talent_market.models import TalentCardSpecialization

        spec = await _spec(db, tenant, "HRP365 Spec2")
        grade = await _grade(db, tenant)
        card = await _talent_card(db, tenant, user)
        db.add(
            TalentCardSpecialization(
                card_id=card.id,
                specialization_id=spec["id"],
                grade_id=grade["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, grade["id"])
        assert exc.value.status_code == 409


class TestVacancyRefsBlockDelete:
    async def test_vacancy_specialization_blocks_delete(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.models import Vacancy

        spec = await _spec(db, tenant, "HRP365 VacSpec")
        db.add(
            Vacancy(
                tenant_id=tenant.id,
                title="HRP365 vacancy",
                owner_id=user.id,
                specialization_id=spec["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, spec["id"])
        assert exc.value.status_code == 409
        others = exc.value.detail["counts"]["others"]
        assert others.get("vacancies.specialization_id") == 1


class TestRecommendedGradeBlocksDelete:
    async def test_recommended_grade_blocks_delete(
        self, db: AsyncSession, tenant, user, employee, assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment import service as assessment_service
        from app.modules.assessment.models import Assessment
        from app.modules.assessment.schemas import AssessmentCreate

        grade = await _grade(db, tenant, "HRP365 RecGrade")
        created = await assessment_service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="HRP365 rec",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        a = await db.get(Assessment, created["id"])
        a.recommended_grade_id = grade["id"]
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, grade["id"])
        assert exc.value.status_code == 409
        others = exc.value.detail["counts"]["others"]
        assert others.get("assessments.recommended_grade_id") == 1


class TestExemptRefsDoNotBlock:
    async def test_unused_spec_still_deletable(self, db: AsyncSession, tenant):
        spec = await _spec(db, tenant, "HRP365 free")
        await service.delete_item(db, tenant.id, spec["id"])

    async def test_spec_division_mapping_does_not_block(
        self, db: AsyncSession, tenant
    ):
        from app.modules.company.models import Division, SpecializationDivision

        spec = await _spec(db, tenant, "HRP365 mapped")
        div = Division(tenant_id=tenant.id, name="HRP365 div")
        db.add(div)
        await db.commit()
        db.add(
            SpecializationDivision(
                tenant_id=tenant.id,
                specialization_id=spec["id"],
                division_id=div.id,
            )
        )
        await db.commit()

        # The junction row is config, not usage — delete goes through.
        await service.delete_item(db, tenant.id, spec["id"])
