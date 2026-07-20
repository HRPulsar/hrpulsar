"""HRP-51: AI-generated learning materials per skill level."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from app.modules.company.models import Division
from app.modules.competence import ai_materials
from app.modules.competence.ai_materials import (
    GeneratedMaterialItem,
    build_materials_prompt,
)
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    SkillLevel,
)
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from app.modules.position.models import Position
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class TestBuildMaterialsPrompt:
    def test_includes_levels_and_indicators(self) -> None:
        system, user = build_materials_prompt(
            competence_title="Code review",
            competence_type=None,
            competence_description="Reviews diffs.",
            group_title="Engineering",
            indicators_by_level={
                "Basic": ["Reads diff carefully"],
                "Advanced": ["Coaches reviewers"],
            },
            specializations=["Backend Engineer"],
            divisions=[],
            sibling_competences=[],
            company_description=None,
            skill_levels=["Basic", "Advanced"],
            count_per_level=3,
            refinement=None,
        )
        assert "Code review" in system
        assert "AT LEAST 3" not in system  # this prompt uses a different wording
        assert "at least 3" in system
        assert "Code review" in user
        assert "Engineering" in user
        assert "Reads diff carefully" in user
        assert "Backend Engineer" in user

    def test_refinement_appended(self) -> None:
        _, user = build_materials_prompt(
            competence_title="Code review",
            competence_type=None,
            competence_description=None,
            group_title=None,
            indicators_by_level={"Basic": []},
            specializations=[],
            divisions=[],
            sibling_competences=[],
            company_description=None,
            skill_levels=["Basic"],
            count_per_level=2,
            refinement="Prefer free resources.",
        )
        assert "Prefer free resources." in user
        # No specialization block when the input list is empty.
        assert "specializations" not in user
        # New optional context blocks must stay out when their lists are empty.
        assert "divisions" not in user
        assert "sibling_competences" not in user
        assert '"company"' not in user

    def test_optional_blocks_are_included_when_provided(self) -> None:
        # HRP-51 review: every new block (divisions / sibling competences /
        # company description / competence type) must reach the prompt when
        # the operator opts into it.
        _, user = build_materials_prompt(
            competence_title="Code review",
            competence_type="soft_skill",
            competence_description="Reviews diffs.",
            group_title="Engineering",
            indicators_by_level={"Basic": ["Reads diff"]},
            specializations=["Backend Engineer"],
            divisions=["Platform"],
            sibling_competences=["Pair programming"],
            company_description="A B2B SaaS focused on HR talent management.",
            skill_levels=["Basic"],
            count_per_level=3,
            refinement=None,
        )
        assert "Platform" in user
        assert "Pair programming" in user
        assert "soft_skill" in user
        assert "A B2B SaaS focused on HR talent management." in user

    def test_skips_decorative_empty_indicator_levels(self) -> None:
        # An operator who deselected every indicator on a level should not
        # leak an empty list into the prompt — the prompt should look as if
        # the level had no indicators at all.
        _, user = build_materials_prompt(
            competence_title="Code review",
            competence_type=None,
            competence_description=None,
            group_title=None,
            indicators_by_level={"Basic": ["x"], "Advanced": []},
            specializations=[],
            divisions=[],
            sibling_competences=[],
            company_description=None,
            skill_levels=["Basic", "Advanced"],
            count_per_level=3,
            refinement=None,
        )
        assert '"Basic"' in user
        # Advanced is empty → must not show up under indicators_by_level.
        # The level itself still ships in `skill_levels` so the LLM knows
        # to generate Advanced materials.
        assert '"Advanced": []' not in user


# ---------------------------------------------------------------------------
# generate_materials end-to-end (LLM stubbed)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tenant_competence(db: AsyncSession, tenant) -> Competence:
    group = CompetenceGroup(
        title="Engineering", tenant_id=tenant.id, sort_index=0, is_active=True
    )
    db.add(group)
    await db.flush()
    comp = Competence(
        title="Code review",
        description="Reviews diffs constructively.",
        tenant_id=tenant.id,
        group_id=group.id,
        is_active=True,
    )
    db.add(comp)
    await db.commit()
    await db.refresh(comp)
    return comp


@pytest_asyncio.fixture
async def basic_level(db: AsyncSession) -> SkillLevel:
    level = SkillLevel(
        title="Basic", sort_index=0, i18n_key="basic", tenant_id=None
    )
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


@pytest_asyncio.fixture
async def advanced_level(db: AsyncSession) -> SkillLevel:
    level = SkillLevel(
        title="Advanced", sort_index=2, i18n_key="advanced", tenant_id=None
    )
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return level


class TestGenerateMaterials:
    async def test_returns_items_and_filters_unknown_levels(
        self,
        monkeypatch,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
        advanced_level,
    ) -> None:
        # Add one indicator so the prompt carries something for the basic
        # level — the worker fetches it from the DB by competence + level.
        db.add(
            Indicator(
                title="Reads diff carefully",
                competence_id=tenant_competence.id,
                skill_level_id=basic_level.id,
                tenant_id=tenant.id,
                is_active=True,
            )
        )
        await db.commit()

        fake_payload = {
            "materials": [
                {
                    "title": "Effective Code Review (book)",
                    "format": "PDF book",
                    "link": None,
                    "study_time": 8,
                    "comment": "Maps onto the basic 'reads diff' indicator.",
                    "material_type": "book",
                    "skill_level": "Basic",
                },
                {
                    "title": "Architecting Reviewable Diffs",
                    "format": "Online course",
                    "link": "https://example.com/course",
                    "study_time": 12,
                    "comment": "Targets advanced reviewers.",
                    "material_type": "course",
                    "skill_level": "Advanced",
                },
                # Drifted level — must be dropped by the filter.
                {
                    "title": "Beginner intro",
                    "format": None,
                    "link": None,
                    "study_time": None,
                    "comment": None,
                    "material_type": "article",
                    "skill_level": "Beginner",
                },
            ]
        }
        monkeypatch.setattr(
            ai_materials.llm_client,
            "generate_json",
            AsyncMock(return_value=fake_payload),
        )

        items = await ai_materials.generate_materials(
            db,
            tenant_id=tenant.id,
            competence_id=tenant_competence.id,
            skill_level_ids=[basic_level.id, advanced_level.id],
            specialization_ids=None,
            refinement=None,
        )
        titles = [i.title for i in items]
        assert "Effective Code Review (book)" in titles
        assert "Architecting Reviewable Diffs" in titles
        assert "Beginner intro" not in titles  # drifted skill_level filtered

    async def test_raises_when_competence_missing(
        self,
        monkeypatch,
        db: AsyncSession,
        tenant,
        basic_level,
    ) -> None:
        monkeypatch.setattr(
            ai_materials.llm_client,
            "generate_json",
            AsyncMock(return_value={"materials": []}),
        )
        with pytest.raises(ValueError):
            await ai_materials.generate_materials(
                db,
                tenant_id=tenant.id,
                competence_id=uuid.uuid4(),
                skill_level_ids=[basic_level.id],
                specialization_ids=None,
                refinement=None,
            )

    async def test_resolves_linked_specializations_when_ids_omitted(
        self,
        monkeypatch,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
    ) -> None:
        # Link the competence to a specialization through the matrix so the
        # auto-resolution branch has something to find.
        spec = DictionaryItem(
            type="specialization",
            title="Backend Engineer",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(spec)
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
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        db.add(gs)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=tenant_competence.id,
                skill_level_id=basic_level.id,
            )
        )
        await db.commit()

        captured: dict[str, object] = {}

        async def fake_generate_json(*args, **kwargs):
            captured["user_prompt"] = args[0] if args else kwargs.get("prompt")
            return {"materials": []}

        monkeypatch.setattr(
            ai_materials.llm_client,
            "generate_json",
            fake_generate_json,
        )

        await ai_materials.generate_materials(
            db,
            tenant_id=tenant.id,
            competence_id=tenant_competence.id,
            skill_level_ids=[basic_level.id],
            specialization_ids=None,
            refinement=None,
        )
        assert isinstance(captured["user_prompt"], str)
        assert "Backend Engineer" in captured["user_prompt"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Router endpoints (preview + bulk save)
# ---------------------------------------------------------------------------


class TestAiGenerateMaterialsEndpoint:
    async def test_endpoint_returns_preview_list(
        self,
        monkeypatch,
        auth_client,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
    ) -> None:
        async def fake_generate(*args, **kwargs):
            return [
                GeneratedMaterialItem(
                    title="Effective Code Review",
                    format=None,
                    link=None,
                    study_time=5,
                    comment="Pairs to basic indicators",
                    material_type="book",
                    skill_level="Basic",
                ),
            ]

        monkeypatch.setattr(ai_materials, "generate_materials", fake_generate)

        resp = await auth_client.post(
            f"/api/competences/{tenant_competence.id}/ai-generate-materials",
            json={"skill_level_ids": [str(basic_level.id)]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, list)
        assert body[0]["title"] == "Effective Code Review"


class TestBulkCreateMaterialsEndpoint:
    async def test_bulk_creates_each_row(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
        advanced_level,
    ) -> None:
        resp = await auth_client.post(
            f"/api/competences/{tenant_competence.id}/materials/bulk",
            json={
                "materials": [
                    {
                        "title": "Material A",
                        "skill_level_id": str(basic_level.id),
                        "material_type": "book",
                    },
                    {
                        "title": "Material B",
                        "skill_level_id": str(advanced_level.id),
                        "material_type": "course",
                    },
                ]
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert {row["title"] for row in body} == {"Material A", "Material B"}
        assert all(row["competence_id"] == str(tenant_competence.id) for row in body)

    async def test_bulk_refuses_competence_from_other_tenant(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        basic_level,
    ) -> None:
        """HRP-51 review: cross-tenant write must be blocked."""
        from app.modules.company.models import Tenant as TenantModel

        other = TenantModel(name="Other Tenant", slug="other-co")
        db.add(other)
        await db.flush()
        other_group = CompetenceGroup(
            title="Other Engineering",
            tenant_id=other.id,
            sort_index=0,
            is_active=True,
        )
        db.add(other_group)
        await db.flush()
        other_comp = Competence(
            title="Other competence",
            tenant_id=other.id,
            group_id=other_group.id,
            is_active=True,
        )
        db.add(other_comp)
        await db.commit()

        resp = await auth_client.post(
            f"/api/competences/{other_comp.id}/materials/bulk",
            json={
                "materials": [
                    {
                        "title": "Material A",
                        "skill_level_id": str(basic_level.id),
                        "material_type": "book",
                    }
                ]
            },
        )
        assert resp.status_code == 404, resp.text

    async def test_bulk_refuses_skill_level_from_other_tenant(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        tenant_competence,
    ) -> None:
        from app.modules.company.models import Tenant as TenantModel

        other = TenantModel(name="Other Tenant 2", slug="other-co-2")
        db.add(other)
        await db.flush()
        other_level = SkillLevel(
            title="Custom",
            sort_index=0,
            i18n_key="custom",
            tenant_id=other.id,
        )
        db.add(other_level)
        await db.commit()

        resp = await auth_client.post(
            f"/api/competences/{tenant_competence.id}/materials/bulk",
            json={
                "materials": [
                    {
                        "title": "Material X",
                        "skill_level_id": str(other_level.id),
                        "material_type": "book",
                    }
                ]
            },
        )
        assert resp.status_code == 404, resp.text


class TestGenerateMaterialsDriftHandling:
    async def test_per_item_validation_drops_bad_material_type(
        self,
        monkeypatch,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
    ) -> None:
        """HRP-51 review: an LLM emitting an unsupported material_type
        must NOT crash the whole batch — drop the row, keep the rest."""

        async def fake_generate_json(prompt, system=None, **kwargs):
            return {
                "materials": [
                    {
                        "title": "Good item",
                        "material_type": "book",
                        "skill_level": "Basic",
                    },
                    {
                        "title": "Bad type",
                        # 'tutorial' is not in the Literal — must be skipped.
                        "material_type": "tutorial",
                        "skill_level": "Basic",
                    },
                ]
            }

        monkeypatch.setattr(
            ai_materials.llm_client,
            "generate_json",
            fake_generate_json,
        )

        items = await ai_materials.generate_materials(
            db,
            tenant_id=tenant.id,
            competence_id=tenant_competence.id,
            skill_level_ids=[basic_level.id],
            specialization_ids=None,
            refinement=None,
        )
        titles = [it.title for it in items]
        assert "Good item" in titles
        assert "Bad type" not in titles


# ---------------------------------------------------------------------------
# HRP-51 review: extended context options endpoint
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def linked_spec_division(
    db: AsyncSession, tenant, tenant_competence, basic_level
):
    """Wires the test competence up to a Specialization + Division through
    the matrix + a Position. Returns (spec, division)."""
    spec = DictionaryItem(
        type="specialization",
        title="Backend Engineer",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(spec)
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
        specialization_id=spec.id,
        grade_id=grade.id,
    )
    db.add(gs)
    await db.flush()
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=tenant_competence.id,
            skill_level_id=basic_level.id,
        )
    )
    division = Division(name="Platform", tenant_id=tenant.id)
    db.add(division)
    await db.flush()
    db.add(
        Position(
            title="Senior Backend Engineer",
            tenant_id=tenant.id,
            specialization_id=spec.id,
            grade_id=grade.id,
            division_id=division.id,
            is_active=True,
        )
    )
    await db.commit()
    return spec, division


class TestListMaterialsContextOptions:
    async def test_returns_full_competence_with_indicators_and_linked_flags(
        self,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
        linked_spec_division,
    ) -> None:
        spec, division = linked_spec_division
        # Add an unrelated specialization + division to verify the linked
        # flag actually distinguishes connected rows from the rest.
        unrelated_spec = DictionaryItem(
            type="specialization",
            title="Designer",
            tenant_id=tenant.id,
            sort_index=1,
            is_active=True,
        )
        unrelated_div = Division(name="Sales", tenant_id=tenant.id)
        db.add_all([unrelated_spec, unrelated_div])
        # And an active indicator on the competence so the endpoint surfaces
        # it under indicators[].
        ind = Indicator(
            title="Reads diff carefully",
            competence_id=tenant_competence.id,
            skill_level_id=basic_level.id,
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add(ind)
        await db.commit()

        opts = await ai_materials.list_materials_context_options(
            db, tenant_id=tenant.id, competence_id=tenant_competence.id
        )

        assert opts.competence.title == "Code review"
        assert any(i.title == "Reads diff carefully" for i in opts.indicators)

        spec_map = {s.title: s for s in opts.specializations}
        assert spec_map[spec.title].is_linked is True
        assert spec_map[unrelated_spec.title].is_linked is False

        div_map = {d.title: d for d in opts.divisions}
        assert div_map[division.name].is_linked is True
        assert div_map[unrelated_div.name].is_linked is False

    async def test_sibling_competences_excludes_self(
        self,
        db: AsyncSession,
        tenant,
        tenant_competence,
    ) -> None:
        # Drop a second competence into the same group.
        sibling = Competence(
            title="Sibling competence",
            tenant_id=tenant.id,
            group_id=tenant_competence.group_id,
            is_active=True,
        )
        db.add(sibling)
        await db.commit()

        opts = await ai_materials.list_materials_context_options(
            db, tenant_id=tenant.id, competence_id=tenant_competence.id
        )
        titles = {s.title for s in opts.sibling_competences}
        assert "Sibling competence" in titles
        assert tenant_competence.title not in titles

    async def test_raises_when_competence_missing(
        self,
        db: AsyncSession,
        tenant,
    ) -> None:
        with pytest.raises(ValueError):
            await ai_materials.list_materials_context_options(
                db, tenant_id=tenant.id, competence_id=uuid.uuid4()
            )


class TestGenerateMaterialsExtendedContext:
    async def test_indicator_filter_drops_unticked_indicators(
        self,
        monkeypatch,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
    ) -> None:
        keep = Indicator(
            title="Reads diff carefully",
            competence_id=tenant_competence.id,
            skill_level_id=basic_level.id,
            tenant_id=tenant.id,
            is_active=True,
        )
        drop = Indicator(
            title="Ignored indicator",
            competence_id=tenant_competence.id,
            skill_level_id=basic_level.id,
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add_all([keep, drop])
        await db.commit()
        await db.refresh(keep)
        await db.refresh(drop)

        captured: dict[str, object] = {}

        async def fake_generate_json(*args, **kwargs):
            captured["user_prompt"] = args[0] if args else kwargs.get("prompt")
            return {"materials": []}

        monkeypatch.setattr(
            ai_materials.llm_client, "generate_json", fake_generate_json
        )

        await ai_materials.generate_materials(
            db,
            tenant_id=tenant.id,
            competence_id=tenant_competence.id,
            skill_level_ids=[basic_level.id],
            specialization_ids=[],
            indicator_ids=[keep.id],
            refinement=None,
        )
        prompt = captured["user_prompt"]
        assert isinstance(prompt, str)
        assert "Reads diff carefully" in prompt
        assert "Ignored indicator" not in prompt

    async def test_empty_specialization_list_means_no_spec_context(
        self,
        monkeypatch,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
        linked_spec_division,
    ) -> None:
        """An empty list (vs. None) tells the worker the operator deselected
        every spec — the auto-resolution branch must NOT run."""
        captured: dict[str, object] = {}

        async def fake_generate_json(*args, **kwargs):
            captured["user_prompt"] = args[0] if args else kwargs.get("prompt")
            return {"materials": []}

        monkeypatch.setattr(
            ai_materials.llm_client, "generate_json", fake_generate_json
        )

        await ai_materials.generate_materials(
            db,
            tenant_id=tenant.id,
            competence_id=tenant_competence.id,
            skill_level_ids=[basic_level.id],
            specialization_ids=[],
            refinement=None,
        )
        prompt = captured["user_prompt"]
        assert isinstance(prompt, str)
        # The linked spec from the fixture must NOT leak into the prompt.
        assert "Backend Engineer" not in prompt

    async def test_division_and_sibling_blocks_reach_prompt(
        self,
        monkeypatch,
        db: AsyncSession,
        tenant,
        tenant_competence,
        basic_level,
    ) -> None:
        div = Division(name="Platform", tenant_id=tenant.id)
        sibling = Competence(
            title="Pair programming",
            tenant_id=tenant.id,
            group_id=tenant_competence.group_id,
            is_active=True,
        )
        db.add_all([div, sibling])
        await db.commit()
        await db.refresh(div)
        await db.refresh(sibling)

        captured: dict[str, object] = {}

        async def fake_generate_json(*args, **kwargs):
            captured["user_prompt"] = args[0] if args else kwargs.get("prompt")
            return {"materials": []}

        monkeypatch.setattr(
            ai_materials.llm_client, "generate_json", fake_generate_json
        )

        await ai_materials.generate_materials(
            db,
            tenant_id=tenant.id,
            competence_id=tenant_competence.id,
            skill_level_ids=[basic_level.id],
            specialization_ids=[],
            division_ids=[div.id],
            sibling_competence_ids=[sibling.id],
            include_company_description=False,
            refinement=None,
        )
        prompt = captured["user_prompt"]
        assert isinstance(prompt, str)
        assert "Platform" in prompt
        assert "Pair programming" in prompt


class TestMaterialsContextOptionsEndpoint:
    async def test_endpoint_returns_payload(
        self,
        auth_client,
        db: AsyncSession,
        tenant,
        tenant_competence,
    ) -> None:
        resp = await auth_client.get(
            f"/api/competences/{tenant_competence.id}/ai-generate-materials/context-options",
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["competence"]["title"] == "Code review"
        # Every payload key must exist even when empty so the frontend
        # doesn't need to defensively probe for `undefined`.
        for key in (
            "indicators",
            "specializations",
            "divisions",
            "sibling_competences",
            "company_description",
        ):
            assert key in body
