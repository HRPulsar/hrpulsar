"""HRP-226: a mass exam may hold at most one Pass Mark.

Redo: the pass mark is editable (add / update / delete) on any active
exam; only terminal statuses (done / cancelled) freeze it.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.exam import service
from app.modules.exam.models import MassExam
from app.modules.exam.schemas import (
    MassExamCreate,
    PassMarkCreate,
    PassMarkUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _set_status(db: AsyncSession, mass_exam_id, status_code: str) -> None:
    me = await db.get(MassExam, mass_exam_id)
    assert me is not None
    me.status = status_code
    await db.commit()


class TestPassMarkUniqueness:
    async def test_second_add_rejected(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226")
        )
        await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=60)
        )
        with pytest.raises(HTTPException) as exc:
            await service.add_pass_mark(
                db, tenant.id, me["id"], PassMarkCreate(min_score_percent=70)
            )
        assert exc.value.status_code == 400


class TestPassMarkDelete:
    async def test_delete_clears_pass_mark(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 del")
        )
        pm = await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=60)
        )
        await service.delete_pass_mark(db, tenant.id, me["id"], pm["id"])

        detail = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert detail["pass_marks"] == []

        # And a fresh pass mark can be added again.
        await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=80)
        )

    async def test_delete_unknown_pass_mark_raises_404(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 missing")
        )
        with pytest.raises(HTTPException) as exc:
            await service.delete_pass_mark(db, tenant.id, me["id"], uuid.uuid4())
        assert exc.value.status_code == 404


class TestPassMarkUpdate:
    async def test_update_changes_values(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 upd")
        )
        pm = await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=60)
        )
        out = await service.update_pass_mark(
            db,
            tenant.id,
            me["id"],
            pm["id"],
            PassMarkUpdate(min_score_percent=75, min_score_points=12),
        )
        assert out["min_score_percent"] == 75
        assert out["min_score_points"] == 12

    async def test_update_unknown_pass_mark_raises_404(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 upd missing")
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_pass_mark(
                db, tenant.id, me["id"], uuid.uuid4(), PassMarkUpdate()
            )
        assert exc.value.status_code == 404


class TestPassMarkValidation:
    async def test_add_requires_a_threshold(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 no-threshold")
        )
        with pytest.raises(HTTPException) as exc:
            await service.add_pass_mark(db, tenant.id, me["id"], PassMarkCreate())
        assert exc.value.status_code == 400

    async def test_update_cannot_null_both_thresholds(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 null-out")
        )
        pm = await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=60)
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_pass_mark(
                db,
                tenant.id,
                me["id"],
                pm["id"],
                PassMarkUpdate(min_score_percent=None),
            )
        assert exc.value.status_code == 400

    def test_score_bounds_enforced_by_schema(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PassMarkCreate(min_score_percent=500)
        with pytest.raises(ValidationError):
            PassMarkUpdate(min_score_percent=-5)
        with pytest.raises(ValidationError):
            PassMarkCreate(min_score_points=-1)

    async def test_update_rejects_unknown_grade_ref(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 bogus-ref")
        )
        pm = await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=60)
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_pass_mark(
                db,
                tenant.id,
                me["id"],
                pm["id"],
                PassMarkUpdate(grade_id=uuid.uuid4()),
            )
        assert exc.value.status_code == 404


class TestPassMarkActiveExamGate:
    async def test_crud_allowed_on_sent_exam(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-226 sent")
        )
        await _set_status(db, me["id"], "sent")
        pm = await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=60)
        )
        await service.update_pass_mark(
            db, tenant.id, me["id"], pm["id"], PassMarkUpdate(min_score_percent=65)
        )
        await service.delete_pass_mark(db, tenant.id, me["id"], pm["id"])

    @pytest.mark.parametrize("terminal", ["done", "cancelled"])
    async def test_crud_blocked_on_terminal_exam(
        self, db: AsyncSession, tenant, user, terminal: str
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title=f"HRP-226 {terminal}")
        )
        pm = await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=60)
        )
        await _set_status(db, me["id"], terminal)
        with pytest.raises(HTTPException) as exc_add:
            await service.add_pass_mark(
                db, tenant.id, me["id"], PassMarkCreate(min_score_percent=70)
            )
        assert exc_add.value.status_code == 400
        with pytest.raises(HTTPException) as exc_upd:
            await service.update_pass_mark(
                db, tenant.id, me["id"], pm["id"], PassMarkUpdate(min_score_percent=70)
            )
        assert exc_upd.value.status_code == 400
        with pytest.raises(HTTPException) as exc_del:
            await service.delete_pass_mark(db, tenant.id, me["id"], pm["id"])
        assert exc_del.value.status_code == 400
