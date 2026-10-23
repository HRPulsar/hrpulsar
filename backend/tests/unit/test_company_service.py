import uuid

import pytest
from app.modules.company import service
from app.modules.company.schemas import DivisionCreate, DivisionUpdate, TenantUpdate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestTenant:
    async def test_get_tenant(self, db: AsyncSession, tenant):
        result = await service.get_tenant(db, tenant.id)
        assert result.name == tenant.name

    async def test_get_tenant_not_found(self, db: AsyncSession):
        with pytest.raises(Exception) as exc:
            await service.get_tenant(db, uuid.uuid4())
        assert "404" in str(exc.value.status_code)

    async def test_update_tenant(self, db: AsyncSession, tenant):
        data = TenantUpdate(name="Updated Corp")
        result = await service.update_tenant(db, tenant.id, data)
        assert result.name == "Updated Corp"


class TestDivisions:
    async def test_create_division(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="Engineering", description="Engineering dept")
        div = await service.create_division(db, tenant.id, data)
        assert div["name"] == "Engineering"
        assert div["tenant_id"] == tenant.id

    async def test_create_child_division(self, db: AsyncSession, tenant):
        parent_data = DivisionCreate(name="Engineering")
        parent = await service.create_division(db, tenant.id, parent_data)

        child_data = DivisionCreate(name="Backend", parent_id=parent["id"])
        child = await service.create_division(db, tenant.id, child_data)
        assert child["parent_id"] == parent["id"]

    async def test_get_division(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="HR")
        div = await service.create_division(db, tenant.id, data)
        result = await service.get_division(db, tenant.id, div["id"])
        assert result["name"] == "HR"

    async def test_get_division_wrong_tenant(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="Secret")
        div = await service.create_division(db, tenant.id, data)

        with pytest.raises(Exception) as exc:
            await service.get_division(db, uuid.uuid4(), div["id"])
        assert "404" in str(exc.value.status_code)

    async def test_get_division_tree(self, db: AsyncSession, tenant):
        parent = await service.create_division(
            db, tenant.id, DivisionCreate(name="Root")
        )
        await service.create_division(
            db, tenant.id, DivisionCreate(name="Child", parent_id=parent["id"])
        )

        tree = await service.get_division_tree(db, tenant.id)
        assert len(tree) >= 1
        root = next((t for t in tree if t.name == "Root"), None)
        assert root is not None
        assert len(root.children) == 1
        assert root.children[0].name == "Child"

    async def test_tree_counts_the_people_of_each_branch_in_one_query(
        self, db: AsyncSession, tenant
    ):
        # HRP-942: a node counts its own staff plus everything under it -
        # active and on leave, not people who left - and the whole tree costs
        # one count query, not one per node.
        from datetime import UTC, date, datetime

        from app.core.security import hash_password
        from app.modules.auth.models import User
        from app.modules.employee.models import Employee
        from sqlalchemy import event

        root = await service.create_division(db, tenant.id, DivisionCreate(name="R"))
        child = await service.create_division(
            db, tenant.id, DivisionCreate(name="C", parent_id=root["id"])
        )
        leaf = await service.create_division(
            db, tenant.id, DivisionCreate(name="L", parent_id=child["id"])
        )
        await service.create_division(db, tenant.id, DivisionCreate(name="Empty"))
        for division_id, status in [
            (root["id"], "active"),
            (child["id"], "active"),
            (child["id"], "terminated"),
            (child["id"], "inactive"),
            (leaf["id"], "on_leave"),
            (None, "active"),
        ]:
            u = User(
                email=f"e-{uuid.uuid4().hex[:8]}@test.com",
                password_hash=hash_password("testpass123"),
                first_name="Some",
                last_name="One",
                tenant_id=tenant.id,
                email_verified_at=datetime.now(UTC),
            )
            db.add(u)
            await db.flush()
            db.add(
                Employee(
                    user_id=u.id,
                    tenant_id=tenant.id,
                    division_id=division_id,
                    status=status,
                    hire_date=date(2024, 1, 1),
                )
            )
        await db.commit()

        statements: list[str] = []
        engine = db.bind.sync_engine

        def record(_conn, _cursor, statement, *_args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            tree = await service.get_division_tree(db, tenant.id)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        by_name = {n.name: n for n in tree}
        r = by_name["R"]
        assert (r.employee_count, r.children[0].employee_count) == (3, 2)
        assert r.children[0].children[0].employee_count == 1
        assert by_name["Empty"].employee_count == 0
        counts = [s for s in statements if "count(employees.id)" in s]
        assert len(counts) == 1

    async def test_a_division_never_moves_under_its_own_subtree(
        self, db: AsyncSession, tenant
    ):
        # Review 01.10: only parent == self was refused; a move under a
        # descendant made a cycle with no root, and get_division_tree then
        # dropped the whole subtree for everyone.
        root = await service.create_division(db, tenant.id, DivisionCreate(name="A"))
        child = await service.create_division(
            db, tenant.id, DivisionCreate(name="B", parent_id=root["id"])
        )
        grandchild = await service.create_division(
            db, tenant.id, DivisionCreate(name="C", parent_id=child["id"])
        )
        for target in (child, grandchild):
            with pytest.raises(HTTPException) as exc:
                await service.update_division(
                    db, tenant.id, root["id"], DivisionUpdate(parent_id=target["id"])
                )
            assert exc.value.status_code == 400

    async def test_update_division(self, db: AsyncSession, tenant):
        div = await service.create_division(db, tenant.id, DivisionCreate(name="Old"))
        result = await service.update_division(
            db, tenant.id, div["id"], DivisionUpdate(name="New")
        )
        assert result["name"] == "New"

    async def test_delete_division(self, db: AsyncSession, tenant):
        div = await service.create_division(
            db, tenant.id, DivisionCreate(name="ToDelete")
        )
        await service.delete_division(db, tenant.id, div["id"])

        with pytest.raises(HTTPException):
            await service.get_division(db, tenant.id, div["id"])
