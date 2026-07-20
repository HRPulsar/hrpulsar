"""Unit tests for R4b audit log."""

from __future__ import annotations

import uuid

from app.modules.recruitment import audit_service
from sqlalchemy.ext.asyncio import AsyncSession


class TestAuditLog:
    async def test_record_and_list(
        self, db: AsyncSession, tenant, user
    ) -> None:
        entry = await audit_service.record_event(
            db,
            tenant_id=tenant.id,
            user_id=user.id,
            action="vacancy.create",
            entity_type="vacancy",
            entity_id=uuid.uuid4(),
            payload_diff={"title": "PM"},
        )
        assert entry is not None
        assert entry.tenant_id == tenant.id

        items, total = await audit_service.list_events(db, tenant.id)
        assert total == 1
        assert items[0]["action"] == "vacancy.create"
        assert items[0]["user_email"] == user.email

    async def test_filters(self, db: AsyncSession, tenant, user) -> None:
        v_id = uuid.uuid4()
        c_id = uuid.uuid4()
        for action, etype, eid in (
            ("vacancy.create", "vacancy", v_id),
            ("candidate.create", "candidate", c_id),
            ("vacancy.update", "vacancy", v_id),
        ):
            await audit_service.record_event(
                db,
                tenant_id=tenant.id,
                user_id=user.id,
                action=action,
                entity_type=etype,
                entity_id=eid,
            )

        vac_items, vac_total = await audit_service.list_events(
            db, tenant.id, entity_type="vacancy"
        )
        assert vac_total == 2
        assert {i["action"] for i in vac_items} == {
            "vacancy.create",
            "vacancy.update",
        }

        single_items, single_total = await audit_service.list_events(
            db, tenant.id, action="candidate.create"
        )
        assert single_total == 1
        assert single_items[0]["entity_id"] == c_id

    async def test_cross_tenant(self, db: AsyncSession, tenant, user) -> None:
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        await audit_service.record_event(
            db,
            tenant_id=tenant.id,
            user_id=user.id,
            action="vacancy.create",
            entity_type="vacancy",
            entity_id=uuid.uuid4(),
        )

        items, total = await audit_service.list_events(db, other.id)
        assert total == 0
        assert items == []

    async def test_user_lookup_is_tenant_scoped(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """A user_id from another tenant must not leak email / name back.

        Regression for R4b.1 review B-1: ``list_events`` was joining
        ``users`` by id alone, so an audit row recorded with the wrong
        ``user_id`` (or a user that later moved tenants) would expose
        the cross-tenant identity in the response.
        """
        from app.modules.auth.models import User
        from app.modules.company.models import Tenant

        other_tenant = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)

        foreign_user = User(
            email=f"foreign-{uuid.uuid4().hex[:8]}@test.com",
            password_hash="x",
            first_name="Foreign",
            last_name="Person",
            tenant_id=other_tenant.id,
        )
        db.add(foreign_user)
        await db.commit()
        await db.refresh(foreign_user)

        await audit_service.record_event(
            db,
            tenant_id=tenant.id,
            user_id=foreign_user.id,
            action="vacancy.create",
            entity_type="vacancy",
            entity_id=uuid.uuid4(),
        )

        items, total = await audit_service.list_events(db, tenant.id)
        assert total == 1
        row = items[0]
        assert row["user_id"] == foreign_user.id
        # Critical: the foreign user's PII must not be resolved into the
        # response. user_email / user_name stay None.
        assert row["user_email"] is None
        assert row["user_name"] is None
