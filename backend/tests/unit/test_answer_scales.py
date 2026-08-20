"""Unit tests for the rating-scale POSTRELEASE block.

Covers create/update/soft-delete of custom answer scales, snapshot on
status transition, neutral options, percent + level computation in
results, and billing wiring.
"""

import uuid

import pytest
import pytest_asyncio
from app.modules.assessment import service
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    AnswerScaleLevel,
    AssessmentAnswer,
    AssessmentCompetence,
    AssessmentResult,
)
from app.modules.assessment.schemas import (
    AnswerOptionInput,
    AnswerScaleCreate,
    AnswerScaleLevelInput,
    AnswerScaleUpdate,
    AssessmentCreate,
)
from app.modules.competence.models import Competence, Indicator
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import (
    advance_to_done,
    advance_to_in_progress,
    seed_send_prereqs,
)

# ---------- helpers ----------


def _scoring_options(n: int = 3) -> list[AnswerOptionInput]:
    return [
        AnswerOptionInput(title=f"Option {i}", sort_index=i, is_neutral=False)
        for i in range(n)
    ]


def _full_levels() -> list[AnswerScaleLevelInput]:
    return [
        AnswerScaleLevelInput(
            percent_from=0,
            percent_to=50,
            system_title="Low",
            sort_index=0,
        ),
        AnswerScaleLevelInput(
            percent_from=51,
            percent_to=100,
            system_title="High",
            sort_index=1,
        ),
    ]


@pytest_asyncio.fixture
async def default_scale(default_answer_scale):
    """The origin default scale — the canonical conftest fixture.

    This suite used to build its own 3-option "default"; whichever suite
    ran first then defined the global default for the whole session, and
    the demo seed generated answers against the wrong weight range
    (test-order-dependent failures in test_demo_seed). Only the id is
    used here, so the canonical 5-point scale serves both.
    """
    return default_answer_scale


# ---------- create ----------


class TestCreateAnswerScale:
    async def test_create_minimal(self, db: AsyncSession, tenant):
        data = AnswerScaleCreate(
            title="My scale",
            options=_scoring_options(2),
        )
        result = await service.create_answer_scale(db, tenant.id, data)
        assert result["title"] == "My scale"
        assert result["tenant_id"] == tenant.id
        assert result["is_default"] is False
        assert result["is_snapshot"] is False
        assert len(result["options"]) == 2
        assert all(o["is_neutral"] is False for o in result["options"])
        assert result["levels"] == []

    async def test_create_with_neutral_option(self, db: AsyncSession, tenant):
        opts = _scoring_options(3) + [
            AnswerOptionInput(title="Don't know", sort_index=99, is_neutral=True)
        ]
        data = AnswerScaleCreate(title="Neutral test", options=opts)
        result = await service.create_answer_scale(db, tenant.id, data)
        neutral = [o for o in result["options"] if o["is_neutral"]]
        assert len(neutral) == 1
        assert neutral[0]["weight"] is None
        assert neutral[0]["title"] == "Don't know"

    async def test_create_with_levels(self, db: AsyncSession, tenant):
        data = AnswerScaleCreate(
            title="Full",
            options=_scoring_options(3),
            levels=_full_levels(),
        )
        result = await service.create_answer_scale(db, tenant.id, data)
        assert len(result["levels"]) == 2
        assert result["levels"][0]["percent_from"] == 0
        assert result["levels"][-1]["percent_to"] == 100

    async def test_validates_min_2_options(self, db: AsyncSession, tenant):
        # Pydantic guards the wire shape (min_length=2)
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnswerScaleCreate(title="x", options=_scoring_options(1))

    async def test_validates_two_neutral_options_rejected(
        self, db: AsyncSession, tenant
    ):
        opts = _scoring_options(2) + [
            AnswerOptionInput(title="n1", sort_index=10, is_neutral=True),
            AnswerOptionInput(title="n2", sort_index=11, is_neutral=True),
        ]
        with pytest.raises(HTTPException) as exc:
            await service.create_answer_scale(
                db, tenant.id, AnswerScaleCreate(title="x", options=opts)
            )
        assert exc.value.status_code == 400

    async def test_validates_max_10_options(self, db: AsyncSession, tenant):
        # 10 non-neutral + 1 neutral = 11 (allowed by schema), but 11 non-neutral
        # is blocked at the service layer.
        opts = _scoring_options(11)
        with pytest.raises(HTTPException) as exc:
            await service.create_answer_scale(
                db, tenant.id, AnswerScaleCreate(title="x", options=opts)
            )
        assert exc.value.status_code == 400

    async def test_validates_levels_cover_full_range(self, db: AsyncSession, tenant):
        # Gap between 50 and 60
        bad = [
            AnswerScaleLevelInput(
                percent_from=0, percent_to=50, system_title="Low", sort_index=0
            ),
            AnswerScaleLevelInput(
                percent_from=60, percent_to=100, system_title="High", sort_index=1
            ),
        ]
        with pytest.raises(HTTPException) as exc:
            await service.create_answer_scale(
                db,
                tenant.id,
                AnswerScaleCreate(title="x", options=_scoring_options(2), levels=bad),
            )
        assert exc.value.status_code == 400

    async def test_validates_levels_no_overlap(self, db: AsyncSession, tenant):
        bad = [
            AnswerScaleLevelInput(
                percent_from=0, percent_to=60, system_title="Low", sort_index=0
            ),
            AnswerScaleLevelInput(
                percent_from=40,
                percent_to=100,
                system_title="High",
                sort_index=1,
            ),
        ]
        with pytest.raises(HTTPException) as exc:
            await service.create_answer_scale(
                db,
                tenant.id,
                AnswerScaleCreate(title="x", options=_scoring_options(2), levels=bad),
            )
        assert exc.value.status_code == 400

    async def test_validates_levels_end_at_100(self, db: AsyncSession, tenant):
        bad = [
            AnswerScaleLevelInput(
                percent_from=0, percent_to=90, system_title="Low", sort_index=0
            )
        ]
        with pytest.raises(HTTPException) as exc:
            await service.create_answer_scale(
                db,
                tenant.id,
                AnswerScaleCreate(title="x", options=_scoring_options(2), levels=bad),
            )
        assert exc.value.status_code == 400

    async def test_validates_levels_start_at_0(self, db: AsyncSession, tenant):
        bad = [
            AnswerScaleLevelInput(
                percent_from=10,
                percent_to=100,
                system_title="High",
                sort_index=0,
            )
        ]
        with pytest.raises(HTTPException) as exc:
            await service.create_answer_scale(
                db,
                tenant.id,
                AnswerScaleCreate(title="x", options=_scoring_options(2), levels=bad),
            )
        assert exc.value.status_code == 400


# ---------- update ----------


class TestUpdateAnswerScale:
    async def test_full_replace(self, db: AsyncSession, tenant):
        created = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Old", options=_scoring_options(2)),
        )
        updated = await service.update_answer_scale(
            db,
            tenant.id,
            created["id"],
            AnswerScaleUpdate(
                title="New",
                options=_scoring_options(4),
                levels=_full_levels(),
            ),
        )
        assert updated["title"] == "New"
        assert len(updated["options"]) == 4
        assert len(updated["levels"]) == 2

    async def test_blocks_default_scale(self, db: AsyncSession, tenant, default_scale):
        with pytest.raises(HTTPException) as exc:
            await service.update_answer_scale(
                db,
                tenant.id,
                default_scale.id,
                AnswerScaleUpdate(title="hack", options=_scoring_options(2)),
            )
        assert exc.value.status_code == 404

    async def test_blocks_other_tenant(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        foreign = await service.create_answer_scale(
            db,
            other.id,
            AnswerScaleCreate(title="Foreign", options=_scoring_options(2)),
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_answer_scale(
                db,
                tenant.id,
                foreign["id"],
                AnswerScaleUpdate(title="hack", options=_scoring_options(2)),
            )
        assert exc.value.status_code == 404

    async def test_blocks_snapshot(self, db: AsyncSession, tenant):
        snap = AnswerScale(
            tenant_id=None,
            title="snap",
            is_default=False,
            is_snapshot=True,
        )
        db.add(snap)
        await db.commit()
        await db.refresh(snap)
        with pytest.raises(HTTPException) as exc:
            await service.update_answer_scale(
                db,
                tenant.id,
                snap.id,
                AnswerScaleUpdate(title="hack", options=_scoring_options(2)),
            )
        assert exc.value.status_code == 404


# ---------- delete (soft) ----------


class TestDeleteAnswerScale:
    async def test_soft_deletes(self, db: AsyncSession, tenant, default_scale):
        created = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Doomed", options=_scoring_options(2)),
        )
        result = await service.delete_answer_scale(db, tenant.id, created["id"])
        assert result["deleted"] is True

        row = await db.get(AnswerScale, created["id"])
        assert row is not None
        assert row.deleted_at is not None

    async def test_blocks_default_scale(self, db: AsyncSession, tenant, default_scale):
        with pytest.raises(HTTPException) as exc:
            await service.delete_answer_scale(db, tenant.id, default_scale.id)
        assert exc.value.status_code == 404

    async def test_reassigns_draft_assessments_to_default(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        default_scale,
    ):
        created = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Drop", options=_scoring_options(2)),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Draft",
                employee_id=employee.id,
                type_code="self",
                scale_id=created["id"],
            ),
        )
        result = await service.delete_answer_scale(db, tenant.id, created["id"])
        assert result["reassigned_drafts"] == 1

        from app.modules.assessment.models import Assessment as AssessmentModel

        refreshed = await db.get(AssessmentModel, a["id"])
        assert refreshed.scale_id == default_scale.id

    async def test_keeps_running_assessments_intact(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        default_scale,
    ):
        created = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Live", options=_scoring_options(2)),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Live A",
                employee_id=employee.id,
                type_code="self",
                scale_id=created["id"],
            ),
        )
        await seed_send_prereqs(db, tenant.id, a["id"])

        await service.change_status(db, tenant.id, a["id"], "sent")

        result = await service.delete_answer_scale(db, tenant.id, created["id"])
        assert result["reassigned_drafts"] == 0

        from app.modules.assessment.models import Assessment as AssessmentModel

        refreshed = await db.get(AssessmentModel, a["id"])
        # snapshot already replaced original scale_id; not the original scale
        assert refreshed.scale_id != created["id"]


# ---------- list / get ----------


class TestListAndGetScales:
    async def test_list_excludes_deleted(self, db: AsyncSession, tenant, default_scale):
        created = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Hidden", options=_scoring_options(2)),
        )
        await service.delete_answer_scale(db, tenant.id, created["id"])
        scales = await service.list_scales(db, tenant.id)
        assert created["id"] not in [s.id for s in scales]

    async def test_list_excludes_snapshots(
        self, db: AsyncSession, tenant, default_scale
    ):
        snap = AnswerScale(
            tenant_id=None, title="snap", is_default=False, is_snapshot=True
        )
        db.add(snap)
        await db.commit()
        scales = await service.list_scales(db, tenant.id)
        assert snap.id not in [s.id for s in scales]

    async def test_get_returns_deleted_for_archive(
        self, db: AsyncSession, tenant, default_scale
    ):
        created = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Archive", options=_scoring_options(2)),
        )
        await service.delete_answer_scale(db, tenant.id, created["id"])
        # Direct GET still resolves the scale
        result = await service.get_answer_scale(db, tenant.id, created["id"])
        assert result["id"] == created["id"]
        assert result["deleted_at"] is not None


# ---------- snapshot on status transition ----------


class TestSnapshotOnStatusTransition:
    async def test_snapshot_created_on_draft_to_sent(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Src", options=_scoring_options(3)),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="To snap",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale["id"],
            ),
        )
        await seed_send_prereqs(db, tenant.id, a["id"])

        await service.change_status(db, tenant.id, a["id"], "sent")

        from app.modules.assessment.models import Assessment as AssessmentModel

        refreshed = await db.get(AssessmentModel, a["id"])
        assert refreshed.scale_id != scale["id"]
        snap = await db.get(AnswerScale, refreshed.scale_id)
        assert snap is not None
        assert snap.is_snapshot is True
        assert snap.tenant_id is None

    async def test_edit_after_snapshot_does_not_affect_assessment(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="Original", options=_scoring_options(3)),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Snap stable",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale["id"],
            ),
        )
        await seed_send_prereqs(db, tenant.id, a["id"])

        await service.change_status(db, tenant.id, a["id"], "sent")

        from app.modules.assessment.models import Assessment as AssessmentModel

        snap_scale_id = (await db.get(AssessmentModel, a["id"])).scale_id

        # Mutate the source: rename + add an option
        await service.update_answer_scale(
            db,
            tenant.id,
            scale["id"],
            AnswerScaleUpdate(
                title="Mutated",
                options=_scoring_options(5),
            ),
        )

        snap = await service._load_scale_full(db, snap_scale_id)
        assert snap.title == "Original"
        assert len(snap.options) == 3

    async def test_snapshot_copies_system_code_for_i18n_levels(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        # Origin/seeded levels carry system_code with system_title=NULL
        # (CR12 migration). The snapshot must copy system_code or it will
        # fall foul of ck_scale_level_code_or_title.
        scale = AnswerScale(tenant_id=tenant.id, title="Code-driven scale")
        db.add(scale)
        await db.flush()
        for idx, (lo, hi, code) in enumerate(
            [
                (0, 50, "below_expectations"),
                (51, 75, "meets_with_growth"),
                (76, 100, "fully_meets"),
            ]
        ):
            db.add(
                AnswerScaleLevel(
                    scale_id=scale.id,
                    percent_from=lo,
                    percent_to=hi,
                    system_code=code,
                    system_title=None,
                    sort_index=idx,
                )
            )
        for idx, title in enumerate(["Below", "Meets", "Exceeds"]):
            db.add(
                AnswerOption(
                    scale_id=scale.id,
                    title=title,
                    code=f"opt_{idx}",
                    weight=idx,
                    sort_index=idx,
                )
            )
        await db.commit()

        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="i18n snap",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        await seed_send_prereqs(db, tenant.id, a["id"])
        await service.change_status(db, tenant.id, a["id"], "sent")

        from app.modules.assessment.models import Assessment as AssessmentModel

        snap_scale_id = (await db.get(AssessmentModel, a["id"])).scale_id
        snap = await service._load_scale_full(db, snap_scale_id)
        codes = sorted(lvl.system_code for lvl in snap.levels)
        assert codes == ["below_expectations", "fully_meets", "meets_with_growth"]
        for lvl in snap.levels:
            assert lvl.system_title is None


# ---------- global default uniqueness ----------


class TestGlobalDefaultUniqueness:
    async def test_partial_unique_index_blocks_second_default(
        self, db: AsyncSession, default_scale
    ):
        from sqlalchemy.exc import IntegrityError

        dup = AnswerScale(
            title="another global default",
            tenant_id=None,
            is_default=True,
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# ---------- recompute results ----------


@pytest_asyncio.fixture
async def competence_with_indicators(db: AsyncSession, tenant):
    from app.modules.competence.models import CompetenceGroup, SkillLevel

    skill_q = await db.execute(select(SkillLevel).limit(1))
    skill = skill_q.scalar_one_or_none()
    if skill is None:
        skill = SkillLevel(title="Basic", sort_index=0)
        db.add(skill)
        await db.flush()

    group = CompetenceGroup(tenant_id=tenant.id, title="Group")
    db.add(group)
    await db.flush()
    comp = Competence(
        tenant_id=tenant.id, title="Comp", description=None, group_id=group.id
    )
    db.add(comp)
    await db.flush()
    indicators = []
    for i in range(2):
        ind = Indicator(
            competence_id=comp.id,
            title=f"Ind {i}",
            weight=1,
            is_active=True,
            skill_level_id=skill.id,
        )
        db.add(ind)
        indicators.append(ind)
    await db.commit()
    for ind in indicators:
        await db.refresh(ind)
    await db.refresh(comp)
    return comp, indicators


class TestRecomputeResults:
    async def test_neutral_option_excluded_from_avg(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        competence_with_indicators,
    ):
        comp, indicators = competence_with_indicators
        opts = _scoring_options(3) + [
            AnswerOptionInput(title="Don't know", sort_index=99, is_neutral=True)
        ]
        scale_dict = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(
                title="With neutral",
                options=opts,
                levels=_full_levels(),
            ),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Recompute",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale_dict["id"],
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp.id))

        from app.modules.assessment.models import AssessmentParticipant

        result = await db.execute(
            select(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == a["id"]
            )
        )
        participant = result.scalar_one()
        await db.commit()

        await seed_send_prereqs(db, tenant.id, a["id"])

        await service.change_status(db, tenant.id, a["id"], "sent")

        # Resolve snapshot scale options
        from app.modules.assessment.models import Assessment as AssessmentModel

        ass = await db.get(AssessmentModel, a["id"])
        snap = await service._load_scale_full(db, ass.scale_id)
        scoring = sorted(
            [o for o in snap.options if not o.is_neutral],
            key=lambda o: o.weight or 0,
        )
        neutral = next(o for o in snap.options if o.is_neutral)
        top = scoring[-1]

        # Indicator 0 — neutral (skipped); Indicator 1 — top score (100%)
        await advance_to_in_progress(db, tenant.id, a["id"])
        db.add(
            AssessmentAnswer(
                assessment_id=a["id"],
                participant_id=participant.id,
                indicator_id=indicators[0].id,
                answer_option_id=neutral.id,
                score=None,
            )
        )
        db.add(
            AssessmentAnswer(
                assessment_id=a["id"],
                participant_id=participant.id,
                indicator_id=indicators[1].id,
                answer_option_id=top.id,
                score=top.weight,
            )
        )
        await db.commit()

        await advance_to_done(db, tenant.id, a["id"])

        result_q = await db.execute(
            select(AssessmentResult).where(AssessmentResult.assessment_id == a["id"])
        )
        results = result_q.scalars().all()
        assert len(results) == 1
        r = results[0]
        # Only the non-neutral indicator counts; should be 100%.
        assert r.percent == 100
        assert r.level_id is not None

    async def test_legacy_no_levels_yields_null_percent(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        competence_with_indicators,
    ):
        comp, indicators = competence_with_indicators
        scale_dict = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="No levels", options=_scoring_options(3)),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="No levels",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale_dict["id"],
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp.id))
        await db.commit()

        await seed_send_prereqs(db, tenant.id, a["id"])

        await service.change_status(db, tenant.id, a["id"], "sent")
        await advance_to_in_progress(db, tenant.id, a["id"])
        await advance_to_done(db, tenant.id, a["id"])

        result_q = await db.execute(
            select(AssessmentResult).where(AssessmentResult.assessment_id == a["id"])
        )
        results = result_q.scalars().all()
        assert len(results) == 1
        r = results[0]
        # No answers + no levels → percent stays null
        assert r.percent is None
        assert r.level_id is None


# ---------- detail serialization ----------


class TestAssessmentDetailSerialization:
    async def test_assessment_detail_serializes_percent_and_level(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        competence_with_indicators,
    ):
        comp, indicators = competence_with_indicators
        scale_dict = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(
                title="Detail levels",
                options=_scoring_options(3),
                levels=_full_levels(),
            ),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Detail levels",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale_dict["id"],
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp.id))

        from app.modules.assessment.models import Assessment as AssessmentModel
        from app.modules.assessment.models import AssessmentParticipant

        participant_q = await db.execute(
            select(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == a["id"]
            )
        )
        participant = participant_q.scalar_one()
        await db.commit()

        await seed_send_prereqs(db, tenant.id, a["id"])

        await service.change_status(db, tenant.id, a["id"], "sent")

        ass = await db.get(AssessmentModel, a["id"])
        snap = await service._load_scale_full(db, ass.scale_id)
        scoring = sorted(
            [o for o in snap.options if not o.is_neutral],
            key=lambda o: o.weight or 0,
        )
        top = scoring[-1]

        await advance_to_in_progress(db, tenant.id, a["id"])
        for ind in indicators:
            db.add(
                AssessmentAnswer(
                    assessment_id=a["id"],
                    participant_id=participant.id,
                    indicator_id=ind.id,
                    answer_option_id=top.id,
                    score=top.weight,
                )
            )
        await db.commit()
        await advance_to_done(db, tenant.id, a["id"])

        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        assert len(detail["results"]) == 1
        row = detail["results"][0]
        assert isinstance(row["percent"], int)
        assert row["percent"] == 100
        assert row["level"] is not None
        assert row["level"]["system_title"] == "High"
        assert row["level"]["percent_from"] == 51
        assert row["level"]["percent_to"] == 100

    async def test_assessment_detail_legacy_no_levels(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        competence_with_indicators,
    ):
        comp, _ = competence_with_indicators
        scale_dict = await service.create_answer_scale(
            db,
            tenant.id,
            AnswerScaleCreate(title="No levels", options=_scoring_options(3)),
        )
        a = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Legacy",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale_dict["id"],
            ),
        )
        db.add(AssessmentCompetence(assessment_id=a["id"], competence_id=comp.id))
        await db.commit()

        await seed_send_prereqs(db, tenant.id, a["id"])

        await service.change_status(db, tenant.id, a["id"], "sent")
        await advance_to_in_progress(db, tenant.id, a["id"])
        await advance_to_done(db, tenant.id, a["id"])

        detail = await service.get_assessment_detail(db, tenant.id, a["id"])
        assert len(detail["results"]) == 1
        row = detail["results"][0]
        assert row["percent"] is None
        assert row["level"] is None


# Billing-wiring assertions live in `tests/unit/ee/test_answer_scales_billing.py`
# (kept out of the public repo, which doesn't ship `ee/`).
