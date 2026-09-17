"""HRP-750: AI competence → primitive mapping — batch run, re-run rules,
internal review, tenant isolation, and the hidden internal surface."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.ai import llm_client
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Tenant
from app.modules.competence.models import Competence, CompetenceGroup, Indicator
from app.modules.primitives import catalog_data, mapping_service
from app.modules.primitives.mapping_service import (
    PROMPT_VERSION,
    TOP_LEVEL_TAG,
    MappedCompetencesSchema,
)
from app.modules.primitives.models import (
    CompetenceMappingState,
    CompetencePrimitive,
    Primitive,
)
from app.modules.primitives.schemas import ReviewItem
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(db: AsyncSession) -> None:
    await db.execute(catalog_data.seed_insert())
    await db.commit()


async def _tenant(db: AsyncSession) -> Tenant:
    suffix = uuid.uuid4().hex[:8]
    t = Tenant(name=f"Other {suffix}", slug=f"other-{suffix}")
    db.add(t)
    await db.commit()
    return t


async def _competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    title: str,
    *,
    is_active: bool = True,
) -> Competence:
    group = CompetenceGroup(title=f"Group {uuid.uuid4().hex[:6]}", tenant_id=tenant_id)
    db.add(group)
    await db.flush()
    comp = Competence(
        title=title,
        description="Described",
        group_id=group.id,
        tenant_id=tenant_id,
        is_active=is_active,
    )
    db.add(comp)
    await db.commit()
    return comp


async def _codes(db: AsyncSession, competence_id: uuid.UUID) -> list[str]:
    rows = await db.execute(
        select(Primitive.code)
        .join(CompetencePrimitive, CompetencePrimitive.primitive_id == Primitive.id)
        .where(CompetencePrimitive.competence_id == competence_id)
        .order_by(Primitive.sort_index)
    )
    return list(rows.scalars().all())


async def _links(
    db: AsyncSession, competence_id: uuid.UUID
) -> list[CompetencePrimitive]:
    rows = await db.execute(
        select(CompetencePrimitive).where(
            CompetencePrimitive.competence_id == competence_id
        )
    )
    return list(rows.scalars().all())


async def _non_admin_token(db: AsyncSession, tenant: Tenant) -> str:
    role = (
        (await db.execute(select(Role).where(Role.code == "employee")))
        .scalars()
        .first()
    )
    if role is None:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
    u = User(
        email=f"emp-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Plain",
        last_name="Employee",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.commit()
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    return create_access_token(str(u.id), str(tenant.id))


async def _state(db: AsyncSession, competence_id: uuid.UUID) -> CompetenceMappingState:
    return (
        await db.execute(
            select(CompetenceMappingState).where(
                CompetenceMappingState.competence_id == competence_id
            )
        )
    ).scalar_one()


class FakeLLM:
    """Stands in for ``llm_client.generate_json``: answers P1+P2 for every
    competence in the prompt unless ``answers`` overrides a competence id;
    ``extra`` items are appended verbatim (hallucination probes)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.answers: dict[str, list[str]] = {}
        self.extra: list[dict] = []

    async def __call__(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        payload = json.loads(prompt)
        items = [
            {
                "competence_id": c["competence_id"],
                "primitives": self.answers.get(c["competence_id"], ["P1", "P2"]),
                "confidence": 0.8,
                "rationale": "Reads documents and checks them against a reference.",
            }
            for c in payload["competences"]
        ]
        return MappedCompetencesSchema.model_validate({"items": items + self.extra})

    def sent_ids(self) -> list[set[str]]:
        return [
            {c["competence_id"] for c in json.loads(call["prompt"])["competences"]}
            for call in self.calls
        ]


@pytest.fixture
def llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(llm_client, "generate_json", fake)
    return fake


class TestMapCompetences:
    async def test_writes_ai_suggested_links_with_run_metadata(self, db, tenant, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "Contract review")
        b = await _competence(db, tenant.id, "Incident analysis")

        result = await mapping_service.map_competences(db, tenant.id)

        assert result.as_dict() == {
            "mapped": 2,
            "empty": 0,
            "kept": 0,
            "skipped": 0,
            "batches": 1,
        }
        for comp in (a, b):
            assert await _codes(db, comp.id) == ["P1", "P2"]
            state = await _state(db, comp.id)
            assert state.status == "ai_suggested"
            assert state.prompt_version == PROMPT_VERSION
            assert state.confidence == 0.8
            assert state.rationale
            assert not mapping_service.is_stale(state, comp)
        call = llm.calls[0]
        assert call["schema"] is MappedCompetencesSchema
        assert call["tenant_id"] == tenant.id
        assert call["max_tokens"] == mapping_service.MAX_OUTPUT_TOKENS
        # Every active code with its scope reaches the model.
        for code in ("P1", "P11", "P13", "B4"):
            assert f"- {code} - " in call["system"]
        assert "kind: boundary" in call["system"]
        # v2 rules (HRP-751 round 1) reach the model.
        assert "least one of its indicators evidences" in call["system"]
        assert "P12 when the competence is explicitly about following" in call["system"]

    async def test_batches_by_size(self, db, tenant, llm):
        await _seed(db)
        for i in range(3):
            await _competence(db, tenant.id, f"Skill {i}")

        result = await mapping_service.map_competences(db, tenant.id, batch_size=2)

        assert result.batches == 2
        assert result.mapped == 3
        assert [len(ids) for ids in llm.sent_ids()] == [2, 1]

    async def test_is_scoped_to_the_tenant(self, db, tenant, llm):
        await _seed(db)
        mine = await _competence(db, tenant.id, "Mine")
        other = await _tenant(db)
        theirs = await _competence(db, other.id, "Theirs")

        await mapping_service.map_competences(db, tenant.id)

        assert await _codes(db, mine.id) == ["P1", "P2"]
        assert await _links(db, theirs.id) == []
        assert llm.sent_ids() == [{str(mine.id)}]
        assert await mapping_service.list_mappings(db, other.id) == []

    async def test_explicit_ids_and_inactive_rows(self, db, tenant, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        b = await _competence(db, tenant.id, "B")
        inactive = await _competence(db, tenant.id, "Gone", is_active=False)

        result = await mapping_service.map_competences(
            db, tenant.id, [a.id, inactive.id]
        )

        assert result.mapped == 1
        assert await _codes(db, a.id) == ["P1", "P2"]
        assert await _links(db, b.id) == []
        assert await _links(db, inactive.id) == []

    async def test_model_noise_is_normalised(self, db, tenant, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        b = await _competence(db, tenant.id, "B")
        llm.answers[str(a.id)] = ["P1", "P99"]
        llm.answers[str(b.id)] = []
        llm.extra.append(
            {
                "competence_id": "not-a-uuid",
                "primitives": ["P3"],
                "confidence": 7,
                "rationale": "x" * 5000,
            }
        )
        llm.extra.append(
            {"competence_id": str(uuid.uuid4()), "primitives": ["P3"]},
        )

        result = await mapping_service.map_competences(db, tenant.id)

        assert result.as_dict() == {
            "mapped": 1,
            "empty": 1,
            "kept": 0,
            "skipped": 2,
            "batches": 1,
        }
        assert await _codes(db, a.id) == ["P1"]
        assert await _links(db, b.id) == []
        assert (await _state(db, b.id)).status == "ai_suggested"

    async def test_omitted_competence_counts_as_skipped(self, db, tenant, monkeypatch):
        await _seed(db)
        await _competence(db, tenant.id, "A")

        async def silent(prompt, **kwargs):
            return MappedCompetencesSchema(items=[])

        monkeypatch.setattr(llm_client, "generate_json", silent)
        result = await mapping_service.map_competences(db, tenant.id)
        assert (result.mapped, result.skipped) == (0, 1)

    async def test_empty_tenant_makes_no_llm_call(self, db, tenant, llm):
        await _seed(db)
        result = await mapping_service.map_competences(db, tenant.id)
        assert result.as_dict() == {
            "mapped": 0,
            "empty": 0,
            "kept": 0,
            "skipped": 0,
            "batches": 0,
        }
        assert llm.calls == []


class TestRerun:
    async def test_rerun_keeps_reviewed_and_current_links(self, db, tenant, user, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        b = await _competence(db, tenant.id, "B")
        await mapping_service.map_competences(db, tenant.id)
        await mapping_service.review_mapping(
            db,
            tenant.id,
            [ReviewItem(competence_id=a.id, verdict="corrected", primitives=["P6"])],
            reviewed_by_id=user.id,
        )
        reviewed_at = (await _state(db, a.id)).reviewed_at

        # Same prompt version, nothing stale: no model call at all.
        result = await mapping_service.map_competences(db, tenant.id)
        assert (result.kept, result.batches) == (2, 0)

        # force re-maps the ai_suggested row, never the reviewed one.
        result = await mapping_service.map_competences(db, tenant.id, force=True)
        assert (result.kept, result.mapped) == (1, 1)
        assert llm.sent_ids()[-1] == {str(b.id)}
        assert await _codes(db, a.id) == ["P6"]
        a_state = await _state(db, a.id)
        assert a_state.status == "reviewed"
        assert a_state.reviewed_at == reviewed_at

    async def test_older_prompt_version_is_remapped(self, db, tenant, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        await mapping_service.apply_mapping(
            db, a, ["P5"], status="ai_suggested", prompt_version="v2map.v0"
        )

        result = await mapping_service.map_competences(db, tenant.id)

        assert result.mapped == 1
        assert await _codes(db, a.id) == ["P1", "P2"]

    async def test_stale_reviewed_link_is_remapped(self, db, tenant, user, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        await mapping_service.apply_mapping(
            db, a, ["P6"], status="reviewed", reviewed_by_id=user.id
        )
        a.title = "A renamed"
        await db.commit()

        result = await mapping_service.map_competences(db, tenant.id)

        assert result.mapped == 1
        assert await _codes(db, a.id) == ["P1", "P2"]
        assert (await _state(db, a.id)).status == "ai_suggested"

    async def test_rejected_and_empty_states_survive_a_rerun(
        self, db, tenant, user, llm
    ):
        await _seed(db)
        rejected = await _competence(db, tenant.id, "Rejected")
        empty = await _competence(db, tenant.id, "Empty")
        llm.answers[str(empty.id)] = []
        await mapping_service.map_competences(db, tenant.id)
        await mapping_service.review_mapping(
            db,
            tenant.id,
            [ReviewItem(competence_id=rejected.id, verdict="rejected")],
            reviewed_by_id=user.id,
        )
        assert (await _state(db, rejected.id)).status == "rejected"

        # Without force nothing is stale or outdated: no model call.
        result = await mapping_service.map_competences(db, tenant.id)
        assert (result.kept, result.batches) == (2, 0)

        # force re-sends the empty ai_suggested one, never the rejection.
        result = await mapping_service.map_competences(db, tenant.id, force=True)
        assert (result.kept, result.mapped, result.empty) == (1, 0, 1)
        assert llm.sent_ids()[-1] == {str(empty.id)}
        assert await _links(db, rejected.id) == []
        assert (await _state(db, rejected.id)).status == "rejected"

    async def test_stale_rejected_state_is_remapped(self, db, tenant, user, llm):
        # A rejection was about the old text: renaming the competence sends
        # it back to the model (documented in _needs_mapping).
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        await mapping_service.apply_mapping(
            db, a, [], status="rejected", reviewed_by_id=user.id
        )
        a.title = "A renamed"
        await db.commit()

        result = await mapping_service.map_competences(db, tenant.id)

        assert result.mapped == 1
        assert (await _state(db, a.id)).status == "ai_suggested"

    async def test_manual_state_is_protected(self, db, tenant, user, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        await mapping_service.apply_mapping(
            db, a, ["P3"], status="manual", reviewed_by_id=user.id
        )

        result = await mapping_service.map_competences(db, tenant.id, force=True)

        assert (result.kept, result.batches) == (1, 0)
        assert await _codes(db, a.id) == ["P3"]


class TestReview:
    async def test_accepted_flips_to_reviewed_and_keeps_the_verdict(
        self, db, tenant, user, llm
    ):
        await _seed(db)
        comp = await _competence(db, tenant.id, "A")
        await mapping_service.map_competences(db, tenant.id)

        counts = await mapping_service.review_mapping(
            db,
            tenant.id,
            [ReviewItem(competence_id=comp.id, verdict="accepted")],
            reviewed_by_id=user.id,
        )

        assert counts == {"accepted": 1, "corrected": 0, "rejected": 0}
        assert await _codes(db, comp.id) == ["P1", "P2"]
        state = await _state(db, comp.id)
        assert state.status == "reviewed"
        assert state.reviewed_at is not None
        assert state.reviewed_by_id == user.id
        assert state.confidence == 0.8
        assert state.prompt_version == PROMPT_VERSION

    async def test_corrected_and_rejected(self, db, tenant, user, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        b = await _competence(db, tenant.id, "B")
        await mapping_service.map_competences(db, tenant.id)

        counts = await mapping_service.review_mapping(
            db,
            tenant.id,
            [
                ReviewItem(competence_id=a.id, verdict="corrected", primitives=["P6"]),
                ReviewItem(competence_id=b.id, verdict="rejected"),
            ],
            reviewed_by_id=user.id,
        )

        assert counts == {"accepted": 0, "corrected": 1, "rejected": 1}
        assert await _codes(db, a.id) == ["P6"]
        assert (await _state(db, a.id)).status == "reviewed"
        assert await _links(db, b.id) == []
        assert (await _state(db, b.id)).status == "rejected"

    async def test_review_validates_the_whole_batch_before_writing(
        self, db, tenant, user, llm
    ):
        await _seed(db)
        other = await _tenant(db)
        theirs = await _competence(db, other.id, "Theirs")
        mine = await _competence(db, tenant.id, "Mine")
        await mapping_service.map_competences(db, tenant.id)

        with pytest.raises(AppError) as exc:
            await mapping_service.review_mapping(
                db,
                tenant.id,
                [
                    ReviewItem(competence_id=mine.id, verdict="accepted"),
                    ReviewItem(competence_id=theirs.id, verdict="accepted"),
                ],
                reviewed_by_id=user.id,
            )
        assert exc.value.code == "competence_not_found"

        with pytest.raises(AppError) as exc:
            await mapping_service.review_mapping(
                db,
                tenant.id,
                [
                    ReviewItem(competence_id=mine.id, verdict="accepted"),
                    ReviewItem(
                        competence_id=mine.id, verdict="corrected", primitives=["P99"]
                    ),
                ],
                reviewed_by_id=user.id,
            )
        assert exc.value.code == "primitive_not_found"
        # Nothing landed: the first item did not flip before the failure.
        assert (await _state(db, mine.id)).status == "ai_suggested"
        assert await _links(db, theirs.id) == []

    async def test_accept_needs_a_fresh_mapping(self, db, tenant, user, llm):
        await _seed(db)
        never = await _competence(db, tenant.id, "Never mapped")
        stale = await _competence(db, tenant.id, "Stale")
        await mapping_service.map_competences(db, tenant.id, [stale.id])
        stale.title = "Stale renamed"
        await db.commit()

        with pytest.raises(AppError) as exc:
            await mapping_service.review_mapping(
                db,
                tenant.id,
                [ReviewItem(competence_id=never.id, verdict="accepted")],
                reviewed_by_id=user.id,
            )
        assert exc.value.code == "mapping_not_found"

        with pytest.raises(AppError) as exc:
            await mapping_service.review_mapping(
                db,
                tenant.id,
                [ReviewItem(competence_id=stale.id, verdict="accepted")],
                reviewed_by_id=user.id,
            )
        assert exc.value.code == "mapping_stale"
        assert (await _state(db, stale.id)).status == "ai_suggested"

        # A stale row can still be corrected or rejected.
        counts = await mapping_service.review_mapping(
            db,
            tenant.id,
            [
                ReviewItem(
                    competence_id=stale.id, verdict="corrected", primitives=["P2"]
                )
            ],
            reviewed_by_id=user.id,
        )
        assert counts["corrected"] == 1
        assert await _codes(db, stale.id) == ["P2"]

    async def test_accepted_codes_are_validated_before_writing(
        self, db, tenant, user, llm
    ):
        await _seed(db)
        fine = await _competence(db, tenant.id, "Fine")
        retired = await _competence(db, tenant.id, "Retired")
        llm.answers[str(retired.id)] = ["P13"]
        await mapping_service.map_competences(db, tenant.id)
        p13 = (
            await db.execute(select(Primitive).where(Primitive.code == "P13"))
        ).scalar_one()
        p13.retired_in = "v9-test"
        await db.commit()
        try:
            with pytest.raises(AppError) as exc:
                await mapping_service.review_mapping(
                    db,
                    tenant.id,
                    [
                        ReviewItem(competence_id=fine.id, verdict="accepted"),
                        ReviewItem(competence_id=retired.id, verdict="accepted"),
                    ],
                    reviewed_by_id=user.id,
                )
            assert exc.value.code == "primitive_not_found"
            assert (await _state(db, fine.id)).status == "ai_suggested"
        finally:
            p13.retired_in = None
            await db.commit()

    async def test_duplicate_items_last_verdict_wins(self, db, tenant, user, llm):
        await _seed(db)
        a = await _competence(db, tenant.id, "A")
        await mapping_service.map_competences(db, tenant.id)

        counts = await mapping_service.review_mapping(
            db,
            tenant.id,
            [
                ReviewItem(competence_id=a.id, verdict="accepted"),
                ReviewItem(competence_id=a.id, verdict="rejected"),
            ],
            reviewed_by_id=user.id,
        )

        assert counts == {"accepted": 0, "corrected": 0, "rejected": 1}
        assert (await _state(db, a.id)).status == "rejected"


class TestOrigin:
    """An origin competence (tenant_id IS NULL) is shared by every tenant:
    mapped once, by whichever tenant's run gets to it first, and read-only
    to all of them after that."""

    async def _origin(self, db):
        return await _competence(db, None, f"Origin {uuid.uuid4().hex[:6]}")

    async def _drop(self, db, comp):
        from app.modules.competence.models import CompetenceGroup
        from sqlalchemy import delete

        await db.execute(delete(Competence).where(Competence.id == comp.id))
        await db.execute(
            delete(CompetenceGroup).where(CompetenceGroup.id == comp.group_id)
        )
        await db.commit()

    async def test_force_never_re_maps_a_shared_competence(self, db, tenant, llm):
        await _seed(db)
        origin = await self._origin(db)
        try:
            first = await mapping_service.map_competences(
                db, tenant.id, [origin.id], include_origin=True
            )
            assert first.mapped == 1
            again = await mapping_service.map_competences(
                db, tenant.id, [origin.id], force=True, include_origin=True
            )
            assert (again.kept, again.batches) == (1, 0)
        finally:
            await self._drop(db, origin)

    async def test_review_of_a_shared_competence_is_refused(
        self, db, tenant, user, llm
    ):
        from app.core.errors import AppError

        await _seed(db)
        origin = await self._origin(db)
        try:
            await mapping_service.map_competences(
                db, tenant.id, [origin.id], include_origin=True
            )
            with pytest.raises(AppError) as exc:
                await mapping_service.review_mapping(
                    db,
                    tenant.id,
                    [ReviewItem(competence_id=origin.id, verdict="accepted")],
                    reviewed_by_id=user.id,
                )
            assert exc.value.code == "origin_competence_read_only"
            assert (await _state(db, origin.id)).status == "ai_suggested"
        finally:
            await self._drop(db, origin)

    async def test_ids_alone_do_not_reach_the_shared_library(self, db, tenant, llm):
        """Only coverage may aim a run at a shared row: what the model
        writes there is read by every tenant, so an id in a request body
        must not be enough to have it re-written."""
        await _seed(db)
        origin = await self._origin(db)
        try:
            result = await mapping_service.map_competences(db, tenant.id, [origin.id])
            assert (result.mapped, result.batches) == (0, 0)
            assert (
                await db.execute(
                    select(CompetenceMappingState).where(
                        CompetenceMappingState.competence_id == origin.id
                    )
                )
            ).first() is None
        finally:
            await self._drop(db, origin)

    async def test_a_shared_row_never_shares_a_prompt_with_tenant_text(
        self, db, tenant, llm
    ):
        """One prompt holding both lets a tenant's own competence text steer
        the codes written on a row every other tenant reads."""
        await _seed(db)
        origin = await self._origin(db)
        own = await _competence(db, tenant.id, "Contract review")
        try:
            result = await mapping_service.map_competences(
                db, tenant.id, [origin.id, own.id], include_origin=True
            )
            assert result.mapped == 2
            assert llm.sent_ids() == [{str(own.id)}, {str(origin.id)}]
        finally:
            await self._drop(db, origin)


class TestListMappings:
    async def test_groups_codes_and_flags_stale_rows(self, db, tenant, llm):
        await _seed(db)
        comp = await _competence(db, tenant.id, "A")
        await mapping_service.map_competences(db, tenant.id)

        [entry] = await mapping_service.list_mappings(db, tenant.id)
        assert entry["competence_id"] == comp.id
        assert entry["codes"] == ["P1", "P2"]
        assert entry["status"] == "ai_suggested"
        assert entry["confidence"] == 0.8
        assert entry["stale"] is False
        assert (
            await mapping_service.list_mappings(db, tenant.id, status="reviewed") == []
        )

        comp.title = "A renamed"
        await db.commit()

        [entry] = await mapping_service.list_mappings(db, tenant.id)
        assert entry["stale"] is True

    async def test_rejected_entry_is_listed_with_no_codes(self, db, tenant, user, llm):
        await _seed(db)
        comp = await _competence(db, tenant.id, "A")
        await mapping_service.map_competences(db, tenant.id)
        await mapping_service.review_mapping(
            db,
            tenant.id,
            [ReviewItem(competence_id=comp.id, verdict="rejected")],
            reviewed_by_id=user.id,
        )

        [entry] = await mapping_service.list_mappings(db, tenant.id, status="rejected")
        assert entry["competence_id"] == comp.id
        assert entry["codes"] == []
        assert entry["reviewed_at"] is not None


class TestSurface:
    def test_internal_endpoints_are_hidden_from_public_openapi(self):
        paths = app.openapi()["paths"]
        assert "/api/primitives" in paths
        assert not any(path.startswith("/api/primitives/internal") for path in paths)

    async def test_catalog_and_internal_endpoints(
        self, db, auth_client, tenant, llm, monkeypatch
    ):
        await _seed(db)
        comp = await _competence(db, tenant.id, "A")
        resp = await auth_client.get("/api/primitives")
        assert resp.status_code == 200
        assert len(resp.json()) == 17

        captured: dict = {}

        def fake_enqueue(task, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return type("Result", (), {"id": "task-123"})()

        monkeypatch.setattr("app.modules.primitives.router.enqueue_task", fake_enqueue)
        resp = await auth_client.post(
            "/api/primitives/internal/map", json={"force": True}
        )
        assert resp.status_code == 202
        assert resp.json() == {"task_id": "task-123"}
        assert captured["args"] == (str(tenant.id), None, True)
        assert captured["kwargs"]["module"] == "primitives"

        await mapping_service.map_competences(db, tenant.id)
        resp = await auth_client.get("/api/primitives/internal/mappings")
        assert resp.status_code == 200
        [entry] = resp.json()
        assert entry["competence_id"] == str(comp.id)
        assert entry["codes"] == ["P1", "P2"]

        resp = await auth_client.post(
            "/api/primitives/internal/mappings/review",
            json={"items": [{"competence_id": str(comp.id), "verdict": "accepted"}]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"accepted": 1, "corrected": 0, "rejected": 0}
        resp = await auth_client.get(
            "/api/primitives/internal/mappings", params={"status": "reviewed"}
        )
        assert [e["competence_id"] for e in resp.json()] == [str(comp.id)]

    async def test_map_endpoint_holds_one_slot_and_rations_force(
        self, db, auth_client, tenant, monkeypatch
    ):
        """The endpoint used to be unlocked and un-throttled: every call
        queued another run, and ``force`` re-sent competences the model had
        already been paid to answer for."""
        from app.core.redis import redis_client

        await _seed(db)
        monkeypatch.setattr(
            "app.modules.primitives.router.enqueue_task",
            lambda task, *a, **kw: type("Result", (), {"id": "task-1"})(),
        )

        async def post(body: dict):
            return await auth_client.post("/api/primitives/internal/map", json=body)

        try:
            assert (await post({"force": True})).status_code == 202
            # The slot stays taken until the run frees it.
            second = await post({})
            assert second.status_code == 409
            assert second.json()["detail"] == (
                "A mapping run is already in progress for this tenant"
            )

            await mapping_service.release_mapping_slot(tenant.id)
            # Free again, but the hourly ceiling on ``force`` stands.
            forced = await post({"force": True})
            assert forced.status_code == 429
            # A refused force leaves the slot free for a plain run.
            assert (await post({})).status_code == 202
        finally:
            await mapping_service.release_mapping_slot(tenant.id)
            async with redis_client() as client:
                await client.delete(mapping_service.force_cooldown_key(tenant.id))

    async def test_internal_endpoints_require_admin(self, db, client, tenant):
        await _seed(db)
        headers = {"Authorization": f"Bearer {await _non_admin_token(db, tenant)}"}

        assert (await client.get("/api/primitives", headers=headers)).status_code == 200
        assert (
            await client.get("/api/primitives/internal/mappings", headers=headers)
        ).status_code == 403
        assert (
            await client.post("/api/primitives/internal/map", json={}, headers=headers)
        ).status_code == 403
        assert (
            await client.post(
                "/api/primitives/internal/mappings/review",
                json={
                    "items": [
                        {"competence_id": str(uuid.uuid4()), "verdict": "accepted"}
                    ]
                },
                headers=headers,
            )
        ).status_code == 403


class TestPromptV5:
    def test_rules_are_pinned(self):
        from app.modules.primitives.mapping_service import build_system_prompt

        system = build_system_prompt([])
        for phrase in (
            f"({TOP_LEVEL_TAG}) alone is not enough evidence",
            "party outside the company",
            "a spoken presentation adds no code",
            "escalation by rule",
            "Posting transactions to accounts",
            "system from its documents is P1",
        ):
            assert phrase in system, phrase

    async def test_payload_marks_only_the_competence_top_level(self, db, tenant):
        from app.modules.competence.models import SkillLevel
        from app.modules.primitives.mapping_service import _payloads

        # Two levels of this test's own, with distinct sort indexes: the
        # shared test DB carries global levels from other suites, several
        # of them at sort_index 0, and "top" is decided by sort_index.
        suffix = uuid.uuid4().hex[:6]
        levels = [
            SkillLevel(tenant_id=None, title=f"Low {suffix}", sort_index=900),
            SkillLevel(tenant_id=None, title=f"High {suffix}", sort_index=901),
        ]
        db.add_all(levels)
        await db.flush()
        two = await _competence(db, tenant.id, "Two levels")
        one = await _competence(db, tenant.id, "One level")
        db.add_all(
            [
                Indicator(
                    competence_id=two.id,
                    skill_level_id=levels[0].id,
                    title="checks the file",
                    sort_index=0,
                ),
                Indicator(
                    competence_id=two.id,
                    skill_level_id=levels[1].id,
                    title="signs off the run",
                    sort_index=0,
                ),
                Indicator(
                    competence_id=one.id,
                    skill_level_id=levels[0].id,
                    title="only one level",
                    sort_index=0,
                ),
            ]
        )
        await db.commit()
        payload = {
            p["title"]: p["indicators"]
            for p in await _payloads(db, tenant.id, [two, one])
        }
        assert payload["Two levels"] == [
            f"[{levels[0].title}] checks the file",
            f"[{levels[1].title} ({TOP_LEVEL_TAG})] signs off the run",
        ]
        # A single-level competence keeps its evidence untagged.
        assert payload["One level"] == [f"[{levels[0].title}] only one level"]


class TestReviewInput:
    """The review body is bounded everywhere the batch turns into writes."""

    def test_codes_are_bounded(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ReviewItem(
                competence_id=uuid.uuid4(), verdict="corrected", primitives=["P1"] * 51
            )
        with pytest.raises(ValidationError):
            ReviewItem(
                competence_id=uuid.uuid4(), verdict="corrected", primitives=["P" * 11]
            )
        # The catalog's longest code still fits.
        assert ReviewItem(
            competence_id=uuid.uuid4(), verdict="corrected", primitives=["P11"]
        ).primitives == ["P11"]


class TestTaskFailures:
    """A clipped answer is worth the one retry; a wrong shape is not."""

    def test_incomplete_json_retries(self, monkeypatch):
        from app.modules.primitives import tasks

        def boom(_run):
            raise json.JSONDecodeError("Unterminated string", '{"items": [', 11)

        retried: dict = {}

        def fake_retry(self, exc=None, **kwargs):
            retried["exc"] = exc
            return RuntimeError("retry scheduled")

        # The module attribute is a lazy celery proxy; the generated task
        # class behind it is what carries ``retry``.
        task = tasks.map_competences_task._get_current_object()
        monkeypatch.setattr(tasks, "_run_with_async_session", boom)
        monkeypatch.setattr(type(task), "retry", fake_retry)

        with pytest.raises(RuntimeError, match="retry scheduled"):
            tasks.map_competences_task(str(uuid.uuid4()))
        assert isinstance(retried["exc"], json.JSONDecodeError)

    def test_wrong_shape_does_not_retry(self, monkeypatch):
        from app.modules.primitives import tasks
        from pydantic import ValidationError

        def boom(_run):
            MappedCompetencesSchema.model_validate({"items": [{"nope": 1}]})

        def fake_retry(self, exc=None, **kwargs):
            raise AssertionError("a schema error must not be retried")

        # The module attribute is a lazy celery proxy; the generated task
        # class behind it is what carries ``retry``.
        task = tasks.map_competences_task._get_current_object()
        monkeypatch.setattr(tasks, "_run_with_async_session", boom)
        monkeypatch.setattr(type(task), "retry", fake_retry)

        with pytest.raises(ValidationError):
            tasks.map_competences_task(str(uuid.uuid4()))
