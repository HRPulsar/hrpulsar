"""HRP-180 — vacancy ↔ Position + spec/grade multi-select.

Covers:
- Create vacancy with ``position_id`` auto-fills the spec/grade
  multi-select from the Position's pair, plus pulls division from
  the Position when caller didn't supply one.
- Spec/grade IDs not in the Position's pool are rejected with 422.
- PATCH supports partial update of position_id / specialization_ids /
  grade_ids.
- Legacy single-value ``specialization_id`` / ``grade_id`` text-y FKs
  are preserved alongside the new junction rows.
- HRP-131 REDO: PATCH /vacancies with library_refs serialises nested
  UUIDs even when the existing library_refs is being cleared.
"""

import uuid

import pytest
from app.modules.recruitment import service
from app.modules.recruitment.models import Vacancy
from app.modules.recruitment.schemas import (
    SpecializationGradePair,
    VacancyCreate,
    VacancyLibraryRefs,
    VacancyUpdate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_position(db: AsyncSession, tenant_id, *, with_division=False):
    """Create a Position with a (specialization, grade) pair and return it.

    Optionally also creates a Division and links it so the vacancy can
    inherit it on create.
    """
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.position.models import Position

    spec = DictionaryItem(
        type="specialization", title=f"Spec {uuid.uuid4().hex[:6]}", tenant_id=tenant_id
    )
    grade = DictionaryItem(
        type="grade", title=f"Grade {uuid.uuid4().hex[:6]}", tenant_id=tenant_id
    )
    db.add_all([spec, grade])
    await db.flush()

    division_id = None
    if with_division:
        from app.modules.company.models import Division

        division = Division(
            name=f"Div {uuid.uuid4().hex[:6]}",
            tenant_id=tenant_id,
        )
        db.add(division)
        await db.flush()
        division_id = division.id

    pos = Position(
        tenant_id=tenant_id,
        title=f"Pos {uuid.uuid4().hex[:6]}",
        specialization_id=spec.id,
        grade_id=grade.id,
        division_id=division_id,
    )
    db.add(pos)
    await db.commit()
    return pos, spec, grade, division_id


def _vacancy_data(**overrides) -> VacancyCreate:
    defaults = {"title": f"V {uuid.uuid4().hex[:6]}"}
    defaults.update(overrides)
    return VacancyCreate(**defaults)


class TestCreateWithPosition:
    async def test_position_autofills_division_when_not_supplied(
        self, db: AsyncSession, tenant, user
    ):
        pos, spec, grade, div_id = await _make_position(
            db, tenant.id, with_division=True
        )
        result = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(position_id=pos.id),
        )
        assert result["position_id"] == pos.id
        assert result["division_id"] == div_id
        # HRP-180: spec/grade default to the Position pair when caller omits.
        assert [s["id"] for s in result["specializations"]] == [spec.id]
        assert [g["id"] for g in result["grades"]] == [grade.id]

    async def test_caller_supplied_division_wins_over_position(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.company.models import Division

        pos, _spec, _grade, _ = await _make_position(
            db, tenant.id, with_division=True
        )
        other = Division(name=f"Other {uuid.uuid4().hex[:6]}", tenant_id=tenant.id)
        db.add(other)
        await db.commit()

        result = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(position_id=pos.id, division_id=other.id),
        )
        assert result["division_id"] == other.id

    async def test_invalid_position_rejected(
        self, db: AsyncSession, tenant, user
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_vacancy(
                db,
                tenant.id,
                user.id,
                _vacancy_data(position_id=uuid.uuid4()),
            )
        assert exc.value.status_code == 422


class TestSpecGradeValidation:
    async def test_spec_not_in_position_pool_rejected(
        self, db: AsyncSession, tenant, user
    ):
        pos, _spec, grade, _ = await _make_position(db, tenant.id)
        with pytest.raises(HTTPException) as exc:
            await service.create_vacancy(
                db,
                tenant.id,
                user.id,
                _vacancy_data(
                    position_id=pos.id,
                    specialization_ids=[uuid.uuid4()],
                    grade_ids=[grade.id],
                ),
            )
        assert exc.value.status_code == 422

    async def test_grade_not_in_position_pool_rejected(
        self, db: AsyncSession, tenant, user
    ):
        pos, spec, _grade, _ = await _make_position(db, tenant.id)
        with pytest.raises(HTTPException) as exc:
            await service.create_vacancy(
                db,
                tenant.id,
                user.id,
                _vacancy_data(
                    position_id=pos.id,
                    specialization_ids=[spec.id],
                    grade_ids=[uuid.uuid4()],
                ),
            )
        assert exc.value.status_code == 422

    async def test_spec_grade_without_position_rejected(
        self, db: AsyncSession, tenant, user
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_vacancy(
                db,
                tenant.id,
                user.id,
                _vacancy_data(specialization_ids=[uuid.uuid4()]),
            )
        assert exc.value.status_code == 422


class TestPatchMultiSelect:
    async def test_patch_specializations_replaces_set(
        self, db: AsyncSession, tenant, user
    ):
        pos, spec, grade, _ = await _make_position(db, tenant.id)
        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(
                position_id=pos.id,
                specialization_ids=[spec.id],
                grade_ids=[grade.id],
            ),
        )
        row = await db.get(Vacancy, vacancy["id"])
        etag = service.vacancy_etag(row)

        # Clear the selection.
        updated = await service.update_vacancy(
            db,
            tenant.id,
            vacancy["id"],
            VacancyUpdate(specialization_ids=[], grade_ids=[]),
            if_match=etag,
        )
        assert updated["specializations"] == []
        assert updated["grades"] == []

    async def test_patch_invalid_spec_rejected(
        self, db: AsyncSession, tenant, user
    ):
        pos, _spec, _grade, _ = await _make_position(db, tenant.id)
        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(position_id=pos.id),
        )
        row = await db.get(Vacancy, vacancy["id"])
        etag = service.vacancy_etag(row)

        with pytest.raises(HTTPException) as exc:
            await service.update_vacancy(
                db,
                tenant.id,
                vacancy["id"],
                VacancyUpdate(specialization_ids=[uuid.uuid4()]),
                if_match=etag,
            )
        assert exc.value.status_code == 422

    async def test_patch_position_changes_pool(
        self, db: AsyncSession, tenant, user
    ):
        pos_a, _, _, _ = await _make_position(db, tenant.id)
        pos_b, spec_b, grade_b, _ = await _make_position(db, tenant.id)
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data(position_id=pos_a.id)
        )
        row = await db.get(Vacancy, vacancy["id"])
        etag = service.vacancy_etag(row)

        updated = await service.update_vacancy(
            db,
            tenant.id,
            vacancy["id"],
            VacancyUpdate(
                position_id=pos_b.id,
                specialization_ids=[spec_b.id],
                grade_ids=[grade_b.id],
            ),
            if_match=etag,
        )
        assert updated["position_id"] == pos_b.id
        assert [s["id"] for s in updated["specializations"]] == [spec_b.id]
        assert [g["id"] for g in updated["grades"]] == [grade_b.id]


class TestLegacyCompatibility:
    async def test_legacy_text_spec_grade_preserved(
        self, db: AsyncSession, tenant, user
    ):
        """Existing vacancies write to the single-value spec/grade FKs.
        The new junction tables coexist — neither side is mandatory."""
        from app.modules.dictionary.models import DictionaryItem

        legacy_spec = DictionaryItem(
            type="specialization", title="Legacy", tenant_id=tenant.id
        )
        db.add(legacy_spec)
        await db.commit()

        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(specialization_id=legacy_spec.id),
        )
        assert vacancy["specialization_id"] == legacy_spec.id
        assert vacancy["specializations"] == []
        assert vacancy["position_id"] is None


class TestLibraryRefsPatchUuidSafety:
    async def test_patch_clears_library_refs_without_error(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-131 REDO: PATCH must support clearing library_refs to null.

        The previous bug only handled the non-null branch — clearing
        crashed because the dict path was never taken yet asyncpg still
        saw a JSONB column with no conversion hook.
        """
        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(
                library_refs=VacancyLibraryRefs(
                    specialization_grade_pairs=[
                        SpecializationGradePair(
                            specialization_id=uuid.uuid4(),
                            grade_ids=[uuid.uuid4()],
                        )
                    ]
                )
            ),
        )
        row = await db.get(Vacancy, vacancy["id"])
        etag = service.vacancy_etag(row)

        await service.update_vacancy(
            db,
            tenant.id,
            vacancy["id"],
            VacancyUpdate(library_refs=None),
            if_match=etag,
        )
        row = await db.get(Vacancy, vacancy["id"])
        assert row.library_refs is None

    async def test_patch_library_refs_round_trip_uuids(
        self, db: AsyncSession, tenant, user
    ):
        """Smoke test: round-tripping a library_refs payload with nested
        UUIDs must not fail in asyncpg's json serialiser."""
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data()
        )
        row = await db.get(Vacancy, vacancy["id"])
        etag = service.vacancy_etag(row)

        spec_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        await service.update_vacancy(
            db,
            tenant.id,
            vacancy["id"],
            VacancyUpdate(
                library_refs=VacancyLibraryRefs(
                    position_ids=[uuid.uuid4()],
                    specialization_grade_pairs=[
                        SpecializationGradePair(
                            specialization_id=spec_id, grade_ids=[grade_id]
                        )
                    ],
                )
            ),
            if_match=etag,
        )
        row = await db.get(Vacancy, vacancy["id"])
        assert str(spec_id) in str(row.library_refs)
        assert str(grade_id) in str(row.library_refs)


class TestPositionReadExposesPool:
    async def test_position_read_lists_spec_grade(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.position import service as position_service

        pos, spec, grade, _ = await _make_position(db, tenant.id)
        read = await position_service.get_position(db, tenant.id, pos.id)
        assert [s["id"] for s in read["specializations"]] == [spec.id]
        assert [g["id"] for g in read["grades"]] == [grade.id]


class TestVacancyReadShape:
    async def test_get_vacancy_returns_position_title(
        self, db: AsyncSession, tenant, user
    ):
        pos, _spec, _grade, _ = await _make_position(db, tenant.id)
        created = await service.create_vacancy(
            db, tenant.id, user.id, _vacancy_data(position_id=pos.id)
        )
        fetched = await service.get_vacancy(db, tenant.id, created["id"])
        assert fetched["position_id"] == pos.id
        assert fetched["position_title"] == pos.title

    async def test_junction_row_count_matches_response(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.models import (
            vacancy_grades_table,
            vacancy_specializations_table,
        )

        pos, spec, grade, _ = await _make_position(db, tenant.id)
        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            _vacancy_data(
                position_id=pos.id,
                specialization_ids=[spec.id],
                grade_ids=[grade.id],
            ),
        )
        specs = (
            await db.execute(
                select(vacancy_specializations_table.c.specialization_id).where(
                    vacancy_specializations_table.c.vacancy_id == vacancy["id"]
                )
            )
        ).scalars().all()
        grades = (
            await db.execute(
                select(vacancy_grades_table.c.grade_id).where(
                    vacancy_grades_table.c.vacancy_id == vacancy["id"]
                )
            )
        ).scalars().all()
        assert specs == [spec.id]
        assert grades == [grade.id]
