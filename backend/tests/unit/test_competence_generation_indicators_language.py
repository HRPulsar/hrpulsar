"""HRP-541: Augment indicators must honour the tenant's content language.

Two reported symptoms, one root area:

* picking a generation language in settings did not change the language of
  the indicators the button produced, and
* some competences "fell off" — the run reported success but the indicators
  never landed.

The language directive did reach the system prompt, but the JSON Schema
block ``llm_client.generate_json`` appends lands *after* it, so the last
thing the model read was English boilerplate — and for this scope the
entire user payload is English too. Restating the directive at the end of
the user turn fixes the ordering, and it restates the verbatim carve-out
that keeps ``skill_level`` (a join key) untranslated.

The silent loss is the apply step: ``_resolve_skill_level`` looks the row
up by ``i18n_key`` or ``title ILIKE`` and ``_apply_indicators_only`` skips
a miss without a word. Case alone survives that lookup; padding does not,
so a padded echo dropped the indicator with no error anywhere. The worker
now snaps the model's echo back to the exact title it offered, and every
remaining drop is logged.

Review follow-up: the tree scopes (whole_base, group, specialization_matrix)
go through the same resolver and the same silent ``continue``, so they are
normalised too — including a matrix payload's ``grade_levels``, whose keys
and values come from two different vocabularies.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from app.modules.ai import llm_client
from app.modules.ai_competence_generation import service, tasks
from app.modules.ai_competence_generation.schemas import (
    GeneratedIndicatorsSchema,
    SessionCreate,
)
from app.modules.ai_settings import service as ai_settings_service
from app.modules.ai_settings.schemas import AISettingsUpdate
from app.modules.dictionary.models import DictionaryItem
from sqlalchemy.ext.asyncio import AsyncSession

# Levels echoed the way models actually echo them: wrong case on one,
# padded on the other. `title ILIKE` survives the first, not the second.
_PAYLOAD = {
    "indicators": [
        {"title": "Kennt die REST-Verben", "skill_level": "basic"},
        {"title": "Entwirft idempotente Endpunkte", "skill_level": " Advanced\n"},
    ]
}


@pytest_asyncio.fixture
async def levels(db: AsyncSession, tenant):
    """Two skill levels with deliberately mixed-case titles."""
    from app.modules.competence.models import SkillLevel

    created = []
    for index, title in enumerate(("Basic", "Advanced")):
        lvl = SkillLevel(
            title=title, tenant_id=tenant.id, sort_index=index, is_active=True
        )
        db.add(lvl)
        created.append(lvl)
    await db.commit()
    for lvl in created:
        await db.refresh(lvl)
    return created


@pytest_asyncio.fixture
async def specialization(db: AsyncSession, tenant) -> DictionaryItem:
    """whole_base generation refuses to start without one."""
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


@pytest_asyncio.fixture
async def competence(db: AsyncSession, tenant, levels):
    """Competence with one existing indicator — the augment case."""
    from app.modules.competence.models import Competence, CompetenceGroup, Indicator

    grp = CompetenceGroup(
        title="Integration", tenant_id=tenant.id, sort_index=0, is_active=True
    )
    db.add(grp)
    await db.flush()
    comp = Competence(
        title="Asynchronous Messaging & Event-Driven Integration",
        tenant_id=tenant.id,
        group_id=grp.id,
        is_active=True,
    )
    db.add(comp)
    await db.flush()
    db.add(
        Indicator(
            title="Explains at-least-once delivery",
            tenant_id=tenant.id,
            competence_id=comp.id,
            skill_level_id=levels[0].id,
            is_active=True,
        )
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def _run(session_factory, db, tenant, user, competence, captured):
    sess = await service.create_session(
        db,
        tenant.id,
        user.id,
        SessionCreate(scope="competence_indicators", target_id=competence.id),
    )

    async def capture(prompt, system=None, **_):
        captured["user"] = prompt
        captured["system"] = system
        return GeneratedIndicatorsSchema.model_validate(_PAYLOAD)

    with patch.object(llm_client, "generate_json", side_effect=capture):
        result = await tasks.execute_session(session_factory, sess.id)
    return sess, result


class TestLanguageDirectiveReachesIndicators:
    @pytest.mark.parametrize(
        ("locale", "expected"),
        [("de", "German"), ("ru", "Russian"), ("en", "English")],
    )
    async def test_directive_ends_the_user_turn(
        self, db, tenant, user, competence, session_factory, locale, expected
    ) -> None:
        """The output-language instruction is the model's last instruction.

        The user turn is sent after the system prompt *and* after the JSON
        Schema block, so this is the only position nothing else follows.
        """
        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(content_language=locale)
        )
        captured: dict[str, str] = {}

        _, result = await _run(session_factory, db, tenant, user, competence, captured)

        assert result["status"] == "ready"
        assert f"Generate ALL content in {expected}." in captured["user"]
        assert (
            captured["user"]
            .rstrip()
            .endswith("and any skill-level or grade titles that come from the input.")
        )

    async def test_directive_still_in_system_prompt(
        self, db, tenant, user, competence, session_factory
    ) -> None:
        """Restating it in the user turn must not remove it from the system."""
        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(content_language="de")
        )
        captured: dict[str, str] = {}

        await _run(session_factory, db, tenant, user, competence, captured)

        assert "Generate ALL content in German." in captured["system"]

    async def test_non_english_run_does_not_ask_for_english(
        self, db, tenant, user, competence, session_factory
    ) -> None:
        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(content_language="ru")
        )
        captured: dict[str, str] = {}

        await _run(session_factory, db, tenant, user, competence, captured)

        assert "Generate ALL content in English." not in captured["user"]
        assert "Generate ALL content in English." not in captured["system"]

    async def test_verbatim_carve_out_is_restated_with_the_directive(
        self, db, tenant, user, competence, session_factory
    ) -> None:
        """The carve-out travels with the directive.

        It is what keeps ``skill_level`` — a join key resolved by title at
        apply time — from being translated along with the prose.
        """
        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(content_language="de")
        )
        captured: dict[str, str] = {}

        await _run(session_factory, db, tenant, user, competence, captured)

        assert "Echo machine-readable values verbatim" in captured["user"]


class TestSkillLevelSnapping:
    """The model's echo is snapped back to the exact offered title."""

    def test_exact_match_is_kept(self):
        assert tasks._snap_skill_level("Basic", ["Basic", "Advanced"]) == "Basic"

    def test_case_difference_snaps(self):
        assert tasks._snap_skill_level("basic", ["Basic", "Advanced"]) == "Basic"

    def test_surrounding_whitespace_snaps(self):
        assert tasks._snap_skill_level(" Advanced\n", ["Basic", "Advanced"]) == (
            "Advanced"
        )

    def test_unknown_value_is_left_alone(self):
        """It may still resolve by i18n_key; guessing would be worse."""
        assert tasks._snap_skill_level("Fortgeschritten", ["Basic"]) == (
            "Fortgeschritten"
        )

    def test_no_offered_levels_leaves_value_untouched(self):
        assert tasks._snap_skill_level("basic", []) == "basic"

    def test_normalise_indicators_snaps_every_row(self):
        payload = {
            "indicators": [
                {"title": "a", "skill_level": "basic"},
                {"title": "b", "skill_level": "ADVANCED"},
            ]
        }
        normalised, selection = tasks._normalise_indicators(
            payload, ["Basic", "Advanced"]
        )
        assert [i["skill_level"] for i in normalised["indicators"]] == [
            "Basic",
            "Advanced",
        ]
        assert all(selection.values())

    async def test_payload_stores_resolvable_levels(
        self, db, tenant, user, competence, session_factory
    ) -> None:
        """End-to-end: the stored payload carries the tenant's own titles."""
        captured: dict[str, str] = {}

        sess, result = await _run(
            session_factory, db, tenant, user, competence, captured
        )

        assert result["status"] == "ready"
        await db.refresh(sess)
        stored = [i["skill_level"] for i in sess.payload["indicators"]]
        assert stored == ["Basic", "Advanced"]

    async def test_snapped_indicators_survive_apply(
        self, db, tenant, user, competence, session_factory, levels
    ) -> None:
        """The whole point: nothing is silently dropped at apply time.

        The padded " Advanced\\n" echo misses `title ILIKE` outright, so
        before snapping that indicator never reached the database.
        """
        from app.modules.competence.models import Indicator
        from sqlalchemy import select

        sess, _ = await _run(session_factory, db, tenant, user, competence, {})
        await db.refresh(sess)

        await service.apply_session(
            db,
            sess.id,
            user_id=user.id,
            tenant_id=tenant.id,
            publish=True,
            idempotency_key=f"hrp541-{sess.id}",
        )

        rows = (
            (
                await db.execute(
                    select(Indicator.title).where(
                        Indicator.competence_id == competence.id,
                        Indicator.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "Kennt die REST-Verben" in rows
        assert "Entwirft idempotente Endpunkte" in rows


class TestTreeScopeSnapping:
    """Tree scopes lose nodes the same way — same resolver, same silent skip.

    ``_apply_group_recursive`` and ``_apply_specialization_matrix`` both call
    ``_resolve_skill_level`` and ``continue`` on a miss, so whole_base, group
    and specialization_matrix need the same normalisation as the indicators
    scope (HRP-541 review).
    """

    def test_tree_indicators_are_snapped(self):
        payload = {
            "groups": [
                {
                    "title": "G",
                    "competences": [
                        {
                            "title": "C",
                            "indicators": [
                                {"title": "a", "skill_level": " basic "},
                                {"title": "b", "skill_level": "ADVANCED"},
                            ],
                        }
                    ],
                }
            ]
        }
        normalised, _ = tasks._normalise_tree(payload, ["Basic", "Advanced"])
        levels = [
            i["skill_level"]
            for i in normalised["groups"][0]["competences"][0]["indicators"]
        ]
        assert levels == ["Basic", "Advanced"]

    def test_nested_children_are_snapped(self):
        payload = {
            "groups": [
                {
                    "title": "root",
                    "children": [
                        {
                            "title": "child",
                            "competences": [
                                {
                                    "title": "C",
                                    "indicators": [
                                        {"title": "a", "skill_level": "basic"}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        normalised, _ = tasks._normalise_tree(payload, ["Basic"])
        child = normalised["groups"][0]["children"][0]
        assert child["competences"][0]["indicators"][0]["skill_level"] == "Basic"

    def test_matrix_grade_levels_snapped_on_both_sides(self):
        """Keys are grade titles, values are skill levels — different lists."""
        payload = {
            "groups": [
                {
                    "title": "G",
                    "competences": [
                        {
                            "title": "C",
                            "indicators": [],
                            "grade_levels": {" junior ": "basic", "SENIOR": "advanced"},
                        }
                    ],
                }
            ]
        }
        normalised, _ = tasks._normalise_tree(
            payload, ["Basic", "Advanced"], ["Junior", "Senior"]
        )
        assert normalised["groups"][0]["competences"][0]["grade_levels"] == {
            "Junior": "Basic",
            "Senior": "Advanced",
        }

    async def test_whole_base_run_carries_the_tenant_levels(
        self, db, tenant, user, session_factory, levels, specialization
    ) -> None:
        """End-to-end on a non-en tenant: the worker knows the real levels."""
        from app.modules.ai_competence_generation.schemas import GeneratedTreeSchema

        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(content_language="de")
        )
        sess = await service.create_session(
            db, tenant.id, user.id, SessionCreate(scope="whole_base")
        )
        tree = {
            "groups": [
                {
                    "title": "Integration",
                    "competences": [
                        {
                            "title": "Messaging",
                            "indicators": [
                                {
                                    "title": "Kennt Zustellgarantien",
                                    "skill_level": "basic",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        captured: dict[str, str] = {}

        async def capture(prompt, system=None, **_):
            captured["user"] = prompt
            return GeneratedTreeSchema.model_validate(tree)

        with patch.object(llm_client, "generate_json", side_effect=capture):
            result = await tasks.execute_session(session_factory, sess.id)

        assert result["status"] == "ready"
        assert "Generate ALL content in German." in captured["user"]
        await db.refresh(sess)
        stored = sess.payload["groups"][0]["competences"][0]["indicators"][0]
        assert stored["skill_level"] == "Basic"


class TestIndicatorPromptInputs:
    async def test_existing_indicators_carry_their_skill_level(
        self, db, tenant, user, competence, session_factory
    ) -> None:
        """Blanking it hid which levels were already covered (HRP-541).

        It also stripped the only place the tenant's own level titles
        reached the prompt.
        """
        captured: dict[str, str] = {}

        await _run(session_factory, db, tenant, user, competence, captured)

        assert "Explains at-least-once delivery" in captured["user"]
        assert '"skill_level": ""' not in captured["user"]

    async def test_competence_type_comes_from_the_competence(
        self, db, tenant, user, competence, session_factory
    ) -> None:
        """Soft-skill competences were announced to the model as hard skills.

        "Soft skill" is the title the origin seed actually ships, so the
        prompt carries the tenant-visible wording.
        """
        soft = DictionaryItem(
            type="competence_type",
            title="Soft skill",
            tenant_id=tenant.id,
            sort_index=0,
            is_active=True,
        )
        db.add(soft)
        await db.commit()
        await db.refresh(soft)
        competence.competence_type_id = soft.id
        await db.commit()

        captured: dict[str, str] = {}
        await _run(session_factory, db, tenant, user, competence, captured)

        assert '"competence_type": "Soft skill"' in captured["user"]

    async def test_untyped_competence_falls_back_to_hard_skill(
        self, db, tenant, user, competence, session_factory
    ) -> None:
        captured: dict[str, str] = {}

        await _run(session_factory, db, tenant, user, competence, captured)

        assert '"competence_type": "hard_skill"' in captured["user"]
