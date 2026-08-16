"""POS5 — Celery task + apply for `specialization_matrix` scope.

Covers two contracts:

1. **Tenant settings invariant.** Every `llm_client.generate_json(...)` call
   the new task makes receives a non-None `tenant_settings`. Tested by
   spying on the call's kwargs (after CR10c, calling without settings is a
   regression).
2. **Apply persists matrix into `GradeCompetenceLink`.** Picking only the
   selected nodes; grade-level pairs that don't resolve are skipped.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest_asyncio
from app.modules.ai import llm_client
from app.modules.ai_competence_generation import service, tasks
from app.modules.ai_competence_generation.schemas import (
    GeneratedMatrixSchema,
    SessionApply,
    SessionCreate,
)
from app.modules.competence.models import SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def skill_levels(db: AsyncSession):
    """Ensure Basic/Intermediate/Advanced exist as origin levels.

    `Base.metadata.create_all` skips data migrations, so the test DB has no
    skill_levels rows on first call. Subsequent calls within the same
    pytest session reuse rows seeded by earlier tests in the file: we
    fetch first, only insert what's missing. This keeps the fixture
    idempotent across test orderings — important because the shared `db`
    factory persists DDL between tests.
    """
    desired = [
        (0, "basic", "Basic"),
        (1, "intermediate", "Intermediate"),
        (2, "advanced", "Advanced"),
    ]
    existing = await db.execute(
        select(SkillLevel).where(SkillLevel.tenant_id.is_(None))
    )
    by_key = {lvl.i18n_key: lvl for lvl in existing.scalars().all()}

    levels: list[SkillLevel] = []
    inserted = False
    for sort, key, title in desired:
        if key in by_key:
            levels.append(by_key[key])
            continue
        lvl = SkillLevel(
            tenant_id=None,
            i18n_key=key,
            title=title,
            sort_index=sort,
            is_active=True,
        )
        db.add(lvl)
        levels.append(lvl)
        inserted = True
    if inserted:
        await db.commit()
        for lvl in levels:
            await db.refresh(lvl)
    return levels


@pytest_asyncio.fixture
async def specialization_with_grades(db: AsyncSession, tenant):
    spec = DictionaryItem(
        type="specialization",
        title="Backend Engineer",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(spec)
    await db.commit()
    await db.refresh(spec)

    grades = []
    for sort, title in [(10, "Junior"), (20, "Middle"), (30, "Senior")]:
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

    pairs = []
    for g in grades:
        await db.refresh(g)
        pair = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=g.id,
            specialization_id=spec.id,
            sort_index=g.sort_index,
        )
        db.add(pair)
        pairs.append(pair)
    await db.commit()
    for p in pairs:
        await db.refresh(p)

    return {"spec": spec, "grades": grades, "pairs": pairs}


_FAKE_MATRIX_PAYLOAD = {
    "groups": [
        {
            "title": "Engineering Excellence",
            "description": "Core craft skills.",
            "competences": [
                {
                    "title": "API design",
                    "description": "REST + async APIs.",
                    "type": "hard_skill",
                    "indicators": [
                        {"title": "Knows HTTP semantics", "skill_level": "Basic"},
                        {
                            "title": "Designs versioned endpoints",
                            "skill_level": "Intermediate",
                        },
                    ],
                    "grade_levels": {
                        "Junior": "Basic",
                        "Middle": "Intermediate",
                        "Senior": "Advanced",
                    },
                }
            ],
        }
    ]
}


class TestMatrixSessionLLMInvariants:
    async def test_llm_called_with_tenant_settings(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        spec = specialization_with_grades["spec"]
        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
        )

        captured: dict = {}

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
            **kwargs,
        ):
            captured["tenant_settings"] = tenant_settings
            captured["system"] = system
            return GeneratedMatrixSchema.model_validate(_FAKE_MATRIX_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "ready", result
        assert (
            captured["tenant_settings"] is not None
        ), "POS5 invariant violated: LLM was called without tenant_settings"
        assert getattr(captured["tenant_settings"], "tenant_id", None) == tenant.id


class TestApplyMatrix:
    async def test_apply_creates_grade_competence_links(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        spec = specialization_with_grades["spec"]
        pair_ids = {p.id for p in specialization_with_grades["pairs"]}

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
        )

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
            **kwargs,
        ):
            return GeneratedMatrixSchema.model_validate(_FAKE_MATRIX_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        await db.refresh(sess)
        assert sess.status == "ready"

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="apply-pos5-test-key",
            actor_id=user.id,
        )

        assert len(result["created_competences"]) == 1
        assert len(result["created_grade_links"]) == 3

        rows = await db.execute(
            select(GradeCompetenceLink).where(
                GradeCompetenceLink.grade_specialization_id.in_(pair_ids)
            )
        )
        links = list(rows.scalars().all())
        assert len(links) == 3
        levels_by_grade: dict[uuid.UUID, str] = {}
        for link in links:
            sl = await db.get(SkillLevel, link.skill_level_id)
            pair = await db.get(GradeSpecialization, link.grade_specialization_id)
            grade = await db.get(DictionaryItem, pair.grade_id)
            levels_by_grade[grade.title] = sl.title
        assert levels_by_grade == {
            "Junior": "Basic",
            "Middle": "Intermediate",
            "Senior": "Advanced",
        }

    async def test_apply_idempotent_on_repeat(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        spec = specialization_with_grades["spec"]
        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
        )

        async def fake_generate(*a, **kw):
            return GeneratedMatrixSchema.model_validate(_FAKE_MATRIX_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        await db.refresh(sess)
        body = SessionApply(publish=False, idempotency_key="repeat-key-xyz1")
        first = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=body.publish,
            idempotency_key=body.idempotency_key,
        )
        second = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=body.publish,
            idempotency_key=body.idempotency_key,
        )
        assert first == second
        assert len(first["created_grade_links"]) == 3


class TestApplyMatrixForPosition:
    """HRP-33: matrix sessions launched from a Position fold every selected
    competence under one group named after the position."""

    async def test_apply_collapses_groups_into_position_group(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.position.models import Position

        spec = specialization_with_grades["spec"]
        position = Position(
            tenant_id=tenant.id,
            title="Senior Backend Engineer · Platform",
            specialization_id=spec.id,
            grade_id=specialization_with_grades["grades"][2].id,
            source="manual",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        # Two LLM groups in the payload — apply should still produce ONE
        # CompetenceGroup whose title equals the position's title.
        payload = {
            "groups": [
                {
                    "title": "Engineering Excellence",
                    "description": "Core craft skills.",
                    "competences": [
                        {
                            "title": "API design",
                            "description": "REST + async APIs.",
                            "type": "hard_skill",
                            "indicators": [],
                            "grade_levels": {
                                "Junior": "Basic",
                                "Middle": "Intermediate",
                                "Senior": "Advanced",
                            },
                        }
                    ],
                },
                {
                    "title": "Communication",
                    "description": "Collaboration and writing.",
                    "competences": [
                        {
                            "title": "Tech writing",
                            "description": "Clear async writing.",
                            "type": "soft_skill",
                            "indicators": [],
                            "grade_levels": {
                                "Junior": "Basic",
                                "Middle": "Intermediate",
                                "Senior": "Advanced",
                            },
                        }
                    ],
                },
            ]
        }

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
            extra_params={
                "position_id": str(position.id),
                "position_title": position.title,
            },
        )

        async def fake_generate(*a, **kw):
            return GeneratedMatrixSchema.model_validate(payload)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        await db.refresh(sess)
        assert sess.status == "ready"

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="apply-hrp33-position-key",
            actor_id=user.id,
        )

        assert len(result["created_groups"]) == 1
        assert len(result["created_competences"]) == 2

        groups = await db.execute(
            select(CompetenceGroup).where(
                CompetenceGroup.id == uuid.UUID(result["created_groups"][0])
            )
        )
        group = groups.scalar_one()
        assert group.title == position.title

        comps = await db.execute(
            select(Competence).where(Competence.group_id == group.id)
        )
        comp_titles = sorted(c.title for c in comps.scalars().all())
        assert comp_titles == ["API design", "Tech writing"]

    async def test_reapply_reuses_existing_position_group(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        """Re-running AI on the same position must not stack duplicate groups."""
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.position.models import Position

        spec = specialization_with_grades["spec"]
        position = Position(
            tenant_id=tenant.id,
            title="Backend Engineer · Platform",
            specialization_id=spec.id,
            grade_id=specialization_with_grades["grades"][1].id,
            source="manual",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        async def fake_generate(*a, **kw):
            return GeneratedMatrixSchema.model_validate(_FAKE_MATRIX_PAYLOAD)

        for idem in ("apply-1", "apply-2"):
            sess = await service.create_session(
                db,
                tenant.id,
                user.id,
                SessionCreate(scope="specialization_matrix", target_id=spec.id),
                extra_params={
                    "position_id": str(position.id),
                    "position_title": position.title,
                },
            )
            with patch.object(llm_client, "generate_json", side_effect=fake_generate):
                await tasks.execute_session(session_factory, sess.id)
            # The Celery worker uses its own session_factory; the fixture's
            # `db` still has the stale `pending` snapshot. Expire so apply
            # observes the row's true `ready` status.
            await db.refresh(sess)
            await service.apply_session(
                db,
                sess.id,
                user_id=user.id,
                tenant_id=tenant.id,
                publish=True,
                idempotency_key=f"reuse-test-{idem}-key",
                actor_id=user.id,
            )

        groups = await db.execute(
            select(CompetenceGroup).where(
                CompetenceGroup.tenant_id == tenant.id,
                CompetenceGroup.title == position.title,
            )
        )
        group_rows = list(groups.scalars().all())
        assert len(group_rows) == 1, "second apply must reuse the position's group"

        comps = await db.execute(
            select(Competence).where(Competence.group_id == group_rows[0].id)
        )
        # Two applies of the same single-competence payload → two competence
        # rows under the shared group, never a sibling group with the same title.
        assert len(list(comps.scalars().all())) == 2


class TestApplyMatrixEmptyResult:
    """HRP-105: a matrix apply that ends up creating nothing must still
    leave the session in `applied` status with empty arrays in
    `applied_result` — that's the contract the frontend relies on to
    show an explicit "no new competences" warning instead of a misleading
    success toast.
    """

    async def test_apply_empty_payload_returns_empty_arrays(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        from app.modules.position.models import Position

        spec = specialization_with_grades["spec"]
        position = Position(
            tenant_id=tenant.id,
            title="Position For Empty Apply",
            specialization_id=spec.id,
            grade_id=specialization_with_grades["grades"][1].id,
            source="manual",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        # LLM legitimately decides every competence is covered by the
        # existing matrix and returns zero groups. Apply must accept it.
        async def fake_generate(*a, **kw):
            return GeneratedMatrixSchema.model_validate({"groups": []})

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
            extra_params={
                "position_id": str(position.id),
                "position_title": position.title,
            },
        )
        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        await db.refresh(sess)
        assert sess.status == "ready"

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="apply-hrp105-empty-key",
            actor_id=user.id,
        )

        assert result["created_groups"] == []
        assert result["created_competences"] == []
        assert result["created_indicators"] == []
        assert result["created_grade_links"] == []

        await db.refresh(sess)
        assert sess.status == "applied"
        assert sess.applied_result is not None
        # Idempotent re-apply must echo the same empty result (not 409).
        replay = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="apply-hrp105-empty-key",
            actor_id=user.id,
        )
        assert replay == result

    async def test_apply_all_deselected_returns_empty_arrays(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        """Same contract when the user rejects every suggestion in review."""
        from app.modules.position.models import Position

        spec = specialization_with_grades["spec"]
        position = Position(
            tenant_id=tenant.id,
            title="Position For Deselect Apply",
            specialization_id=spec.id,
            grade_id=specialization_with_grades["grades"][0].id,
            source="manual",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        async def fake_generate(*a, **kw):
            return GeneratedMatrixSchema.model_validate(_FAKE_MATRIX_PAYLOAD)

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
            extra_params={
                "position_id": str(position.id),
                "position_title": position.title,
            },
        )
        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        await db.refresh(sess)
        # Flip every selection bit off so apply walks the tree but skips
        # every leaf — same observable outcome as an empty payload.
        sess.selection_state = {
            tid: False for tid in (sess.selection_state or {}) if tid != "_edits"
        }
        await db.commit()

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="apply-hrp105-deselect-key",
            actor_id=user.id,
        )

        assert result["created_groups"] == []
        assert result["created_competences"] == []
        assert result["created_indicators"] == []
        assert result["created_grade_links"] == []


class TestMatrixEmptyGradesGuard:
    """HRP-33 redo: protect the LLM call from empty-grade snapshots."""

    async def test_execute_session_terminates_when_snapshot_has_no_grades(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        """When base_snapshot.specialization.grades is empty, terminate with
        insufficient_data BEFORE burning 5 LLM retries on a degenerate prompt."""
        spec = specialization_with_grades["spec"]
        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
        )
        # Forge the snapshot to mimic a runtime race: pairs vanished between
        # session create and Celery pickup. service.create_session blocks the
        # empty-grade case at the door — this test exercises the defence in
        # `execute_session`.
        sess.base_snapshot = {
            "specialization": {
                "id": str(spec.id),
                "title": spec.title,
                "description": None,
                "grades": [],
            }
        }
        await db.commit()

        called = False

        async def fake_generate(*a, **kw):
            nonlocal called
            called = True
            return GeneratedMatrixSchema.model_validate(_FAKE_MATRIX_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "error", result
        assert called is False, "LLM must NOT be called when grades are empty"
        await db.refresh(sess)
        assert sess.status == "error"
        assert sess.error_code == "insufficient_data"
        assert "grade" in (sess.error_message or "").lower()

    async def test_error_message_surfaces_underlying_exception_type(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_levels,
        specialization_with_grades,
        session_factory,
    ) -> None:
        """HRP-33: when retries exhaust, the user-facing error_message must
        include the underlying exception type so root cause is visible
        without log access (was: bare 'failed after N attempts' for any
        flavour)."""
        spec = specialization_with_grades["spec"]
        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="specialization_matrix", target_id=spec.id),
        )

        async def boom(*a, **kw):
            raise ValueError("truncated JSON: expecting property name at line 1")

        with patch.object(llm_client, "generate_json", side_effect=boom):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "error", result
        await db.refresh(sess)
        assert sess.status == "error"
        # Parse errors map to parse_error code.
        assert sess.error_code == "parse_error"
        msg = sess.error_message or ""
        assert "ValueError" in msg, msg
        assert "truncated JSON" in msg, msg
