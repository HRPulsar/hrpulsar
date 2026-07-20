import uuid
from datetime import date

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import AnswerScale
from app.modules.assessment.schemas import (
    AnswerRecord,
    AssessmentCreate,
    CalibrateItem,
    CPACreate,
    MassAssessmentCreate,
    ParticipantAdd,
)
from app.modules.employee.models import Employee
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import (
    advance_to_done,
    advance_to_in_progress,
    seed_send_prereqs,
)


class TestAssessmentCRUD:
    async def test_create_assessment(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        data = AssessmentCreate(
            title="Q1 Review",
            employee_id=employee.id,
            type_code="self",
        )
        result = await service.create_assessment(db, tenant.id, user.id, data)
        assert result["title"] == "Q1 Review"
        assert result["type_code"] == "self"
        assert result["status_code"] == "draft"

    async def test_list_assessments(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        data = AssessmentCreate(title="Test", employee_id=employee.id, type_code="360")
        await service.create_assessment(db, tenant.id, user.id, data)

        items, total = await service.list_assessments(db, tenant.id)
        assert total >= 1

    async def test_list_assessments_filtered_by_employee(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        data = AssessmentCreate(
            title="Emp filter", employee_id=employee.id, type_code="self"
        )
        await service.create_assessment(db, tenant.id, user.id, data)

        items, total = await service.list_assessments(
            db, tenant.id, employee_id=employee.id
        )
        assert total >= 1
        assert all(i["employee_id"] == employee.id for i in items)

    async def test_list_assessments_pagination(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        for i in range(3):
            await service.create_assessment(
                db,
                tenant.id,
                user.id,
                AssessmentCreate(
                    title=f"A{i}", employee_id=employee.id, type_code="self"
                ),
            )

        items, total = await service.list_assessments(db, tenant.id, skip=0, limit=2)
        assert len(items) == 2
        assert total >= 3

    async def test_get_assessment_detail(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        data = AssessmentCreate(
            title="Detail test", employee_id=employee.id, type_code="180"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["title"] == "Detail test"
        assert "participants" in detail
        assert "competence_ids" in detail
        assert "results" in detail

    async def test_get_detail_embeds_scale_after_send(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """HRP-11: after Sent, scale_id points at a snapshot that the
        picker list (`/answer-scales`) does not return; detail must
        embed the resolved scale so the UI keeps rendering it."""
        data = AssessmentCreate(
            title="Scale embed", employee_id=employee.id, type_code="self"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)

        await seed_send_prereqs(db, tenant.id, created["id"])
        sent = await service.change_status(db, tenant.id, created["id"], "sent")

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        assert detail["scale"] is not None
        # scale_id was rewritten to the snapshot id during change_status
        assert detail["scale"]["id"] == sent["scale_id"]
        assert detail["scale"]["is_snapshot"] is True
        # Snapshots have tenant_id=NULL; lock that contract so a future
        # rewrite of snapshot_scale_for_assessment can't quietly leak the
        # original tenant link.
        assert detail["scale"]["tenant_id"] is None
        assert len(detail["scale"]["options"]) >= 2


class TestAssessmentStatus:
    async def test_change_status_does_not_raise(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        data = AssessmentCreate(
            title="Status test", employee_id=employee.id, type_code="self"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)
        assert created["status_code"] == "draft"

        # Should not raise — successfully changes status
        await seed_send_prereqs(db, tenant.id, created["id"])
        result = await service.change_status(db, tenant.id, created["id"], "sent")
        assert result is not None

    async def test_cannot_go_backwards(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        data = AssessmentCreate(
            title="Back test", employee_id=employee.id, type_code="self"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)

        # Forward transition should work
        await seed_send_prereqs(db, tenant.id, created["id"])

        await service.change_status(db, tenant.id, created["id"], "sent")

        # Backward transition should fail
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "draft")
        assert exc.value.status_code == 400


class TestParticipants:
    async def test_add_participant(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        admin_role,
        position,
        assessment_statuses,
        assessment_types,
    ):
        # HRP-18 auto-adds the assessee as a "self" participant on create —
        # validate manual add-participant against a *different* employee/user.
        from datetime import date, datetime, timezone

        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles
        from app.modules.employee.models import Employee

        peer_user = User(
            email=f"peer-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="Peer",
            last_name="Reviewer",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(peer_user)
        await db.commit()
        await db.refresh(peer_user)
        await db.execute(
            user_roles.insert().values(user_id=peer_user.id, role_id=admin_role.id)
        )
        peer_emp = Employee(
            user_id=peer_user.id,
            tenant_id=tenant.id,
            position_id=position.id,
            position_title=position.title,
            hire_date=date(2024, 1, 15),
        )
        db.add(peer_emp)
        await db.commit()
        await db.refresh(peer_emp)

        data = AssessmentCreate(
            title="Part test", employee_id=employee.id, type_code="360"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)

        p = await service.add_participant(
            db,
            tenant.id,
            created["id"],
            ParticipantAdd(employee_id=peer_emp.id, role="manager"),
        )
        assert p["user_id"] == peer_user.id
        assert p["role"] == "manager"
        assert p["is_completed"] is False

    async def test_add_participant_404_when_user_row_missing(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Production hit this on 2026-04-22: an Employee row whose user_id
        no longer points at any users row. Without the guard, the INSERT
        into assessment_participants trips a FK violation at commit time.
        """
        from sqlalchemy import text

        data = AssessmentCreate(
            title="Orphan test", employee_id=employee.id, type_code="360"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)

        # Simulate the orphan: detach the user FK on the employee row via
        # raw SQL (the model's CASCADE would otherwise wipe the employee).
        bogus_user_id = uuid.uuid4()
        await db.execute(
            text("ALTER TABLE employees DROP CONSTRAINT employees_user_id_fkey")
        )
        await db.execute(
            text("UPDATE employees SET user_id = :u WHERE id = :e"),
            {"u": bogus_user_id, "e": employee.id},
        )
        await db.commit()
        db.expunge_all()  # force add_participant's db.get() to re-read from DB

        with pytest.raises(HTTPException) as exc:
            await service.add_participant(
                db,
                tenant.id,
                created["id"],
                ParticipantAdd(employee_id=employee.id, role="peer"),
            )
        assert exc.value.status_code == 404
        assert "user" in exc.value.detail.lower()

    async def test_user_delete_cascades_participants(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Regression guard: assessment_participants.user_id has ON DELETE
        CASCADE so removing a user atomically removes their participations
        instead of restricting the delete with a FK violation.
        """
        from datetime import date as _date
        from datetime import datetime, timezone

        from app.core.security import hash_password
        from app.modules.assessment.models import AssessmentParticipant
        from app.modules.auth.models import User
        from app.modules.employee.models import Employee
        from app.modules.position.models import Position
        from sqlalchemy import select as _sel

        # Separate peer user — `user` itself is the assessment initiator,
        # which is a different FK without cascade. Test cascade on a user
        # whose only references are participation rows.
        peer = User(
            email=f"peer-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("x"),
            first_name="Peer",
            last_name="User",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(peer)
        await db.commit()
        await db.refresh(peer)

        # Position required by Employee FK
        pos = Position(tenant_id=tenant.id, title="Tester", source="manual")
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        peer_emp = Employee(
            user_id=peer.id,
            tenant_id=tenant.id,
            position_id=pos.id,
            position_title=pos.title,
            hire_date=_date(2024, 1, 1),
        )
        db.add(peer_emp)
        await db.commit()
        await db.refresh(peer_emp)

        data = AssessmentCreate(
            title="Cascade test", employee_id=employee.id, type_code="360"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)
        await service.add_participant(
            db,
            tenant.id,
            created["id"],
            ParticipantAdd(employee_id=peer_emp.id, role="peer"),
        )

        rows_before = (
            (
                await db.execute(
                    _sel(AssessmentParticipant).where(
                        AssessmentParticipant.assessment_id == created["id"],
                        AssessmentParticipant.user_id == peer.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_before) == 1

        # HRP-305: prod DELETE-guard triggers refuse to delete users that
        # belong to a non-demo tenant. Flip the fixture tenant to demo
        # for the duration of the cascade-coverage delete, then reset it
        # in a try/finally so the leak does not pollute downstream tests
        # that share the test DB (conftest's _tables_created global means
        # tenants persist across tests).
        from sqlalchemy import text as _text

        await db.execute(
            _text("UPDATE tenants SET is_demo = TRUE WHERE id = :t"),
            {"t": tenant.id},
        )
        await db.commit()

        try:
            target = await db.get(User, peer.id)
            await db.delete(target)
            await db.commit()
        finally:
            await db.execute(
                _text("UPDATE tenants SET is_demo = FALSE WHERE id = :t"),
                {"t": tenant.id},
            )
            await db.commit()

        rows_after = (
            (
                await db.execute(
                    _sel(AssessmentParticipant).where(
                        AssessmentParticipant.assessment_id == created["id"],
                        AssessmentParticipant.user_id == peer.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows_after == []


class TestCalibration:
    async def test_calibrate_creates_results(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        # Create a real competence for the FK constraint
        from app.modules.competence import service as comp_service
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Calib Group")
        )
        comp = await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title="Calib Comp", group_id=group.id)
        )

        data = AssessmentCreate(
            title="Calib test", employee_id=employee.id, type_code="self"
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)

        items = [CalibrateItem(competence_id=comp.id, calibrated_score=4.5)]
        results = await service.calibrate(db, tenant.id, created["id"], items)
        assert len(results) == 1
        assert results[0]["calibrated_score"] == 4.5


# --- Helper to create an assessment ---


async def _make_assessment(
    db, tenant, user, employee, assessment_statuses, assessment_types, **kwargs
):
    data = AssessmentCreate(
        title=kwargs.get("title", f"Test-{uuid.uuid4().hex[:6]}"),
        employee_id=employee.id,
        type_code=kwargs.get("type_code", "self"),
    )
    return await service.create_assessment(db, tenant.id, user.id, data)


# --- Detail / status edge cases ---


class TestAutoSelfParticipant:
    @pytest.mark.parametrize("type_code", ["self", "180", "360"])
    async def test_self_participant_auto_added(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        type_code,
    ):
        from app.modules.assessment.models import AssessmentParticipant
        from sqlalchemy import select as _sel

        data = AssessmentCreate(
            title="Auto-self",
            employee_id=employee.id,
            type_code=type_code,
        )
        created = await service.create_assessment(db, tenant.id, user.id, data)

        result = await db.execute(
            _sel(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == created["id"]
            )
        )
        participants = result.scalars().all()
        self_parts = [p for p in participants if p.role == "self"]
        assert len(self_parts) == 1
        # The self-participant must be the assessed employee's user
        assert self_parts[0].user_id == employee.user_id

    async def test_self_type_does_not_add_manager_for_division_manager(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """For type=self, manager auto-assignment is skipped even when a division manager exists."""
        from app.core.security import hash_password
        from app.modules.assessment.models import AssessmentParticipant
        from app.modules.auth.models import User as AuthUser
        from app.modules.company.models import Division
        from sqlalchemy import select as _sel

        # Create a manager and link the employee's division to them
        mgr_user = AuthUser(
            email=f"mgrself-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("test"),
            first_name="Mgr",
            last_name="Self",
            tenant_id=tenant.id,
        )
        db.add(mgr_user)
        await db.flush()
        mgr_emp = Employee(
            user_id=mgr_user.id,
            tenant_id=tenant.id,
            position_title="Manager",
            hire_date=date(2023, 1, 1),
        )
        db.add(mgr_emp)
        await db.flush()
        div = Division(
            tenant_id=tenant.id,
            name=f"Div-{uuid.uuid4().hex[:6]}",
            manager_id=mgr_emp.id,
        )
        db.add(div)
        await db.flush()
        employee.division_id = div.id
        await db.commit()

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Self only", employee_id=employee.id, type_code="self"
            ),
        )

        result = await db.execute(
            _sel(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == created["id"]
            )
        )
        roles = [p.role for p in result.scalars().all()]
        assert roles == ["self"]


class TestTerminalStatusGuard:
    async def test_cannot_change_status_from_done(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await seed_send_prereqs(db, tenant.id, created["id"])
        await service.change_status(db, tenant.id, created["id"], "sent")
        await advance_to_in_progress(db, tenant.id, created["id"])
        await advance_to_done(db, tenant.id, created["id"])

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "cancelled")
        assert exc.value.status_code == 400

    async def test_cannot_change_status_from_cancelled(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.change_status(db, tenant.id, created["id"], "cancelled")

        with pytest.raises(HTTPException) as exc:
            await seed_send_prereqs(db, tenant.id, created["id"])

            await service.change_status(db, tenant.id, created["id"], "sent")
        assert exc.value.status_code == 400

    async def test_cannot_add_participant_to_terminal(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.change_status(db, tenant.id, created["id"], "cancelled")

        with pytest.raises(HTTPException) as exc:
            await service.add_participant(
                db,
                tenant.id,
                created["id"],
                ParticipantAdd(employee_id=employee.id, role="peer"),
            )
        assert exc.value.status_code == 400

    async def test_cannot_add_competences_to_terminal(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.change_status(db, tenant.id, created["id"], "cancelled")

        with pytest.raises(HTTPException) as exc:
            await service.add_competences(db, tenant.id, created["id"], [uuid.uuid4()])
        assert exc.value.status_code == 400

    async def test_cannot_record_answer_terminal(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")
        await service.change_status(db, tenant.id, created["id"], "cancelled")

        data = AnswerRecord(
            participant_id=self_part["id"],
            indicator_id=uuid.uuid4(),
            score=3,
        )
        with pytest.raises(HTTPException) as exc:
            await service.record_answer(db, tenant.id, user.id, created["id"], data)
        assert exc.value.status_code == 400

    async def test_cannot_calibrate_terminal(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.change_status(db, tenant.id, created["id"], "cancelled")

        with pytest.raises(HTTPException) as exc:
            await service.calibrate(
                db,
                tenant.id,
                created["id"],
                [CalibrateItem(competence_id=uuid.uuid4(), calibrated_score=4.0)],
            )
        assert exc.value.status_code == 400


class TestAssessmentDetailEdgeCases:
    async def test_get_detail_not_found(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        with pytest.raises(HTTPException) as exc:
            await service.get_assessment_detail(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_change_status_not_found(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        with pytest.raises(HTTPException) as exc:
            await seed_send_prereqs(db, tenant.id, uuid.uuid4())

            await service.change_status(db, tenant.id, uuid.uuid4(), "sent")
        assert exc.value.status_code == 404

    async def test_change_status_to_in_progress_sets_started_at(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        # draft -> sent -> in_progress
        await seed_send_prereqs(db, tenant.id, created["id"])

        await service.change_status(db, tenant.id, created["id"], "sent")
        result = await advance_to_in_progress(db, tenant.id, created["id"])
        assert result["started_at"] is not None

    async def test_change_status_to_done_sets_finished_at(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await seed_send_prereqs(db, tenant.id, created["id"])

        await service.change_status(db, tenant.id, created["id"], "sent")
        await advance_to_in_progress(db, tenant.id, created["id"])
        result = await advance_to_done(db, tenant.id, created["id"])
        assert result["finished_at"] is not None


# --- Participant edge cases ---


class TestParticipantEdgeCases:
    async def test_add_participant_assessment_not_found(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        with pytest.raises(HTTPException) as exc:
            await service.add_participant(
                db,
                tenant.id,
                uuid.uuid4(),
                ParticipantAdd(employee_id=user.id, role="self"),
            )
        assert exc.value.status_code == 404


# --- Add competences edge cases ---


class TestAddCompetencesEdgeCases:
    async def test_add_competences_success(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.competence import service as comp_service
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="ACG")
        )
        comp = await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title="ACC", group_id=group.id)
        )

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        result = await service.add_competences(db, tenant.id, created["id"], [comp.id])
        assert comp.id in result

    async def test_add_competences_assessment_not_found(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        with pytest.raises(HTTPException) as exc:
            await service.add_competences(db, tenant.id, uuid.uuid4(), [uuid.uuid4()])
        assert exc.value.status_code == 404


# --- Record answer ---


class TestRecordAnswer:
    async def test_record_answer_success(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.competence import service as comp_service
        from app.modules.competence.models import Indicator, SkillLevel
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )
        from sqlalchemy import select

        # Create competence + indicator
        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="AnswerG")
        )
        comp = await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title="AnswerC", group_id=group.id)
        )

        result = await db.execute(select(SkillLevel).limit(1))
        sl = result.scalar_one_or_none()
        if not sl:
            sl = SkillLevel(title="Basic", sort_index=0)
            db.add(sl)
            await db.commit()
            await db.refresh(sl)

        ind = Indicator(
            title="Test Ind",
            weight=1,
            sort_index=0,
            skill_level_id=sl.id,
            competence_id=comp.id,
            tenant_id=tenant.id,
        )
        db.add(ind)
        await db.commit()
        await db.refresh(ind)

        # Create assessment — auto-adds self-participant for the evaluatee
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.add_competences(db, tenant.id, created["id"], [comp.id])
        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")

        data = AnswerRecord(
            participant_id=self_part["id"],
            indicator_id=ind.id,
            score=4,
            comment="Good",
        )
        answer = await service.record_answer(
            db, tenant.id, user.id, created["id"], data
        )
        assert answer["indicator_id"] == ind.id
        assert answer["score"] == 4

    async def test_record_answer_rejects_indicator_outside_assessment(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """An indicator whose competence is not attached to the assessment must be rejected."""
        from app.modules.competence import service as comp_service
        from app.modules.competence.models import Indicator, SkillLevel
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )
        from sqlalchemy import select

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="Outside G")
        )
        outside_comp = await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title="OutsideC", group_id=group.id)
        )
        result = await db.execute(select(SkillLevel).limit(1))
        sl = result.scalar_one_or_none()
        if not sl:
            sl = SkillLevel(title="Basic", sort_index=0)
            db.add(sl)
            await db.commit()
            await db.refresh(sl)
        ind = Indicator(
            title="Outside Ind",
            weight=1,
            sort_index=0,
            skill_level_id=sl.id,
            competence_id=outside_comp.id,
            tenant_id=tenant.id,
        )
        db.add(ind)
        await db.commit()
        await db.refresh(ind)

        # Assessment has NO competences attached
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")

        data = AnswerRecord(
            participant_id=self_part["id"], indicator_id=ind.id, score=3
        )
        with pytest.raises(HTTPException) as exc:
            await service.record_answer(db, tenant.id, user.id, created["id"], data)
        assert exc.value.status_code == 400

    async def test_record_answer_assessment_not_found(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        data = AnswerRecord(
            participant_id=uuid.uuid4(),
            indicator_id=uuid.uuid4(),
            score=3,
        )
        with pytest.raises(HTTPException) as exc:
            await service.record_answer(db, tenant.id, user.id, uuid.uuid4(), data)
        assert exc.value.status_code == 404

    async def test_record_answer_rejects_other_users_participant(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """A user cannot submit answers for a participant entry that isn't theirs."""
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")

        data = AnswerRecord(
            participant_id=self_part["id"],
            indicator_id=uuid.uuid4(),
            score=3,
        )
        # A different user trying to submit for the assessee's participant row
        with pytest.raises(HTTPException) as exc:
            await service.record_answer(
                db, tenant.id, uuid.uuid4(), created["id"], data
            )
        assert exc.value.status_code == 403


# --- Get results ---


class TestGetResults:
    async def test_get_results_empty(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        results = await service.get_results(db, tenant.id, created["id"])
        assert results == []

    async def test_get_results_after_calibration(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.competence import service as comp_service
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="ResG")
        )
        comp = await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title="ResC", group_id=group.id)
        )

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.calibrate(
            db,
            tenant.id,
            created["id"],
            [CalibrateItem(competence_id=comp.id, calibrated_score=3.5)],
        )

        results = await service.get_results(db, tenant.id, created["id"])
        assert len(results) == 1
        assert results[0]["calibrated_score"] == 3.5

    async def test_get_results_assessment_not_found(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        with pytest.raises(HTTPException) as exc:
            await service.get_results(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404


# --- Calibrate edge cases ---


class TestCalibrateEdgeCases:
    async def test_calibrate_assessment_not_found(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        with pytest.raises(HTTPException) as exc:
            await service.calibrate(
                db,
                tenant.id,
                uuid.uuid4(),
                [CalibrateItem(competence_id=uuid.uuid4(), calibrated_score=5.0)],
            )
        assert exc.value.status_code == 404

    async def test_calibrate_upsert_updates_existing(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.competence import service as comp_service
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="UpsG")
        )
        comp = await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title="UpsC", group_id=group.id)
        )

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )

        # First calibration creates the result
        await service.calibrate(
            db,
            tenant.id,
            created["id"],
            [CalibrateItem(competence_id=comp.id, calibrated_score=3.0)],
        )

        # Second calibration updates it
        results = await service.calibrate(
            db,
            tenant.id,
            created["id"],
            [CalibrateItem(competence_id=comp.id, calibrated_score=4.5)],
        )
        assert len(results) == 1
        assert results[0]["calibrated_score"] == 4.5


# --- Answer scales ---


class TestListScales:
    async def test_list_scales_empty(self, db: AsyncSession, tenant):
        scales = await service.list_scales(db, tenant.id)
        # May be empty or have pre-seeded data; just ensure no error
        assert isinstance(scales, list)

    async def test_list_scales_includes_origin_and_tenant(
        self, db: AsyncSession, tenant
    ):
        from sqlalchemy import select as sa_select

        # Reuse-or-seed the singleton global default scale (partial unique
        # index forbids a second tenant_id=NULL is_default=true row).
        existing_q = await db.execute(
            sa_select(AnswerScale).where(
                AnswerScale.tenant_id.is_(None),
                AnswerScale.is_default.is_(True),
                AnswerScale.deleted_at.is_(None),
            )
        )
        origin_scale = existing_q.scalar_one_or_none()
        if origin_scale is None:
            origin_scale = AnswerScale(
                title="Standard 5-Point Scale",
                is_default=True,
                tenant_id=None,
            )
            db.add(origin_scale)
            await db.flush()
        # Tenant-owned custom scale
        tenant_scale = AnswerScale(
            title=f"Tenant Scale {uuid.uuid4().hex[:6]}",
            is_default=False,
            tenant_id=tenant.id,
        )
        db.add(tenant_scale)
        await db.commit()

        scales = await service.list_scales(db, tenant.id)
        scale_ids = [s.id for s in scales]
        assert origin_scale.id in scale_ids
        assert tenant_scale.id in scale_ids


class TestSetAssessmentScale:
    async def test_assigns_scale_when_none(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="No scale", employee_id=employee.id, type_code="self"
            ),
        )
        assert created["scale_id"] is None

        scale = AnswerScale(
            title=f"Pickable {uuid.uuid4().hex[:6]}",
            is_default=False,
            tenant_id=tenant.id,
        )
        db.add(scale)
        await db.commit()
        await db.refresh(scale)

        result = await service.set_assessment_scale(
            db, tenant.id, created["id"], scale.id
        )
        assert result["scale_id"] == scale.id

    async def test_clears_scale_with_none(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = AnswerScale(
            title=f"Clearable {uuid.uuid4().hex[:6]}",
            is_default=False,
            tenant_id=tenant.id,
        )
        db.add(scale)
        await db.commit()
        await db.refresh(scale)

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Scaled",
                employee_id=employee.id,
                type_code="self",
                scale_id=scale.id,
            ),
        )
        assert created["scale_id"] == scale.id

        result = await service.set_assessment_scale(db, tenant.id, created["id"], None)
        assert result["scale_id"] is None

    async def test_rejects_scale_from_other_tenant(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherT", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        foreign = AnswerScale(
            title=f"Foreign {uuid.uuid4().hex[:6]}",
            is_default=False,
            tenant_id=other.id,
        )
        db.add(foreign)
        await db.commit()
        await db.refresh(foreign)

        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="No scale", employee_id=employee.id, type_code="self"
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await service.set_assessment_scale(db, tenant.id, created["id"], foreign.id)
        assert exc.value.status_code == 404

    async def test_rejects_change_on_terminal(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Done", employee_id=employee.id, type_code="self"),
        )
        await seed_send_prereqs(db, tenant.id, created["id"])

        await service.change_status(db, tenant.id, created["id"], "sent")
        await advance_to_in_progress(db, tenant.id, created["id"])
        await advance_to_done(db, tenant.id, created["id"])

        scale = AnswerScale(
            title=f"Late {uuid.uuid4().hex[:6]}",
            is_default=False,
            tenant_id=tenant.id,
        )
        db.add(scale)
        await db.commit()
        await db.refresh(scale)

        with pytest.raises(HTTPException) as exc:
            await service.set_assessment_scale(db, tenant.id, created["id"], scale.id)
        assert exc.value.status_code == 400


# --- CPA ---


class TestCPA:
    async def test_create_cpa(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        data = CPACreate(title="Q1 Campaign", type_code="360")
        result = await service.create_cpa(db, tenant.id, user.id, data)
        assert result["title"] == "Q1 Campaign"
        assert result["author_id"] == user.id
        assert result["status"] == "draft"
        assert result["tenant_id"] == tenant.id

    async def test_create_cpa_with_scale(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        scale = AnswerScale(title="Test Scale", is_default=False, tenant_id=tenant.id)
        db.add(scale)
        await db.commit()
        await db.refresh(scale)

        data = CPACreate(title="With Scale", type_code="self", scale_id=scale.id)
        result = await service.create_cpa(db, tenant.id, user.id, data)
        assert result["scale_id"] == scale.id

    async def test_list_cpas_empty(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        from app.modules.company.models import Tenant

        # Use a fresh tenant to ensure empty list
        fresh = Tenant(name="FreshCPA", slug=f"fcpa-{uuid.uuid4().hex[:6]}")
        db.add(fresh)
        await db.commit()
        await db.refresh(fresh)

        cpas = await service.list_cpas(db, fresh.id)
        assert cpas == []

    async def test_list_cpas_returns_created(
        self, db: AsyncSession, tenant, user, assessment_statuses, assessment_types
    ):
        data = CPACreate(title=f"List CPA {uuid.uuid4().hex[:6]}", type_code="180")
        await service.create_cpa(db, tenant.id, user.id, data)

        cpas = await service.list_cpas(db, tenant.id)
        assert len(cpas) >= 1
        titles = [c["title"] for c in cpas]
        assert data.title in titles


# --- Mass Assessment (Groups) ---


async def _make_employee(db: AsyncSession, tenant, suffix: str) -> Employee:
    """Create a User + Employee pair for mass assessment tests."""
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User as AuthUser

    u = AuthUser(
        email=f"mass-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass"),
        first_name=f"First{suffix}",
        last_name=f"Last{suffix}",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)

    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_title="Engineer",
        hire_date=date(2024, 1, 1),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestMassAssessment:
    async def test_create_mass_assessment(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_employee(db, tenant, "m1")
        emp3 = await _make_employee(db, tenant, "m2")

        data = MassAssessmentCreate(
            title="Q2 Mass Review",
            employee_ids=[employee.id, emp2.id, emp3.id],
            type_code="360",
        )
        result = await service.create_mass_assessment(db, tenant.id, user.id, data)
        assert result["title"] == "Q2 Mass Review"
        assert result["assessment_count"] == 3
        assert len(result["assessments"]) == 3
        assert all(a["group_id"] == result["id"] for a in result["assessments"])
        assert all(a["status_code"] == "draft" for a in result["assessments"])

    async def test_create_mass_assessment_deduplicates(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        data = MassAssessmentCreate(
            title="Dedup",
            employee_ids=[employee.id, employee.id, employee.id],
            type_code="self",
        )
        result = await service.create_mass_assessment(db, tenant.id, user.id, data)
        assert result["assessment_count"] == 1

    async def test_create_mass_assessment_invalid_employee(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
    ):
        data = MassAssessmentCreate(
            title="Bad emp",
            employee_ids=[uuid.uuid4()],
            type_code="self",
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_mass_assessment(db, tenant.id, user.id, data)
        assert exc.value.status_code == 400

    async def test_list_assessments_grouped(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        # Create a standalone assessment
        await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Standalone", employee_id=employee.id, type_code="self"
            ),
        )

        # Create a mass assessment
        emp2 = await _make_employee(db, tenant, "g1")
        await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Group",
                employee_ids=[employee.id, emp2.id],
                type_code="360",
            ),
        )

        items, total = await service.list_assessments_grouped(db, tenant.id)
        assert total >= 2
        kinds = [item["kind"] for item in items]
        assert "single" in kinds
        assert "group" in kinds

    async def test_get_assessment_group(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_employee(db, tenant, "d1")
        result = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Detail Group",
                employee_ids=[employee.id, emp2.id],
                type_code="180",
            ),
        )

        detail = await service.get_assessment_group(db, tenant.id, result["id"])
        assert detail["title"] == "Detail Group"
        assert detail["assessment_count"] == 2
        assert len(detail["assessments"]) == 2

    async def test_get_assessment_group_not_found(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        with pytest.raises(HTTPException) as exc:
            await service.get_assessment_group(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_bulk_change_status(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_employee(db, tenant, "b1")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Bulk Status",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        for a in group["assessments"]:
            await seed_send_prereqs(db, tenant.id, a["id"])
        result = await service.bulk_change_status(db, tenant.id, group["id"], "sent")
        assert result["changed"] == 2
        assert result["skipped"] == 0

    async def test_bulk_change_status_skips_invalid(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_employee(db, tenant, "s1")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Skip Status",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        # Move first assessment forward; seed both so bulk transition can succeed for the other.
        for a in group["assessments"]:
            await seed_send_prereqs(db, tenant.id, a["id"])
        first_id = group["assessments"][0]["id"]

        await service.change_status(db, tenant.id, first_id, "sent")

        # Now try to bulk move to "sent" — first should be skipped
        result = await service.bulk_change_status(db, tenant.id, group["id"], "sent")
        assert result["changed"] == 1
        assert result["skipped"] == 1

    async def test_bulk_cancel_skips_done_assessments(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """HRP-26: bulk cancel must leave terminal "done" children alone.

        QA flagged that pre-fix behavior flipped already-completed
        assessments to cancelled, which silently rewrote finalized
        results. Terminal statuses are immutable in bulk transitions
        too — only assessments still in flight are cancelled.
        """
        emp2 = await _make_employee(db, tenant, "bc1")
        emp3 = await _make_employee(db, tenant, "bc2")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Cancel-all",
                employee_ids=[employee.id, emp2.id, emp3.id],
                type_code="self",
            ),
        )

        # Move first to done (draft -> sent -> in_progress -> on_review -> done)
        first_id = group["assessments"][0]["id"]
        await seed_send_prereqs(db, tenant.id, first_id)
        await service.change_status(db, tenant.id, first_id, "sent")
        await advance_to_in_progress(db, tenant.id, first_id)
        await advance_to_done(db, tenant.id, first_id)

        # Bulk cancel — only the two non-terminal ones should flip.
        result = await service.bulk_change_status(
            db, tenant.id, group["id"], "cancelled"
        )
        assert result["changed"] == 2
        assert result["skipped"] == 1
        assert result["skipped_reasons"]["terminal"] == 1

        detail = await service.get_assessment_group(db, tenant.id, group["id"])
        statuses = {a["id"]: a["status_code"] for a in detail["assessments"]}
        assert statuses[first_id] == "done"
        for aid, code in statuses.items():
            if aid != first_id:
                assert code == "cancelled"

    async def test_bulk_cancel_skips_already_cancelled(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_employee(db, tenant, "bcc")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Already-cancelled",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )
        first_id = group["assessments"][0]["id"]
        await service.change_status(db, tenant.id, first_id, "cancelled")

        result = await service.bulk_change_status(
            db, tenant.id, group["id"], "cancelled"
        )
        assert result["changed"] == 1
        assert result["skipped"] == 1

    async def test_create_mass_assessment_cross_tenant_rejected(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.company.models import Tenant

        other_tenant = Tenant(name="OtherOrg", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)

        other_emp = await _make_employee(db, other_tenant, "cross")

        data = MassAssessmentCreate(
            title="Cross tenant",
            employee_ids=[other_emp.id],
            type_code="self",
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_mass_assessment(db, tenant.id, user.id, data)
        assert exc.value.status_code == 400


class TestGroupScale:
    async def _make_scale(self, db, tenant) -> AnswerScale:
        scale = AnswerScale(
            title=f"Scale {uuid.uuid4().hex[:6]}",
            is_default=False,
            tenant_id=tenant.id,
        )
        db.add(scale)
        await db.commit()
        await db.refresh(scale)
        return scale

    async def test_create_mass_assessment_persists_scale_on_group(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await self._make_scale(db, tenant)
        emp2 = await _make_employee(db, tenant, "gs1")

        result = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="With scale",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
                scale_id=scale.id,
            ),
        )
        assert result["scale_id"] == scale.id
        assert result["scale"] is not None
        assert all(a["scale_id"] == scale.id for a in result["assessments"])

    async def test_set_group_scale_propagates_to_draft_children(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_employee(db, tenant, "gs2")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="No scale",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )
        assert group["scale_id"] is None

        scale = await self._make_scale(db, tenant)
        result = await service.set_group_scale(db, tenant.id, group["id"], scale.id)
        assert result["scale_id"] == scale.id
        assert all(a["scale_id"] == scale.id for a in result["assessments"])

    async def test_set_group_scale_clears_with_none(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        scale = await self._make_scale(db, tenant)
        emp2 = await _make_employee(db, tenant, "gs3")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Clear scale",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
                scale_id=scale.id,
            ),
        )

        result = await service.set_group_scale(db, tenant.id, group["id"], None)
        assert result["scale_id"] is None
        assert all(a["scale_id"] is None for a in result["assessments"])

    async def test_set_group_scale_locked_when_child_left_draft(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        emp2 = await _make_employee(db, tenant, "gs4")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Locked",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )
        first_id = group["assessments"][0]["id"]
        await seed_send_prereqs(db, tenant.id, first_id)
        await service.change_status(db, tenant.id, first_id, "sent")

        scale = await self._make_scale(db, tenant)
        with pytest.raises(HTTPException) as exc:
            await service.set_group_scale(db, tenant.id, group["id"], scale.id)
        assert exc.value.status_code == 400

    async def test_set_group_scale_unknown_scale_404(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Unknown scale",
                employee_ids=[employee.id],
                type_code="self",
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await service.set_group_scale(db, tenant.id, group["id"], uuid.uuid4())
        assert exc.value.status_code == 404


# --- Criteria selection (PDF spec) ---


class TestCriteriaSelection:
    async def _make_competence(self, db, tenant, title="C1"):
        from app.modules.competence import service as comp_service
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title=f"G-{title}")
        )
        return await comp_service.create_competence(
            db, tenant.id, CompetenceCreate(title=title, group_id=group.id)
        )

    async def _make_skill_level(self, db, sort_index=0):
        from app.modules.competence.models import SkillLevel
        from sqlalchemy import select

        result = await db.execute(
            select(SkillLevel).where(SkillLevel.sort_index == sort_index).limit(1)
        )
        sl = result.scalar_one_or_none()
        if sl:
            return sl
        sl = SkillLevel(title=f"L{sort_index}", sort_index=sort_index)
        db.add(sl)
        await db.commit()
        await db.refresh(sl)
        return sl

    async def _make_dictionary_item(self, db, tenant, type_, title):
        from app.modules.dictionary.models import DictionaryItem

        item = DictionaryItem(
            tenant_id=tenant.id, type=type_, title=title, is_active=True
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    async def _wire_grade_link(self, db, tenant, spec, grade, comp, level):
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        gs = GradeSpecialization(
            tenant_id=tenant.id, grade_id=grade.id, specialization_id=spec.id
        )
        db.add(gs)
        await db.flush()
        link = GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=level.id,
        )
        db.add(link)
        await db.commit()
        return gs

    async def test_set_criteria_competences(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.schemas import (
            CompetenceCriteriaItem,
            CriteriaUpdate,
        )

        comp = await self._make_competence(db, tenant, "Crit1")
        level = await self._make_skill_level(db, sort_index=1)
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="competences",
                competences=[
                    CompetenceCriteriaItem(
                        competence_id=comp.id, skill_level_id=level.id
                    )
                ],
            ),
        )
        assert result["criteria_type"] == "competences"
        assert any(
            c["competence_id"] == comp.id and c["skill_level_id"] == level.id
            for c in result["competences"]
        )

    async def test_set_criteria_competences_requires_items(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.schemas import CriteriaUpdate

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        with pytest.raises(HTTPException) as exc:
            await service.set_assessment_criteria(
                db,
                tenant.id,
                created["id"],
                CriteriaUpdate(criteria_type="competences", competences=[]),
            )
        assert exc.value.status_code == 400

    async def test_set_criteria_target_position_resolves_competences(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.schemas import CriteriaUpdate

        spec = await self._make_dictionary_item(db, tenant, "specialization", "QA")
        grade = await self._make_dictionary_item(db, tenant, "grade", "Junior")
        comp = await self._make_competence(db, tenant, "TargetC")
        level = await self._make_skill_level(db, sort_index=2)
        await self._wire_grade_link(db, tenant, spec, grade, comp, level)

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="target_position",
                specialization_id=spec.id,
                grade_id=grade.id,
            ),
        )
        assert result["criteria_type"] == "target_position"
        assert result["specialization_id"] == spec.id
        assert result["grade_id"] == grade.id
        assert result["specialization_title"] == "QA"
        assert result["grade_title"] == "Junior"
        assert any(c["competence_id"] == comp.id for c in result["competences"])

    async def test_set_criteria_target_position_all_grades(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.schemas import CriteriaUpdate

        spec = await self._make_dictionary_item(db, tenant, "specialization", "Dev")
        grade_jr = await self._make_dictionary_item(db, tenant, "grade", "Junior2")
        grade_sr = await self._make_dictionary_item(db, tenant, "grade", "Senior2")
        comp = await self._make_competence(db, tenant, "AllGradesC")
        level_low = await self._make_skill_level(db, sort_index=1)
        level_high = await self._make_skill_level(db, sort_index=3)
        await self._wire_grade_link(db, tenant, spec, grade_jr, comp, level_low)
        await self._wire_grade_link(db, tenant, spec, grade_sr, comp, level_high)

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        result = await service.set_assessment_criteria(
            db,
            tenant.id,
            created["id"],
            CriteriaUpdate(
                criteria_type="target_position",
                specialization_id=spec.id,
                grade_id=None,
            ),
        )
        # All grades: pick highest level per competence
        assert any(
            c["competence_id"] == comp.id and c["skill_level_id"] == level_high.id
            for c in result["competences"]
        )

    async def test_set_criteria_target_position_requires_competences(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.schemas import CriteriaUpdate

        spec = await self._make_dictionary_item(db, tenant, "specialization", "Empty")
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        with pytest.raises(HTTPException) as exc:
            await service.set_assessment_criteria(
                db,
                tenant.id,
                created["id"],
                CriteriaUpdate(
                    criteria_type="target_position", specialization_id=spec.id
                ),
            )
        assert exc.value.status_code == 400

    async def test_specializations_filter_only_with_competences(
        self,
        db: AsyncSession,
        tenant,
    ):
        spec_full = await self._make_dictionary_item(
            db, tenant, "specialization", "WithComp"
        )
        await self._make_dictionary_item(db, tenant, "specialization", "Empty2")
        grade = await self._make_dictionary_item(db, tenant, "grade", "G2")
        comp = await self._make_competence(db, tenant, "FilterC")
        level = await self._make_skill_level(db, sort_index=1)
        await self._wire_grade_link(db, tenant, spec_full, grade, comp, level)

        items = await service.list_criteria_specializations(db, tenant.id)
        ids = {item["id"] for item in items}
        assert spec_full.id in ids

    async def test_criteria_specializations_include_id_keeps_deactivated(
        self, db: AsyncSession, tenant
    ):
        # HRP-292: a deactivated specialization is dropped from the picker,
        # unless it is the assessment's already-saved value (include_id).
        spec = await self._make_dictionary_item(
            db, tenant, "specialization", "HRP292 Spec Off"
        )
        spec.is_active = False
        await db.commit()

        items = await service.list_criteria_specializations(db, tenant.id)
        assert spec.id not in {i["id"] for i in items}

        items = await service.list_criteria_specializations(
            db, tenant.id, include_id=spec.id
        )
        assert spec.id in {i["id"] for i in items}

    async def test_criteria_grades_hide_inactive_keep_included(
        self, db: AsyncSession, tenant
    ):
        # HRP-292: grades deactivated in Dictionaries → Grades disappear
        # from the criteria grade dropdown; the saved grade survives via
        # include_id, other inactive grades don't leak.
        spec = await self._make_dictionary_item(
            db, tenant, "specialization", "HRP292 Spec"
        )
        grade_on = await self._make_dictionary_item(db, tenant, "grade", "HRP292 On")
        grade_off = await self._make_dictionary_item(db, tenant, "grade", "HRP292 Off")
        comp = await self._make_competence(db, tenant, "HRP292 C")
        level = await self._make_skill_level(db, sort_index=1)
        await self._wire_grade_link(db, tenant, spec, grade_on, comp, level)
        await self._wire_grade_link(db, tenant, spec, grade_off, comp, level)
        grade_off.is_active = False
        await db.commit()

        items = await service.list_criteria_grades(db, tenant.id, spec.id)
        ids = {i["id"] for i in items}
        assert grade_on.id in ids
        assert grade_off.id not in ids

        items = await service.list_criteria_grades(
            db, tenant.id, spec.id, include_id=grade_off.id
        )
        ids = {i["id"] for i in items}
        assert grade_on.id in ids
        assert grade_off.id in ids

    async def test_criteria_grades_respect_tenant_override_on_origin(
        self, db: AsyncSession, tenant
    ):
        # HRP-292 + HRP-285: an origin (System) grade deactivated for THIS
        # tenant via dictionary_item_tenant_overrides disappears from the
        # dropdown, comes back with include_id, and other tenants are
        # unaffected.
        from app.modules.company.models import Tenant
        from app.modules.dictionary import service as dictionary_service
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.dictionary.schemas import DictionaryItemUpdate

        other = Tenant(name="Other HRP292", slug="other-hrp292")
        db.add(other)
        origin_grade = DictionaryItem(
            tenant_id=None, type="grade", title="HRP292 Origin G", is_active=True
        )
        db.add(origin_grade)
        await db.commit()
        await db.refresh(other)
        await db.refresh(origin_grade)

        spec = await self._make_dictionary_item(
            db, tenant, "specialization", "HRP292 OvSpec"
        )
        comp = await self._make_competence(db, tenant, "HRP292 OvC")
        level = await self._make_skill_level(db, sort_index=1)
        await self._wire_grade_link(db, tenant, spec, origin_grade, comp, level)
        # Same ladder for the other tenant, own chain rows.
        other_spec = DictionaryItem(
            tenant_id=other.id, type="specialization", title="HRP292 OvSpec B"
        )
        db.add(other_spec)
        await db.commit()
        await db.refresh(other_spec)
        await self._wire_grade_link(db, other, other_spec, origin_grade, comp, level)

        await dictionary_service.update_item(
            db, tenant.id, origin_grade.id, DictionaryItemUpdate(is_active=False)
        )

        ids = {
            i["id"] for i in await service.list_criteria_grades(db, tenant.id, spec.id)
        }
        assert origin_grade.id not in ids

        ids = {
            i["id"]
            for i in await service.list_criteria_grades(
                db, tenant.id, spec.id, include_id=origin_grade.id
            )
        }
        assert origin_grade.id in ids

        # The other tenant never deactivated it — visible without include_id.
        ids = {
            i["id"]
            for i in await service.list_criteria_grades(db, other.id, other_spec.id)
        }
        assert origin_grade.id in ids

    async def test_criteria_include_id_cannot_leak_foreign_items(
        self, db: AsyncSession, tenant
    ):
        # HRP-292: include_id is caller-controlled — a foreign tenant's
        # custom item must not surface through either endpoint.
        from app.modules.company.models import Tenant
        from app.modules.dictionary.models import DictionaryItem

        other = Tenant(name="Leak HRP292", slug="leak-hrp292")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        foreign_spec = DictionaryItem(
            tenant_id=other.id, type="specialization", title="Foreign Spec"
        )
        foreign_grade = DictionaryItem(
            tenant_id=other.id, type="grade", title="Foreign Grade"
        )
        db.add_all([foreign_spec, foreign_grade])
        await db.commit()
        await db.refresh(foreign_spec)
        await db.refresh(foreign_grade)

        spec = await self._make_dictionary_item(
            db, tenant, "specialization", "HRP292 LeakSpec"
        )

        items = await service.list_criteria_specializations(
            db, tenant.id, include_id=foreign_spec.id
        )
        assert foreign_spec.id not in {i["id"] for i in items}

        items = await service.list_criteria_grades(
            db, tenant.id, spec.id, include_id=foreign_grade.id
        )
        assert foreign_grade.id not in {i["id"] for i in items}

    async def test_set_group_criteria_propagates(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.schemas import (
            CompetenceCriteriaItem,
            CriteriaUpdate,
        )

        comp = await self._make_competence(db, tenant, "GroupC")
        mass = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="MassCriteria",
                employee_ids=[employee.id],
                type_code="self",
            ),
        )
        result = await service.set_group_criteria(
            db,
            tenant.id,
            mass["id"],
            CriteriaUpdate(
                criteria_type="competences",
                competences=[CompetenceCriteriaItem(competence_id=comp.id)],
            ),
        )
        assert result["criteria_type"] == "competences"
        for a in result["assessments"]:
            detail = await service.get_assessment_detail(db, tenant.id, a["id"])
            assert detail["criteria_type"] == "competences"
            assert any(c["competence_id"] == comp.id for c in detail["competences"])


class TestParticipantCompletionSkillLevelCascade:
    """HRP-75: is_completed must mirror the HRP-43 cascade.

    Older logic counted every indicator on the competence regardless of
    AssessmentCompetence.skill_level_id, so any competence with higher-
    level indicators left the participant stuck on Completed=No even
    after they answered every question the questionnaire actually
    surfaced.
    """

    async def _seed_three_level_competence(self, db, tenant):
        """Make a competence with one indicator at each of Basic / Intermediate
        / Advanced (sort_index 0/1/2). Returns (competence, indicators_by_level).
        """
        from app.modules.competence import service as comp_service
        from app.modules.competence.models import Indicator, SkillLevel
        from app.modules.competence.schemas import (
            CompetenceCreate,
            CompetenceGroupCreate,
        )
        from sqlalchemy import select as _sel

        group = await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title=f"G-{uuid.uuid4().hex[:6]}")
        )
        comp = await comp_service.create_competence(
            db,
            tenant.id,
            CompetenceCreate(title=f"C-{uuid.uuid4().hex[:6]}", group_id=group.id),
        )

        levels_by_sort: dict[int, SkillLevel] = {}
        existing = (
            await db.execute(_sel(SkillLevel).order_by(SkillLevel.sort_index))
        ).scalars().all()
        for lvl in existing:
            levels_by_sort.setdefault(lvl.sort_index, lvl)
        for sort_index, title in [(0, "Basic"), (1, "Intermediate"), (2, "Advanced")]:
            if sort_index in levels_by_sort:
                continue
            lvl = SkillLevel(title=title, sort_index=sort_index, is_active=True)
            db.add(lvl)
            await db.commit()
            await db.refresh(lvl)
            levels_by_sort[sort_index] = lvl

        indicators: dict[int, Indicator] = {}
        for sort_index in (0, 1, 2):
            ind = Indicator(
                title=f"Ind-L{sort_index}",
                weight=1,
                sort_index=sort_index,
                skill_level_id=levels_by_sort[sort_index].id,
                competence_id=comp.id,
                tenant_id=tenant.id,
                is_active=True,
            )
            db.add(ind)
        await db.commit()
        result = await db.execute(
            _sel(Indicator).where(Indicator.competence_id == comp.id)
        )
        for ind in result.scalars().all():
            sort_idx = next(
                s for s, lvl in levels_by_sort.items() if lvl.id == ind.skill_level_id
            )
            indicators[sort_idx] = ind
        return comp, levels_by_sort, indicators

    async def test_intermediate_filter_completes_after_basic_plus_intermediate(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """When AssessmentCompetence.skill_level_id = Intermediate, answering
        Basic + Intermediate is enough — Advanced is never shown."""
        from app.modules.assessment.models import (
            AssessmentCompetence,
            AssessmentParticipant,
        )
        from sqlalchemy import select as _sel

        comp, levels, indicators = await self._seed_three_level_competence(db, tenant)

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        # Manual AssessmentCompetence with skill_level filter at Intermediate.
        db.add(
            AssessmentCompetence(
                assessment_id=created["id"],
                competence_id=comp.id,
                skill_level_id=levels[1].id,
            )
        )
        await db.commit()

        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")

        for sort_index in (0, 1):  # Basic, Intermediate — Advanced skipped.
            data = AnswerRecord(
                participant_id=self_part["id"],
                indicator_id=indicators[sort_index].id,
                score=4,
            )
            await service.record_answer(
                db, tenant.id, user.id, created["id"], data
            )

        participant = (
            await db.execute(
                _sel(AssessmentParticipant).where(
                    AssessmentParticipant.id == self_part["id"]
                )
            )
        ).scalar_one()
        assert participant.is_completed is True, (
            "HRP-75 regression: cascade-filtered assessment should complete after "
            "answering only the levels visible in the questionnaire"
        )

    async def test_no_filter_still_requires_every_indicator(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Legacy contract: when AssessmentCompetence.skill_level_id is NULL the
        participant must answer every active indicator (no cascade short-cut).
        """
        from app.modules.assessment.models import AssessmentParticipant
        from sqlalchemy import select as _sel

        comp, _levels, indicators = await self._seed_three_level_competence(db, tenant)

        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.add_competences(db, tenant.id, created["id"], [comp.id])
        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_part = next(p for p in detail["participants"] if p["role"] == "self")

        for sort_index in (0, 1):  # Skip Advanced.
            data = AnswerRecord(
                participant_id=self_part["id"],
                indicator_id=indicators[sort_index].id,
                score=4,
            )
            await service.record_answer(
                db, tenant.id, user.id, created["id"], data
            )

        participant = (
            await db.execute(
                _sel(AssessmentParticipant).where(
                    AssessmentParticipant.id == self_part["id"]
                )
            )
        ).scalar_one()
        assert participant.is_completed is False

        # Answering the last (Advanced) indicator flips it.
        await service.record_answer(
            db,
            tenant.id,
            user.id,
            created["id"],
            AnswerRecord(
                participant_id=self_part["id"],
                indicator_id=indicators[2].id,
                score=4,
            ),
        )
        await db.refresh(participant)
        assert participant.is_completed is True


class TestHRP333EmployeeSummary:
    async def test_assessment_read_carries_position_and_status(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        assert created["employee_position_title"] == employee.position_title
        assert created["employee_status"] == employee.status

    async def test_participants_carry_position_and_status(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        self_p = next(p for p in detail["participants"] if p["role"] == "self")
        assert self_p["position_title"] == employee.position_title
        assert self_p["employee_status"] == employee.status

    async def test_external_participant_summary_fields_are_none(
        self, db, tenant, user, employee, assessment_statuses, assessment_types
    ):
        created = await _make_assessment(
            db, tenant, user, employee, assessment_statuses, assessment_types
        )
        await service.create_external_reviewer(
            db,
            tenant.id,
            created["id"],
            "Outside Reviewer",
            "outside@example.com",
            "external",
        )
        detail = await service.get_assessment_detail(db, tenant.id, created["id"])
        ext = next(
            p for p in detail["participants"] if p["external_reviewer_id"] is not None
        )
        assert ext["position_title"] is None
        assert ext["employee_status"] is None
