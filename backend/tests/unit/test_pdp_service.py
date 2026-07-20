import uuid

import pytest
from app.modules.assessment import pdp_service as service
from app.modules.assessment.schemas import (
    PDPCommentCreate,
    PDPCreate,
    PDPItemCreate,
    PDPItemUpdate,
    PDPMaterialCreate,
    PDPMaterialUpdate,
    PDPUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestPDPCrud:
    async def test_create_pdp(self, db: AsyncSession, tenant, user, employee):
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await service.create_pdp(db, tenant.id, user.id, data)
        assert pdp["title"] == "Plan"
        assert pdp["employee_id"] == employee.id
        assert pdp["employee_name"] == "Test User"
        assert pdp["status"] == "draft"
        assert pdp["total_progress"] == 0

    async def test_create_pdp_without_grade_link_creates_no_items(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Empty", employee_id=employee.id)
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["items"] == []

    async def test_create_pdp_auto_items_from_grade_link(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.competence.models import (
            Competence,
            CompetenceGroup,
            SkillLevel,
        )
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        spec = DictionaryItem(
            type="specialization", title="Backend", tenant_id=tenant.id
        )
        grade = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
        group = CompetenceGroup(title="General", tenant_id=tenant.id)
        skill = SkillLevel(title="Advanced")
        db.add_all([spec, grade, group, skill])
        await db.flush()

        comp_a = Competence(title="Python", group_id=group.id, tenant_id=tenant.id)
        comp_b = Competence(title="SQL", group_id=group.id, tenant_id=tenant.id)
        db.add_all([comp_a, comp_b])
        await db.flush()

        gs = GradeSpecialization(
            tenant_id=tenant.id, grade_id=grade.id, specialization_id=spec.id
        )
        db.add(gs)
        await db.flush()
        db.add_all(
            [
                GradeCompetenceLink(
                    grade_specialization_id=gs.id,
                    competence_id=comp_a.id,
                    skill_level_id=skill.id,
                ),
                GradeCompetenceLink(
                    grade_specialization_id=gs.id,
                    competence_id=comp_b.id,
                    skill_level_id=skill.id,
                ),
            ]
        )
        await db.commit()

        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Senior Backend Plan",
                employee_id=employee.id,
                specialization_id=spec.id,
                grade_id=grade.id,
            ),
        )
        assert pdp["specialization_title"] == "Backend"
        assert pdp["grade_title"] == "Senior"

        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        titles = sorted(item["title"] for item in detail["items"])
        assert titles == ["Python", "SQL"]
        assert all(item["entity_type"] == "competence" for item in detail["items"])

    async def test_create_pdp_grade_without_link_keeps_items_empty(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.dictionary.models import DictionaryItem

        spec = DictionaryItem(
            type="specialization", title="Frontend", tenant_id=tenant.id
        )
        grade = DictionaryItem(type="grade", title="Middle", tenant_id=tenant.id)
        db.add_all([spec, grade])
        await db.commit()

        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="No-link plan",
                employee_id=employee.id,
                specialization_id=spec.id,
                grade_id=grade.id,
            ),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["items"] == []

    async def test_create_pdp_with_deadline(
        self, db: AsyncSession, tenant, user, employee
    ):
        from datetime import datetime, timedelta, timezone

        # Future date so the not_past_deadline validator stays happy (HRP-23).
        dl = datetime.now(timezone.utc) + timedelta(days=30)
        data = PDPCreate(title="Plan", employee_id=employee.id, deadline=dl)
        pdp = await service.create_pdp(db, tenant.id, user.id, data)
        assert pdp["deadline"] is not None

    async def test_list_pdps(self, db: AsyncSession, tenant, user, employee):
        await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        pdps = await service.list_pdps(db, tenant.id)
        assert len(pdps) >= 1

    async def test_list_pdps_filter_by_employee(
        self, db: AsyncSession, tenant, user, employee
    ):
        await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        pdps = await service.list_pdps(db, tenant.id, employee_id=employee.id)
        assert all(p["employee_id"] == employee.id for p in pdps)

    async def test_get_pdp_detail(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["id"] == pdp["id"]
        assert "items" in detail
        assert "comments" in detail

    async def test_get_pdp_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.get_pdp_detail(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_create_pdp_rejects_fourth_active_plan(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-38: cap concurrent active plans per employee at 3."""
        for i in range(service.MAX_ACTIVE_PDPS_PER_EMPLOYEE):
            await service.create_pdp(
                db,
                tenant.id,
                user.id,
                PDPCreate(title=f"Plan {i}", employee_id=employee.id),
            )

        with pytest.raises(HTTPException) as exc:
            await service.create_pdp(
                db,
                tenant.id,
                user.id,
                PDPCreate(title="Over the cap", employee_id=employee.id),
            )
        assert exc.value.status_code == 409
        # The wording is reused verbatim by the Create plan dialog —
        # snapshot it so the UI doesn't have to second-guess the
        # message.
        assert "limit 3" in exc.value.detail
        assert (
            "Finish or cancel an existing one before starting another."
            in exc.value.detail
        )

    async def test_create_pdp_allows_when_existing_plans_are_terminal(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-38: only non-terminal plans count toward the cap."""
        from app.modules.assessment.models import PDP
        from sqlalchemy import select

        # Seed three Done plans + one Cancelled plan + verify a fresh
        # active plan still goes through.
        for status_code, title in [
            ("done", "Done 1"),
            ("done", "Done 2"),
            ("done", "Done 3"),
            ("cancelled", "Cancelled 1"),
        ]:
            pdp = await service.create_pdp(
                db,
                tenant.id,
                user.id,
                PDPCreate(title=title, employee_id=employee.id),
            )
            row = (
                await db.execute(select(PDP).where(PDP.id == pdp["id"]))
            ).scalar_one()
            row.status = status_code
            await db.commit()

        fresh = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(title="Fresh start", employee_id=employee.id),
        )
        assert fresh["status"] == "draft"


async def _seed_sendable_item(db, tenant_id, pdp_id):
    """HRP-12: helper for tests that need to move past ``draft``.

    Every plan must carry at least one item with at least one material
    before it can be sent — this seeds a minimal pair so tests focused on
    status transitions don't have to repeat the boilerplate.
    """
    item = await service.add_item(
        db, tenant_id, pdp_id, PDPItemCreate(title="Seed item")
    )
    await service.add_material(
        db,
        tenant_id,
        pdp_id,
        item["id"],
        PDPMaterialCreate(title="Seed material", link="https://example.com"),
    )
    return item


async def _ensure_all_items_have_materials(db, tenant_id, pdp_id):
    """HRP-12: backfill a stub material on every item so a plan whose
    items were auto-generated (without Material rows seeded in the test
    DB) can still be sent."""
    detail = await service.get_pdp_detail(db, tenant_id, pdp_id)
    for item in detail["items"]:
        if not item["materials"]:
            await service.add_material(
                db,
                tenant_id,
                pdp_id,
                item["id"],
                PDPMaterialCreate(
                    title=f"Stub material for {item['title']}",
                    link="https://example.com",
                ),
            )


class TestPDPStatus:
    async def test_draft_to_sent(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        await _seed_sendable_item(db, tenant.id, pdp["id"])
        result = await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert result is not None

    async def test_draft_to_cancelled(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        result = await service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        assert result is not None

    async def test_invalid_transition(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "done")
        assert exc.value.status_code == 400

    async def test_send_blocked_without_items(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-12: an empty draft cannot move to sent.
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert exc.value.status_code == 409
        assert "item" in exc.value.detail.lower()

    async def test_send_blocked_when_item_has_no_material(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-12: items must each carry at least one material before send.
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Bare item")
        )
        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert exc.value.status_code == 409
        assert "material" in exc.value.detail.lower()

    async def test_full_lifecycle(self, db: AsyncSession, tenant, user, employee):
        # HRP-16: simplified graph — review goes straight to done, no
        # on_approval/approved hops.
        # HRP-197: ``sent → in_progress`` is no longer a manual transition;
        # the plan promotes itself the first time the owner ticks an item.
        # We use ``bypass_transition_check`` here so the test can keep
        # asserting on the underlying status machine without simulating an
        # employee tick.
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        pid = pdp["id"]
        await _seed_sendable_item(db, tenant.id, pid)
        await service.change_pdp_status(db, tenant.id, pid, "sent")
        await service.change_pdp_status(
            db, tenant.id, pid, "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pid, "review")
        await service.change_pdp_status(db, tenant.id, pid, "done")

    async def test_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, uuid.uuid4(), "sent")
        assert exc.value.status_code == 404


class TestPDPUpdate:
    async def test_update_title(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        result = await service.update_pdp(
            db, tenant.id, pdp["id"], PDPUpdate(title="Renamed plan")
        )
        assert result["title"] == "Renamed plan"
        assert result["deadline"] is None

    async def test_update_deadline(self, db: AsyncSession, tenant, user, employee):
        from datetime import datetime, timezone

        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        new_deadline = datetime(2026, 9, 1, tzinfo=timezone.utc)
        result = await service.update_pdp(
            db, tenant.id, pdp["id"], PDPUpdate(deadline=new_deadline)
        )
        assert result["deadline"] is not None
        assert result["title"] == "Plan"

    async def test_update_clear_deadline(
        self, db: AsyncSession, tenant, user, employee
    ):
        from datetime import datetime, timezone

        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Plan",
                employee_id=employee.id,
                deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
            ),
        )
        result = await service.update_pdp(
            db, tenant.id, pdp["id"], PDPUpdate(deadline=None)
        )
        assert result["deadline"] is None

    async def test_update_finalized_blocks(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        with pytest.raises(HTTPException) as exc:
            await service.update_pdp(db, tenant.id, pdp["id"], PDPUpdate(title="x"))
        assert exc.value.status_code == 409

    async def test_update_no_fields_rejected_by_schema(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PDPUpdate()


def _seed_grade_link(db, tenant, *, spec_title="Backend", grade_title="Senior"):
    from app.modules.competence.models import CompetenceGroup, SkillLevel
    from app.modules.dictionary.models import DictionaryItem

    spec = DictionaryItem(type="specialization", title=spec_title, tenant_id=tenant.id)
    grade = DictionaryItem(type="grade", title=grade_title, tenant_id=tenant.id)
    group = CompetenceGroup(title=f"Group {spec_title}", tenant_id=tenant.id)
    skill = SkillLevel(title=f"Level {grade_title}")
    db.add_all([spec, grade, group, skill])
    return spec, grade, group, skill


class TestPDPRecomputeOnGradeChange:
    async def _setup_two_links(self, db, tenant):
        """Create two distinct (spec, grade) pairs with their competences."""
        from app.modules.competence.models import Competence
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        spec_a, grade_a, group_a, skill_a = _seed_grade_link(
            db, tenant, spec_title="Backend A", grade_title="Senior A"
        )
        spec_b, grade_b, group_b, skill_b = _seed_grade_link(
            db, tenant, spec_title="Backend B", grade_title="Senior B"
        )
        await db.flush()

        comp_a1 = Competence(title="Python A", group_id=group_a.id, tenant_id=tenant.id)
        comp_a2 = Competence(title="SQL A", group_id=group_a.id, tenant_id=tenant.id)
        comp_b1 = Competence(title="Python B", group_id=group_b.id, tenant_id=tenant.id)
        comp_b2 = Competence(title="SQL B", group_id=group_b.id, tenant_id=tenant.id)
        db.add_all([comp_a1, comp_a2, comp_b1, comp_b2])
        await db.flush()

        gs_a = GradeSpecialization(
            tenant_id=tenant.id, grade_id=grade_a.id, specialization_id=spec_a.id
        )
        gs_b = GradeSpecialization(
            tenant_id=tenant.id, grade_id=grade_b.id, specialization_id=spec_b.id
        )
        db.add_all([gs_a, gs_b])
        await db.flush()
        db.add_all(
            [
                GradeCompetenceLink(
                    grade_specialization_id=gs_a.id,
                    competence_id=comp_a1.id,
                    skill_level_id=skill_a.id,
                ),
                GradeCompetenceLink(
                    grade_specialization_id=gs_a.id,
                    competence_id=comp_a2.id,
                    skill_level_id=skill_a.id,
                ),
                GradeCompetenceLink(
                    grade_specialization_id=gs_b.id,
                    competence_id=comp_b1.id,
                    skill_level_id=skill_b.id,
                ),
                GradeCompetenceLink(
                    grade_specialization_id=gs_b.id,
                    competence_id=comp_b2.id,
                    skill_level_id=skill_b.id,
                ),
            ]
        )
        await db.commit()
        return (spec_a, grade_a, comp_a1, comp_a2), (spec_b, grade_b, comp_b1, comp_b2)

    async def test_change_grade_replaces_auto_items(
        self, db: AsyncSession, tenant, user, employee
    ):
        (spec_a, grade_a, _, _), (spec_b, grade_b, _, _) = await self._setup_two_links(
            db, tenant
        )
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Plan",
                employee_id=employee.id,
                specialization_id=spec_a.id,
                grade_id=grade_a.id,
            ),
        )
        await service.update_pdp(
            db,
            tenant.id,
            pdp["id"],
            PDPUpdate(specialization_id=spec_b.id, grade_id=grade_b.id),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        titles = sorted(item["title"] for item in detail["items"])
        assert titles == ["Python B", "SQL B"]

    async def test_change_grade_replaces_custom_items(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-189: the modal warns "All items will be replaced with the new
        # specialization & grade set." — that includes custom items the admin
        # added by hand, since the operation is only available in draft and
        # the admin can reauthor anything they want before pressing Send.
        (spec_a, grade_a, _, _), (spec_b, grade_b, _, _) = await self._setup_two_links(
            db, tenant
        )
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Plan",
                employee_id=employee.id,
                specialization_id=spec_a.id,
                grade_id=grade_a.id,
            ),
        )
        await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="My custom goal")
        )
        await service.update_pdp(
            db,
            tenant.id,
            pdp["id"],
            PDPUpdate(specialization_id=spec_b.id, grade_id=grade_b.id),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        titles = sorted(i["title"] for i in detail["items"])
        assert "My custom goal" not in titles
        assert titles == ["Python B", "SQL B"]

    async def test_change_grade_in_progress_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        (spec_a, grade_a, _, _), (spec_b, grade_b, _, _) = await self._setup_two_links(
            db, tenant
        )
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Plan",
                employee_id=employee.id,
                specialization_id=spec_a.id,
                grade_id=grade_a.id,
            ),
        )
        await _ensure_all_items_have_materials(db, tenant.id, pdp["id"])
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        # HRP-189: spec/grade is now locked starting from ``sent``; this test
        # asserts the lock against ``in_progress`` for backwards-compatibility,
        # but the same 409 also covers ``sent`` and ``returned``.
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_pdp(
                db,
                tenant.id,
                pdp["id"],
                PDPUpdate(specialization_id=spec_b.id, grade_id=grade_b.id),
            )
        assert exc.value.status_code == 409

    async def test_change_grade_locked_in_sent(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-189: once the admin presses Send the (spec, grade) link is
        # frozen — both pencil icons disappear and the API answers 409.
        (spec_a, grade_a, _, _), (spec_b, grade_b, _, _) = await self._setup_two_links(
            db, tenant
        )
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Plan",
                employee_id=employee.id,
                specialization_id=spec_a.id,
                grade_id=grade_a.id,
            ),
        )
        await _ensure_all_items_have_materials(db, tenant.id, pdp["id"])
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        with pytest.raises(HTTPException) as exc:
            await service.update_pdp(
                db,
                tenant.id,
                pdp["id"],
                PDPUpdate(specialization_id=spec_b.id, grade_id=grade_b.id),
            )
        assert exc.value.status_code == 409

    async def test_change_grade_no_link_clears_auto_items(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.dictionary.models import DictionaryItem

        (spec_a, grade_a, _, _), _ = await self._setup_two_links(db, tenant)
        spec_orphan = DictionaryItem(
            type="specialization", title="Orphan spec", tenant_id=tenant.id
        )
        grade_orphan = DictionaryItem(
            type="grade", title="Orphan grade", tenant_id=tenant.id
        )
        db.add_all([spec_orphan, grade_orphan])
        await db.commit()

        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Plan",
                employee_id=employee.id,
                specialization_id=spec_a.id,
                grade_id=grade_a.id,
            ),
        )
        await service.update_pdp(
            db,
            tenant.id,
            pdp["id"],
            PDPUpdate(specialization_id=spec_orphan.id, grade_id=grade_orphan.id),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["items"] == []


class TestPDPItems:
    async def test_add_item(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Learn Python")
        )
        assert item["title"] == "Learn Python"
        assert item["is_passed"] is False

    async def test_mark_item_passed(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        # HRP-20: marking in ``sent`` auto-promotes the plan to in_progress.
        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id
        )
        assert result["is_passed"] is True

    async def test_mark_item_updates_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item1 = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="A")
        )
        item2 = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="B")
        )
        for it in (item1, item2):
            await service.add_material(
                db,
                tenant.id,
                pdp["id"],
                it["id"],
                PDPMaterialCreate(title="Mat", link="https://example.com"),
            )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.mark_item_passed(
            db, tenant.id, pdp["id"], item1["id"], user.id
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["total_progress"] == 50

    async def test_add_item_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException):
            await service.add_item(
                db, tenant.id, uuid.uuid4(), PDPItemCreate(title="X")
            )


class TestPDPListVisibility:
    """HRP-19: regular employees / managers don't see ``draft`` plans —
    those belong to the admin authoring queue."""

    async def test_admin_sees_drafts(self, db: AsyncSession, tenant, user, employee):
        await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Draft 1", employee_id=employee.id)
        )
        # hide_drafts=False simulates the router's branch for admin roles.
        pdps = await service.list_pdps(db, tenant.id, hide_drafts=False)
        statuses = [p["status"] for p in pdps]
        assert "draft" in statuses

    async def test_non_admin_does_not_see_drafts(
        self, db: AsyncSession, tenant, user, employee
    ):
        draft = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Draft", employee_id=employee.id)
        )
        sendable = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Active", employee_id=employee.id)
        )
        await _seed_sendable_item(db, tenant.id, sendable["id"])
        await service.change_pdp_status(db, tenant.id, sendable["id"], "sent")

        # hide_drafts=True simulates a non-admin caller.
        pdps = await service.list_pdps(db, tenant.id, hide_drafts=True)
        ids = {p["id"] for p in pdps}
        assert sendable["id"] in ids
        assert draft["id"] not in ids


class TestPDPMarkItemPermissions:
    """HRP-13 + HRP-20: only the plan owner may tick items, and only
    while the plan is in ``sent``/``in_progress``/``returned``. Marking
    in ``sent`` also auto-promotes the plan to ``in_progress``."""

    async def _create_with_item(self, db, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )
        return pdp, item

    async def test_non_owner_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        other_user_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await service.mark_item_passed(
                db, tenant.id, pdp["id"], item["id"], other_user_id
            )
        assert exc.value.status_code == 403

    async def test_owner_blocked_in_draft(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        # Still in draft — even the owner can't tick items off yet.
        with pytest.raises(HTTPException) as exc:
            await service.mark_item_passed(
                db, tenant.id, pdp["id"], item["id"], user.id
            )
        assert exc.value.status_code == 409

    async def test_owner_blocked_in_terminal(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        with pytest.raises(HTTPException) as exc:
            await service.mark_item_passed(
                db, tenant.id, pdp["id"], item["id"], user.id
            )
        assert exc.value.status_code == 409

    async def test_owner_can_mark_in_sent_auto_promotes(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-20: first tick in ``sent`` auto-promotes to ``in_progress``
        # and sets started_at.
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id
        )
        assert result["is_passed"] is True

        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "in_progress"
        assert detail["started_at"] is not None

    async def test_owner_can_mark_in_in_progress_no_status_change(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-197: ``sent → in_progress`` isn't a manual admin step anymore,
        # so we promote through the auto-promote path (owner tick on a
        # throwaway item) instead of calling change_pdp_status directly.
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )

        await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "in_progress"

    async def test_owner_can_mark_in_returned(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-198: ``returned`` is only reachable from ``review``, which the
        # admin moves the plan through. The bypass flag lets the test land in
        # the target state without enacting the full owner workflow.
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        await service.change_pdp_status(db, tenant.id, pdp["id"], "returned")

        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id
        )
        assert result["is_passed"] is True
        # Returned → mark does NOT auto-promote anywhere (only sent does).
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "returned"

    async def test_owner_round_trip_toggle_in_in_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-19 REDO Case 4: owner can set → unset → re-set an item in
        # ``in_progress``. Unticking never demotes the plan back to ``sent``.
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        # First tick auto-promotes ``sent`` → ``in_progress``.
        await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=True
        )
        # Untick.
        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=False
        )
        assert result["is_passed"] is False
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "in_progress"
        assert detail["items"][0]["is_passed"] is False
        # Re-tick.
        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=True
        )
        assert result["is_passed"] is True
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "in_progress"
        assert detail["items"][0]["is_passed"] is True

    async def test_owner_can_re_mark_passed_item_idempotent(
        self, db: AsyncSession, tenant, user, employee
    ):
        # Repeat set (True → True) stays idempotent — UI never triggers it
        # but the API must not error on a no-op write either.
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=True
        )
        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=True
        )
        assert result["is_passed"] is True

    async def test_owner_round_trip_toggle_in_returned(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-19 REDO Case 4: same round-trip works in ``returned`` —
        # the owner reworks the plan and may flip checkboxes both ways.
        # HRP-198: ``returned`` is only reachable from ``review`` now.
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        await service.change_pdp_status(db, tenant.id, pdp["id"], "returned")
        await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=True
        )
        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=False
        )
        assert result["is_passed"] is False
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "returned"
        assert detail["items"][0]["is_passed"] is False
        result = await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=True
        )
        assert result["is_passed"] is True

    async def test_owner_unmark_in_sent_does_not_promote(
        self, db: AsyncSession, tenant, user, employee
    ):
        # Owner unticking an unset checkbox while plan is ``sent`` is a no-op:
        # the plan must NOT auto-promote to in_progress on ``is_passed=False``.
        pdp, item = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.mark_item_passed(
            db, tenant.id, pdp["id"], item["id"], user.id, is_passed=False
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "sent"

    async def test_owner_can_submit_for_review_from_returned(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-19 case 3: returned -> review is a legitimate owner action.
        # HRP-198: this transition is now also part of the canonical map so
        # the admin can issue it without the bypass flag, but the owner path
        # still passes ``bypass_transition_check`` so the gate that requires
        # every item to be passed runs in the router rather than the service.
        pdp, _ = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        await service.change_pdp_status(db, tenant.id, pdp["id"], "returned")
        result = await service.change_pdp_status(
            db,
            tenant.id,
            pdp["id"],
            "review",
            bypass_transition_check=True,
        )
        assert result["status"] == "review"

    async def test_returned_to_review_now_in_map(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-198: ``returned → review`` is now part of the canonical
        # transition map (admins click "submit for review" from the
        # Returned details page).
        pdp, _ = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        await service.change_pdp_status(db, tenant.id, pdp["id"], "returned")
        result = await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        assert result["status"] == "review"

    async def test_returned_to_sent_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-198 Case 2: ``returned → sent`` is no longer allowed; the
        # only forward move is "submit for review".
        pdp, _ = await self._create_with_item(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        await service.change_pdp_status(db, tenant.id, pdp["id"], "returned")
        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert exc.value.status_code == 400


class TestPDPReviewItemToggle:
    """HRP-130: while a plan is in ``review``, admins and the assigned
    reviewer can tick/untick items. The plan owner cannot — they handed it
    off for review. Items must remain readable but not mutable for them."""

    async def _create_in_review(self, db, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        # HRP-197: ``sent → in_progress`` only happens via owner auto-promote,
        # but tests need the underlying state — use the bypass flag.
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        return pdp, item

    async def test_admin_can_toggle_in_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item = await self._create_in_review(db, tenant, user, employee)
        # The admin happens to also own the plan in the test fixture, so use a
        # different id to prove permission comes from ``is_admin`` and not
        # ownership.
        admin_id = uuid.uuid4()
        result = await service.mark_item_passed(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            admin_id,
            is_passed=True,
            is_admin=True,
        )
        assert result["is_passed"] is True
        # And unset works too.
        result = await service.mark_item_passed(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            admin_id,
            is_passed=False,
            is_admin=True,
        )
        assert result["is_passed"] is False

    async def test_reviewer_can_toggle_in_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        # The assigned PDP reviewer (non-admin) can also tick items in
        # ``review``. Create a real user row so ``pdps.reviewer_id`` FK holds.
        from datetime import datetime, timezone

        from app.core.security import hash_password
        from app.modules.assessment.models import PDP
        from app.modules.auth.models import User

        reviewer = User(
            email=f"reviewer-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="Rev",
            last_name="Iewer",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(reviewer)
        await db.commit()
        await db.refresh(reviewer)

        pdp_dict, item = await self._create_in_review(db, tenant, user, employee)
        pdp_row = await db.get(PDP, pdp_dict["id"])
        assert pdp_row is not None
        pdp_row.reviewer_id = reviewer.id
        await db.commit()

        result = await service.mark_item_passed(
            db,
            tenant.id,
            pdp_dict["id"],
            item["id"],
            reviewer.id,
            is_passed=True,
            is_admin=False,
        )
        assert result["is_passed"] is True

    async def test_division_manager_can_toggle_in_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-130 REDO Case 2: the implicit reviewer — the employee's
        # division manager — must be able to toggle items even when the
        # PDP has no explicit ``reviewer_id`` set. The UI surfaces them as
        # the Reviewer via the same fallback, so permissions have to
        # agree.
        from datetime import date, datetime, timezone

        from app.core.security import hash_password
        from app.modules.auth.models import User
        from app.modules.company.models import Division
        from app.modules.employee.models import Employee

        # Create a manager user + employee row and assign them as the
        # employee's division manager. ``reviewer_id`` on the PDP stays
        # NULL so the fallback path is exercised.
        manager_user = User(
            email=f"mgr-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="Mgr",
            last_name="One",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(manager_user)
        await db.commit()
        await db.refresh(manager_user)

        manager_employee = Employee(
            tenant_id=tenant.id,
            user_id=manager_user.id,
            hire_date=date(2024, 1, 15),
        )
        db.add(manager_employee)
        await db.commit()
        await db.refresh(manager_employee)

        division = Division(
            tenant_id=tenant.id,
            name="Engineering",
            manager_id=manager_employee.id,
        )
        db.add(division)
        await db.commit()
        await db.refresh(division)

        employee.division_id = division.id
        await db.commit()

        pdp, item = await self._create_in_review(db, tenant, user, employee)
        # No explicit reviewer_id — the manager is only the implicit
        # reviewer via the division fallback.
        result = await service.mark_item_passed(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            manager_user.id,
            is_passed=True,
            is_admin=False,
        )
        assert result["is_passed"] is True
        # And the PDPDetail surfaces ``is_reviewer=True`` for the same
        # viewer, so the UI checkbox unlocks.
        detail = await service.get_pdp_detail(
            db, tenant.id, pdp["id"], viewer_user_id=manager_user.id
        )
        assert detail["is_reviewer"] is True

    async def test_random_user_blocked_in_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item = await self._create_in_review(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await service.mark_item_passed(
                db,
                tenant.id,
                pdp["id"],
                item["id"],
                uuid.uuid4(),
                is_passed=True,
                is_admin=False,
            )
        assert exc.value.status_code == 403

    async def test_return_blocked_when_all_items_accepted(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-130: once every item is accepted while in review, the only
        # next step is to complete the plan. The API rejects the implicit
        # "return" path to keep parity with the UI which hides the button.
        pdp, item = await self._create_in_review(db, tenant, user, employee)
        # Mark the single item passed as admin.
        await service.mark_item_passed(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            uuid.uuid4(),
            is_passed=True,
            is_admin=True,
        )
        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(
                db, tenant.id, pdp["id"], "returned"
            )
        assert exc.value.status_code == 409

    async def test_return_allowed_when_any_item_unchecked(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, _ = await self._create_in_review(db, tenant, user, employee)
        # No items are passed at this point — Return is the natural choice.
        result = await service.change_pdp_status(
            db, tenant.id, pdp["id"], "returned"
        )
        assert result["status"] == "returned"

    async def test_admin_blocked_outside_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-13 still holds: even an admin cannot tick items while the plan
        # is being executed by the employee (sent/in_progress/returned).
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        with pytest.raises(HTTPException) as exc:
            await service.mark_item_passed(
                db,
                tenant.id,
                pdp["id"],
                item["id"],
                uuid.uuid4(),  # non-owner
                is_passed=True,
                is_admin=True,
            )
        assert exc.value.status_code == 403


class TestPDPTerminalTimestamp:
    """HRP-132: cancelling or completing a plan records ``finished_at`` so
    the UI can show "Completed at" / "Cancelled at" instead of the deadline.
    """

    async def test_finished_at_set_on_cancelled(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        before = pdp.get("finished_at")
        assert before is None
        result = await service.change_pdp_status(
            db, tenant.id, pdp["id"], "cancelled"
        )
        assert result["status"] == "cancelled"
        assert result["finished_at"] is not None

    async def test_finished_at_set_on_done(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        pid = pdp["id"]
        await _seed_sendable_item(db, tenant.id, pid)
        await service.change_pdp_status(db, tenant.id, pid, "sent")
        await service.change_pdp_status(
            db, tenant.id, pid, "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pid, "review")
        result = await service.change_pdp_status(db, tenant.id, pid, "done")
        assert result["finished_at"] is not None


class TestPDPTerminalLockHRP17:
    """HRP-17: a plan in ``done``/``cancelled`` is fully read-only —
    every mutating endpoint returns 409.

    The Items/Materials add/update/delete paths are already covered by
    ``_ensure_pdp_editable`` (see TestPDPItems and TestPDPMaterials).
    HRP-17 extends the lock to comments and mark_item_passed.
    """

    async def _terminal_pdp(self, db, tenant, user, employee, status="cancelled"):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )
        if status == "cancelled":
            await service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        else:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
            await service.change_pdp_status(
                db,
                tenant.id,
                pdp["id"],
                "in_progress",
                bypass_transition_check=True,
            )
            await service.change_pdp_status(db, tenant.id, pdp["id"], "review")
            await service.change_pdp_status(db, tenant.id, pdp["id"], "done")
        return pdp, item

    async def test_add_comment_blocked_in_cancelled(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, _ = await self._terminal_pdp(db, tenant, user, employee, "cancelled")
        with pytest.raises(HTTPException) as exc:
            await service.add_comment(
                db,
                tenant.id,
                pdp["id"],
                user.id,
                PDPCommentCreate(text="Nope"),
            )
        assert exc.value.status_code == 409

    async def test_add_comment_blocked_in_done(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, _ = await self._terminal_pdp(db, tenant, user, employee, "done")
        with pytest.raises(HTTPException) as exc:
            await service.add_comment(
                db,
                tenant.id,
                pdp["id"],
                user.id,
                PDPCommentCreate(text="Late thought"),
            )
        assert exc.value.status_code == 409

    async def test_mark_item_passed_blocked_in_terminal(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item = await self._terminal_pdp(db, tenant, user, employee, "done")
        with pytest.raises(HTTPException) as exc:
            await service.mark_item_passed(
                db, tenant.id, pdp["id"], item["id"], user.id
            )
        assert exc.value.status_code == 409


class TestPDPMaterials:
    async def test_add_material(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task")
        )
        mat = await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Python docs", link="https://docs.python.org"),
        )
        assert mat["title"] == "Python docs"
        assert mat["link"] == "https://docs.python.org"

    async def test_add_material_not_found(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        with pytest.raises(HTTPException):
            await service.add_material(
                db, tenant.id, pdp["id"], uuid.uuid4(), PDPMaterialCreate(title="X")
            )


class TestPDPComments:
    async def test_add_comment(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        comment = await service.add_comment(
            db, tenant.id, pdp["id"], user.id, PDPCommentCreate(text="Good progress")
        )
        assert comment["text"] == "Good progress"
        assert comment["user_id"] == user.id

    async def test_comment_appears_in_detail(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        await service.add_comment(
            db, tenant.id, pdp["id"], user.id, PDPCommentCreate(text="Note")
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["comments"]) >= 1

    async def test_comment_pdp_not_found(self, db: AsyncSession, tenant, user):
        with pytest.raises(HTTPException):
            await service.add_comment(
                db, tenant.id, uuid.uuid4(), user.id, PDPCommentCreate(text="X")
            )


class TestPDPItemEdit:
    async def test_update_item_changes_fields(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Old", description="Old desc")
        )
        updated = await service.update_item(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPItemUpdate(title="New", description="New desc"),
        )
        assert updated["title"] == "New"
        assert updated["description"] == "New desc"

    async def test_update_item_with_materials_returns_them(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Doc", link="https://x.test"),
        )
        updated = await service.update_item(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPItemUpdate(title="Renamed"),
        )
        assert updated["title"] == "Renamed"
        assert len(updated["materials"]) == 1
        assert updated["materials"][0]["title"] == "Doc"

    async def test_update_item_blocked_in_terminal_status(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task")
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        with pytest.raises(HTTPException) as exc:
            await service.update_item(
                db,
                tenant.id,
                pdp["id"],
                item["id"],
                PDPItemUpdate(title="Renamed"),
            )
        assert exc.value.status_code == 409

    async def test_delete_item_recomputes_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-13/HRP-17: deleting items is admin-only and forbidden once the
        # plan is active. To keep the test focused on the progress-recompute
        # path we stay in draft and flip is_passed on the ORM directly.
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        kept = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="A")
        )
        doomed = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="B")
        )

        from app.modules.assessment.models import PDPItem

        kept_obj = await db.get(PDPItem, kept["id"])
        assert kept_obj is not None
        kept_obj.is_passed = True
        await db.commit()
        # Reflect the manual flip on PDP.total_progress, which mark_item_passed
        # would normally maintain.
        await service._recompute_progress(db, pdp["id"])
        await db.commit()

        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["total_progress"] == 50

        await service.delete_item(db, tenant.id, pdp["id"], doomed["id"])
        # After delete: 1/1 passed → 100%
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["total_progress"] == 100
        assert len(detail["items"]) == 1

    async def test_delete_item_with_materials_cascades(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task")
        )
        await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://x.test"),
        )
        await service.delete_item(db, tenant.id, pdp["id"], item["id"])
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["items"] == []

    async def test_reorder_items(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        a = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="A", sort_index=0)
        )
        b = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="B", sort_index=1)
        )
        c = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="C", sort_index=2)
        )
        ordered = await service.reorder_items(
            db, tenant.id, pdp["id"], [c["id"], a["id"], b["id"]]
        )
        titles = [i["title"] for i in ordered]
        assert titles == ["C", "A", "B"]
        assert [i["sort_index"] for i in ordered] == [0, 1, 2]

    async def test_reorder_rejects_incomplete_list(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        a = await service.add_item(db, tenant.id, pdp["id"], PDPItemCreate(title="A"))
        await service.add_item(db, tenant.id, pdp["id"], PDPItemCreate(title="B"))
        with pytest.raises(HTTPException) as exc:
            await service.reorder_items(db, tenant.id, pdp["id"], [a["id"]])
        assert exc.value.status_code == 400


class TestPDPMaterialEdit:
    async def test_update_material(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task")
        )
        mat = await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Old", format="article"),
        )
        updated = await service.update_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            mat["id"],
            PDPMaterialUpdate(title="New", format="course"),
        )
        assert updated["title"] == "New"
        assert updated["format"] == "course"

    async def test_delete_material(self, db: AsyncSession, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task")
        )
        mat = await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Doc"),
        )
        await service.delete_material(db, tenant.id, pdp["id"], item["id"], mat["id"])
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["items"][0]["materials"] == []

    async def test_delete_material_blocked_in_terminal(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task")
        )
        mat = await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Doc"),
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        with pytest.raises(HTTPException) as exc:
            await service.delete_material(
                db, tenant.id, pdp["id"], item["id"], mat["id"]
            )
        assert exc.value.status_code == 409


class TestPDPReviewerName:
    async def test_explicit_reviewer_name(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.core.security import hash_password
        from app.modules.auth.models import User

        reviewer = User(
            email=f"rev-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("x"),
            first_name="Anna",
            last_name="Reviewer",
            tenant_id=tenant.id,
        )
        db.add(reviewer)
        await db.commit()
        await db.refresh(reviewer)

        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Plan",
                employee_id=employee.id,
                reviewer_id=reviewer.id,
            ),
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["reviewer_name"] == "Anna Reviewer"

    async def test_reviewer_falls_back_to_division_manager(
        self, db: AsyncSession, tenant, user, employee
    ):
        from datetime import date

        from app.core.security import hash_password
        from app.modules.auth.models import User
        from app.modules.company.models import Division
        from app.modules.employee.models import Employee

        manager_user = User(
            email=f"mgr-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("x"),
            first_name="Mike",
            last_name="Manager",
            tenant_id=tenant.id,
        )
        db.add(manager_user)
        await db.flush()
        manager_emp = Employee(
            user_id=manager_user.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 1),
        )
        db.add(manager_emp)
        await db.flush()
        division = Division(
            name="Engineering",
            tenant_id=tenant.id,
            manager_id=manager_emp.id,
        )
        db.add(division)
        await db.flush()
        employee.division_id = division.id
        await db.commit()

        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["reviewer_name"] == "Mike Manager"

    async def test_no_reviewer_no_division(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["reviewer_name"] is None


class TestPDPDraftSentEmail:
    async def test_draft_to_sent_enqueues_email(
        self, db: AsyncSession, tenant, user, employee, monkeypatch
    ):
        calls: list[dict] = []

        def fake_enqueue(to, subject, body, **kwargs):
            calls.append(
                {
                    "to": to,
                    "subject": subject,
                    "body": body,
                    "kwargs": kwargs,
                }
            )

        monkeypatch.setattr(
            "app.core.email.enqueue_email",
            fake_enqueue,
        )

        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        await _seed_sendable_item(db, tenant.id, pdp["id"])
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        assert len(calls) == 1
        assert calls[0]["to"] == user.email
        assert "Development plan" in calls[0]["subject"]
        assert calls[0]["kwargs"].get("template_code") == "pdp.sent"

    async def test_other_transitions_do_not_email(
        self, db: AsyncSession, tenant, user, employee, monkeypatch
    ):
        calls: list[dict] = []
        monkeypatch.setattr(
            "app.core.email.enqueue_email",
            lambda *a, **kw: calls.append({"a": a, "kw": kw}),
        )

        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        assert calls == []


class TestPDPDeadlineGates:
    """HRP-191 + HRP-187: a deadline strictly in the past blocks
    Draft→Sent and Review→Returned. Same-day deadlines are still valid.

    The schema validator (HRP-23 ``not_past_deadline``) rejects past dates
    on the create / patch endpoints, so the gates only meaningfully fire on
    plans whose deadline was set in the future and elapsed in between. We
    simulate that by mutating ``PDP.deadline`` directly via the ORM after
    seeding.
    """

    async def _seeded_plan(self, db, tenant, user, employee):
        pdp = await service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(title="Plan", employee_id=employee.id),
        )
        await _seed_sendable_item(db, tenant.id, pdp["id"])
        return pdp

    async def _set_deadline(self, db, pdp_id, deadline):
        from app.modules.assessment.models import PDP as PDPModel

        p = await db.get(PDPModel, pdp_id)
        assert p is not None
        p.deadline = deadline
        await db.commit()

    async def test_send_blocked_when_deadline_in_past(
        self, db: AsyncSession, tenant, user, employee
    ):
        from datetime import datetime, timedelta, timezone

        pdp = await self._seeded_plan(db, tenant, user, employee)
        await self._set_deadline(
            db, pdp["id"], datetime.now(timezone.utc) - timedelta(days=2)
        )

        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert exc.value.status_code == 400
        assert "deadline" in exc.value.detail.lower()

        # Status must not flip — gate runs before the write.
        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "draft"

    async def test_send_allowed_when_deadline_today(
        self, db: AsyncSession, tenant, user, employee
    ):
        from datetime import datetime, time, timezone

        pdp = await self._seeded_plan(db, tenant, user, employee)
        today_end = datetime.combine(
            datetime.now(timezone.utc).date(), time(23, 59), tzinfo=timezone.utc
        )
        await self._set_deadline(db, pdp["id"], today_end)
        result = await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert result["status"] == "sent"

    async def test_send_allowed_when_no_deadline(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await self._seeded_plan(db, tenant, user, employee)
        result = await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        assert result["status"] == "sent"

    async def test_review_to_returned_blocked_when_deadline_in_past(
        self, db: AsyncSession, tenant, user, employee
    ):
        from datetime import datetime, timedelta, timezone

        pdp = await self._seeded_plan(db, tenant, user, employee)
        # Move through the FSM with no deadline so the gate doesn't fire on
        # Send; only afterwards put the deadline into the past.
        await service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await service.change_pdp_status(db, tenant.id, pdp["id"], "review")

        await self._set_deadline(
            db, pdp["id"], datetime.now(timezone.utc) - timedelta(days=2)
        )

        with pytest.raises(HTTPException) as exc:
            await service.change_pdp_status(db, tenant.id, pdp["id"], "returned")
        assert exc.value.status_code == 400
        assert "deadline" in exc.value.detail.lower()

        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["status"] == "review"


class TestPDPProgressOnAddItem:
    """HRP-199: progress is recomputed when items are added so the cached
    ``total_progress`` value never falls out of sync with the live ratio."""

    async def test_add_item_after_progress_recomputes_total_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.assessment.models import PDPItem

        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item_a = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="A")
        )
        item_b = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="B")
        )

        # Mark one item as passed via the ORM (status is draft, so the
        # mark_item_passed gate would 409; this test is about the cached
        # ``total_progress`` value being kept in sync, not the transition
        # machinery).
        passed = await db.get(PDPItem, item_a["id"])
        assert passed is not None
        passed.is_passed = True
        await db.commit()
        await service._recompute_progress(db, pdp["id"])
        await db.commit()

        detail = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail["total_progress"] == 50  # 1/2

        # Adding a new item drops the ratio from 1/2 to 1/3.
        await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="C")
        )
        detail2 = await service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert detail2["total_progress"] == 33  # int(1/3 * 100)
        # Sanity: the newly added items appear in sort order.
        sorted_titles = [
            i["title"] for i in sorted(detail2["items"], key=lambda i: i["sort_index"])
        ]
        assert sorted_titles[-1] == "C"
        assert item_b["id"] in {i["id"] for i in detail2["items"]}


class TestPDPItemSortIndex:
    """HRP-201: new items land at the end of the list, regardless of the
    ``sort_index`` value the client sent."""

    async def test_add_item_assigns_next_sort_index(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        a = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="A", sort_index=0)
        )
        b = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="B", sort_index=0)
        )
        c = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="C", sort_index=0)
        )
        # Indices are strictly ascending so the list is order-stable.
        assert (a["sort_index"], b["sort_index"], c["sort_index"]) == (0, 1, 2)


class TestPDPPassedItemLock:
    """HRP-200: passed items + their materials are read-only. The admin
    has to clear the checkbox (via Review) before editing them again."""

    async def _passed_item(self, db, tenant, user, employee):
        pdp = await service.create_pdp(
            db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
        )
        item = await service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        mat = await service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )

        from app.modules.assessment.models import PDPItem

        item_obj = await db.get(PDPItem, item["id"])
        assert item_obj is not None
        item_obj.is_passed = True
        await db.commit()
        return pdp, item, mat

    async def test_update_passed_item_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item, _ = await self._passed_item(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await service.update_item(
                db,
                tenant.id,
                pdp["id"],
                item["id"],
                PDPItemUpdate(title="rename"),
            )
        assert exc.value.status_code == 403

    async def test_delete_passed_item_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item, _ = await self._passed_item(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, pdp["id"], item["id"])
        assert exc.value.status_code == 403

    async def test_add_material_to_passed_item_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item, _ = await self._passed_item(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await service.add_material(
                db,
                tenant.id,
                pdp["id"],
                item["id"],
                PDPMaterialCreate(title="More", link="https://example.com"),
            )
        assert exc.value.status_code == 403

    async def test_update_material_of_passed_item_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item, mat = await self._passed_item(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await service.update_material(
                db,
                tenant.id,
                pdp["id"],
                item["id"],
                mat["id"],
                PDPMaterialUpdate(title="rename"),
            )
        assert exc.value.status_code == 403

    async def test_delete_material_of_passed_item_blocked(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp, item, mat = await self._passed_item(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await service.delete_material(
                db, tenant.id, pdp["id"], item["id"], mat["id"]
            )
        assert exc.value.status_code == 403

    async def test_unchecking_passed_item_restores_edit_access(
        self, db: AsyncSession, tenant, user, employee
    ):
        # After the reviewer clears the checkbox the item is editable
        # again — confirmed by a successful update.
        pdp, item, _ = await self._passed_item(db, tenant, user, employee)
        from app.modules.assessment.models import PDPItem

        item_obj = await db.get(PDPItem, item["id"])
        assert item_obj is not None
        item_obj.is_passed = False
        await db.commit()

        updated = await service.update_item(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPItemUpdate(title="renamed"),
        )
        assert updated["title"] == "renamed"


class TestHRP333EmployeeSummary:
    async def test_pdp_read_carries_position_and_status(
        self, db, tenant, user, employee
    ):
        data = PDPCreate(title="Summary Plan", employee_id=employee.id)
        pdp = await service.create_pdp(db, tenant.id, user.id, data)
        assert pdp["employee_position_title"] == employee.position_title
        assert pdp["employee_status"] == employee.status
