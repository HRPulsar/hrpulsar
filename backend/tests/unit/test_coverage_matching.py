"""HRP-758: coverage matching — the agent layer (step ⊆ pack), the human
cascade (assessed → expected), the automation mode table, weights and the
percentage gate. Pure arithmetic over the breakdown: no LLM anywhere."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.core.security import hash_password
from app.modules.ai_workforce import service as agents_service
from app.modules.ai_workforce.models import AIAgentPack
from app.modules.ai_workforce.schemas import AgentCreate, PrimitiveOverride
from app.modules.assessment.models import (
    Assessment,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import User
from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.position.models import Position
from app.modules.primitives import catalog_data
from app.modules.primitives.mapping_service import source_fingerprint
from app.modules.primitives.models import (
    CompetenceMappingState,
    CompetencePrimitive,
    Primitive,
)
from app.modules.work import coverage, service
from app.modules.work.schemas import ContainerCreate, StepCreate, StepUpdate
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def seeded(db: AsyncSession):
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    await agents_service.seed_packs(db)


@pytest.fixture(autouse=True)
def no_mapping_enqueue():
    """Coverage schedules a competence mapping when it finds unmapped
    competences; the tests that care patch this themselves."""
    with patch.object(coverage, "_schedule_mapping", new=AsyncMock(return_value=False)):
        yield


@pytest.fixture
async def origin_competence(db: AsyncSession):
    """Origin rows (tenant_id IS NULL) are global and this suite has no
    per-test cleanup, so one left behind is mapped and matched in every later
    tenant's run. The links, the state row and any result cascade off the
    competence; the group has to go by hand."""
    made: list[Competence] = []

    async def make(codes, **kwargs) -> Competence:
        comp = await _competence(db, None, codes, **kwargs)
        made.append(comp)
        return comp

    yield make
    for comp in made:
        await db.execute(delete(Competence).where(Competence.id == comp.id))
        await db.execute(
            delete(CompetenceGroup).where(CompetenceGroup.id == comp.group_id)
        )
    await db.commit()


async def _container(db, tenant, user, **overrides):
    data = ContainerCreate(
        **{"type": "process", "title": "Month-end close", **overrides}
    )
    return await service.create_container(db, tenant.id, data, user_id=user.id)


async def _step(db, tenant, container, codes, **attrs):
    return await service.create_step(
        db,
        tenant.id,
        container.id,
        StepCreate(
            title=attrs.pop("title", " ".join(codes) or "sign"),
            primitive_codes=codes,
            **attrs,
        ),
    )


async def _primitive_ids(db, codes) -> dict[str, uuid.UUID]:
    rows = await db.execute(
        select(Primitive.code, Primitive.id).where(Primitive.code.in_(codes))
    )
    return dict(rows.tuples().all())


async def _employee(
    db, tenant, *, last_name="Doe", status="active", position=None
) -> Employee:
    u = User(
        email=f"e-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Jane",
        last_name=last_name,
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.flush()
    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 1),
        status=status,
        position_id=position.id if position else None,
    )
    db.add(emp)
    await db.commit()
    return emp


async def _competence(
    db, tenant_id, codes, *, applicable_to="both", mapped=True
) -> Competence:
    group = CompetenceGroup(title=f"G {uuid.uuid4().hex[:6]}", tenant_id=tenant_id)
    db.add(group)
    await db.flush()
    comp = Competence(
        title=f"C {uuid.uuid4().hex[:6]}",
        description="d",
        group_id=group.id,
        tenant_id=tenant_id,
        applicable_to=applicable_to,
    )
    db.add(comp)
    await db.flush()
    ids = await _primitive_ids(db, codes)
    db.add_all(
        CompetencePrimitive(
            competence_id=comp.id, primitive_id=ids[c], tenant_id=tenant_id
        )
        for c in codes
    )
    if mapped:
        db.add(
            CompetenceMappingState(
                competence_id=comp.id,
                tenant_id=tenant_id,
                status="manual",
                source_fingerprint=source_fingerprint(comp.title, comp.description),
            )
        )
    await db.commit()
    return comp


async def _ref(db, model, **kw):
    row = (await db.execute(select(model).filter_by(**kw))).scalars().first()
    if row is None:
        extra = {"sequence": 6} if model is AssessmentStatus else {}
        row = model(**kw, title=kw["code"].title(), **extra)
        db.add(row)
        await db.commit()
    return row


async def _done(
    db, tenant, emp, competence, percent, *, days_ago=1, status="done"
) -> Assessment:
    status = await _ref(db, AssessmentStatus, code=status)
    kind = await _ref(db, AssessmentType, code="self")
    a = Assessment(
        tenant_id=tenant.id,
        employee_id=emp.id,
        type_id=kind.id,
        status_id=status.id,
        initiator_id=emp.user_id,
        finished_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(a)
    await db.flush()
    db.add(
        AssessmentResult(
            assessment_id=a.id,
            competence_id=competence.id,
            avg_score=1,
            percent=percent,
        )
    )
    await db.commit()
    return a


async def _position_expecting(
    db, tenant, competence, *, passing_score=None
) -> Position:
    """A position whose grade matrix requires ``competence``."""
    suffix = uuid.uuid4().hex[:6]
    spec = DictionaryItem(
        type="specialization", title=f"Spec {suffix}", tenant_id=tenant.id
    )
    grade = DictionaryItem(type="grade", title=f"Grade {suffix}", tenant_id=tenant.id)
    level = SkillLevel(tenant_id=tenant.id, title=f"L {suffix}")
    db.add_all([spec, grade, level])
    await db.flush()
    gs = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=grade.id,
        specialization_id=spec.id,
        salary_currency="EUR",
        passing_score=passing_score,
    )
    db.add(gs)
    await db.flush()
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=competence.id,
            skill_level_id=level.id,
        )
    )
    pos = Position(
        tenant_id=tenant.id,
        title=f"Pos {suffix}",
        source="manual",
        specialization_id=spec.id,
        grade_id=grade.id,
    )
    db.add(pos)
    await db.commit()
    return pos


async def _pack_id(db, code) -> uuid.UUID:
    return (
        await db.execute(
            select(AIAgentPack.id).where(
                AIAgentPack.code == code, AIAgentPack.tenant_id.is_(None)
            )
        )
    ).scalar_one()


async def _agent(db, tenant, user, pack_code, *, name="Cursor", add=()):
    return await agents_service.create_agent(
        db,
        tenant.id,
        AgentCreate(
            name=name,
            category="code",
            pack_id=await _pack_id(db, pack_code),
            primitives=[PrimitiveOverride(code=c, mode="add") for c in add],
        ),
        user_id=user.id,
    )


async def _row(db, tenant, container, step_id):
    result = await coverage.compute(db, tenant.id, container.id)
    return next(s for s in result["steps"] if s["step_id"] == step_id), result


# --- Modes and scope ---------------------------------------------------------


class TestModes:
    @pytest.mark.parametrize(
        ("codes", "attrs", "mode"),
        [
            (["P1"], {}, "automatable"),
            (["P1", "P2", "P3"], {}, "automatable"),
            (["P1", "P5"], {}, "draft_then_review"),
            (["P13"], {}, "draft_then_review"),
            # Accountability overrides capability - the catalog's main finding.
            (["P1"], {"responsibility": "formal"}, "review_required"),
            (["P1"], {"responsibility": "regulatory"}, "review_required"),
            (["P1"], {"output_type": "external_change"}, "review_required"),
            (["P1", "P5"], {"responsibility": "formal"}, "review_required"),
            # Judgement beats accountability, a boundary code beats both.
            (["P6"], {"responsibility": "formal"}, "blocked_judgment"),
            (["P1", "P7"], {}, "blocked_judgment"),
            (["P1", "B1"], {}, "blocked_physical"),
            (["P6", "B3"], {"responsibility": "regulatory"}, "blocked_physical"),
        ],
    )
    async def test_mode_table(self, db, tenant, user, seeded, codes, attrs, mode):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, codes, **attrs)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["mode"] == mode

    async def test_coverage_reads_accepted_steps_too(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"], responsibility="formal")
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["state"] == "accepted"
        assert row["mode"] == "review_required"

    async def test_accountability_only_step_is_out_of_scope(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, [], responsibility="regulatory")
        row, result = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "out_of_scope"
        assert row["mode"] is None
        assert row["in_scope"] is False
        # Nothing to match against: it is neither an agent nor a gap.
        assert await coverage.gaps(db, tenant.id, c.id) == []

    async def test_a_step_added_without_codes_is_unclassified(
        self, db, tenant, user, seeded
    ):
        """HRP-944: a step typed in with no codes has not been classified -
        not the same as a step that needs no capability."""
        c = await _container(db, tenant, user)
        step = await service.create_step(
            db, tenant.id, c.id, StepCreate(title="Approve the budget")
        )
        row, result = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "unclassified"
        assert row["in_scope"] is False
        assert result["candidate_step_ids"] == []
        assert await coverage.gaps(db, tenant.id, c.id) == []

    async def test_a_writer_that_predates_the_column_leaves_the_step_classified(
        self, db, tenant, user, seeded
    ):
        """Review of HRP-944: the old backend still serving during a deploy,
        or a raw copy, inserts steps without ``classified_at``; the server
        default keeps a model's empty step out of scope, not unclassified."""
        c = await _container(db, tenant, user)
        step_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO work_steps "
                "(id, tenant_id, container_id, position, title, state) "
                "VALUES (:id, :tenant, :container, 1, 'Signature', "
                "'system_suggested')"
            ),
            {"id": step_id, "tenant": tenant.id, "container": c.id},
        )
        await db.commit()
        row, _ = await _row(db, tenant, c, step_id)
        assert row["verdict"] == "out_of_scope"

    async def test_an_empty_picker_save_classifies_the_step(
        self, db, tenant, user, seeded
    ):
        """Saving the picker empty is the company's word: nothing is needed."""
        c = await _container(db, tenant, user)
        step = await service.create_step(
            db, tenant.id, c.id, StepCreate(title="Sign the contract")
        )
        await service.set_step_primitives(db, tenant.id, step["id"], [])
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "out_of_scope"

    async def test_pure_boundary_step_is_out_of_scope_but_blocked_physical(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["B2"])
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "out_of_scope"
        assert row["mode"] == "blocked_physical"
        assert row["in_scope"] is False

    def test_count_toward_coverage_is_the_kind_column(self):
        cognitive = Primitive(code="P1", kind="cognitive")
        boundary = Primitive(code="B1", kind="boundary")
        assert coverage.count_toward_coverage(cognitive)
        assert not coverage.count_toward_coverage(boundary)


# --- Agent layer -------------------------------------------------------------


class TestAgentLayer:
    async def test_empty_tenant_gives_agent_or_gap(self, db, tenant, user, seeded):
        """§5.4: no employees, no competences, no agents - packs alone."""
        c = await _container(db, tenant, user)
        extract = await _step(db, tenant, c, ["P1"])
        judge = await _step(db, tenant, c, ["P6"])
        result = await coverage.compute(db, tenant.id, c.id)
        by_id = {s["step_id"]: s for s in result["steps"]}
        assert by_id[extract["id"]]["verdict"] == "agent"
        assert by_id[extract["id"]]["agent"]["pack_code"] == "extraction"
        assert by_id[extract["id"]]["agent"]["agent_name"] is None
        assert by_id[judge["id"]]["verdict"] == "gap"
        assert by_id[judge["id"]]["agent"] is None

    async def test_step_must_fit_in_one_pack(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        # P1+P5 is drafting; P5+P9 spans drafting and artifact_builder.
        fits = await _step(db, tenant, c, ["P1", "P5"])
        spans = await _step(db, tenant, c, ["P5", "P9"])
        result = await coverage.compute(db, tenant.id, c.id)
        by_id = {s["step_id"]: s for s in result["steps"]}
        assert by_id[fits["id"]]["agent"]["pack_code"] == "drafting"
        assert by_id[spans["id"]]["verdict"] == "gap"

    async def test_registered_agent_is_named(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1", "P2"])
        agent = await _agent(db, tenant, user, "compliance_check", name="Harvey")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["agent"] == {
            "pack_id": agent["pack_id"],
            "pack_code": "compliance_check",
            "pack_manual": False,
            "agent_id": agent["id"],
            "agent_name": "Harvey",
        }

    async def test_agent_overrides_extend_the_match(self, db, tenant, user, seeded):
        """pack ∪ add − remove: an agent with an added code matches a step
        no built-in pack covers."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1", "P4", "P5"])
        await _agent(db, tenant, user, "investigation", name="Sherlock", add=["P5"])
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "agent"
        assert row["agent"]["agent_name"] == "Sherlock"

    async def test_inactive_agent_is_ignored(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        agent = await _agent(db, tenant, user, "extraction", name="Old")
        await agents_service.delete_agent(db, tenant.id, agent["id"], user_id=user.id)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "agent"  # the pack still covers it
        assert row["agent"]["agent_name"] is None

    def test_two_matching_agents_resolve_the_same_way(self):
        """Whatever order the registry comes back in, the step keeps the
        same owner between two refreshes of the tab."""
        agents = [
            {
                "id": uuid.UUID(int=2),
                "name": "Zoe",
                "pack_id": None,
                "pack_code": "extraction",
                "codes": {"P1"},
            },
            {
                "id": uuid.UUID(int=1),
                "name": "Ada",
                "pack_id": None,
                "pack_code": "extraction",
                "codes": {"P1"},
            },
        ]
        assert coverage._match_agent({"P1"}, [], agents)["agent_name"] == "Ada"
        assert (
            coverage._match_agent({"P1"}, [], list(reversed(agents)))["agent_name"]
            == "Ada"
        )

    async def test_a_truncated_agent_registry_is_logged(
        self, db, tenant, user, seeded, caplog
    ):
        """Matching against page one only would show a step as a gap while
        the agent that covers it sits on page two."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, ["P1"])
        await _agent(db, tenant, user, "extraction", name="One")
        await _agent(db, tenant, user, "extraction", name="Two")
        with (
            patch.object(coverage, "AGENT_PAGE", 1),
            caplog.at_level("WARNING", logger=coverage.logger.name),
        ):
            await coverage.compute(db, tenant.id, c.id)
        assert "matching against the first" in caplog.text


# --- Human layer -------------------------------------------------------------


class TestHumanLayer:
    async def test_agent_wins_and_human_rides_as_backup(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        comp = await _competence(db, tenant.id, ["P1"])
        emp = await _employee(db, tenant, last_name="Marin")
        await _done(db, tenant, emp, comp, 90)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "agent"
        assert row["human_backup"] is True
        assert row["human"] == {
            "employee_id": emp.id,
            "name": "Jane Marin",
            "position": None,
            "label": "assessed",
            "missing_codes": [],
            # HRP-871: what the match stands on (test_coverage_match_grounds).
            "passing_score": 75,
            "grounds": [
                {
                    "competence_id": comp.id,
                    "title": comp.title,
                    "state": "assessed",
                    "percent": 90,
                    "codes": ["P1"],
                }
            ],
        }

    async def test_assessed_beats_expected_beats_gap(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        # Nobody: gap.
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "gap"
        assert row["human"] is None
        # The matrix expects it of the position: expected.
        pos = await _position_expecting(db, tenant, comp)
        emp = await _employee(db, tenant, position=pos)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "human"
        assert row["human"]["label"] == "expected"
        assert row["human"]["employee_id"] == emp.id
        # A passed assessment: assessed.
        await _done(db, tenant, emp, comp, 80)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "assessed"

    async def test_origin_competences_count_for_the_tenant(
        self, db, tenant, user, seeded, origin_competence
    ):
        """Grade matrices may name origin competences (tenant_id IS NULL) and
        nothing clones them, so a tenant on the shared library would get an
        empty human layer if coverage read its own rows only."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        origin = await origin_competence(["P6"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, origin, 90)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "human"
        assert row["human"]["label"] == "assessed"

    async def test_threshold_is_the_grade_specialization_passing_score(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        strict = await _position_expecting(db, tenant, comp, passing_score=90)
        emp = await _employee(db, tenant, position=strict)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "expected"
        await _done(db, tenant, emp, comp, 80)
        row, _ = await _row(db, tenant, c, step["id"])
        # 80 < 90: the assessment does not confirm the competence, and a
        # measured failure withdraws what the grade matrix expected.
        assert row["verdict"] == "gap"
        assert row["human"] is None

    async def test_a_failure_withdraws_only_its_own_competence(
        self, db, tenant, user, seeded
    ):
        """Two competences behind one code: failing one must not drop the
        credit the other still gives."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        failed = await _competence(db, tenant.id, ["P6"])
        held = await _competence(db, tenant.id, ["P6"])
        pos = await _position_expecting(db, tenant, failed)
        emp = await _employee(db, tenant, position=pos)
        await _done(db, tenant, emp, failed, 40)
        await _done(db, tenant, emp, held, 95)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "assessed"

    async def test_threshold_falls_back_to_75_without_a_grade(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, comp, 74)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "gap"
        await _done(db, tenant, emp, comp, 75)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "assessed"

    async def test_only_done_assessments_count(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, comp, 95, status="on_review")
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "gap"

    async def test_latest_done_assessment_wins(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, comp, 95, days_ago=30)
        await _done(db, tenant, emp, comp, 40, days_ago=1)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "gap"

    async def test_whole_set_must_sit_with_one_person(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6", "P7"])
        judge = await _competence(db, tenant.id, ["P6"])
        talk = await _competence(db, tenant.id, ["P7"])
        one = await _employee(db, tenant, last_name="One")
        two = await _employee(db, tenant, last_name="Two")
        await _done(db, tenant, one, judge, 90)
        await _done(db, tenant, two, talk, 90)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "gap"
        await _done(db, tenant, two, judge, 90)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["name"] == "Jane Two"

    async def test_mixed_labels_report_expected(self, db, tenant, user, seeded):
        """One code assessed, the other only expected: the person covers the
        step, but the weaker label is what the COO sees."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6", "P7"])
        judge = await _competence(db, tenant.id, ["P6"])
        talk = await _competence(db, tenant.id, ["P7"])
        pos = await _position_expecting(db, tenant, talk)
        emp = await _employee(db, tenant, position=pos)
        await _done(db, tenant, emp, judge, 90)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "human"
        assert row["human"]["label"] == "expected"

    async def test_terminated_employee_and_agent_only_competence_are_ignored(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        gone = await _employee(db, tenant, status="terminated")
        await _done(db, tenant, gone, await _competence(db, tenant.id, ["P6"]), 90)
        here = await _employee(db, tenant)
        bot_only = await _competence(db, tenant.id, ["P6"], applicable_to="agent")
        await _done(db, tenant, here, bot_only, 90)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "gap"

    # --- Assignment (HRP-809) ----------------------------------------------------

    async def test_boundary_code_does_not_sink_the_human_match(
        self, db, tenant, user, seeded
    ):
        """A mixed step is matched on its cognitive codes, like
        ``required_codes`` and an assignee's ``missing_codes``: nobody is
        assessed on a boundary code, and the step must not read as a gap to
        hire for while a colleague holds everything an assessment can."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6", "B1"])
        emp = await _employee(db, tenant)
        comp = await _competence(db, tenant.id, ["P6"])
        await _done(db, tenant, emp, comp, 90)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "human"
        assert row["human"]["employee_id"] == emp.id
        assert row["human"]["label"] == "assessed"
        assert row["required_codes"] == ["P6"]


async def _assign(db, tenant, step, **fields):
    return await service.update_step(db, tenant.id, step["id"], StepUpdate(**fields))


class TestAssignment:
    async def test_assigned_without_skills_closes_the_gap(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6", "P8", "B1"])
        emp = await _employee(db, tenant, last_name="Novak")
        await _assign(db, tenant, step, executor_employee_id=emp.id)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "human"
        assert row["human"] == {
            "employee_id": emp.id,
            "name": "Jane Novak",
            "position": None,
            "label": "assigned",
            # Cognitive codes only: nobody is short of a boundary one.
            "missing_codes": ["P6", "P8"],
        }
        assert row["gap_label"] is None
        assert await coverage.gaps(db, tenant.id, c.id) == []

    async def test_assigned_person_outranks_the_agent(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        emp = await _employee(db, tenant)
        await _assign(db, tenant, step, executor_employee_id=emp.id)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "human"
        assert row["human"]["label"] == "assigned"
        assert row["human_backup"] is False
        # Still on the row: what could take the step.
        assert row["agent"]["pack_code"] == "extraction"
        assert coverage.gap_kind(row) is None
        assert await coverage.gaps(db, tenant.id, c.id) == []

    async def test_assigned_person_with_every_code_misses_nothing(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, await _competence(db, tenant.id, ["P6"]), 90)
        await _assign(db, tenant, step, executor_employee_id=emp.id)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "assigned"
        assert row["human"]["missing_codes"] == []

    async def test_out_of_scope_step_keeps_its_verdict(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, [], responsibility="regulatory")
        emp = await _employee(db, tenant)
        await _assign(db, tenant, step, executor_employee_id=emp.id)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "out_of_scope"
        assert row["human"]["label"] == "assigned"
        assert row["human"]["missing_codes"] == []
        assert row["needs_accountable"] is False

    async def test_terminated_assignee_is_ignored(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"], responsibility="formal")
        emp = await _employee(db, tenant)
        await _assign(
            db,
            tenant,
            step,
            executor_employee_id=emp.id,
            accountable_employee_id=emp.id,
        )
        emp.status = "terminated"
        await db.commit()
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["verdict"] == "gap"
        assert row["human"] is None
        assert row["accountable"] is None
        assert row["needs_accountable"] is True

    async def test_needs_accountable(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        review = await _step(db, tenant, c, ["P1"], responsibility="formal")
        draft = await _step(db, tenant, c, ["P1", "P5"])
        auto = await _step(db, tenant, c, ["P1"])
        judged = await _step(db, tenant, c, ["P6"], responsibility="reputational")
        result = await coverage.compute(db, tenant.id, c.id)
        by_id = {s["step_id"]: s for s in result["steps"]}
        assert by_id[review["id"]]["mode"] == "review_required"
        assert by_id[review["id"]]["needs_accountable"] is True
        assert by_id[draft["id"]]["needs_accountable"] is True
        assert by_id[auto["id"]]["needs_accountable"] is False
        # Blocked for an agent, but somebody still answers for it.
        assert by_id[judged["id"]]["needs_accountable"] is True

        emp = await _employee(db, tenant, last_name="Keller")
        await _assign(db, tenant, review, accountable_employee_id=emp.id)
        row, _ = await _row(db, tenant, c, review["id"])
        assert row["needs_accountable"] is False
        assert row["accountable"] == {
            "employee_id": emp.id,
            "name": "Jane Keller",
            "position": None,
        }
        # Only the accountable is named: the verdict is still computed.
        assert row["verdict"] == "agent"

    async def test_assignment_leaves_shares_and_hours_alone(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        hours = {"hours_per_run": 2, "runs_per_year": 50}
        moves = await _step(db, tenant, c, ["P1"], **hours)
        await _step(db, tenant, c, ["P1", "P5"], **hours)
        gap = await _step(db, tenant, c, ["P6"], **hours)
        await _step(db, tenant, c, ["P6", "P8"], **hours)
        before = await coverage.compute(db, tenant.id, c.id)
        emp = await _employee(db, tenant)
        await _assign(db, tenant, moves, executor_employee_id=emp.id)
        await _assign(db, tenant, gap, executor_employee_id=emp.id)
        after = await coverage.compute(db, tenant.id, c.id)
        assert before["shares"] is not None
        for key in ("shares", "hours", "quality", "candidate_step_ids"):
            assert after[key] == before[key]


# --- Gaps, weights, percentages ----------------------------------------------


class TestGapsAndWeights:
    async def test_gap_label_step_then_heuristic_then_container_default(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user, gap_default_label="hire")
        explicit = await _step(db, tenant, c, ["P6"], gap_label="agency")
        rare = await _step(
            db, tenant, c, ["P6"], responsibility="none", runs_per_year=12
        )
        default = await _step(
            db, tenant, c, ["P6"], responsibility="formal", runs_per_year=12
        )
        gaps = {g["step_id"]: g for g in await coverage.gaps(db, tenant.id, c.id)}
        assert gaps[explicit["id"]]["gap_label"] == "agency"
        assert gaps[rare["id"]]["gap_label"] == "agency"
        assert gaps[default["id"]]["gap_label"] == "hire"
        assert gaps[default["id"]]["required_codes"] == ["P6"]

    async def test_gaps_list_both_kinds_in_order(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        # P1 is covered by a pack but the tenant registered no agent for it
        # and wrote no skill: automatable, not automated (§5.10).
        first = await _step(db, tenant, c, ["P1"])
        second = await _step(db, tenant, c, ["P6", "B1"])
        await _step(db, tenant, c, [])  # out of scope: on neither list
        third = await _step(db, tenant, c, ["P8"])
        gaps = await coverage.gaps(db, tenant.id, c.id)
        assert [g["step_id"] for g in gaps] == [
            first["id"],
            second["id"],
            third["id"],
        ]
        assert [g["kind"] for g in gaps] == [
            "not_automated_yet",
            "no_owner",
            "no_owner",
        ]
        assert gaps[0]["gap_label"] is None
        assert gaps[0]["agent"]["pack_code"]
        assert gaps[0]["skill_status"] == "none"
        # Boundary codes are not what one hires for (§6).
        assert gaps[1]["required_codes"] == ["P6"]

    async def test_shares_are_yearly_hours_of_estimated_steps(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        moves = await _step(db, tenant, c, ["P1"])
        review = await _step(db, tenant, c, ["P1", "P5"])
        stays = await _step(db, tenant, c, ["P6"], hours_per_run=2, runs_per_year=50)
        await _step(db, tenant, c, ["P6"])
        await _step(db, tenant, c, [])  # out of scope: never in the denominator
        result = await coverage.compute(db, tenant.id, c.id)
        assert set(result["candidate_step_ids"]) == {moves["id"], review["id"]}
        # Four steps in scope, but no candidate carries an estimate: lists.
        assert result["shares"] is None
        assert result["hours"] == {
            "total": 100.0,
            "moves": 0.0,
            "to_review": 0.0,
            "stays": 100.0,
            "unestimated": 3,
            # HRP-861: nothing in review, nothing moves - nothing is freed.
            "to_review_after": 0.0,
            "freed": 0.0,
            # HRP-862: no agent of the tenant's own does any of it yet.
            "automated": 0.0,
        }
        await service.update_step(
            db, tenant.id, moves["id"], StepUpdate(hours_per_run=8, runs_per_year=50)
        )
        result = await coverage.compute(db, tenant.id, c.id)
        # moves 400 h, stays 100 h; the two unestimated steps are in no bucket.
        assert result["shares"] == {
            "moves": pytest.approx(80.0),
            "to_review": 0.0,
            "stays": pytest.approx(20.0),
        }
        assert result["hours"]["unestimated"] == 2
        by_id = {s["step_id"]: s for s in result["steps"]}
        assert by_id[moves["id"]]["hours_per_year"] == 400
        assert by_id[stays["id"]]["hours_per_year"] == 100
        assert by_id[review["id"]]["hours_per_year"] is None
        # Half an estimate is no estimate.
        await service.update_step(
            db, tenant.id, review["id"], StepUpdate(hours_per_run=1)
        )
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hours"]["unestimated"] == 2

    async def test_no_percentages_on_a_short_breakdown(self, db, tenant, user, seeded):
        # Decision 2026-08-31, kept: a number on two or three steps is noise.
        c = await _container(db, tenant, user)
        for _ in range(3):
            await _step(db, tenant, c, ["P1"], hours_per_run=1, runs_per_year=10)
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["shares"] is None
        assert result["hours"]["moves"] == 30
        await _step(db, tenant, c, ["P1"], hours_per_run=1, runs_per_year=10)
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["shares"] == {"moves": 100.0, "to_review": 0.0, "stays": 0.0}

    async def test_quality_is_the_weakest_cognitive_capability(
        self, db, tenant, user, seeded
    ):
        # P2 better_than_human, P1/P3 strong, P4 draft, P6 no.
        c = await _container(db, tenant, user)
        best = await _step(db, tenant, c, ["P2"])
        mixed = await _step(db, tenant, c, ["P2", "P1"])
        drafty = await _step(db, tenant, c, ["P2", "P4"])
        judged = await _step(db, tenant, c, ["P1", "P6"])
        # A boundary code does not drag the quality down: it is why the
        # step is out of scope, and the cognitive half is still rated.
        physical = await _step(db, tenant, c, ["P1", "B1"])
        signature = await _step(db, tenant, c, [])
        result = await coverage.compute(db, tenant.id, c.id)
        by_id = {s["step_id"]: s for s in result["steps"]}
        assert by_id[best["id"]]["quality"] == "better_than_human"
        assert by_id[mixed["id"]]["quality"] == "strong"
        assert by_id[drafty["id"]]["quality"] == "draft"
        assert by_id[judged["id"]]["quality"] == "no"
        assert by_id[physical["id"]]["quality"] == "strong"
        assert by_id[signature["id"]]["quality"] is None
        # Counted over the in-scope steps only: the signature is in none.
        assert result["quality"] == {
            "better_than_human": 1,
            "strong": 2,
            "draft": 1,
            "no": 1,
        }

    async def test_a_blocked_step_is_not_listed_as_automatable(
        self, db, tenant, user, seeded
    ):
        """A tenant may add any catalog code to its own agent, including a
        judgement one. Such a step matches an agent but the catalog still
        blocks it, and offering a skill for it would land on a 422."""
        c = await _container(db, tenant, user)
        judged = await _step(db, tenant, c, ["P1", "P6"])
        await _agent(db, tenant, user, "extraction", add=["P6"])
        row, _ = await _row(db, tenant, c, judged["id"])
        assert row["verdict"] == "agent"
        assert row["mode"] == "blocked_judgment"
        assert coverage.gap_kind(row) is None
        assert await coverage.gaps(db, tenant.id, c.id) == []

    async def test_hourly_rate_travels_with_the_coverage(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, ["P1"])
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hourly_rate"] is None
        assert result["hourly_rate_currency"] is None
        tenant.hourly_rate = Decimal("50.00")
        tenant.hourly_rate_currency = "EUR"
        await db.commit()
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["hourly_rate"] == 50.0
        assert result["hourly_rate_currency"] == "EUR"

    async def test_no_candidates_means_lists(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        for _ in range(4):
            await _step(db, tenant, c, ["P6"], hours_per_run=1, runs_per_year=10)
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["candidate_step_ids"] == []
        assert result["shares"] is None
        assert result["hours"]["stays"] == 40

    async def test_empty_container(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["steps"] == []
        assert result["shares"] is None


# --- Mapping trigger (§3.3) --------------------------------------------------


class TestMappingTrigger:
    async def test_unmapped_competence_schedules_mapping(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, ["P1"])
        await _competence(db, tenant.id, ["P1"])  # mapped: not sent
        unmapped = await _competence(db, tenant.id, [], mapped=False)
        with patch.object(
            coverage, "_schedule_mapping", new=AsyncMock(return_value=True)
        ) as schedule:
            result = await coverage.compute(db, tenant.id, c.id, user_id=user.id)
        assert result["mapping_pending"] is True
        schedule.assert_awaited_once_with(tenant.id, [unmapped.id], user.id)

    async def test_referenced_origin_competence_is_sent_too(
        self, db, tenant, user, seeded, origin_competence
    ):
        """Nothing else maps the shared library: if coverage does not send an
        origin competence the grade matrix names, mapping_pending stays false
        and every step reads gap for good. One nobody references is left
        alone - the tenant does not pay to map the whole library."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, ["P1"])
        referenced = await origin_competence([], mapped=False)
        await origin_competence([], mapped=False)  # in the library, unused
        pos = await _position_expecting(db, tenant, referenced)
        await _employee(db, tenant, position=pos)
        with patch.object(
            coverage, "_schedule_mapping", new=AsyncMock(return_value=True)
        ) as schedule:
            result = await coverage.compute(db, tenant.id, c.id, user_id=user.id)
        assert result["mapping_pending"] is True
        schedule.assert_awaited_once_with(tenant.id, [referenced.id], user.id)

    async def test_stale_mapping_is_sent_again(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        comp = await _competence(db, tenant.id, ["P1"])
        comp.title = "Renamed"
        await db.commit()
        with patch.object(
            coverage, "_schedule_mapping", new=AsyncMock(return_value=True)
        ) as schedule:
            result = await coverage.compute(db, tenant.id, c.id)
        assert result["mapping_pending"] is True
        schedule.assert_awaited_once_with(tenant.id, [comp.id], None)

    async def test_nothing_to_map_is_quiet(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        await _competence(db, tenant.id, ["P1"])
        with patch.object(coverage, "_schedule_mapping", new=AsyncMock()) as schedule:
            result = await coverage.compute(db, tenant.id, c.id)
        assert result["mapping_pending"] is False
        schedule.assert_not_awaited()

    async def test_a_reader_does_not_start_a_run(self, db, tenant, user, seeded):
        """HRP-810: a plain reader's coverage is answered from what is
        mapped; only a manager's read pays for a model run."""
        c = await _container(db, tenant, user)
        await _step(db, tenant, c, ["P1"])
        await _competence(db, tenant.id, [], mapped=False)
        with patch.object(coverage, "_schedule_mapping", new=AsyncMock()) as schedule:
            result = await coverage.compute(
                db, tenant.id, c.id, user_id=user.id, schedule_mapping=False
            )
        assert result["mapping_pending"] is False
        schedule.assert_not_awaited()


# --- HTTP ----------------------------------------------------------------------


class TestRoutes:
    async def test_endpoints(self, db, tenant, user, seeded, auth_client):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"], runs_per_year=12)
        res = await auth_client.get(f"/api/work/containers/{c.id}/coverage")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["container_id"] == str(c.id)
        assert body["steps"][0]["verdict"] == "gap"
        assert body["steps"][0]["hours_per_year"] is None
        assert body["shares"] is None
        assert body["hours"]["unestimated"] == 1
        res = await auth_client.get(f"/api/work/containers/{c.id}/gaps")
        assert res.status_code == 200
        assert res.json()[0]["step_id"] == str(step["id"])
        assert res.json()[0]["gap_label"] == "agency"

    async def test_missing_container_is_404(self, seeded, auth_client):
        res = await auth_client.get(f"/api/work/containers/{uuid.uuid4()}/coverage")
        assert res.status_code == 404

