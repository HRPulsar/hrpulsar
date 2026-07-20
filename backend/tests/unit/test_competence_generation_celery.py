"""Phase CR11 — `tasks.execute_session` end-to-end with mocked LLM."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from app.modules.ai import llm_client
from app.modules.ai_competence_generation import service, tasks
from app.modules.ai_competence_generation.schemas import (
    GeneratedTreeSchema,
    SessionCreate,
)
from app.modules.dictionary.models import DictionaryItem
from app.modules.notification.models import Notification
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def session_factory(db: AsyncSession):
    """Build a real `async_sessionmaker` against the test DB.

    We rely on `db` being requested first so the schema is set up. Then we
    create a fresh engine for the worker code paths — `execute_session`
    opens its own `async with session_factory() as session` context.
    """
    from app.config import settings as app_settings

    test_url = app_settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
    engine = create_async_engine(test_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
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


_FAKE_TREE_PAYLOAD = {
    "groups": [
        {
            "title": "Engineering Excellence",
            "description": "Core skills for shipping production code.",
            "children": [],
            "competences": [
                {
                    "title": "API design",
                    "description": "Designing REST APIs.",
                    "type": "hard_skill",
                    "indicators": [
                        {
                            "title": "Knows HTTP semantics",
                            "skill_level": "basic",
                        }
                    ],
                }
            ],
        }
    ]
}


class TestExecuteSession:
    async def test_success_path_persists_payload(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "ready"
        await db.refresh(sess)
        assert sess.status == "ready"
        assert sess.payload is not None
        assert sess.payload["groups"][0]["title"] == "Engineering Excellence"
        # Every node got a temp_id; selection defaults to True.
        gid = sess.payload["groups"][0]["temp_id"]
        cid = sess.payload["groups"][0]["competences"][0]["temp_id"]
        iid = sess.payload["groups"][0]["competences"][0]["indicators"][0]["temp_id"]
        assert sess.selection_state[gid] is True
        assert sess.selection_state[cid] is True
        assert sess.selection_state[iid] is True

    async def test_parse_error_then_success(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        call_count = {"n": 0}

        async def flaky(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise json.JSONDecodeError("bad", "", 0)
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=flaky):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "ready"
        assert call_count["n"] == 2

    async def test_retry_exhausted_marks_error(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        async def always_bad(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            raise json.JSONDecodeError("bad", "", 0)

        with patch.object(llm_client, "generate_json", side_effect=always_bad):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "error"
        await db.refresh(sess)
        assert sess.status == "error"
        assert sess.error_code == "parse_error"

    async def test_cooperative_cancel_before_llm_skips_call(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        # Worker flips status='running' and builds the prompt; user cancels
        # in that window. The pre-LLM refresh must catch it and skip the
        # provider call entirely — no tokens spent, no billing.
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        from app.modules.ai_competence_generation.models import (
            CompetenceGenerationSession,
        )
        from app.modules.ai_settings import service as ai_settings_service

        original_get_or_default = ai_settings_service.get_or_default

        async def cancel_then_settings(db_session, tenant_id):
            # `get_or_default` runs between the status='running' flip and
            # the pre-LLM refresh. Use a fresh DB session to flip status
            # to 'cancelled' the way cancel_session would in production.
            async with session_factory() as cancel_db:
                row = await cancel_db.get(CompetenceGenerationSession, sess.id)
                assert row is not None
                row.status = "cancelled"
                await cancel_db.commit()
            return await original_get_or_default(db_session, tenant_id)

        async def llm_should_not_run(*args, **kwargs):
            raise AssertionError("LLM client called after cancellation")

        with (
            patch.object(
                ai_settings_service,
                "get_or_default",
                side_effect=cancel_then_settings,
            ),
            patch.object(llm_client, "generate_json", side_effect=llm_should_not_run),
        ):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "cancelled"
        await db.refresh(sess)
        assert sess.status == "cancelled"
        assert sess.payload is None

    async def test_unexpected_crash_marks_session_as_error(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        """HRP-33: if anything downstream of the LLM call raises, the
        session must be flipped to `error` instead of left as `running`.

        Without the catch-all, the partial unique index on
        ``ux_compgen_one_active_per_user`` would treat the stale row as
        active forever, and the user's next AI Generate would 409 with
        "An active generation session already exists" — exactly the QA
        symptom the REDO was filed for.
        """
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        from app.core import billing_hooks

        async def boom(*args, **kwargs):
            raise RuntimeError("simulated post-LLM crash")

        with (
            patch.object(llm_client, "generate_json", side_effect=fake_generate),
            patch.object(billing_hooks, "consume_action", side_effect=boom),
        ):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "error"
        await db.refresh(sess)
        assert sess.status == "error"
        assert sess.error_code == "service_error"
        assert "simulated post-LLM crash" in (sess.error_message or "")

        # The whole point: the user can now start a fresh generation.
        next_sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        assert next_sess.id != sess.id

    async def test_notification_row_written_on_ready(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        # Seed the notification template (migration already does it in prod).
        from sqlalchemy import text

        await db.execute(
            text("""
                INSERT INTO notification_templates
                    (id, code, subject_template, body_template,
                     notification_type, created_at, updated_at)
                VALUES (
                    gen_random_uuid(),
                    'competence_generation_ready',
                    'AI competence generation is ready',
                    '<p>Hi {{ recipient_name }}.</p>',
                    'in_app', now(), now()
                )
                ON CONFLICT (code) DO NOTHING
                """)
        )
        await db.commit()

        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        notif_q = await db.execute(
            select(Notification).where(Notification.recipient_id == user.id)
        )
        assert notif_q.scalar_one_or_none() is not None


class TestContextExcludesWholeBase:
    """HRP-123: preflight modal can drop categories from the whole_base prompt."""

    async def test_default_keeps_full_context(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.company.models import Division

        div = Division(name="Engineering", tenant_id=tenant.id)
        db.add(div)
        tenant.description = "Acme Corp"
        await db.commit()

        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        captured: dict[str, str] = {}

        async def capture(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Backend Engineer" in captured["user"]
        assert "Engineering" in captured["user"]
        assert "Acme Corp" in captured["user"]

    async def test_excluding_specializations_drops_them_from_prompt(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(context_excludes=["specializations"]),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Backend Engineer" not in captured["user"]

    async def test_excluding_divisions_and_company(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.company.models import Division

        div = Division(name="Engineering", tenant_id=tenant.id)
        db.add(div)
        tenant.description = "Acme Corp"
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(context_excludes=["divisions", "company"]),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        # Specialization is still in the prompt — only divisions/company were excluded.
        assert "Backend Engineer" in captured["user"]
        assert "Engineering" not in captured["user"]
        assert "Acme Corp" not in captured["user"]

    async def test_excluding_source_tree_drops_existing_library(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        """HRP-124: augment session can launch as if the library were empty."""
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.competence.models import Competence, CompetenceGroup

        group = CompetenceGroup(
            title="Legacy group",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(group)
        await db.flush()
        comp = Competence(
            title="Pre-existing competence",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        db.add(comp)
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(context_excludes=["source_tree"]),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Pre-existing competence" not in captured["user"]
        assert "Legacy group" not in captured["user"]
        # Default categories (specialization) still survive the run.
        assert "Backend Engineer" in captured["user"]

    async def test_refinement_prompt_passed_to_llm(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(
                    refinement_prompt="Focus on cloud platforms and security"
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Focus on cloud platforms and security" in captured["user"]


class TestProgressStreaming:
    """HRP-71 phase 4: synthetic streaming via `compgen.progress` events."""

    async def test_emits_thinking_then_per_phase_progress(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
        monkeypatch,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        recorded: list[dict[str, object]] = []

        async def fake_progress(
            tenant_id, user_id, session_id, phase, *, total=None, current=None
        ):
            recorded.append({"phase": phase, "total": total, "current": current})

        monkeypatch.setattr(tasks, "_broadcast_progress", fake_progress)
        # Indicator-step delay defaults to 40ms — drop to 0 in tests so the
        # whole sequence settles synchronously without flakiness.
        monkeypatch.setattr(tasks, "PROGRESS_INDICATOR_STEP_DELAY_S", 0)

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        phases = [r["phase"] for r in recorded]
        # thinking before LLM, then competences, then per-indicator ticks.
        assert phases[0] == "thinking"
        assert "competences" in phases
        assert phases.count("indicators") >= 1

        comp_event = next(r for r in recorded if r["phase"] == "competences")
        assert comp_event["total"] == 1
        ind_events = [r for r in recorded if r["phase"] == "indicators"]
        assert ind_events[-1]["total"] == 1
        assert ind_events[-1]["current"] == 1
        # whole_base scope must not emit grades / matrix phases.
        assert "grades" not in phases
        assert "matrix" not in phases

    async def test_count_payload_totals_for_matrix_scope(self) -> None:
        payload = {
            "groups": [
                {
                    "competences": [
                        {"indicators": [{"title": "i1"}, {"title": "i2"}]},
                        {"indicators": [{"title": "i3"}]},
                    ],
                    "children": [
                        {
                            "competences": [
                                {"indicators": [{"title": "i4"}]},
                            ],
                            "children": [],
                        }
                    ],
                }
            ]
        }
        snapshot = {"specialization": {"grades": [{}, {}, {}]}}
        grades, comps, inds = tasks._count_payload_totals(
            payload, "specialization_matrix", snapshot
        )
        assert grades == 3
        assert comps == 3  # 2 root + 1 in child group
        assert inds == 4  # 2+1+1

    async def test_cancel_during_streaming_skips_billing(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
        monkeypatch,
    ) -> None:
        """Cancel between cancel-check #2 and the post-stream check #3 must
        not bill — without check #3 the user gets charged for output they
        already discarded.
        """
        from app.modules.ai_competence_generation.models import (
            CompetenceGenerationSession,
        )

        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        # Replace the streamer with one that flips `cancelled` mid-flight.
        async def fake_stream(
            tenant_id, user_id, session_id, payload, scope, base_snapshot
        ):
            async with session_factory() as cancel_db:
                row = await cancel_db.get(CompetenceGenerationSession, session_id)
                assert row is not None
                row.status = "cancelled"
                await cancel_db.commit()

        monkeypatch.setattr(tasks, "_stream_progress_after_parse", fake_stream)

        billed: list[str] = []

        async def fake_consume(*args, **kwargs):
            billed.append("yes")

        monkeypatch.setattr("app.core.billing_hooks.consume_action", fake_consume)

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "cancelled"
        assert billed == []
        await db.refresh(sess)
        assert sess.status == "cancelled"
        assert sess.payload is None  # never written

    async def test_count_payload_totals_indicator_scope(self) -> None:
        payload = {"indicators": [{"title": "a"}, {"title": "b"}]}
        grades, comps, inds = tasks._count_payload_totals(
            payload, "competence_indicators", None
        )
        assert (grades, comps, inds) == (0, 0, 2)


class TestNormalisationHelpers:
    def test_normalise_tree_assigns_unique_temp_ids(self) -> None:
        payload = {
            "groups": [
                {
                    "title": "G",
                    "competences": [
                        {
                            "title": "C",
                            "indicators": [{"title": "I1", "skill_level": "basic"}],
                        }
                    ],
                    "children": [],
                }
            ]
        }
        normalised, selection = tasks._normalise_tree(payload)
        ids = {
            normalised["groups"][0]["temp_id"],
            normalised["groups"][0]["competences"][0]["temp_id"],
            normalised["groups"][0]["competences"][0]["indicators"][0]["temp_id"],
        }
        assert len(ids) == 3
        assert all(selection[t] is True for t in ids)

    def test_normalise_indicators_only(self) -> None:
        payload = {"indicators": [{"title": "I", "skill_level": "basic"}]}
        normalised, selection = tasks._normalise_indicators(payload)
        iid = normalised["indicators"][0]["temp_id"]
        assert iid
        assert selection[iid] is True


# ---------------------------------------------------------------------------
# HRP-114: context_excludes + tenant-context for group / competence_indicators
# ---------------------------------------------------------------------------


_FAKE_GROUP_PAYLOAD = {
    "groups": [
        {
            "title": "Cloud Foundations",
            "description": "Cloud-native basics.",
            "children": [],
            "competences": [
                {
                    "title": "AWS",
                    "description": "AWS basics.",
                    "type": "hard_skill",
                    "indicators": [
                        {"title": "Knows IAM basics", "skill_level": "basic"}
                    ],
                }
            ],
        }
    ]
}


_FAKE_INDICATOR_PAYLOAD = {
    "indicators": [
        {"title": "Knows REST verbs", "skill_level": "basic"},
        {"title": "Designs idempotent endpoints", "skill_level": "advanced"},
    ]
}


@pytest_asyncio.fixture
async def skill_level_basic(db: AsyncSession, tenant):
    from app.modules.competence.models import SkillLevel

    lvl = SkillLevel(
        title="basic",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(lvl)
    await db.commit()
    await db.refresh(lvl)
    return lvl


@pytest_asyncio.fixture
async def group_with_competences(db: AsyncSession, tenant):
    """Fresh group with two competences for `group` scope tests."""
    from app.modules.competence.models import Competence, CompetenceGroup

    grp = CompetenceGroup(
        title="Backend Skills",
        description="Server-side engineering",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(grp)
    await db.flush()
    for title in ("Python", "PostgreSQL"):
        db.add(
            Competence(
                title=title,
                tenant_id=tenant.id,
                group_id=grp.id,
                is_active=True,
            )
        )
    await db.commit()
    await db.refresh(grp)
    return grp


@pytest_asyncio.fixture
async def competence_with_siblings(db: AsyncSession, tenant, skill_level_basic):
    """Target competence + two sibling competences in the same group."""
    from app.modules.competence.models import Competence, CompetenceGroup, Indicator

    grp = CompetenceGroup(
        title="Communication",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(grp)
    await db.flush()
    target = Competence(
        title="Active listening",
        tenant_id=tenant.id,
        group_id=grp.id,
        is_active=True,
    )
    db.add(target)
    await db.flush()
    db.add(
        Indicator(
            title="Restates the speaker's point",
            tenant_id=tenant.id,
            competence_id=target.id,
            skill_level_id=skill_level_basic.id,
            is_active=True,
        )
    )
    for sib in ("Public speaking", "Written communication"):
        db.add(
            Competence(
                title=sib,
                tenant_id=tenant.id,
                group_id=grp.id,
                is_active=True,
            )
        )
    await db.commit()
    await db.refresh(target)
    return target


class TestGroupScopeRelatedSpecsAndAncestry:
    """HRP-114: `group` scope must surface related specializations,
    ancestors, and descendants — and each must be droppable per-item."""

    async def test_related_specs_only_lists_linked_specs(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        skill_level_basic,
        session_factory,
    ) -> None:
        """`related_specializations` is the subset of tenant specs linked
        to a competence in the target group. Tenant-wide specs include
        the unrelated extras; related list does not."""
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        # Group with one competence wired into a grade-specialization
        # matrix entry → its spec is "related". Add an unrelated spec on
        # the tenant so we can prove it doesn't slip into related.
        grade = DictionaryItem(
            type="grade",
            title="Senior",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        unrelated = DictionaryItem(
            type="specialization",
            title="Frontend Engineer",
            tenant_id=tenant.id,
            sort_index=1,
            is_active=True,
        )
        group = CompetenceGroup(
            title="API design",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add_all([grade, unrelated, group])
        await db.flush()
        comp = Competence(
            title="REST conventions",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        db.add(comp)
        await db.flush()
        pair = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=specialization.id,
        )
        db.add(pair)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=pair.id,
                competence_id=comp.id,
                skill_level_id=skill_level_basic.id,
            )
        )
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="group", target_id=group.id),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_GROUP_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "related_specializations" in captured["user"]
        # Backend Engineer is the linked spec; Frontend Engineer is not.
        related_block = captured["user"].split("related_specializations")[1].split(
            "]"
        )[0]
        assert "Backend Engineer" in related_block
        assert "Frontend Engineer" not in related_block

    async def test_ancestors_and_descendants_in_prompt(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.competence.models import Competence, CompetenceGroup

        root = CompetenceGroup(
            title="Engineering",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(root)
        await db.flush()
        target = CompetenceGroup(
            title="Backend",
            tenant_id=tenant.id,
            parent_id=root.id,
            sort_index=0,
            is_active=True,
        )
        db.add(target)
        await db.flush()
        child = CompetenceGroup(
            title="Databases",
            tenant_id=tenant.id,
            parent_id=target.id,
            sort_index=0,
            is_active=True,
        )
        db.add(child)
        await db.flush()
        db.add(
            Competence(
                title="PostgreSQL tuning",
                tenant_id=tenant.id,
                group_id=child.id,
                is_active=True,
            )
        )
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="group", target_id=target.id),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_GROUP_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        # Ancestor chain rendered as the parent title list.
        assert "ancestor_groups" in captured["user"]
        assert "Engineering" in captured["user"]
        # Descendant subtree includes the child group + its competences.
        assert "descendant_groups" in captured["user"]
        assert "Databases" in captured["user"]
        assert "PostgreSQL tuning" in captured["user"]

    async def test_per_item_descendant_exclude_drops_subtree(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.competence.models import Competence, CompetenceGroup

        target = CompetenceGroup(
            title="Backend",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(target)
        await db.flush()
        drop = CompetenceGroup(
            title="Legacy",
            tenant_id=tenant.id,
            parent_id=target.id,
            sort_index=0,
            is_active=True,
        )
        keep = CompetenceGroup(
            title="Modern",
            tenant_id=tenant.id,
            parent_id=target.id,
            sort_index=1,
            is_active=True,
        )
        db.add_all([drop, keep])
        await db.flush()
        db.add_all(
            [
                Competence(
                    title="ColdFusion",
                    tenant_id=tenant.id,
                    group_id=drop.id,
                    is_active=True,
                ),
                Competence(
                    title="Async I/O",
                    tenant_id=tenant.id,
                    group_id=keep.id,
                    is_active=True,
                ),
            ]
        )
        await db.commit()
        await db.refresh(drop)

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=target.id,
                params=SessionParams(
                    context_excludes=[f"descendant:{drop.id}"]
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_GROUP_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        # Descendant subtree (Legacy + ColdFusion) is gone, but the
        # sibling Modern branch survived.
        descendants_block = captured["user"].split("descendant_groups")[1]
        assert "Legacy" not in descendants_block
        assert "ColdFusion" not in descendants_block
        assert "Modern" in descendants_block
        assert "Async I/O" in descendants_block


class TestIndicatorsScopeRelatedSpecs:
    """HRP-114: indicators scope must surface specs linked specifically
    to the target competence (not just tenant-wide)."""

    async def test_related_specializations_for_competence(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        skill_level_basic,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
        )
        from app.modules.competence.models import Competence, CompetenceGroup
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        grade = DictionaryItem(
            type="grade",
            title="Senior",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        unrelated = DictionaryItem(
            type="specialization",
            title="Frontend Engineer",
            tenant_id=tenant.id,
            sort_index=1,
            is_active=True,
        )
        group = CompetenceGroup(
            title="Backend",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add_all([grade, unrelated, group])
        await db.flush()
        comp = Competence(
            title="Async I/O",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        db.add(comp)
        await db.flush()
        pair = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=specialization.id,
        )
        db.add(pair)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=pair.id,
                competence_id=comp.id,
                skill_level_id=skill_level_basic.id,
            )
        )
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="competence_indicators", target_id=comp.id),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "related_specializations" in captured["user"]
        related_block = captured["user"].split("related_specializations")[1].split(
            "]"
        )[0]
        assert "Backend Engineer" in related_block
        assert "Frontend Engineer" not in related_block


class TestContextExcludesGroupScope:
    """HRP-114: preflight modal can trim context for `group` scope too."""

    async def test_default_includes_tenant_context_and_existing_tree(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        group_with_competences,
        session_factory,
    ) -> None:
        from app.modules.company.models import Division

        db.add(Division(name="Platform", tenant_id=tenant.id))
        tenant.description = "Acme Corp"
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="group", target_id=group_with_competences.id),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_GROUP_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        # Tenant-wide chips are present by default.
        assert "Backend Engineer" in captured["user"]
        assert "Platform" in captured["user"]
        assert "Acme Corp" in captured["user"]
        # Existing group competences are visible (source_tree default-on).
        assert "Python" in captured["user"]
        assert "PostgreSQL" in captured["user"]

    async def test_excluding_tenant_categories_drops_them(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        group_with_competences,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.company.models import Division

        db.add(Division(name="Platform", tenant_id=tenant.id))
        tenant.description = "Acme Corp"
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=group_with_competences.id,
                params=SessionParams(
                    context_excludes=["specializations", "divisions", "company"]
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_GROUP_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Backend Engineer" not in captured["user"]
        assert "Platform" not in captured["user"]
        assert "Acme Corp" not in captured["user"]
        # Source tree still in (not excluded).
        assert "Python" in captured["user"]

    async def test_excluding_source_tree_drops_existing_competences(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        group_with_competences,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=group_with_competences.id,
                params=SessionParams(context_excludes=["source_tree"]),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_GROUP_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Python" not in captured["user"]
        assert "PostgreSQL" not in captured["user"]
        # Tenant context still present.
        assert "Backend Engineer" in captured["user"]

    async def test_refinement_prompt_for_group_scope(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        group_with_competences,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=group_with_competences.id,
                params=SessionParams(
                    refinement_prompt="Cover async patterns specifically"
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_GROUP_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Cover async patterns specifically" in captured["user"]


class TestContextExcludesIndicatorScope:
    """HRP-114: preflight modal can trim context for indicator scope."""

    async def test_default_includes_tenant_context_siblings_and_existing(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        competence_with_siblings,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
        )
        from app.modules.company.models import Division

        db.add(Division(name="People Ops", tenant_id=tenant.id))
        tenant.description = "Acme Corp"
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=competence_with_siblings.id,
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Backend Engineer" in captured["user"]
        assert "People Ops" in captured["user"]
        assert "Acme Corp" in captured["user"]
        # Sibling competences from the same group are listed.
        assert "Public speaking" in captured["user"]
        assert "Written communication" in captured["user"]
        # Existing indicator title carried into prompt by default.
        assert "Restates the speaker's point" in captured["user"]

    async def test_excluding_tenant_categories(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        competence_with_siblings,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
            SessionParams,
        )
        from app.modules.company.models import Division

        db.add(Division(name="People Ops", tenant_id=tenant.id))
        tenant.description = "Acme Corp"
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=competence_with_siblings.id,
                params=SessionParams(
                    context_excludes=["specializations", "divisions", "company"]
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Backend Engineer" not in captured["user"]
        assert "People Ops" not in captured["user"]
        assert "Acme Corp" not in captured["user"]
        # Sibling competences default-on (only tenant chips were excluded).
        assert "Public speaking" in captured["user"]

    async def test_excluding_existing_indicators_drops_them(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        competence_with_siblings,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
            SessionParams,
        )

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=competence_with_siblings.id,
                params=SessionParams(context_excludes=["existing_indicators"]),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Restates the speaker's point" not in captured["user"]
        # Tenant context is untouched.
        assert "Backend Engineer" in captured["user"]

    async def test_excluding_sibling_competences_drops_them(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        competence_with_siblings,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
            SessionParams,
        )

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=competence_with_siblings.id,
                params=SessionParams(context_excludes=["sibling_competences"]),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Public speaking" not in captured["user"]
        assert "Written communication" not in captured["user"]
        # Target competence itself + tenant context untouched.
        assert "Active listening" in captured["user"]
        assert "Backend Engineer" in captured["user"]

    async def test_refinement_prompt_for_indicator_scope(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        competence_with_siblings,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
            SessionParams,
        )

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=competence_with_siblings.id,
                params=SessionParams(
                    refinement_prompt="Lean towards remote-team collaboration"
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Lean towards remote-team collaboration" in captured["user"]

    async def test_excluding_sibling_competences_also_strips_matrix_context(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        competence_with_siblings,
        skill_level_basic,
        session_factory,
    ) -> None:
        """HRP-114: one chip kills both same-group siblings AND matrix siblings.

        Matrix-launched indicator sessions (HRP-102) carry a
        ``specialization_context.sibling_competences`` block on the
        snapshot. Excluding ``sibling_competences`` must drop *both*
        same-group siblings AND that matrix sibling list — without it
        the user sees a chip that only half-removes the context.
        """
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
            SessionParams,
        )
        from app.modules.competence.models import Competence
        from app.modules.dictionary.models import DictionaryItem
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        # Wire competence into the spec matrix so the snapshot picks up a
        # specialization_context block with a matrix sibling. Grades are
        # DictionaryItem rows with type="grade".
        grade = DictionaryItem(
            type="grade",
            title="Senior",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(grade)
        await db.flush()
        pair = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade.id,
            specialization_id=specialization.id,
            sort_index=0,
        )
        db.add(pair)
        await db.flush()
        matrix_sibling = Competence(
            title="Matrix-only sibling",
            tenant_id=tenant.id,
            group_id=competence_with_siblings.group_id,
            is_active=True,
        )
        db.add(matrix_sibling)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=pair.id,
                competence_id=matrix_sibling.id,
                skill_level_id=skill_level_basic.id,
            )
        )
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="competence_indicators",
                target_id=competence_with_siblings.id,
                params=SessionParams(
                    specialization_id=specialization.id,
                    context_excludes=["sibling_competences"],
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Matrix-only sibling" not in captured["user"]
        assert "Public speaking" not in captured["user"]
        # Tenant-wide context untouched.
        assert "Backend Engineer" in captured["user"]


# ---------------------------------------------------------------------------
# HRP-122: max_tokens budget per scope + in-task celery heartbeat
# ---------------------------------------------------------------------------


class TestMaxTokensByScope:
    """Tree-shaped scopes need more room than the SDK's 8192 default — without
    it the LLM truncates mid-JSON and the partial payload surfaces as
    ``parse_error`` even when the model was producing valid content."""

    async def test_whole_base_scope_bumps_max_tokens(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        captured: dict[str, object] = {}

        async def capture(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            captured["max_tokens"] = max_tokens
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert captured["max_tokens"] == tasks._max_tokens_for_scope("whole_base")
        assert captured["max_tokens"] >= 16384

    async def test_indicators_scope_keeps_default_budget(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        skill_level_basic,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            GeneratedIndicatorsSchema,
        )
        from app.modules.competence.models import Competence, CompetenceGroup

        group = CompetenceGroup(
            title="Cloud",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(group)
        await db.flush()
        comp = Competence(
            title="AWS",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        db.add(comp)
        await db.commit()
        await db.refresh(comp)

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(scope="competence_indicators", target_id=comp.id),
        )

        captured: dict[str, object] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["max_tokens"] = max_tokens
            return GeneratedIndicatorsSchema.model_validate(_FAKE_INDICATOR_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        # Indicator-only output fits in 8192 — bumping it would just waste
        # provider quota.
        assert captured["max_tokens"] == 8192


class TestCeleryHeartbeatFromTask:
    """HRP-122: with ``worker_prefetch_multiplier=1`` the beat heartbeat task
    sits queued behind a long compgen run; refresh from inside the task so
    the UI doesn't flip to "Background worker offline" mid-generation."""

    async def test_execute_session_starts_and_stops_pulser(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
        monkeypatch,
    ) -> None:
        """Confirm the in-task pulser is wired into ``execute_session``: it
        starts before the body runs and is cancelled when the body returns.
        """
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        pulse_calls: list[str] = []

        async def fake_pulse(stop_event, **_kwargs):
            pulse_calls.append("started")
            await stop_event.wait()
            pulse_calls.append("stopped")

        monkeypatch.setattr(tasks, "_heartbeat_pulse", fake_pulse)

        async def fake_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=fake_generate):
            await tasks.execute_session(session_factory, sess.id)

        # The pulser must both start and shut down cleanly — otherwise the
        # task would leak across compgen runs and the stop_event/redis
        # handle would never be released.
        assert pulse_calls == ["started", "stopped"]

    async def test_pulser_keeps_writing_during_slow_generation(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
        monkeypatch,
    ) -> None:
        """Slow LLM call must see multiple heartbeat writes — that's the whole
        point of the in-task refresh under ``worker_prefetch_multiplier=1``.
        """
        import asyncio as _asyncio

        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        writes: list[str] = []

        class _FakeRedis:
            async def set(self, key, value, ex=None):
                writes.append(key)

            async def aclose(self):
                pass

        monkeypatch.setattr(tasks, "_open_heartbeat_redis", lambda: _FakeRedis())
        monkeypatch.setattr(tasks, "HEARTBEAT_REFRESH_INTERVAL_S", 0.05)

        async def slow_generate(
            prompt,
            system=None,
            model=None,
            temperature=None,
            tenant_settings=None,
            schema=None,
            max_tokens=None,
        ):
            await _asyncio.sleep(0.25)
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=slow_generate):
            await tasks.execute_session(session_factory, sess.id)

        # 0.25s call with a 0.05s refresh interval = 5+ pulses expected.
        # Allow some slack for loop scheduling, but require >1 to prove the
        # refresh actually kept up with the LLM call.
        pulses = sum(1 for k in writes if k == tasks.HEARTBEAT_KEY)
        assert pulses >= 2, f"expected >=2 heartbeat writes, got {pulses}"

    async def test_pulser_stops_when_body_raises(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
        monkeypatch,
    ) -> None:
        """Pulser must shut down cleanly even when the body propagates an
        exception — otherwise the task leaks across compgen runs."""
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )

        pulse_calls: list[str] = []

        async def fake_pulse(stop_event, **_kwargs):
            pulse_calls.append("started")
            try:
                await stop_event.wait()
            finally:
                pulse_calls.append("stopped")

        monkeypatch.setattr(tasks, "_heartbeat_pulse", fake_pulse)

        # `_terminate` returns a dict (status="error") rather than raising,
        # so simulate a true exception via the LLM call raising something
        # non-recoverable that escapes the retry loop's exception handler.
        # We use an async-cancel from inside the body to force the
        # ``except asyncio.CancelledError`` path in ``execute_session``.
        import asyncio as _asyncio

        async def boom(*args, **kwargs):
            raise _asyncio.CancelledError("simulated worker shutdown")

        with (
            patch.object(llm_client, "generate_json", side_effect=boom),
            pytest.raises(_asyncio.CancelledError),
        ):
            await tasks.execute_session(session_factory, sess.id)

        assert pulse_calls == ["started", "stopped"]

    async def test_per_item_specialization_exclude_drops_one(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        """HRP-143: ``specialization:<uuid>`` drops a single spec from the
        whole_base prompt while keeping the rest."""
        from app.modules.ai_competence_generation.schemas import SessionParams

        # Add a second specialization that must survive the per-item drop.
        keep = DictionaryItem(
            type="specialization",
            title="DevOps Engineer",
            tenant_id=tenant.id,
            sort_index=1,
            is_active=True,
        )
        db.add(keep)
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(
                    context_excludes=[f"specialization:{specialization.id}"]
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Backend Engineer" not in captured["user"]
        assert "DevOps Engineer" in captured["user"]

    async def test_per_item_division_exclude_drops_one(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.company.models import Division

        drop = Division(name="HR", tenant_id=tenant.id)
        keep = Division(name="Engineering", tenant_id=tenant.id)
        db.add_all([drop, keep])
        await db.commit()
        await db.refresh(drop)

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(
                    context_excludes=[f"division:{drop.id}"]
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "HR" not in captured["user"]
        assert "Engineering" in captured["user"]

    async def test_per_item_group_exclude_prunes_subtree(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        """HRP-143: ``group:<uuid>`` drops the named group and every node
        under it (children, competences) from the source_tree dump."""
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.competence.models import Competence, CompetenceGroup

        drop = CompetenceGroup(
            title="Legacy stack",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        keep = CompetenceGroup(
            title="Modern stack",
            tenant_id=tenant.id,
            sort_index=1,
            is_active=True,
        )
        db.add_all([drop, keep])
        await db.flush()
        db.add(
            Competence(
                title="ColdFusion expertise",
                tenant_id=tenant.id,
                group_id=drop.id,
                is_active=True,
            )
        )
        db.add(
            Competence(
                title="React 19 patterns",
                tenant_id=tenant.id,
                group_id=keep.id,
                is_active=True,
            )
        )
        await db.commit()

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(context_excludes=[f"group:{drop.id}"]),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Legacy stack" not in captured["user"]
        assert "ColdFusion expertise" not in captured["user"]
        assert "Modern stack" in captured["user"]
        assert "React 19 patterns" in captured["user"]

    async def test_per_item_competence_exclude_keeps_group(
        self,
        db: AsyncSession,
        tenant,
        user,
        specialization,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import SessionParams
        from app.modules.competence.models import Competence, CompetenceGroup

        group = CompetenceGroup(
            title="Backend",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(group)
        await db.flush()
        drop = Competence(
            title="Outdated framework",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        keep = Competence(
            title="Modern framework",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        db.add_all([drop, keep])
        await db.commit()
        await db.refresh(drop)

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="whole_base",
                params=SessionParams(
                    context_excludes=[f"competence:{drop.id}"]
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, max_tokens=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_FAKE_TREE_PAYLOAD)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        assert "Outdated framework" not in captured["user"]
        assert "Modern framework" in captured["user"]
        assert "Backend" in captured["user"]

    async def test_heartbeat_pulse_writes_then_stops(self, monkeypatch) -> None:
        """Pulser writes the heartbeat key, then exits cleanly on stop."""
        import asyncio as _asyncio

        writes: list[tuple[str, int | None]] = []
        closes: list[bool] = []

        class _FakeRedis:
            async def set(self, key, value, ex=None):
                writes.append((key, ex))

            async def aclose(self):
                closes.append(True)

        monkeypatch.setattr(tasks, "_open_heartbeat_redis", lambda: _FakeRedis())
        # Speed the interval down so the loop exits via `wait_for` quickly.
        monkeypatch.setattr(tasks, "HEARTBEAT_REFRESH_INTERVAL_S", 0.05)

        stop = _asyncio.Event()
        task = _asyncio.create_task(tasks._heartbeat_pulse(stop))
        # Yield enough for the first iteration to land its write.
        await _asyncio.sleep(0.02)
        stop.set()
        await _asyncio.wait_for(task, timeout=2.0)

        # At least one write happened with the correct TTL, and the redis
        # handle was disposed.
        assert any(
            k == tasks.HEARTBEAT_KEY and ex == tasks.HEARTBEAT_TTL_S
            for (k, ex) in writes
        )
        assert closes == [True]


# HRP-155: group-scope augment mode — `source_tree` included means the LLM is
# told to extend existing items, and the worker tags matched nodes with
# `snapshot_id` so the apply step reuses existing rows and the tree UI
# renders them locked.


@pytest_asyncio.fixture
async def group_with_indicators(db: AsyncSession, tenant, skill_level_basic):
    """Group with one competence carrying an existing indicator plus a
    descendant subgroup with its own competence.

    Used to exercise the HRP-155 annotation step end-to-end: the LLM's
    response will mention the existing titles, and we expect the worker
    to attach `snapshot_id` at group, competence, and indicator levels."""
    from app.modules.competence.models import (
        Competence,
        CompetenceGroup,
        Indicator,
    )

    parent = CompetenceGroup(
        title="Platform",
        tenant_id=tenant.id,
        sort_index=0,
        is_active=True,
    )
    db.add(parent)
    await db.flush()
    comp_existing = Competence(
        title="Networking",
        tenant_id=tenant.id,
        group_id=parent.id,
        is_active=True,
    )
    db.add(comp_existing)
    await db.flush()
    indicator_existing = Indicator(
        title="Knows TCP basics",
        tenant_id=tenant.id,
        competence_id=comp_existing.id,
        skill_level_id=skill_level_basic.id,
        is_active=True,
    )
    db.add(indicator_existing)

    child = CompetenceGroup(
        title="Observability",
        tenant_id=tenant.id,
        parent_id=parent.id,
        sort_index=0,
        is_active=True,
    )
    db.add(child)
    await db.flush()
    descendant_comp = Competence(
        title="Logging",
        tenant_id=tenant.id,
        group_id=child.id,
        is_active=True,
    )
    db.add(descendant_comp)
    await db.commit()
    await db.refresh(parent)
    await db.refresh(comp_existing)
    await db.refresh(indicator_existing)
    await db.refresh(child)
    await db.refresh(descendant_comp)
    return {
        "parent": parent,
        "child": child,
        "comp_existing": comp_existing,
        "indicator_existing": indicator_existing,
        "descendant_comp": descendant_comp,
    }


_AUGMENT_LLM_RESPONSE = {
    "groups": [
        # Mirrors the existing target group; carries a NEW competence and
        # echoes the existing competence with one NEW indicator.
        {
            "title": "Platform",
            "description": "Platform engineering",
            "children": [
                # Existing subgroup with a NEW competence underneath.
                {
                    "title": "Observability",
                    "description": "Telemetry & dashboards",
                    "children": [],
                    "competences": [
                        {
                            "title": "Metrics",
                            "description": "Counters and histograms",
                            "type": "hard_skill",
                            "indicators": [
                                {
                                    "title": "Picks the right metric type",
                                    "skill_level": "basic",
                                }
                            ],
                        }
                    ],
                }
            ],
            "competences": [
                # Existing competence with a single NEW indicator.
                {
                    "title": "Networking",
                    "description": "Networking",
                    "type": "hard_skill",
                    "indicators": [
                        {
                            "title": "Debugs latency with traceroute",
                            "skill_level": "basic",
                        },
                        # An echoed existing indicator — annotation should
                        # mark it with snapshot_id and the apply step must
                        # skip it on persistence.
                        {
                            "title": "Knows TCP basics",
                            "skill_level": "basic",
                        },
                    ],
                },
                # Brand-new competence under the target group.
                {
                    "title": "Containers",
                    "description": "Containers and orchestration",
                    "type": "hard_skill",
                    "indicators": [
                        {
                            "title": "Reads a Dockerfile",
                            "skill_level": "basic",
                        }
                    ],
                },
            ],
        }
    ]
}


class TestGroupAugmentMode:
    async def test_snapshot_includes_indicators_for_existing_competences(
        self,
        db: AsyncSession,
        tenant,
        user,
        group_with_indicators,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            SessionParams,
        )

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=group_with_indicators["parent"].id,
                params=SessionParams(),
            ),
        )
        snap = sess.base_snapshot["group"]
        # Own competence carries its indicator list (HRP-155 snapshot
        # extension) so the LLM can avoid duplicates.
        own = next(c for c in snap["competences"] if c["title"] == "Networking")
        assert any(
            i["title"] == "Knows TCP basics" and i["skill_level"] == "basic"
            for i in own["indicators"]
        )
        # Descendant subgroup also carries indicator metadata even when
        # empty so the schema is stable.
        descendants = snap["descendants"]
        assert descendants
        desc_comp = descendants[0]["competences"][0]
        assert "indicators" in desc_comp

    async def test_augment_on_annotates_matched_nodes_with_snapshot_id(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_level_basic,
        group_with_indicators,
        session_factory,
    ) -> None:
        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=group_with_indicators["parent"].id,
            ),
        )

        async def capture(prompt, system=None, **_):
            return GeneratedTreeSchema.model_validate(_AUGMENT_LLM_RESPONSE)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        await db.refresh(sess)
        groups = sess.payload["groups"]
        top = groups[0]
        # Top-level matches the target group itself.
        assert top["snapshot_id"] == str(group_with_indicators["parent"].id)
        # Existing competence carries snapshot_id.
        net = next(c for c in top["competences"] if c["title"] == "Networking")
        assert net["snapshot_id"] == str(
            group_with_indicators["comp_existing"].id
        )
        # New competence stays unannotated — frontend renders it as "new".
        containers = next(
            c for c in top["competences"] if c["title"] == "Containers"
        )
        assert "snapshot_id" not in containers
        # Indicator that echoes the existing one is tagged; the new one is not.
        existing_ind = next(
            i for i in net["indicators"] if i["title"] == "Knows TCP basics"
        )
        new_ind = next(
            i
            for i in net["indicators"]
            if i["title"] == "Debugs latency with traceroute"
        )
        assert existing_ind["snapshot_id"] == str(
            group_with_indicators["indicator_existing"].id
        )
        assert "snapshot_id" not in new_ind
        # Selection should default the echoed indicator off so it doesn't
        # inflate the counter; the new one stays on.
        assert sess.selection_state[existing_ind["temp_id"]] is False
        assert sess.selection_state[new_ind["temp_id"]] is True
        # Descendant subgroup also matched.
        descendant_group = top["children"][0]
        assert descendant_group["snapshot_id"] == str(
            group_with_indicators["child"].id
        )

    async def test_augment_off_skips_annotation_and_source_tree(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_level_basic,
        group_with_indicators,
        session_factory,
    ) -> None:
        from app.modules.ai_competence_generation.schemas import (
            SessionParams,
        )

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=group_with_indicators["parent"].id,
                params=SessionParams(
                    # HRP-155: the UI passes both keys when augment is off.
                    context_excludes=["source_tree", "descendants"]
                ),
            ),
        )

        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(_AUGMENT_LLM_RESPONSE)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        # The existing-tree fingerprints are absent from the prompt body.
        assert "Networking" not in captured["user"]
        assert "Observability" not in captured["user"]

        await db.refresh(sess)
        # With augment off the worker MUST NOT tag echoed titles as existing —
        # the operator chose a fresh-generation run; matching would mis-lock
        # newly suggested rows that happen to share a title with the library.
        top = sess.payload["groups"][0]
        assert "snapshot_id" not in top
        net = next(c for c in top["competences"] if c["title"] == "Networking")
        assert "snapshot_id" not in net

    async def test_apply_reuses_existing_competence_and_skips_existing_indicator(
        self,
        db: AsyncSession,
        tenant,
        user,
        skill_level_basic,
        group_with_indicators,
        session_factory,
    ) -> None:
        from app.modules.competence.models import Competence, Indicator

        sess = await service.create_session(
            db,
            tenant.id,
            user.id,
            SessionCreate(
                scope="group",
                target_id=group_with_indicators["parent"].id,
            ),
        )

        async def capture(prompt, system=None, **_):
            return GeneratedTreeSchema.model_validate(_AUGMENT_LLM_RESPONSE)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            await tasks.execute_session(session_factory, sess.id)

        await db.refresh(sess)
        # Sanity: the worker flipped to ready and tagged the response.
        assert sess.status == "ready"

        result = await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key="augment-mode-apply",
        )

        # Existing competence row reused — no duplicate "Networking" row.
        net_rows = (
            await db.execute(
                select(Competence).where(
                    Competence.tenant_id == tenant.id,
                    Competence.title == "Networking",
                )
            )
        ).scalars().all()
        assert len(net_rows) == 1
        assert net_rows[0].id == group_with_indicators["comp_existing"].id

        # Existing indicator stays a single row — the echoed one was skipped.
        existing_ind_rows = (
            await db.execute(
                select(Indicator).where(
                    Indicator.tenant_id == tenant.id,
                    Indicator.title == "Knows TCP basics",
                    Indicator.competence_id
                    == group_with_indicators["comp_existing"].id,
                )
            )
        ).scalars().all()
        assert len(existing_ind_rows) == 1

        # New indicator under the existing competence WAS persisted.
        new_ind_rows = (
            await db.execute(
                select(Indicator).where(
                    Indicator.tenant_id == tenant.id,
                    Indicator.competence_id
                    == group_with_indicators["comp_existing"].id,
                    Indicator.title == "Debugs latency with traceroute",
                )
            )
        ).scalars().all()
        assert len(new_ind_rows) == 1
        assert new_ind_rows[0].id in [
            (uuid.UUID(s) if isinstance(s, str) else s)
            for s in result["created_indicators"]
        ]

        # Brand-new competence under the target group was created fresh.
        containers_rows = (
            await db.execute(
                select(Competence).where(
                    Competence.tenant_id == tenant.id,
                    Competence.title == "Containers",
                    Competence.group_id == group_with_indicators["parent"].id,
                )
            )
        ).scalars().all()
        assert len(containers_rows) == 1


def test_annotate_group_augment_snapshot_skips_ambiguous_titles() -> None:
    """Two siblings sharing a title leave both unannotated rather than
    silently binding the LLM's echo to the wrong DB row."""
    from app.modules.ai_competence_generation.tasks import (
        _annotate_group_augment_snapshot,
    )

    payload = {
        "groups": [
            {
                "title": "Platform",
                "temp_id": "t-grp",
                "children": [],
                "competences": [
                    {
                        "title": "Networking",
                        "temp_id": "t-comp",
                        "indicators": [],
                    }
                ],
            }
        ]
    }
    base_snapshot = {
        "group": {
            "id": "00000000-0000-0000-0000-000000000001",
            "title": "Platform",
            "competences": [
                {
                    "id": "00000000-0000-0000-0000-000000000010",
                    "title": "Networking",
                    "indicators": [],
                },
                {
                    "id": "00000000-0000-0000-0000-000000000011",
                    "title": "Networking",
                    "indicators": [],
                },
            ],
            "descendants": [],
        }
    }
    selection = {"t-grp": True, "t-comp": True}

    _annotate_group_augment_snapshot(payload, base_snapshot, selection)

    top = payload["groups"][0]
    assert top["snapshot_id"] == base_snapshot["group"]["id"]
    # Ambiguous competence title — neither side is annotated; the apply
    # step will fall through to the legacy create-new branch.
    networking = top["competences"][0]
    assert "snapshot_id" not in networking


def test_build_group_prompt_augment_mode_inserts_override() -> None:
    """The augment task block tells the LLM to relax the duplicate rule."""
    from app.modules.ai_competence_generation import prompts

    source_tree = {
        "group": {"id": "g-1", "title": "Backend", "competences": [], "children": []}
    }
    system, user_prompt = prompts.build_group_prompt(
        group_title="Backend",
        group_description="Backend engineering",
        source_tree=source_tree,
        with_indicators=True,
        refinement=None,
    )
    assert "augment mode" in system.lower()
    assert "augment override" in system.lower()
    assert "source_tree" in user_prompt

    # And without a source tree, the task wording stays in its old shape.
    system_fresh, _ = prompts.build_group_prompt(
        group_title="Backend",
        group_description="Backend engineering",
        source_tree={},
        with_indicators=True,
        refinement=None,
    )
    assert "augment mode" not in system_fresh.lower()
