"""HRP-760: a step's SKILL.md - refused where the catalog says no agent
performs the step, generated from the pack skeleton and the company's
own indicators, a failed regeneration never clearing the last working
file. Since W6 the LLM call runs in a Celery task (§5.12): the service
claims the row and the worker writes the file and charges for it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from app.core import billing_hooks
from app.core.errors import AppError
from app.modules.ai import llm_client
from app.modules.ai_workforce import service as agents_service
from app.modules.competence.models import Indicator, SkillLevel
from app.modules.primitives.models import Primitive
from app.modules.work import coverage, service, skills, tasks
from app.modules.work.models import WorkStepSkill
from app.modules.work.schemas import GeneratedSkillSchema
from sqlalchemy import select

from tests.unit.test_coverage_matching import (
    _competence,
    _container,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded

no_mapping_enqueue = _quiet
seeded = _seeded

_ANSWER = GeneratedSkillSchema(
    name="Month-End Close: Bank Reconciliation!",
    description='Use when the "bank" statement of the month is in.',
    body="# Bank reconciliation\n\n## Rules\n1. Match every line.\n",
)


class _Fake:
    def __init__(self, result=_ANSWER):
        self.calls: list[dict] = []
        self.result = result

    async def __call__(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def _skill(db, step_id) -> WorkStepSkill | None:
    return (
        await db.execute(select(WorkStepSkill).where(WorkStepSkill.step_id == step_id))
    ).scalar_one_or_none()


async def _generate(db, tenant, step_id, *, user_id, session_factory, cost=None):
    """The production path in one call: claim the row, then run the task
    the handler would have queued."""
    row = await service.start_step_skill(db, tenant.id, step_id, user_id=user_id)
    assert row.status == "generating"
    await tasks.execute_skill(session_factory, row.id, row.updated_at, cost)
    await db.refresh(row)
    return row


class TestPackChoice:
    @pytest.mark.parametrize(
        ("codes", "expected"),
        [
            ({"P1", "P2"}, "compliance_check"),
            ({"P1"}, "extraction"),
            # No pack holds both: the largest overlap, catalog order on a tie.
            ({"P5", "P9"}, "drafting"),
            ({"P4", "P9", "P10"}, "investigation"),
            (set(), None),
            ({"P13"}, None),
        ],
    )
    async def test_pack_for_step(self, db, seeded, codes, expected):
        packs = await agents_service.list_packs(db, uuid.uuid4())
        pack = skills.pack_for_step(codes, packs)
        assert (pack["code"] if pack else None) == expected

    def test_fallback_by_verdict(self):
        assert skills.fallback_pack_code([Primitive(code="P13", ai_verdict="draft")])
        assert (
            skills.fallback_pack_code([Primitive(code="P13", ai_verdict="draft")])
            == "drafting"
        )
        assert skills.fallback_pack_code([]) == "extraction"

    def test_slug_and_render(self):
        name, text = skills.render(
            "drafting", _ANSWER.name, _ANSWER.description, _ANSWER.body
        )
        assert name == "month-end-close-bank-reconciliation"
        assert text.startswith(
            "---\nname: month-end-close-bank-reconciliation\n"
            'description: "Use when the \\"bank\\" statement of the month is in."\n'
            "pack: drafting\nconstruction: acceptance\n---\n\n# Bank reconciliation"
        )
        assert skills.slugify("!!!") == "step-skill"
        # A non-latin name falls back to the step title, then to a constant.
        assert (
            skills.slugify("Συμφωνία τραπέζης", "Bank reconciliation")
            == "bank-reconciliation"
        )
        assert skills.slugify("Συμφωνία", "Συμφωνία") == "step-skill"
        assert len(skills.slugify("x" * 200)) == skills.NAME_MAX
        # A body that opens on a thematic break is not a frontmatter: with
        # no closing fence nothing is stripped.
        _, text = skills.render("drafting", "x", "d", "---\n\n# Body\n")
        assert text.endswith("---\n\n---\n\n# Body\n")
        # A frontmatter the model added anyway is dropped, ours stays.
        _, text = skills.render(
            "drafting", "x", "d", "---\nname: theirs\n---\n\n# Body\n"
        )
        assert text.count("---\n") == 2
        assert text.endswith("---\n\n# Body\n")


class TestGeneration:
    async def test_refused_where_no_agent_performs_the_step(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        for codes, attrs in (
            (["P6"], {}),
            (["P1", "B1"], {}),
            ([], {"responsibility": "formal"}),
        ):
            step = await _step(db, tenant, c, codes, **attrs)
            with pytest.raises(AppError) as exc:
                await service.start_step_skill(
                    db, tenant.id, step["id"], user_id=user.id
                )
            assert exc.value.code == "work_skill_not_applicable"
            assert await _skill(db, step["id"]) is None

    async def test_generates_from_skeleton_and_company_context(
        self, db, tenant, user, seeded, session_factory
    ):
        c = await _container(
            db,
            tenant,
            user,
            description="Finance closes the books monthly.",
            goal="Close in 5 days",
        )
        step = await _step(
            db,
            tenant,
            c,
            ["P1", "P2"],
            title="Reconcile the bank statement",
            description="Match bank lines to the ledger",
            responsibility="formal",
        )
        comp = await _competence(db, tenant.id, ["P2"])
        level = SkillLevel(tenant_id=tenant.id, title="Basic")
        db.add(level)
        await db.flush()
        db.add_all(
            [
                Indicator(
                    title="Every unmatched line is explained",
                    competence_id=comp.id,
                    skill_level_id=level.id,
                    tenant_id=tenant.id,
                    sort_index=2,
                ),
                Indicator(
                    title="Closes within the deadline",
                    competence_id=comp.id,
                    skill_level_id=level.id,
                    tenant_id=tenant.id,
                    sort_index=1,
                ),
                Indicator(
                    title="Old and inactive",
                    competence_id=comp.id,
                    skill_level_id=level.id,
                    tenant_id=tenant.id,
                    is_active=False,
                ),
            ]
        )
        await db.commit()
        fake = _Fake()
        with patch.object(llm_client, "generate_json", new=fake):
            row = await _generate(
                db, tenant, step["id"], user_id=user.id, session_factory=session_factory
            )
        assert row.status == "ready"
        assert row.skill_name == "month-end-close-bank-reconciliation"
        assert row.content.startswith(
            "---\nname: month-end-close-bank-reconciliation\n"
        )
        assert "pack: compliance_check\nconstruction: pipeline" in row.content
        assert row.prompt_version == skills.PROMPT_VERSION
        assert row.generated_by_id == user.id
        assert row.generated_at is not None
        assert row.llm_model

        call = fake.calls[0]
        assert call["schema"] is GeneratedSkillSchema
        system, prompt = call["system"], call["prompt"]
        # The skeleton of the matched pack, without its own frontmatter.
        assert "## Verification against the reference" in system
        # R7 (2026-09-10): the reference limits what is certified, not noticed.
        assert "## Beyond the reference" in system
        assert "never dropped as out of scope" in system
        assert "name: " not in system.split("Skeleton:")[1].split("\n\n")[1]
        # A formally signed-off step must end with a handover.
        assert "handover to a named role" in system
        # The language directive rides along.
        assert "language" in system.lower()
        assert "Reconcile the bank statement" in prompt
        assert "Match bank lines to the ledger" in prompt
        assert "Finance closes the books monthly." in prompt
        assert "accountability=formal" in prompt
        assert "handover_required=yes" in prompt
        assert "- P1 " in prompt and "- P2 " in prompt
        # Indicators in sort order; inactive ones stay out.
        assert prompt.index("Closes within the deadline") < prompt.index(
            "Every unmatched line is explained"
        )
        assert "Old and inactive" not in prompt

        result = await coverage.compute(db, tenant.id, c.id)
        assert result["steps"][0]["skill_status"] == "ready"

    async def test_no_indicators_says_so(
        self, db, tenant, user, seeded, session_factory
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P13"])
        fake = _Fake()
        with patch.object(llm_client, "generate_json", new=fake):
            row = await _generate(
                db, tenant, step["id"], user_id=user.id, session_factory=session_factory
            )
        assert "no competences mapped" in fake.calls[0]["prompt"]
        assert "handover_required=no" in fake.calls[0]["prompt"]
        # P13 fits no pack: the acceptance construction is the fallback.
        assert "pack: drafting\nconstruction: acceptance" in row.content

    async def test_failed_regeneration_keeps_the_last_skill(
        self, db, tenant, user, seeded, session_factory
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        with patch.object(llm_client, "generate_json", new=_Fake()):
            first = await _generate(
                db, tenant, step["id"], user_id=user.id, session_factory=session_factory
            )
        content = first.content
        # The failure lands on the row rather than on the caller: by now
        # the request that asked for it is long gone.
        with patch.object(
            llm_client, "generate_json", new=_Fake(RuntimeError("provider down"))
        ):
            row = await _generate(
                db, tenant, step["id"], user_id=user.id, session_factory=session_factory
            )
        assert row.status == "failed"
        # The provider's own message is logged, not written on a row every
        # reader of the step sees: it can quote the prompt or a response
        # body from whatever the endpoint really points at.
        assert row.error_message == "RuntimeError"
        assert row.content == content
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["steps"][0]["skill_status"] == "failed"

    async def test_generation_in_progress_is_409_until_stale(
        self, db, tenant, user, seeded, session_factory
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        db.add(
            WorkStepSkill(
                tenant_id=tenant.id,
                step_id=step["id"],
                status="generating",
                catalog_version="v1.1",
            )
        )
        await db.commit()
        with pytest.raises(AppError) as exc:
            await service.start_step_skill(db, tenant.id, step["id"], user_id=user.id)
        assert exc.value.code == "work_skill_generating"
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["steps"][0]["skill_status"] == "generating"
        row = await _skill(db, step["id"])
        row.updated_at = (
            datetime.now(UTC) - service.SKILL_GENERATING_TIMEOUT - timedelta(seconds=1)
        )
        await db.commit()
        # Past the timeout the row stops blocking the button too, not only
        # the service: a request abandoned mid-flight must be retryable.
        result = await coverage.compute(db, tenant.id, c.id)
        assert result["steps"][0]["skill_status"] == "failed"
        with patch.object(llm_client, "generate_json", new=_Fake()):
            row = await _generate(
                db, tenant, step["id"], user_id=user.id, session_factory=session_factory
            )
        assert row.status == "ready"

    async def test_a_stale_claim_reads_failed_from_the_dialog_too(
        self, db, tenant, user, seeded
    ):
        """The dialog reads the row through ``get_step_skill``; a claim past
        the timeout must not read ``generating`` there while the tab already
        says failed, or the dialog waits on a run that is dead."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        db.add(
            WorkStepSkill(
                tenant_id=tenant.id,
                step_id=step["id"],
                status="generating",
                catalog_version="v1.1",
            )
        )
        await db.commit()
        row = await service.get_step_skill(db, tenant.id, step["id"])
        assert row.status == "generating"
        row.updated_at = (
            datetime.now(UTC) - service.SKILL_GENERATING_TIMEOUT - timedelta(seconds=1)
        )
        await db.commit()
        row = await service.get_step_skill(db, tenant.id, step["id"])
        assert row.status == "failed"
        # Reported, not written: a GET leaves the row to the worker that
        # still owns it - the stored status is the claim it was given.
        assert (await _skill(db, step["id"])).status == "generating"

    async def test_first_insert_race_is_409(
        self, db, tenant, user, seeded, session_factory
    ):
        """Two first-time generations at once (a double click): one claims
        the step, the other is told it is already running - never a 500,
        and never two rows the second of which pays a second time."""
        import asyncio

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        tenant_id, step_id, user_id = tenant.id, step["id"], user.id

        async def _claim():
            async with session_factory() as other:
                try:
                    row = await service.start_step_skill(
                        other, tenant_id, step_id, user_id=user_id
                    )
                    return row.status
                except AppError as exc:
                    return exc

        first, second = await asyncio.gather(_claim(), _claim())
        claimed = [r for r in (first, second) if r == "generating"]
        refused = [r for r in (first, second) if isinstance(r, AppError)]
        assert len(claimed) == 1 and len(refused) == 1
        assert refused[0].code == "work_skill_generating"
        assert refused[0].status_code == 409
        # One claim, one row: the loser wrote nothing.
        rows = await db.execute(
            select(WorkStepSkill).where(WorkStepSkill.step_id == step_id)
        )
        assert len(rows.scalars().all()) == 1

    async def test_routes(self, db, tenant, user, seeded, auth_client, session_factory):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        res = await auth_client.get(f"/api/work/steps/{step['id']}/skill")
        assert res.status_code == 404
        res = await auth_client.get(f"/api/work/steps/{step['id']}/skill/download")
        assert res.status_code == 404
        # Queued, not generated: the row comes back generating and the
        # screen polls the GET until the worker has written the file.
        with patch("app.core.task_enqueue.enqueue_task") as enqueue:
            res = await auth_client.post(f"/api/work/steps/{step['id']}/skill")
        assert res.status_code == 202, res.text
        assert res.json()["status"] == "generating"
        assert enqueue.call_count == 1
        row = await _skill(db, step["id"])
        with patch.object(llm_client, "generate_json", new=_Fake()):
            await tasks.execute_skill(session_factory, row.id, row.updated_at)
        # The worker wrote through its own session; this one still holds the
        # row it read before. A real request opens a fresh session.
        await db.refresh(row)
        res = await auth_client.get(f"/api/work/steps/{step['id']}/skill")
        assert res.json()["content"].startswith("---\nname: ")
        res = await auth_client.get(f"/api/work/steps/{step['id']}/skill/download")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/markdown")
        assert res.headers["content-disposition"] == 'attachment; filename="SKILL.md"'
        assert res.text.startswith("---\nname: ")
        res = await auth_client.post(f"/api/work/steps/{uuid.uuid4()}/skill")
        assert res.status_code == 404

    async def test_archived_container_refuses(self, db, tenant, user, seeded):
        from app.modules.work.schemas import ContainerUpdate

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        await service.update_container(
            db, tenant.id, c.id, ContainerUpdate(status="archived")
        )
        with pytest.raises(AppError) as exc:
            await service.start_step_skill(db, tenant.id, step["id"], user_id=user.id)
        assert exc.value.code == "work_container_archived"


class TestWorkerBilling:
    """§9: the task charges, and only for a file it actually delivered."""

    async def test_charged_once_inside_the_task(
        self, db, tenant, user, seeded, session_factory
    ):
        charged: list[tuple[str, float | None]] = []

        async def _consume(_db, _tenant, _user, action, *, amount_override=None):
            charged.append((action, amount_override))

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        with (
            patch.object(llm_client, "generate_json", new=_Fake()),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            row = await _generate(
                db,
                tenant,
                step["id"],
                user_id=user.id,
                session_factory=session_factory,
                cost=7.0,
            )
        assert row.status == "ready"
        assert charged == [("work_skill.generate", 7.0)]

    async def test_a_failed_call_is_not_charged(
        self, db, tenant, user, seeded, session_factory
    ):
        charged: list[str] = []

        async def _consume(_db, _tenant, _user, action, **_kwargs):
            charged.append(action)

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        with (
            patch.object(llm_client, "generate_json", new=_Fake(RuntimeError("down"))),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            row = await _generate(
                db, tenant, step["id"], user_id=user.id, session_factory=session_factory
            )
        assert row.status == "failed"
        assert charged == []

    async def test_a_failure_that_lost_the_row_leaves_the_newer_run_alone(
        self, db, tenant, user, seeded, session_factory
    ):
        """A call that finally raises after its row went stale and was
        re-claimed must not mark the newer run failed - that run's file
        would then be thrown away and the user told it failed."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        row = await service.start_step_skill(db, tenant.id, step["id"], user_id=user.id)
        stale_stamp = row.updated_at
        row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        await db.commit()
        with patch.object(llm_client, "generate_json", new=_Fake(RuntimeError("x"))):
            result = await tasks.execute_skill(session_factory, row.id, stale_stamp)
        assert result["status"] == "superseded"
        await db.refresh(row)
        assert row.status == "generating"
        assert row.error_message is None

    async def test_an_answer_that_lost_the_row_is_dropped_unbilled(
        self, db, tenant, user, seeded, session_factory
    ):
        """A run read as stale and restarted holds the same row: the older
        answer must not overwrite the newer claim, nor be charged."""
        charged: list[str] = []

        async def _consume(_db, _tenant, _user, action, **_kwargs):
            charged.append(action)

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        row = await service.start_step_skill(db, tenant.id, step["id"], user_id=user.id)
        stale_stamp = row.updated_at
        # Somebody else re-claimed it: the stamp moves.
        row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        await db.commit()
        with (
            patch.object(llm_client, "generate_json", new=_Fake()),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_skill(session_factory, row.id, stale_stamp)
        assert result["status"] == "superseded"
        assert charged == []
        await db.refresh(row)
        assert row.status == "generating"
        assert row.content is None

    async def test_a_superseded_answer_leaves_the_hold_alone(
        self, db, tenant, user, seeded, session_factory
    ):
        """The hold is filed against the skill row, and a re-claim reuses
        that row: releasing it here would free the *newer* run's hold and
        let the tenant queue one generation past its balance."""
        released: list[uuid.UUID] = []

        async def _release(_db, _tenant, *, entity_type, entity_id, action):
            released.append(entity_id)

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        row = await service.start_step_skill(db, tenant.id, step["id"], user_id=user.id)
        stale_stamp = row.updated_at
        row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        await db.commit()
        with (
            patch.object(llm_client, "generate_json", new=_Fake()),
            patch.object(billing_hooks, "release_action", side_effect=_release),
        ):
            result = await tasks.execute_skill(session_factory, row.id, stale_stamp)
        assert result["status"] == "superseded"
        assert released == []

    async def test_a_step_that_stopped_being_automatable_never_reaches_the_model(
        self, db, tenant, user, seeded, session_factory
    ):
        """The step was edited while the task queued: the service would now
        refuse to start it, so the worker must not pay for it either."""
        call = _Fake()
        charged: list[str] = []

        async def _consume(_db, _tenant, _user, action, **_kwargs):
            charged.append(action)

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        row = await service.start_step_skill(db, tenant.id, step["id"], user_id=user.id)
        # The company took the capability off the step while the task was
        # in the queue; the catalog now says no agent performs it.
        await service.set_step_primitives(db, tenant.id, step["id"], ["B1"])
        with (
            patch.object(llm_client, "generate_json", new=call),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_skill(session_factory, row.id, row.updated_at)
        assert result["status"] == "failed"
        assert call.calls == []
        assert charged == []
        await db.refresh(row)
        assert row.status == "failed"
        assert row.content is None

    async def test_a_refused_hold_says_so_on_the_row(
        self, db, tenant, user, seeded, auth_client
    ):
        """402 on the way out: the row must carry the reason the response
        carries, or the dialog reports a generic failure for a balance the
        user could top up."""
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])

        async def _refuse(*_args, **_kwargs):
            raise AppError("credits_limit_reached", 402)

        with patch.object(billing_hooks, "reserve_action", side_effect=_refuse):
            res = await auth_client.post(f"/api/work/steps/{step['id']}/skill")
        assert res.status_code == 402
        row = await _skill(db, step["id"])
        assert row.status == "failed"
        assert row.error_message == AppError("credits_limit_reached", 402).detail
