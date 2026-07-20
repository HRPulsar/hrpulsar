"""Phase CR11 — service-layer tests for AI competence generation sessions."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.modules.ai_competence_generation import service
from app.modules.ai_competence_generation.schemas import (
    SessionCreate,
    SessionRefine,
)
from app.modules.competence import service as comp_service
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    CompetenceTreeAuditLog,
    SkillLevel,
)
from app.modules.competence.schemas import (
    CompetenceCreate,
    CompetenceGroupCreate,
)
from app.modules.dictionary.models import DictionaryItem
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def specialization(db: AsyncSession, tenant) -> DictionaryItem:
    item = DictionaryItem(
        type="specialization",
        title="Backend Engineer",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@pytest.fixture
async def basic_level(db: AsyncSession) -> SkillLevel:
    level = SkillLevel(title="Basic", sort_index=0, i18n_key="basic", tenant_id=None)
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


@pytest.fixture
async def tenant_group(db: AsyncSession, tenant) -> CompetenceGroup:
    return await comp_service.create_group(
        db, tenant.id, CompetenceGroupCreate(title="Engineering")
    )


@pytest.fixture
async def tenant_competence(db: AsyncSession, tenant, tenant_group) -> Competence:
    return await comp_service.create_competence(
        db,
        tenant.id,
        CompetenceCreate(title="API design", group_id=tenant_group.id),
    )


def _patch_payload_with_temp_ids(sess) -> dict[str, Any]:
    """Build a minimal payload with temp_ids; mirrors what the worker writes."""
    payload = {
        "groups": [
            {
                "temp_id": "g1",
                "title": "New Group",
                "description": None,
                "children": [],
                "competences": [
                    {
                        "temp_id": "c1",
                        "title": "New Competence",
                        "description": None,
                        "type": "hard_skill",
                        "indicators": [
                            {
                                "temp_id": "i1",
                                "title": "Knows the basics",
                                "skill_level": "basic",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    sess.payload = payload
    sess.selection_state = {"g1": True, "c1": True, "i1": True}
    sess.status = "ready"
    return payload


# ---------------------------------------------------------------------------
# create_session pre-conditions
# ---------------------------------------------------------------------------


class TestCreateSessionPreconditions:
    async def test_whole_base_requires_specialization(
        self, db: AsyncSession, tenant, user
    ) -> None:
        from fastapi import HTTPException
        from sqlalchemy import update

        # Other tests seed origin/tenant specializations into the shared test
        # DB (no per-test rollback), so deactivate them first.
        await db.execute(
            update(DictionaryItem)
            .where(DictionaryItem.type == "specialization")
            .values(is_active=False)
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_session(
                db, tenant.id, user.id, SessionCreate(scope="whole_base")
            )
        assert exc_info.value.status_code == 422

    async def test_whole_base_succeeds_with_specialization(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        assert sess.scope == "whole_base"
        assert sess.status == "pending"
        assert "groups" in sess.base_snapshot

    async def test_group_scope_requires_target_id(
        self, db: AsyncSession, tenant, user
    ) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.create_session(
                db, tenant.id, user.id, SessionCreate(scope="group")
            )
        assert exc_info.value.status_code == 422

    async def test_competence_indicators_requires_skill_levels(
        self, db: AsyncSession, tenant, user, tenant_competence
    ) -> None:
        from fastapi import HTTPException
        from sqlalchemy import update

        # Other tests may have seeded origin/tenant skill levels into the
        # shared test DB (no per-test rollback). Deactivate them all so the
        # pre-condition check sees zero active rows.
        await db.execute(update(SkillLevel).values(is_active=False))
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_session(
                db,
                tenant.id,
                user.id,
                SessionCreate(
                    scope="competence_indicators", target_id=tenant_competence.id
                ),
            )
        assert exc_info.value.status_code == 422

    async def test_competence_indicators_passes_with_skill_level(
        self,
        db: AsyncSession,
        tenant,
        user,
        tenant_competence,
        basic_level,
    ) -> None:
        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators", target_id=tenant_competence.id
            ),
        )
        assert sess.scope == "competence_indicators"

    async def test_competence_indicators_with_specialization_context(
        self,
        db: AsyncSession,
        tenant,
        user,
        tenant_competence,
        basic_level,
    ) -> None:
        """HRP-102: launching the session from a matrix cell must seed the
        base snapshot with the spec title, its grades, and the sibling
        competences so the prompt can calibrate against the career ladder.
        """
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        spec = DictionaryItem(
            type="specialization", title="Backend Engineer", tenant_id=tenant.id
        )
        grade_junior = DictionaryItem(
            type="grade", title="Junior", tenant_id=tenant.id
        )
        grade_senior = DictionaryItem(
            type="grade", title="Senior", tenant_id=tenant.id
        )
        sibling_group = CompetenceGroup(title="Aux", tenant_id=tenant.id)
        db.add_all([spec, grade_junior, grade_senior, sibling_group])
        await db.flush()

        sibling = Competence(
            title="SQL", group_id=sibling_group.id, tenant_id=tenant.id
        )
        db.add(sibling)
        await db.flush()

        gs_junior = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade_junior.id,
            specialization_id=spec.id,
            sort_index=0,
        )
        gs_senior = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade_senior.id,
            specialization_id=spec.id,
            sort_index=1,
        )
        db.add_all([gs_junior, gs_senior])
        await db.flush()
        db.add_all(
            [
                GradeCompetenceLink(
                    grade_specialization_id=gs_junior.id,
                    competence_id=tenant_competence.id,
                    skill_level_id=basic_level.id,
                ),
                GradeCompetenceLink(
                    grade_specialization_id=gs_junior.id,
                    competence_id=sibling.id,
                    skill_level_id=basic_level.id,
                ),
            ]
        )
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=tenant_competence.id,
                params=SessionParams(specialization_id=spec.id),
            ),
        )
        ctx = sess.base_snapshot.get("specialization_context")
        assert ctx is not None
        assert ctx["specialization_title"] == "Backend Engineer"
        grade_titles = [g["grade_title"] for g in ctx["grades"]]
        assert grade_titles == ["Junior", "Senior"]
        # The target competence must not show up in its own siblings list.
        assert "SQL" in ctx["sibling_competences"]
        assert tenant_competence.title not in ctx["sibling_competences"]
        # The spec id must be persisted in params for downstream calls.
        assert sess.params.get("specialization_id") == str(spec.id)

    async def test_competence_indicators_allows_spec_without_grades(
        self,
        db: AsyncSession,
        tenant,
        user,
        tenant_competence,
        basic_level,
    ) -> None:
        """HRP-102 follow-up: indicator-generation must not require the
        source spec to have grades configured. A reviewer flagged that the
        original `_ensure_specialization_accessible` rejected zero-grade
        specs with 422 — but matrix scope is the only path that truly
        needs grades. Indicator scope should accept the spec and simply
        emit an empty `specialization_context` (no ladder, no siblings)."""
        from app.modules.ai_competence_generation.schemas import SessionParams

        empty_spec = DictionaryItem(
            type="specialization",
            title="Empty Spec",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(empty_spec)
        await db.commit()
        await db.refresh(empty_spec)

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=tenant_competence.id,
                params=SessionParams(specialization_id=empty_spec.id),
            ),
        )
        ctx = sess.base_snapshot.get("specialization_context")
        assert ctx is not None
        assert ctx["specialization_title"] == "Empty Spec"
        assert ctx["grades"] == []
        assert ctx["sibling_competences"] == []
        assert sess.params.get("specialization_id") == str(empty_spec.id)

    async def test_competence_indicators_rejects_foreign_specialization(
        self,
        db: AsyncSession,
        tenant,
        user,
        tenant_competence,
        basic_level,
    ) -> None:
        """HRP-102: a spec that belongs to ANOTHER tenant must 404 — not
        merely a random UUID. Catches the case where the tenant filter is
        ever weakened to "row exists" without the cross-tenant guard."""
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.company.models import Tenant
        from fastapi import HTTPException

        other_tenant = Tenant(
            name=f"Other Corp {uuid.uuid4().hex[:6]}",
            slug=f"other-{uuid.uuid4().hex[:8]}",
        )
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)
        foreign_spec = DictionaryItem(
            type="specialization",
            title="Foreign Spec",
            tenant_id=other_tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(foreign_spec)
        await db.commit()
        await db.refresh(foreign_spec)

        with pytest.raises(HTTPException) as exc_info:
            await service.create_session(
                db,
                tenant.id,
                user.id,
                SessionCreate(
                    scope="competence_indicators",
                    target_id=tenant_competence.id,
                    params=SessionParams(specialization_id=foreign_spec.id),
                ),
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# One-active-session per user
# ---------------------------------------------------------------------------


class TestOneActiveSession:
    async def test_second_pending_session_raises_409(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        from fastapi import HTTPException

        first = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create_session(
                db, tenant.id, user.id, SessionCreate(scope="whole_base")
            )
        assert exc_info.value.status_code == 409
        # HRP-33: the 409 must carry the live session's identity so the UI
        # can redirect the user to the review page instead of dead-ending
        # on a generic "session exists" toast.
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["error_code"] == "active_session_exists"
        assert detail["session"]["id"] == str(first.id)
        assert detail["session"]["scope"] == "whole_base"
        assert detail["session"]["status"] == "pending"

    async def test_can_create_again_after_cancel(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        first = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        await service.cancel_session(db, first.id, user_id=user.id, tenant_id=tenant.id)
        second = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        assert second.id != first.id

    async def test_can_create_again_after_error(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """HRP-33: an errored session is terminal — must not block new ones.

        Mirrors the QA scenario where a prior generation crashed
        (Celery worker died, provider 5xx that escaped the retry wrapper,
        consume_credits raised) and the row was rescued into `error` by
        the worker's catch-all. The next AI Generate from any page must
        succeed without surfacing "active session already exists".
        """
        from datetime import datetime, timezone

        first = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        first.status = "error"
        first.error_code = "service_error"
        first.error_message = "Generation crashed unexpectedly"
        first.finished_at = datetime.now(timezone.utc)
        await db.commit()

        second = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        assert second.id != first.id
        assert second.status == "pending"

    async def test_409_conflict_carries_target_and_position_id(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """HRP-168: ActiveSessionConflictDialog needs target_id and
        position_id to route the user to the right page. Lock the
        contract here so a future refactor of the 409 payload does not
        silently break the new visible-decision dialog.
        """
        from fastapi import HTTPException
        from sqlalchemy.orm.attributes import flag_modified

        first = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="whole_base"),
        )
        # Pin position_id into params the same way the matrix-session
        # router does so the conflict detail can echo it back to the
        # frontend. whole_base never carries position_id naturally, but
        # the JSON column accepts arbitrary keys — this is exactly the
        # contract the frontend relies on.
        params = dict(first.params or {})
        params["position_id"] = "11111111-1111-1111-1111-111111111111"
        first.params = params
        flag_modified(first, "params")
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_session(
                db,
                tenant.id,
                user.id,
                SessionCreate(scope="whole_base"),
            )
        assert exc_info.value.status_code == 409
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["error_code"] == "active_session_exists"
        session_ref = detail["session"]
        assert session_ref["id"] == str(first.id)
        assert session_ref["scope"] == "whole_base"
        assert session_ref["target_id"] is None
        assert session_ref["position_id"] == "11111111-1111-1111-1111-111111111111"
        assert session_ref["status"] == "pending"


# ---------------------------------------------------------------------------
# Snapshot semantics
# ---------------------------------------------------------------------------


class TestSnapshot:
    async def test_base_snapshot_unaffected_by_later_changes(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        tenant_group,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        snap_before = sess.base_snapshot
        snap_titles = {g["title"] for g in snap_before["groups"]}
        assert "Engineering" in snap_titles

        await comp_service.create_group(
            db, tenant.id, CompetenceGroupCreate(title="LaterAdded")
        )
        # Re-read session
        await db.refresh(sess)
        snap_after = sess.base_snapshot
        snap_titles_after = {g["title"] for g in snap_after["groups"]}
        assert "LaterAdded" not in snap_titles_after


# ---------------------------------------------------------------------------
# Selection cascade
# ---------------------------------------------------------------------------


class TestSelectionCascade:
    async def test_select_indicator_propagates_up(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        sess.selection_state = {"g1": False, "c1": False, "i1": False}
        await db.commit()

        result = await service.update_selection(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            node_id="i1",
            selected=True,
        )
        assert result.selection_state["i1"] is True
        assert result.selection_state["c1"] is True
        assert result.selection_state["g1"] is True

    async def test_patch_selection_preserves_edits_sidecar(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """HRP-71 phase 3: PATCH /selection cascade must not clobber `_edits`."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        sess.selection_state = {
            "g1": False,
            "c1": False,
            "i1": False,
            "_edits": {"c1": {"title": "Renamed"}},
        }
        await db.commit()

        result = await service.update_selection(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            node_id="i1",
            selected=True,
        )
        assert result.selection_state["i1"] is True
        assert result.selection_state["c1"] is True  # cascade up
        assert result.selection_state["_edits"] == {"c1": {"title": "Renamed"}}

    async def test_deselect_group_propagates_down(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        await db.commit()

        result = await service.update_selection(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            node_id="g1",
            selected=False,
        )
        assert result.selection_state["g1"] is False
        assert result.selection_state["c1"] is False
        assert result.selection_state["i1"] is False


# ---------------------------------------------------------------------------
# Refine chain
# ---------------------------------------------------------------------------


class TestRefineChain:
    async def test_refine_creates_child_with_parent_id(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(parent)
        await db.commit()

        child = await service.refine_session(
            db,
            parent.id,
            user_id=user.id,
            tenant_id=tenant.id,
            refine=SessionRefine(add="add database skills"),
        )
        assert child.parent_session_id == parent.id
        assert "add database skills" in child.params["refinement_prompt"]
        assert child.scope == parent.scope
        await db.refresh(parent)
        assert parent.status == "cancelled"

    async def test_refine_persists_structured_form_snapshot(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """HRP-97: child.params.refinement_form must mirror what the user
        typed, field by field, so the UI can re-hydrate the panel on
        reopen / page refresh instead of forcing a retype."""
        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(parent)
        await db.commit()

        child = await service.refine_session(
            db,
            parent.id,
            user_id=user.id,
            tenant_id=tenant.id,
            refine=SessionRefine(
                general="more concise",
                add="cover security",
                exclude="drop deprecated APIs",
            ),
        )
        form = child.params.get("refinement_form")
        assert form == {
            "general": "more concise",
            "add": "cover security",
            "exclude": "drop deprecated APIs",
        }, form
        # Empty fields must not bleed into the snapshot — keeps payloads
        # compact and the UI's "has saved data" detector cheap.
        assert "change" not in form


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


class TestApply:
    async def test_apply_creates_groups_and_competences(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        await db.commit()

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="key-001",
            actor_id=user.id,
        )
        assert len(result["created_groups"]) == 1
        assert len(result["created_competences"]) == 1
        assert len(result["created_indicators"]) == 1

        # Verify rows in DB and publish flag
        comp_row = await db.get(Competence, uuid.UUID(result["created_competences"][0]))
        assert comp_row.is_published is True

        # Audit log written (filter by tenant — other test files share the DB
        # within a session, e.g. specialization_matrix apply also writes
        # `ai_generation_applied` rows under their own tenants).
        log_q = await db.execute(
            select(CompetenceTreeAuditLog).where(
                CompetenceTreeAuditLog.action == "ai_generation_applied",
                CompetenceTreeAuditLog.tenant_id == tenant.id,
            )
        )
        assert log_q.scalar_one_or_none() is not None

    async def test_apply_idempotent_with_same_key(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        await db.commit()

        first = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=False,
            idempotency_key="dup",
        )
        second = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=False,
            idempotency_key="dup",
        )
        assert first == second

    async def test_apply_unpublished_when_publish_false(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        await db.commit()

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=False,
            idempotency_key="np",
        )
        comp_row = await db.get(Competence, uuid.UUID(result["created_competences"][0]))
        assert comp_row.is_published is False

    async def test_apply_indicators_scope_respects_publish_flag(
        self,
        db: AsyncSession,
        tenant,
        user,
        tenant_competence,
        basic_level,
    ) -> None:
        """HRP-94: `competence_indicators` scope honours the `publish` flag.

        `publish=True` → created indicators are visible (`is_active=True`).
        `publish=False` → added as drafts (`is_active=False`).
        """
        from app.modules.competence.models import Indicator

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators", target_id=tenant_competence.id
            ),
        )
        sess.payload = {
            "indicators": [
                {
                    "temp_id": "i1",
                    "title": "Generated A",
                    "skill_level": "basic",
                },
                {
                    "temp_id": "i2",
                    "title": "Generated B",
                    "skill_level": "basic",
                },
            ]
        }
        sess.selection_state = {"i1": True, "i2": True}
        sess.status = "ready"
        await db.commit()

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="ind-pub",
        )
        assert len(result["created_indicators"]) == 2
        for ind_id in result["created_indicators"]:
            row = await db.get(Indicator, uuid.UUID(ind_id))
            assert row is not None
            assert row.is_active is True
            assert row.competence_id == tenant_competence.id

        # Second session for the same competence, this time as drafts.
        sess2 = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators", target_id=tenant_competence.id
            ),
        )
        sess2.payload = {
            "indicators": [
                {
                    "temp_id": "i3",
                    "title": "Generated C",
                    "skill_level": "basic",
                }
            ]
        }
        sess2.selection_state = {"i3": True}
        sess2.status = "ready"
        await db.commit()

        result2 = await service.apply_session(
            db,
            sess2.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=False,
            idempotency_key="ind-draft",
        )
        assert len(result2["created_indicators"]) == 1
        row = await db.get(
            Indicator, uuid.UUID(result2["created_indicators"][0])
        )
        assert row is not None
        assert row.is_active is False

    async def test_apply_skips_unselected_competence(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        sess.selection_state = {"g1": True, "c1": False, "i1": False}
        await db.commit()

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=False,
            idempotency_key="partial",
        )
        # Group is created (was selected) but competence skipped.
        assert len(result["created_groups"]) == 1
        assert result["created_competences"] == []

    async def test_apply_uses_inline_edited_titles(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        """HRP-71 phase 3: `_edits[temp_id].title` overrides the LLM title."""
        from app.modules.competence.models import Indicator

        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        sess.selection_state = {
            "g1": True,
            "c1": True,
            "i1": True,
            "_edits": {
                "g1": {"title": "Renamed Group"},
                "c1": {"title": "Renamed Competence"},
                "i1": {"title": "Renamed Indicator"},
            },
        }
        await db.commit()

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=False,
            idempotency_key="edits-1",
        )
        group_row = await db.get(
            CompetenceGroup, uuid.UUID(result["created_groups"][0])
        )
        comp_row = await db.get(Competence, uuid.UUID(result["created_competences"][0]))
        ind_row = await db.get(Indicator, uuid.UUID(result["created_indicators"][0]))
        assert group_row.title == "Renamed Group"
        assert comp_row.title == "Renamed Competence"
        assert ind_row.title == "Renamed Indicator"

    async def test_apply_falls_back_when_edit_title_missing(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        """Empty/whitespace-only edit titles must fall back to the LLM title."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        sess.selection_state = {
            "g1": True,
            "c1": True,
            "i1": True,
            "_edits": {
                "g1": {"title": "   "},  # whitespace-only → ignored
            },
        }
        await db.commit()

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=False,
            idempotency_key="edits-2",
        )
        group_row = await db.get(
            CompetenceGroup, uuid.UUID(result["created_groups"][0])
        )
        assert group_row.title == "New Group"  # original from _patch_payload

    async def test_replace_selection_persists_edits_under_magic_key(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """`replace_selection(edits=...)` stores them under selection_state['_edits']."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        await db.commit()

        result = await service.replace_selection(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            selection_state={"g1": True, "c1": True, "i1": True},
            edits={"c1": {"title": "Edited"}},
        )
        assert result.selection_state["_edits"] == {"c1": {"title": "Edited"}}
        assert result.selection_state["g1"] is True

    async def test_replace_selection_drops_edits_for_unknown_temp_id(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """Edits for temp_ids not in payload are silently dropped."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        await db.commit()

        result = await service.replace_selection(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            selection_state={"g1": True},
            edits={
                "c1": {"title": "Valid"},
                "ghost": {"title": "Should be dropped"},
            },
        )
        assert "ghost" not in result.selection_state.get("_edits", {})
        assert result.selection_state["_edits"] == {"c1": {"title": "Valid"}}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestRegenerate:
    async def test_rejects_in_flight_parent(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        """Pending/running parent → 409 (would compete with the child)."""
        from fastapi import HTTPException

        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        # Default status is `pending` after create_session.
        with pytest.raises(HTTPException) as exc_info:
            await service.regenerate_session(
                db, parent.id, user_id=user.id, tenant_id=tenant.id
            )
        assert exc_info.value.status_code == 409

    async def test_accepts_applied_parent_keeps_status(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        """HRP-71 phase 2: AI history «Repeat» replays applied sessions.

        The applied parent must stay applied (audit trail) while the child
        starts as a fresh pending session.
        """
        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        parent.status = "applied"
        parent.applied_idempotency_key = "k-test-applied-1"
        parent.applied_result = {
            "created_groups": [],
            "created_competences": [],
            "created_indicators": [],
            "created_grade_links": [],
            "idempotency_key": "k-test-applied-1",
        }
        await db.commit()

        child = await service.regenerate_session(
            db, parent.id, user_id=user.id, tenant_id=tenant.id
        )
        await db.refresh(parent)
        assert child.parent_session_id == parent.id
        assert child.status == "pending"
        assert parent.status == "applied"  # untouched

    async def test_accepts_cancelled_parent(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        await service.cancel_session(
            db, parent.id, user_id=user.id, tenant_id=tenant.id
        )
        child = await service.regenerate_session(
            db, parent.id, user_id=user.id, tenant_id=tenant.id
        )
        assert child.parent_session_id == parent.id
        assert child.status == "pending"

    async def test_ready_parent_cancels_and_spawns_child(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        """A `ready` parent occupies the per-user partial unique index, so
        regenerate forcibly cancels it before adding the child to keep both
        rows committable in the same transaction.
        """
        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        parent.status = "ready"
        await db.commit()

        child = await service.regenerate_session(
            db, parent.id, user_id=user.id, tenant_id=tenant.id
        )
        await db.refresh(parent)
        assert parent.status == "cancelled"
        assert child.parent_session_id == parent.id
        assert child.status == "pending"

    async def test_regenerate_inherits_refinement_form(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        """HRP-97: Try again on a session with saved refinement input copies
        both `refinement_prompt` and `refinement_form` to the child so the
        re-run uses the same instructions AND the UI keeps the panel
        pre-filled."""
        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(parent)
        await db.commit()
        # Refine once to populate the form snapshot.
        ref_child = await service.refine_session(
            db,
            parent.id,
            user_id=user.id,
            tenant_id=tenant.id,
            refine=SessionRefine(general="tighter copy"),
        )
        ref_child.status = "ready"
        await db.commit()

        regen = await service.regenerate_session(
            db, ref_child.id, user_id=user.id, tenant_id=tenant.id
        )
        assert regen.params.get("refinement_form") == {"general": "tighter copy"}
        assert "tighter copy" in (regen.params.get("refinement_prompt") or "")

    async def test_returns_409_when_another_active_session_exists(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        """Regression: parent in a terminal state (`error`) plus a stray
        active session for the same user (different parent / scope) used
        to surface as a 500 IntegrityError on `ux_compgen_one_active_per_user`.
        Must now translate cleanly to 409.
        """
        from fastapi import HTTPException

        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        # Drop parent into a terminal state so regenerate accepts it but
        # has nothing to cancel.
        parent.status = "error"
        await db.commit()
        # A second active session sneaks in (e.g. user kicked off a fresh
        # matrix generation in another tab).
        other = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        assert other.status == "pending"

        with pytest.raises(HTTPException) as exc_info:
            await service.regenerate_session(
                db, parent.id, user_id=user.id, tenant_id=tenant.id
            )
        assert exc_info.value.status_code == 409


class TestLifecycle:
    async def test_delete_marks_cancelled(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        result = await service.cancel_session(
            db, sess.id, user_id=user.id, tenant_id=tenant.id
        )
        assert result.status == "cancelled"

    async def test_cancel_broadcasts_status(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        monkeypatch,
    ) -> None:
        # The drawer only leaves the "running" state when a WS event arrives,
        # so cancel_session must emit one even though status is set in-band.
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        recorded: list[dict[str, Any]] = []

        async def fake_broadcast(tenant_id, user_id, session_id, status, **kwargs):
            recorded.append(
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "status": status,
                }
            )

        from app.modules.ai_competence_generation import tasks as task_module

        monkeypatch.setattr(task_module, "_broadcast_session_update", fake_broadcast)

        await service.cancel_session(db, sess.id, user_id=user.id, tenant_id=tenant.id)

        assert len(recorded) == 1
        assert recorded[0]["status"] == "cancelled"
        assert recorded[0]["session_id"] == sess.id

    async def test_cancel_revokes_celery_task(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        monkeypatch,
    ) -> None:
        # When the router stamped a celery_task_id on the session at enqueue
        # time, cancel must tell the broker to drop the task — otherwise the
        # worker keeps running, consumes provider tokens, and bills the
        # tenant for output the user already discarded.
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        sess.celery_task_id = "celery-abc-123"
        await db.commit()

        revoked: list[tuple[str, dict[str, Any]]] = []

        def fake_revoke(task_id, **kwargs):
            revoked.append((task_id, kwargs))

        from app.core import celery_app as celery_module

        monkeypatch.setattr(celery_module.celery.control, "revoke", fake_revoke)

        async def fake_broadcast(*args, **kwargs):
            pass

        from app.modules.ai_competence_generation import tasks as task_module

        monkeypatch.setattr(task_module, "_broadcast_session_update", fake_broadcast)

        await service.cancel_session(db, sess.id, user_id=user.id, tenant_id=tenant.id)

        assert revoked == [("celery-abc-123", {"terminate": False})]

    async def test_cancel_without_task_id_skips_revoke(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        monkeypatch,
    ) -> None:
        # Sessions created before the celery_task_id column existed (or
        # rows where enqueue raced cancel) carry NULL — revoke is a no-op.
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        assert sess.celery_task_id is None

        revoked: list[str] = []

        def fake_revoke(task_id, **kwargs):
            revoked.append(task_id)

        from app.core import celery_app as celery_module

        monkeypatch.setattr(celery_module.celery.control, "revoke", fake_revoke)

        async def fake_broadcast(*args, **kwargs):
            pass

        from app.modules.ai_competence_generation import tasks as task_module

        monkeypatch.setattr(task_module, "_broadcast_session_update", fake_broadcast)

        await service.cancel_session(db, sess.id, user_id=user.id, tenant_id=tenant.id)

        assert revoked == []

    async def test_cancel_idempotent_no_broadcast_on_second_call(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        monkeypatch,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        calls: list[str] = []

        async def fake_broadcast(*args, **kwargs):
            calls.append(args[3] if len(args) > 3 else kwargs.get("status", "?"))

        from app.modules.ai_competence_generation import tasks as task_module

        monkeypatch.setattr(task_module, "_broadcast_session_update", fake_broadcast)

        await service.cancel_session(db, sess.id, user_id=user.id, tenant_id=tenant.id)
        await service.cancel_session(db, sess.id, user_id=user.id, tenant_id=tenant.id)

        assert calls == ["cancelled"]

    async def test_clear_payload_keeps_session_active(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(sess)
        await db.commit()

        result = await service.clear_payload(
            db, sess.id, user_id=user.id, tenant_id=tenant.id
        )
        assert result.payload is None
        assert result.selection_state == {}
        assert result.status == "ready"

    async def test_clear_payload_wipes_refinement_form_and_prompt(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """HRP-97: Clear data is the explicit reset lever — refinement form
        snapshot and composed prompt must both drop so Try again runs
        against the original brief.
        """
        parent = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        _patch_payload_with_temp_ids(parent)
        await db.commit()
        ref_child = await service.refine_session(
            db,
            parent.id,
            user_id=user.id,
            tenant_id=tenant.id,
            refine=SessionRefine(general="keep it short", add="security"),
        )
        ref_child.status = "ready"
        _patch_payload_with_temp_ids(ref_child)
        await db.commit()
        assert ref_child.params.get("refinement_form")
        assert ref_child.params.get("refinement_prompt")

        cleared = await service.clear_payload(
            db, ref_child.id, user_id=user.id, tenant_id=tenant.id
        )
        assert cleared.payload is None
        assert "refinement_form" not in cleared.params
        assert "refinement_prompt" not in cleared.params


# ---------------------------------------------------------------------------
# list_other_active_sessions — powers PreflightModal
# ---------------------------------------------------------------------------


class TestListOtherActiveSessions:
    async def _make_user(self, db: AsyncSession, tenant, admin_role, suffix: str):
        from datetime import datetime, timezone

        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles

        u = User(
            email=f"other-{suffix}@test.com",
            password_hash=hash_password("testpass123"),
            first_name=f"John{suffix}",
            last_name="Smith",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await db.execute(
            user_roles.insert().values(user_id=u.id, role_id=admin_role.id)
        )
        await db.commit()
        return u

    async def test_excludes_self(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        rows = await service.list_other_active_sessions(
            db, tenant_id=tenant.id, user_id=user.id
        )
        assert rows == []

    async def test_returns_other_user_with_full_name(
        self, db: AsyncSession, tenant, user, admin_role, specialization
    ) -> None:
        other = await self._make_user(db, tenant, admin_role, "1")
        await service.create_session(
            db, tenant.id, other.id, SessionCreate(scope="whole_base")
        )
        rows = await service.list_other_active_sessions(
            db, tenant_id=tenant.id, user_id=user.id
        )
        assert len(rows) == 1
        assert rows[0]["user_id"] == other.id
        assert rows[0]["user_full_name"] == "John1 Smith"
        assert rows[0]["scope"] == "whole_base"
        assert rows[0]["status"] in ("pending", "running", "ready")

    async def test_skips_terminal_sessions(
        self, db: AsyncSession, tenant, user, admin_role, specialization
    ) -> None:
        other = await self._make_user(db, tenant, admin_role, "2")
        sess = await service.create_session(
            db, tenant.id, other.id, SessionCreate(scope="whole_base")
        )
        await service.cancel_session(db, sess.id, user_id=other.id, tenant_id=tenant.id)
        rows = await service.list_other_active_sessions(
            db, tenant_id=tenant.id, user_id=user.id
        )
        assert rows == []

    async def test_endpoint_returns_others(
        self, auth_client, db: AsyncSession, tenant, user, admin_role, specialization
    ) -> None:
        other = await self._make_user(db, tenant, admin_role, "3")
        await service.create_session(
            db, tenant.id, other.id, SessionCreate(scope="whole_base")
        )
        resp = await auth_client.get(
            "/api/competence-generation/sessions/active-others"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["user_full_name"] == "John3 Smith"


# ---------------------------------------------------------------------------
# create_session HTTP endpoint — regression for the post-commit greenlet bug
# ---------------------------------------------------------------------------


class TestContextOptionsEndpoint:
    """HRP-143: ``GET /context-options?scope=whole_base`` returns lists the
    preflight modal renders as per-item chips."""

    async def test_whole_base_returns_specializations_and_tree(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        from app.modules.company.models import Division
        from app.modules.competence.models import Competence, CompetenceGroup

        # Make sure there is a tree node + a division to surface in the response.
        group = CompetenceGroup(
            title="Cloud",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(group)
        await db.flush()
        db.add(
            Competence(
                title="AWS",
                tenant_id=tenant.id,
                group_id=group.id,
                is_active=True,
            )
        )
        db.add(Division(name="Engineering", tenant_id=tenant.id))
        tenant.description = "Acme Inc."
        await db.commit()

        resp = await auth_client.get(
            "/api/competence-generation/context-options?scope=whole_base"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {"specializations", "divisions", "company_description", "source_tree"} <= set(
            body.keys()
        )
        spec_titles = [s["title"] for s in body["specializations"]]
        assert "Backend Engineer" in spec_titles
        div_names = [d["name"] for d in body["divisions"]]
        assert "Engineering" in div_names
        assert body["company_description"] == "Acme Inc."
        tree_titles = [g["title"] for g in body["source_tree"]]
        assert "Cloud" in tree_titles

    async def test_indicators_scope_returns_empty_tree(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        resp = await auth_client.get(
            "/api/competence-generation/context-options?scope=competence_indicators"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_tree"] == []

    async def test_specialization_matrix_returns_context_blocks(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        """HRP-159: scope=specialization_matrix returns positions linked
        to the spec, tenant divisions with a ``related`` flag, existing
        competences in the matrix, and the specialization's description."""
        from app.modules.company.models import Division
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )
        from app.modules.position.models import Position

        specialization.description = "Designs payment APIs"
        platform = Division(name="Platform", tenant_id=tenant.id)
        payments = Division(name="Payments", tenant_id=tenant.id)
        db.add_all([platform, payments])
        await db.flush()

        db.add(
            Position(
                title="Senior Backend",
                tenant_id=tenant.id,
                specialization_id=specialization.id,
                division_id=payments.id,
                is_active=True,
                description="Owns the SDK",
            )
        )

        grade = DictionaryItem(
            type="grade",
            title="Senior",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(grade)
        await db.flush()
        gs = GradeSpecialization(
            tenant_id=tenant.id,
            specialization_id=specialization.id,
            grade_id=grade.id,
        )
        db.add(gs)
        await db.flush()

        group = CompetenceGroup(
            title="Cloud", tenant_id=tenant.id, sort_index=0, is_active=True
        )
        db.add(group)
        await db.flush()
        competence = Competence(
            title="AWS",
            description="Hands-on with AWS",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        db.add(competence)
        await db.flush()
        skill_level = SkillLevel(
            title="Basic", sort_index=0, i18n_key="basic", tenant_id=None
        )
        db.add(skill_level)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=competence.id,
                skill_level_id=skill_level.id,
            )
        )
        await db.commit()

        resp = await auth_client.get(
            "/api/competence-generation/context-options"
            f"?scope=specialization_matrix&target_id={specialization.id}"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["specialization_description"] == "Designs payment APIs"

        position_titles = [p["title"] for p in body["positions"]]
        assert "Senior Backend" in position_titles

        matrix_divs = body["matrix_divisions"]
        related_names = {d["name"]: d["related"] for d in matrix_divs}
        assert related_names["Payments"] is True
        assert related_names["Platform"] is False

        existing_titles = [c["title"] for c in body["existing_competences"]]
        assert "AWS" in existing_titles


class TestContextOptionsLinkedFlags:
    """HRP-114 re-spec: `group` / `competence_indicators` scopes ship the full
    spec + division list with `is_linked` so the modal can pre-check the
    linked subset and dim the rest."""

    async def _seed_linked_world(
        self,
        db: AsyncSession,
        tenant,
        specialization,
        basic_level,
    ):
        """Set up: target competence → matrix → `specialization` (linked) +
        an unrelated spec + a division wired through `specialization`'s
        position vs. a stand-alone division."""
        from app.modules.company.models import Division
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )
        from app.modules.position.models import Position

        unrelated_spec = DictionaryItem(
            type="specialization",
            title="Frontend Engineer",
            tenant_id=tenant.id,
            sort_index=1,
            is_active=True,
        )
        db.add(unrelated_spec)

        linked_division = Division(name="Payments", tenant_id=tenant.id)
        unrelated_division = Division(name="Marketing", tenant_id=tenant.id)
        db.add_all([linked_division, unrelated_division])
        await db.flush()

        # Position uses the *linked* spec → wires Division↔Spec.
        db.add(
            Position(
                title="Senior Backend",
                tenant_id=tenant.id,
                specialization_id=specialization.id,
                division_id=linked_division.id,
                is_active=True,
            )
        )

        grp = CompetenceGroup(
            title="Backend",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(grp)
        await db.flush()
        comp = Competence(
            title="Python",
            tenant_id=tenant.id,
            group_id=grp.id,
            is_active=True,
        )
        db.add(comp)
        await db.flush()

        grade = DictionaryItem(
            type="grade",
            title="Senior",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(grade)
        await db.flush()
        gs = GradeSpecialization(
            tenant_id=tenant.id,
            specialization_id=specialization.id,
            grade_id=grade.id,
        )
        db.add(gs)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=basic_level.id,
            )
        )
        await db.commit()
        await db.refresh(grp)
        await db.refresh(comp)
        return grp, comp, linked_division, unrelated_division, unrelated_spec

    async def test_group_scope_marks_linked_specs_and_divisions(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        grp, _, _, _, _ = await self._seed_linked_world(
            db, tenant, specialization, basic_level
        )

        resp = await auth_client.get(
            "/api/competence-generation/context-options"
            f"?scope=group&target_id={grp.id}"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        spec_by_title = {s["title"]: s for s in body["specializations"]}
        assert spec_by_title["Backend Engineer"]["is_linked"] is True
        assert spec_by_title["Frontend Engineer"]["is_linked"] is False

        div_by_name = {d["name"]: d for d in body["divisions"]}
        assert div_by_name["Payments"]["is_linked"] is True
        assert div_by_name["Marketing"]["is_linked"] is False

    async def test_indicators_scope_marks_linked_specs_and_divisions(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        _, comp, _, _, _ = await self._seed_linked_world(
            db, tenant, specialization, basic_level
        )

        resp = await auth_client.get(
            "/api/competence-generation/context-options"
            f"?scope=competence_indicators&target_id={comp.id}"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        spec_by_title = {s["title"]: s for s in body["specializations"]}
        assert spec_by_title["Backend Engineer"]["is_linked"] is True
        assert spec_by_title["Frontend Engineer"]["is_linked"] is False

        div_by_name = {d["name"]: d for d in body["divisions"]}
        assert div_by_name["Payments"]["is_linked"] is True
        assert div_by_name["Marketing"]["is_linked"] is False

    async def test_whole_base_scope_omits_is_linked_flag(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        from app.modules.company.models import Division

        db.add(Division(name="Engineering", tenant_id=tenant.id))
        await db.commit()

        resp = await auth_client.get(
            "/api/competence-generation/context-options?scope=whole_base"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for s in body["specializations"]:
            assert "is_linked" not in s
        for d in body["divisions"]:
            assert "is_linked" not in d

    async def test_group_with_no_competences_marks_all_specs_unlinked(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
    ) -> None:
        from app.modules.competence.models import CompetenceGroup

        grp = CompetenceGroup(
            title="Empty group",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(grp)
        await db.commit()
        await db.refresh(grp)

        resp = await auth_client.get(
            "/api/competence-generation/context-options"
            f"?scope=group&target_id={grp.id}"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Full list still surfaced, just with everything dimmed.
        assert body["specializations"], "expected at least the seeded spec"
        assert all(s["is_linked"] is False for s in body["specializations"])
        for d in body["divisions"]:
            assert d["is_linked"] is False


class TestExistingTreeAndIndicatorsInSessionRead:
    """HRP-114 re-spec: SessionRead surfaces `existing_tree` /
    `existing_indicators` so the result modal can render new + existing in
    one tree without an extra round-trip."""

    async def test_group_session_returns_existing_tree(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        from app.modules.competence.models import Competence, CompetenceGroup

        grp = CompetenceGroup(
            title="Backend",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(grp)
        await db.flush()
        db.add(
            Competence(
                title="Python",
                tenant_id=tenant.id,
                group_id=grp.id,
                is_active=True,
            )
        )
        await db.commit()
        await db.refresh(grp)

        resp = await auth_client.post(
            "/api/competence-generation/sessions",
            json={
                "scope": "group",
                "target_id": str(grp.id),
                "params": {},
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        tree = body["existing_tree"]
        assert isinstance(tree, list) and len(tree) == 1
        root = tree[0]
        assert root["title"] == "Backend"
        # Competence shows up so the result preview can list it disabled.
        titles = [c["title"] for c in (root.get("competences") or [])]
        assert "Python" in titles
        assert body["existing_indicators"] is None

    async def test_indicators_session_returns_existing_indicators(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        from app.modules.competence.models import (
            Competence,
            CompetenceGroup,
            Indicator,
        )

        grp = CompetenceGroup(
            title="Communication",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(grp)
        await db.flush()
        comp = Competence(
            title="Active listening",
            tenant_id=tenant.id,
            group_id=grp.id,
            is_active=True,
        )
        db.add(comp)
        await db.flush()
        db.add(
            Indicator(
                title="Restates the speaker's point",
                tenant_id=tenant.id,
                competence_id=comp.id,
                skill_level_id=basic_level.id,
                is_active=True,
            )
        )
        await db.commit()
        await db.refresh(comp)

        resp = await auth_client.post(
            "/api/competence-generation/sessions",
            json={
                "scope": "competence_indicators",
                "target_id": str(comp.id),
                "params": {},
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        indicators = body["existing_indicators"]
        assert isinstance(indicators, list) and len(indicators) == 1
        ind = indicators[0]
        assert ind["title"] == "Restates the speaker's point"
        assert ind["skill_level"] == "Basic"
        # Existing tree only meaningful for group / whole_base.
        assert body["existing_tree"] is None


class TestCreateSessionEndpoint:
    """Guards against MissingGreenlet on _to_read after the post-enqueue commit.

    The endpoint commits a second time (to persist celery_task_id) and then
    serialises the row via _to_read, which touches lazy-loaded attributes on
    an expired ORM instance — without an explicit refresh that fails with
    SQLAlchemy MissingGreenlet under asyncpg.
    """

    async def test_post_returns_201_with_full_session(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        basic_level,
    ) -> None:
        resp = await auth_client.post(
            "/api/competence-generation/sessions",
            json={"scope": "whole_base", "params": {}},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # _to_read touches updated_at — the formerly-lazy attribute that
        # tripped MissingGreenlet. Assert it's serialised so we don't
        # silently regress to the bug.
        assert body["scope"] == "whole_base"
        assert body["status"] == "pending"
        assert body["updated_at"]
        assert body["created_at"]


# ---------------------------------------------------------------------------
# list_sessions — AI history endpoint (HRP-71 phase 1)
# ---------------------------------------------------------------------------


def _matrix_payload_two_competences() -> dict[str, Any]:
    """Minimal `specialization_matrix` payload with two competences + 3 indicators."""
    return {
        "groups": [
            {
                "temp_id": "g1",
                "title": "Backend",
                "description": None,
                "children": [],
                "competences": [
                    {
                        "temp_id": "c1",
                        "title": "API design",
                        "description": None,
                        "type": "hard_skill",
                        "indicators": [
                            {"temp_id": "i1", "title": "REST", "skill_level": "basic"},
                            {
                                "temp_id": "i2",
                                "title": "GraphQL",
                                "skill_level": "basic",
                            },
                        ],
                        "grade_levels": {},
                    },
                    {
                        "temp_id": "c2",
                        "title": "Async I/O",
                        "description": None,
                        "type": "hard_skill",
                        "indicators": [
                            {
                                "temp_id": "i3",
                                "title": "asyncio",
                                "skill_level": "basic",
                            },
                        ],
                        "grade_levels": {},
                    },
                ],
            }
        ]
    }


class TestListSessions:
    async def test_filters_by_target_id_and_scope(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        # Two whole_base sessions (no target_id), one cancelled so the unique
        # index lets the second one exist. Then patch target_id on one row to
        # simulate a specialization-scoped session without dragging in the
        # full grade/skill-level fixtures.
        s1 = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        s1.target_id = specialization.id
        s1.scope = "specialization_matrix"
        await db.commit()
        await service.cancel_session(db, s1.id, user_id=user.id, tenant_id=tenant.id)

        s2 = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        # By target_id: only s1.
        rows = await service.list_sessions(
            db, tenant_id=tenant.id, target_id=specialization.id
        )
        ids = {row["id"] for row in rows}
        assert s1.id in ids
        assert s2.id not in ids

        # By scope: specialization_matrix → only s1.
        rows = await service.list_sessions(
            db, tenant_id=tenant.id, scope="specialization_matrix"
        )
        ids = {row["id"] for row in rows}
        assert s1.id in ids
        assert s2.id not in ids

    async def test_isolates_other_tenants(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        from app.modules.auth.models import Role, User, user_roles
        from app.modules.company.models import Tenant
        from sqlalchemy import select

        await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        other_tenant = Tenant(name="Other Corp", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)
        admin_role = (
            await db.execute(select(Role).where(Role.code == "admin"))
        ).scalar_one()
        other_user = User(
            email=f"other-{uuid.uuid4().hex[:6]}@test.com",
            password_hash="x",
            first_name="Other",
            last_name="Admin",
            tenant_id=other_tenant.id,
        )
        db.add(other_user)
        await db.commit()
        await db.refresh(other_user)
        await db.execute(
            user_roles.insert().values(user_id=other_user.id, role_id=admin_role.id)
        )
        await db.commit()

        rows = await service.list_sessions(db, tenant_id=other_tenant.id)
        assert rows == []

    async def test_counts_for_ready_session_use_selection_state(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        """`ready` status: accepted = number of True checkboxes among competences."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        # Re-shape the row into a matrix-style session post-hoc — avoids the
        # full grade/skill-level fixture chain, since list_sessions doesn't
        # care how the row got there. base_snapshot.specialization.grades
        # drives the `grades` count.
        sess.scope = "specialization_matrix"
        sess.target_id = specialization.id
        sess.base_snapshot = {
            "specialization": {
                "id": str(specialization.id),
                "title": "Backend Engineer",
                "grades": [{"grade_title": "Junior"}],
            }
        }
        sess.payload = _matrix_payload_two_competences()
        sess.selection_state = {
            "g1": True,
            "c1": True,
            "c2": False,
            "i1": True,
            "i2": False,
            "i3": False,
        }
        sess.status = "ready"
        await db.commit()

        rows = await service.list_sessions(
            db, tenant_id=tenant.id, target_id=specialization.id
        )
        assert len(rows) == 1
        counts = rows[0]["counts"]
        assert counts == {
            "grades": 1,
            "competences": 2,
            "indicators": 3,
            "accepted": 1,
            "rejected": 1,
        }

    async def test_counts_for_applied_session_use_applied_result(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        """`applied` status: accepted = len(applied_result.created_competences)."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        sess.payload = _matrix_payload_two_competences()
        sess.selection_state = {"g1": True, "c1": True, "c2": True}
        sess.status = "applied"
        sess.applied_idempotency_key = "k-test-1"
        sess.applied_result = {
            "created_groups": [str(uuid.uuid4())],
            "created_competences": [str(uuid.uuid4()), str(uuid.uuid4())],
            "created_indicators": [str(uuid.uuid4())],
            "created_grade_links": [],
            "idempotency_key": "k-test-1",
        }
        await db.commit()

        rows = await service.list_sessions(db, tenant_id=tenant.id)
        applied = next(r for r in rows if r["id"] == sess.id)
        assert applied["counts"]["competences"] == 2
        assert applied["counts"]["accepted"] == 2
        assert applied["counts"]["rejected"] == 0
        assert applied["status"] == "applied"

    async def test_counts_for_indicator_scope_default_to_accepted(
        self,
        db: AsyncSession,
        tenant,
        user,
        tenant_competence,
        basic_level,
    ) -> None:
        """`competence_indicators` ready scope: empty selection → all accepted.

        Mirrors `_apply_indicators_only`'s `default_when_missing=True`: a fresh
        `ready` session shows N indicators ready to accept, not N rejected.
        """
        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators", target_id=tenant_competence.id
            ),
        )
        sess.payload = {
            "indicators": [
                {"temp_id": "i1", "title": "REST", "skill_level": "basic"},
                {"temp_id": "i2", "title": "GraphQL", "skill_level": "basic"},
                {"temp_id": "i3", "title": "gRPC", "skill_level": "basic"},
            ]
        }
        sess.selection_state = {"i2": False}  # one explicit reject
        sess.status = "ready"
        await db.commit()

        rows = await service.list_sessions(
            db, tenant_id=tenant.id, target_id=tenant_competence.id
        )
        assert len(rows) == 1
        counts = rows[0]["counts"]
        assert counts["indicators"] == 3
        assert counts["accepted"] == 2  # i1 + i3 (default-True), i2 rejected
        assert counts["rejected"] == 1
        assert counts["competences"] == 0  # indicator-only payload has no comps

    async def test_pagination(
        self, db: AsyncSession, tenant, user, specialization
    ) -> None:
        # Three sessions, all cancelled (so the per-user partial unique allows them).
        for _ in range(3):
            sess = await service.create_session(
                db, tenant.id, user.id, SessionCreate(scope="whole_base")
            )
            await service.cancel_session(
                db, sess.id, user_id=user.id, tenant_id=tenant.id
            )

        first = await service.list_sessions(db, tenant_id=tenant.id, limit=2, offset=0)
        rest = await service.list_sessions(db, tenant_id=tenant.id, limit=2, offset=2)
        assert len(first) == 2
        assert len(rest) == 1
        assert {r["id"] for r in first} & {r["id"] for r in rest} == set()

    async def test_endpoint_omits_payload_field(
        self, auth_client, db: AsyncSession, tenant, user, specialization, basic_level
    ) -> None:
        """The list response is the slim history shape — no payload key."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        sess.payload = _matrix_payload_two_competences()
        sess.status = "ready"
        await db.commit()

        resp = await auth_client.get("/api/competence-generation/sessions")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        row = next(r for r in body if r["id"] == str(sess.id))
        assert "payload" not in row
        assert row["counts"]["competences"] == 2
        assert row["user_full_name"] == "Test User"
        assert row["summary"]["with_indicators"] is True
