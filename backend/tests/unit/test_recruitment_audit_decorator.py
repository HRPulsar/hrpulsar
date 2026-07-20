"""Verify that the audit decorator (R4b.1) records a row after a real
service call. ``register_audit_hooks`` is invoked at app-import time, so
by the time these tests run, ``service.create_vacancy`` etc. are wrapped.
"""

from __future__ import annotations

import uuid

from app.modules.recruitment import audit_service, service
from app.modules.recruitment.audit_registry import register_audit_hooks
from app.modules.recruitment.schemas import VacancyCreate, VacancyUpdate
from sqlalchemy.ext.asyncio import AsyncSession


class TestAuditDecorator:
    async def test_wrappers_installed(self) -> None:
        # Sanity: register is idempotent and the function carries the marker.
        register_audit_hooks()
        assert getattr(service.create_vacancy, "_audit_action", None) == (
            "vacancy.create"
        )
        assert getattr(service.update_vacancy, "_audit_action", None) == (
            "vacancy.update"
        )

    async def test_create_vacancy_records_audit_row(
        self, db: AsyncSession, tenant, user
    ) -> None:
        result = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(title=f"Wrapped {uuid.uuid4().hex[:6]}"),
        )

        items, total = await audit_service.list_events(
            db, tenant.id, entity_type="vacancy"
        )
        assert total >= 1
        # newest first
        latest = items[0]
        assert latest["action"] == "vacancy.create"
        assert latest["entity_type"] == "vacancy"
        assert latest["entity_id"] == result["id"]
        assert latest["user_id"] == user.id

    async def test_update_vacancy_records_audit_row(
        self, db: AsyncSession, tenant, user
    ) -> None:
        v = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="To update")
        )
        await service.update_vacancy(
            db, tenant.id, v["id"], VacancyUpdate(title="Updated")
        )

        items, _ = await audit_service.list_events(
            db, tenant.id, entity_type="vacancy", entity_id=v["id"]
        )
        actions = {row["action"] for row in items}
        assert "vacancy.create" in actions
        assert "vacancy.update" in actions
