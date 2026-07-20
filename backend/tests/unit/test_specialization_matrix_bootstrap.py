"""HRP-57 P2 / HRP-33 / HRP-56 — matrix session bootstraps grades from the brief.

The matrix-session endpoint accepts a `grade_ids` field. Pairs are pre-created
via `specialization.service.add_grades` before `_ensure_specialization_accessible`
runs, so the AI flow no longer rejects empty specializations with
`insufficient_data` and `_apply_specialization_matrix` has rows to attach links
to. For Position-launched flows the position's own grade is auto-included so
the active role is guaranteed coverage.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.modules.competence.models import SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import GradeSpecialization
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture(autouse=True)
async def _skill_levels(db: AsyncSession):
    desired = [
        (0, "basic", "Basic"),
        (1, "intermediate", "Intermediate"),
        (2, "advanced", "Advanced"),
    ]
    existing = await db.execute(
        select(SkillLevel).where(SkillLevel.tenant_id.is_(None))
    )
    by_key = {lvl.i18n_key: lvl for lvl in existing.scalars().all()}
    inserted = False
    for sort, key, title in desired:
        if key in by_key:
            continue
        db.add(
            SkillLevel(
                tenant_id=None,
                i18n_key=key,
                title=title,
                sort_index=sort,
                is_active=True,
            )
        )
        inserted = True
    if inserted:
        await db.commit()


@pytest_asyncio.fixture
async def empty_spec(db: AsyncSession, tenant):
    spec = DictionaryItem(
        type="specialization",
        title="P2 Empty Spec",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(spec)
    await db.commit()
    await db.refresh(spec)
    return spec


@pytest_asyncio.fixture
async def two_grades(db: AsyncSession, tenant):
    grades = []
    for sort, title in [(10, "P2 Junior"), (20, "P2 Senior")]:
        g = DictionaryItem(
            type="grade",
            title=title,
            tenant_id=tenant.id,
            sort_index=sort,
            is_active=True,
        )
        db.add(g)
        grades.append(g)
    await db.commit()
    for g in grades:
        await db.refresh(g)
    return grades


@pytest.fixture
def mock_enqueue(monkeypatch):
    """Avoid hitting Redis from the test."""
    fake_result = MagicMock()
    fake_result.id = "fake-celery-id"

    def _fake_enqueue(*_args, **_kwargs):
        return fake_result

    monkeypatch.setattr(
        "app.modules.ai_competence_generation.router.enqueue_task",
        _fake_enqueue,
        raising=False,
    )
    # The router imports lazily; patch via the original module too just in case.
    monkeypatch.setattr(
        "app.core.task_enqueue.enqueue_task",
        _fake_enqueue,
    )
    return fake_result


class TestGradeIdsBootstrapsPairs:
    async def test_grade_ids_creates_pairs_and_session(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        empty_spec,
        two_grades,
        mock_enqueue,
    ) -> None:
        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={
                "target_id": str(empty_spec.id),
                "grade_ids": json.dumps([str(g.id) for g in two_grades]),
            },
        )
        assert resp.status_code == 201, resp.text

        # Pairs were created idempotently by the router before the session
        # row was persisted.
        pairs = (
            (
                await db.execute(
                    select(GradeSpecialization).where(
                        GradeSpecialization.tenant_id == tenant.id,
                        GradeSpecialization.specialization_id == empty_spec.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(pairs) == 2
        assert {p.grade_id for p in pairs} == {g.id for g in two_grades}

    async def test_empty_spec_without_grade_ids_still_rejects(
        self,
        auth_client,
        empty_spec,
        mock_enqueue,
    ) -> None:
        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={"target_id": str(empty_spec.id)},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error_code"] == "insufficient_data"

    async def test_grade_ids_idempotent_when_pair_exists(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        empty_spec,
        two_grades,
        mock_enqueue,
    ) -> None:
        # Seed one pair manually so the bootstrap path has to skip it.
        db.add(
            GradeSpecialization(
                tenant_id=tenant.id,
                grade_id=two_grades[0].id,
                specialization_id=empty_spec.id,
                sort_index=0,
            )
        )
        await db.commit()

        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={
                "target_id": str(empty_spec.id),
                "grade_ids": json.dumps([str(g.id) for g in two_grades]),
            },
        )
        assert resp.status_code == 201, resp.text

        pairs = (
            (
                await db.execute(
                    select(GradeSpecialization).where(
                        GradeSpecialization.tenant_id == tenant.id,
                        GradeSpecialization.specialization_id == empty_spec.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        # Same grade twice in input → unique constraint enforced by add_grades.
        assert len(pairs) == 2


class TestPositionFlowAutoIncludesGrade:
    async def test_position_grade_appended_when_not_in_payload(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        empty_spec,
        two_grades,
        mock_enqueue,
    ) -> None:
        position = Position(
            tenant_id=tenant.id,
            title="P2 Position",
            specialization_id=empty_spec.id,
            grade_id=two_grades[0].id,
            source="manual",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        # Empty grade_ids list → router falls back to position.grade_id.
        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={
                "position_id": str(position.id),
            },
        )
        assert resp.status_code == 201, resp.text

        pairs = (
            (
                await db.execute(
                    select(GradeSpecialization).where(
                        GradeSpecialization.tenant_id == tenant.id,
                        GradeSpecialization.specialization_id == empty_spec.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {p.grade_id for p in pairs} == {two_grades[0].id}


class TestHrp159PreflightContext:
    """HRP-159: matrix endpoint persists ``refinement_prompt`` and
    ``context_excludes`` on the session params for the worker to read."""

    async def test_persists_refinement_and_excludes(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        empty_spec,
        two_grades,
        mock_enqueue,
    ) -> None:
        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={
                "target_id": str(empty_spec.id),
                "grade_ids": json.dumps([str(g.id) for g in two_grades]),
                "refinement_prompt": "Bias towards security.",
                "context_excludes": json.dumps(
                    [
                        "positions",
                        f"competence:{empty_spec.id}",
                    ]
                ),
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        params = body["params"]
        assert params["refinement_prompt"] == "Bias towards security."
        assert "positions" in params["context_excludes"]
        assert f"competence:{empty_spec.id}" in params["context_excludes"]

    async def test_rejects_malformed_context_excludes(
        self,
        auth_client,
        empty_spec,
        two_grades,
        mock_enqueue,
    ) -> None:
        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={
                "target_id": str(empty_spec.id),
                "grade_ids": json.dumps([str(g.id) for g in two_grades]),
                "context_excludes": "not-a-json-array",
            },
        )
        assert resp.status_code == 422
        assert "context_excludes" in resp.text


class TestGradeIdsValidation:
    async def test_rejects_malformed_grade_ids_json(
        self,
        auth_client,
        empty_spec,
        mock_enqueue,
    ) -> None:
        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={
                "target_id": str(empty_spec.id),
                "grade_ids": "not-a-json-array",
            },
        )
        assert resp.status_code == 422
        assert "grade_ids" in resp.text

    async def test_rejects_non_grade_dictionary_item(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        empty_spec,
        mock_enqueue,
    ) -> None:
        # Random valid UUID that points to a specialization (wrong type).
        wrong_type = DictionaryItem(
            type="specialization",
            title="Not A Grade",
            tenant_id=tenant.id,
        )
        db.add(wrong_type)
        await db.commit()
        await db.refresh(wrong_type)

        resp = await auth_client.post(
            "/api/competence-generation/specialization-matrix-sessions",
            data={
                "target_id": str(empty_spec.id),
                "grade_ids": json.dumps([str(wrong_type.id)]),
            },
        )
        assert resp.status_code == 404
