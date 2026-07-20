"""HRP-286: delete error surfaces a single generic message for every
dictionary type, and the FK violation on Roles / Goals / Projects /
Competence Types no longer bubbles up as a bare 500.
"""

import pytest
from app.modules.dictionary import service
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.schemas import DictionaryItemCreate
from app.modules.position.models import Position
from fastapi import HTTPException
from sqlalchemy import select

GENERIC = "This item has connections with other object(s). It can't be deleted"


class TestHRP286GenericDeleteMessage:
    async def test_specialization_in_use_uses_generic_message(
        self, db, tenant
    ):
        spec = await service.create_item(
            db, tenant.id, "specialization", DictionaryItemCreate(title="GenSpec")
        )
        db.add(
            Position(
                tenant_id=tenant.id,
                title="Holder",
                source="manual",
                specialization_id=spec["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, spec["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["message"] == GENERIC

    async def test_grade_in_use_uses_generic_message(self, db, tenant):
        grade = await service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="GenGrade")
        )
        db.add(
            Position(
                tenant_id=tenant.id,
                title="Holder2",
                source="manual",
                grade_id=grade["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, grade["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["message"] == GENERIC

    async def test_competence_type_in_use_blocks_delete(self, db, tenant):
        # HRP-286 redo: the FK from competences is SET NULL, so without an
        # explicit usage gate the delete silently untypes the competences.
        from app.modules.competence.models import Competence, CompetenceGroup

        ctype = await service.create_item(
            db, tenant.id, "competence_type", DictionaryItemCreate(title="GenType")
        )
        group = CompetenceGroup(tenant_id=tenant.id, title="Holder Group")
        db.add(group)
        await db.flush()
        db.add(
            Competence(
                tenant_id=tenant.id,
                group_id=group.id,
                title="Holder Competence",
                competence_type_id=ctype["id"],
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_item(db, tenant.id, ctype["id"])
        assert exc.value.status_code == 409
        assert exc.value.detail["message"] == GENERIC
        assert exc.value.detail["counts"]["competences"] == 1

        # the competence keeps its type
        comp_type_ids = (
            await db.execute(
                select(Competence.competence_type_id).where(
                    Competence.tenant_id == tenant.id
                )
            )
        ).scalars().all()
        assert comp_type_ids == [ctype["id"]]

    async def test_unused_competence_type_still_deletable(self, db, tenant):
        ctype = await service.create_item(
            db, tenant.id, "competence_type", DictionaryItemCreate(title="LoneType")
        )
        await service.delete_item(db, tenant.id, ctype["id"])
        rows = (
            await db.execute(
                select(DictionaryItem).where(DictionaryItem.id == ctype["id"])
            )
        ).scalars().all()
        assert rows == []

    async def test_unrelated_custom_item_still_deletable(self, db, tenant):
        item = await service.create_item(
            db, tenant.id, "role", DictionaryItemCreate(title="DeletableRole")
        )
        await service.delete_item(db, tenant.id, item["id"])
        # gone
        rows = (
            await db.execute(
                select(DictionaryItem).where(DictionaryItem.id == item["id"])
            )
        ).scalars().all()
        assert rows == []
