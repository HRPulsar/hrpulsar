"""HRP-425: the vacancy Analytics tiles must follow the funnel.

Hired / Rejected / In progress used to be derived from the free-text
``CandidateVacancy.status`` column, which no product flow writes apart
from the vacancy-close path — so moving candidates through the funnel
left the tiles saying "everyone is in progress". They now count stages by
``stage_type``, and the tiles are labelled with the vacancy's own terminal
stage names.
"""

from __future__ import annotations

import uuid

from app.modules.recruitment import analytics_service, service, vacancy_service
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    CandidateVacancyPatch,
    VacancyCloseData,
    VacancyCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _vacancy_with_stages(db: AsyncSession, tenant, user) -> uuid.UUID:
    await vacancy_service.seed_default_recruitment_stages(db, tenant.id)
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    return uuid.UUID(str(vacancy["id"]))


async def _attach(db: AsyncSession, tenant, user, vacancy_id: uuid.UUID) -> uuid.UUID:
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"F{uuid.uuid4().hex[:4]}",
            last_name=f"L{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:6]}@example.com",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(candidate["id"])),
            vacancy_id=vacancy_id,
        ),
    )
    return uuid.UUID(str(cv["id"]))


async def _stages_by_code(db: AsyncSession, tenant, vacancy_id: uuid.UUID) -> dict:
    from app.modules.recruitment.common import _get_applicable_stages

    stages = await _get_applicable_stages(db, tenant.id, vacancy_id)
    return {s.code: s for s in stages}


async def _move(
    db: AsyncSession, tenant, user, cv_id: uuid.UUID, stage_id: uuid.UUID
) -> None:
    await service.patch_candidate_vacancy(
        db,
        tenant.id,
        cv_id,
        CandidateVacancyPatch(stage_id=stage_id),
    )


class TestTilesFollowStageType:
    async def test_terminal_stages_drive_the_three_tiles(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy_with_stages(db, tenant, user)
        stages = await _stages_by_code(db, tenant, vacancy_id)

        hired_cv = await _attach(db, tenant, user, vacancy_id)
        rejected_cv = await _attach(db, tenant, user, vacancy_id)
        withdrew_cv = await _attach(db, tenant, user, vacancy_id)
        active_cv = await _attach(db, tenant, user, vacancy_id)

        await _move(db, tenant, user, hired_cv, stages["hired"].id)
        await _move(db, tenant, user, rejected_cv, stages["rejected"].id)
        await _move(db, tenant, user, withdrew_cv, stages["withdrew"].id)
        await _move(db, tenant, user, active_cv, stages["screening"].id)

        data = await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
        assert data["total_candidates"] == 4
        assert data["win_loss"] == {
            "hired": 1,
            "rejected": 1,
            "withdrew": 1,
            # Only the non-terminal candidate is still in progress — the
            # three terminal ones must not be double-counted here.
            "in_progress": 1,
        }

    async def test_status_column_no_longer_drives_the_tiles(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """A stale ``status`` string must not outvote the funnel."""
        from app.modules.recruitment.models import CandidateVacancy

        vacancy_id = await _vacancy_with_stages(db, tenant, user)
        stages = await _stages_by_code(db, tenant, vacancy_id)
        cv_id = await _attach(db, tenant, user, vacancy_id)
        await _move(db, tenant, user, cv_id, stages["screening"].id)

        cv = await db.get(CandidateVacancy, cv_id)
        cv.status = "hired"
        await db.commit()

        data = await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
        assert data["win_loss"]["hired"] == 0
        assert data["win_loss"]["in_progress"] == 1

    async def test_unstaged_candidate_counts_as_in_progress(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy_with_stages(db, tenant, user)
        await _attach(db, tenant, user, vacancy_id)

        data = await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
        assert data["win_loss"]["in_progress"] == 1
        assert data["total_candidates"] == 1


class TestTileLabels:
    async def test_terminal_stage_names_are_returned(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy_with_stages(db, tenant, user)
        data = await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
        assert data["positive_stage_names"] == ["Hired"]
        assert data["negative_stage_names"] == ["Rejected"]

    async def test_several_terminal_stages_are_all_reported(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """A funnel may split rejection into several terminal stages."""
        from app.modules.recruitment.schemas import (
            VacancyStageReplaceItem,
            VacancyStagesReplace,
        )

        vacancy_id = await _vacancy_with_stages(db, tenant, user)
        stages = await _stages_by_code(db, tenant, vacancy_id)
        override = [
            VacancyStageReplaceItem(
                name=s.name,
                code=s.code,
                sort_order=s.sort_order,
                stage_type=s.stage_type,
                color=s.color,
            )
            for s in stages.values()
        ]
        override.append(
            VacancyStageReplaceItem(
                name="Rejected by client",
                code="rejected_client",
                sort_order=85,
                stage_type="terminal_negative",
            )
        )
        await vacancy_service.replace_vacancy_stages_override(
            db, tenant.id, vacancy_id, VacancyStagesReplace(stages=override)
        )

        data = await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
        assert data["negative_stage_names"] == ["Rejected", "Rejected by client"]


class TestCloseVacancyKeepsTheFunnelHonest:
    async def test_closing_as_hired_moves_the_candidate_to_the_hired_stage(
        self, db: AsyncSession, tenant, user
    ) -> None:
        from app.modules.recruitment.models import CandidateVacancy

        vacancy_id = await _vacancy_with_stages(db, tenant, user)
        candidate = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="Hired",
                last_name="One",
                email=f"{uuid.uuid4().hex[:6]}@example.com",
            ),
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(candidate["id"])),
                vacancy_id=vacancy_id,
            ),
        )
        version_before = (
            await db.get(CandidateVacancy, uuid.UUID(str(cv["id"])))
        ).version
        await service.close_vacancy(
            db,
            tenant.id,
            vacancy_id,
            VacancyCloseData(
                resolution="hired",
                hired_candidate_id=uuid.UUID(str(candidate["id"])),
            ),
        )

        stages = await _stages_by_code(db, tenant, vacancy_id)
        row = await db.get(CandidateVacancy, uuid.UUID(str(cv["id"])))
        await db.refresh(row)
        assert row.stage_id == stages["hired"].id
        # The link's ETag is W/"{version}" — moving the candidate has to
        # move the version too, or a request still holding the pre-close
        # ETag would pass If-Match and overwrite the Hired stage.
        assert row.version > version_before

        data = await analytics_service.vacancy_analytics(db, tenant.id, vacancy_id)
        assert data["win_loss"]["hired"] == 1
        assert data["win_loss"]["in_progress"] == 0
