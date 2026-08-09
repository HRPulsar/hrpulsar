"""HRP-373: several internal evaluators inside one assessment round.

Covers the eligibility list behind `+ Add evaluator`, the role gate on the
add itself, the avatar payload the round header renders, and the rule that
a colleague's sheet stays hidden until the viewer's own one is in.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    RoundCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _external_sheet,
    _make_candidate_vacancy,
    _make_extra_user,
    _make_profile,
    _make_vacancy,
)


async def _grant_role(db: AsyncSession, tenant, user, code: str) -> None:
    from app.modules.auth.models import Role, user_roles
    from sqlalchemy import insert, select

    role = (
        await db.execute(select(Role).where(Role.code == code))
    ).scalar_one_or_none()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.flush()
    await db.execute(insert(user_roles).values(user_id=user.id, role_id=role.id))
    await db.commit()


async def _round(db: AsyncSession, tenant, user, kind: str = "interview"):
    vacancy = await _make_vacancy(db, tenant)
    await _make_profile(db, tenant, vacancy)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type=kind)
    )
    return cv, uuid.UUID(str(rd["id"]))


class TestEligibleEvaluators:
    async def test_only_allowed_roles_are_listed(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        manager = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, manager, "manager")
        outsider = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, outsider, "employee")

        rows = await service.list_eligible_evaluators(db, tenant.id, rd_id)
        ids = {r["id"] for r in rows}
        assert manager.id in ids
        # `user` carries the admin role from the fixture.
        assert user.id in ids
        assert outsider.id not in ids

    async def test_already_added_evaluators_are_flagged_not_dropped(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

        rows = await service.list_eligible_evaluators(db, tenant.id, rd_id)
        me = next(r for r in rows if r["id"] == user.id)
        assert me["already_evaluator"] is True

    async def test_full_name_falls_back_to_the_email_local_part(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        nameless = await _make_extra_user(db, tenant)
        nameless.first_name = ""
        nameless.last_name = ""
        await db.commit()
        await _grant_role(db, tenant, nameless, "manager")

        rows = await service.list_eligible_evaluators(db, tenant.id, rd_id)
        row = next(r for r in rows if r["id"] == nameless.id)
        assert row["full_name"] == nameless.email.split("@")[0]


class TestAddEvaluator:
    async def test_colleague_with_allowed_role_is_added_and_notified(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        colleague = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, colleague, "manager")

        with patch("app.core.events.publish", new=AsyncMock()) as publish:
            rd = await service.add_evaluator(
                db, tenant.id, user.id, rd_id, colleague.id
            )

        assert {e["user_id"] for e in rd["evaluators"]} == {colleague.id}
        event, payload = publish.call_args.args
        assert event == "recruitment.assessment.evaluator_invited"
        assert payload["evaluator_user_id"] == str(colleague.id)
        # The link lands on the candidate page in the vacancy's context
        # with the round preselected (decision recorded on HRP-373).
        assert "?vacancyId=" in payload["link"]
        assert f"round={rd_id}" in payload["link"]

    async def test_ineligible_role_is_rejected(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        outsider = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, outsider, "employee")

        with pytest.raises(HTTPException) as exc:
            await service.add_evaluator(db, tenant.id, user.id, rd_id, outsider.id)
        assert exc.value.status_code == 403

    async def test_self_add_bypasses_the_role_list(
        self, db: AsyncSession, tenant, admin_role
    ):
        """`Start scoring this round` must keep working for a recruiter."""
        recruiter = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, recruiter, "recruiter")
        _, rd_id = await _round(db, tenant, recruiter)

        rd = await service.add_evaluator(
            db, tenant.id, recruiter.id, rd_id, recruiter.id
        )
        assert {e["user_id"] for e in rd["evaluators"]} == {recruiter.id}

    async def test_re_adding_does_not_send_a_second_notification(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        colleague = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, colleague, "manager")

        with patch("app.core.events.publish", new=AsyncMock()) as publish:
            await service.add_evaluator(db, tenant.id, user.id, rd_id, colleague.id)
            await service.add_evaluator(db, tenant.id, user.id, rd_id, colleague.id)
        assert publish.call_count == 1

    async def test_pre_interview_refuses_a_second_evaluator(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user, kind="pre_interview")
        colleague = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, colleague, "manager")

        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
        with pytest.raises(HTTPException) as exc:
            await service.add_evaluator(db, tenant.id, user.id, rd_id, colleague.id)
        assert exc.value.status_code == 409

    async def test_notification_failure_does_not_lose_the_evaluator(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        colleague = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, colleague, "manager")

        with patch(
            "app.core.events.publish", new=AsyncMock(side_effect=RuntimeError("bus"))
        ):
            rd = await service.add_evaluator(
                db, tenant.id, user.id, rd_id, colleague.id
            )
        assert {e["user_id"] for e in rd["evaluators"]} == {colleague.id}


class TestRoundEvaluatorPayload:
    async def test_avatar_initials_and_submitted_flag(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id = await _round(db, tenant, user)
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

        rd = await service._load_round(db, tenant.id, rd_id)
        rounds = await service.list_rounds(db, tenant.id, rd.candidate_vacancy_id)
        evaluator = rounds[0]["evaluators"][0]
        assert evaluator["initials"] == service._initials(
            f"{user.first_name} {user.last_name}"
        )
        assert evaluator["full_name"] == f"{user.first_name} {user.last_name}"
        assert evaluator["submitted"] is False

    def test_initials_of_a_single_word_name(self):
        assert service._initials("Cher") == "CH"
        assert service._initials("Anna Petrova") == "AP"
        assert service._initials("") == "?"


class TestColleagueSheetVisibility:
    async def _two_evaluators(self, db, tenant, user):
        cv, rd_id = await _round(db, tenant, user)
        colleague = await _make_extra_user(db, tenant)
        await _grant_role(db, tenant, colleague, "manager")
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
        with patch("app.core.events.publish", new=AsyncMock()):
            await service.add_evaluator(db, tenant.id, user.id, rd_id, colleague.id)
        return rd_id, colleague, cv

    async def test_colleague_sheet_hidden_until_own_is_submitted(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        rd_id, _colleague, _cv = await self._two_evaluators(db, tenant, user)

        visible = await service.list_assessments_for_round(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        assert {a["evaluator_user_id"] for a in visible} == {user.id}

    async def test_colleague_sheet_visible_after_own_submit(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        rd_id, colleague, _cv = await self._two_evaluators(db, tenant, user)
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.submit_assessment(db, tenant.id, user.id, own.id)

        visible = await service.list_assessments_for_round(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        assert {a["evaluator_user_id"] for a in visible} == {user.id, colleague.id}

    async def test_unfiltered_view_without_a_viewer(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        rd_id, colleague, _cv = await self._two_evaluators(db, tenant, user)
        rows = await service.list_assessments_for_round(db, tenant.id, rd_id)
        assert {a["evaluator_user_id"] for a in rows} == {user.id, colleague.id}

    async def test_external_sheets_are_never_hidden(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        # HRP-377's "View submission" reads them, and they are the
        # recruiter's own collected material — not a colleague's opinion.
        rd_id, _colleague, cv = await self._two_evaluators(db, tenant, user)
        external = await _external_sheet(db, tenant, cv, rd_id, name="Ext")

        visible = await service.list_assessments_for_round(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        assert external.id in {a["id"] for a in visible}

    async def test_gate_lifts_once_the_round_is_complete(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        rd_id, colleague, _cv = await self._two_evaluators(db, tenant, user)
        await service.update_round_status(db, tenant.id, user.id, rd_id, "complete")
        visible = await service.list_assessments_for_round(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        assert {a["evaluator_user_id"] for a in visible} == {user.id, colleague.id}


async def _round_scored_by_a_colleague(db, tenant, user):
    """Two evaluators on one round; only the colleague has scored."""
    cv, rd_id = await _round(db, tenant, user)
    colleague = await _make_extra_user(db, tenant)
    await _grant_role(db, tenant, colleague, "manager")
    await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
    with patch("app.core.events.publish", new=AsyncMock()):
        await service.add_evaluator(db, tenant.id, user.id, rd_id, colleague.id)
    sheet = await service.get_or_create_assessment(
        db, tenant.id, rd_id, evaluator_user_id=colleague.id
    )
    await service.set_competence_score(
        db,
        tenant.id,
        colleague.id,
        sheet.id,
        uuid.uuid4(),
        CompetenceScoreIn(score_value=4),
    )
    return cv, rd_id, colleague, sheet


class TestAggregateAnchoring:
    """The round aggregate names every scorer, so it obeys the same gate.

    Hiding only ``scorers`` would not be enough: with two evaluators the
    colleague's exact level falls straight out of ``average`` and the
    viewer's own number, so the aggregate is computed over the sheets the
    viewer is allowed to see at all.
    """

    async def test_colleague_scores_stay_out_until_own_submit(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id, _colleague, _sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        agg = await service.round_aggregate(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        assert agg["competences"] == []
        assert agg["average"] is None

    async def test_gate_lifts_after_own_submit(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id, colleague, _sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.submit_assessment(db, tenant.id, user.id, own.id)

        agg = await service.round_aggregate(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        assert agg["average"] == 4.0
        scorers = agg["competences"][0]["scorers"]
        assert [s["score"] for s in scorers] == [4]

    async def test_gate_lifts_once_the_round_is_closed(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id, _colleague, _sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")
        agg = await service.round_aggregate(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        assert agg["average"] == 4.0

    async def test_a_watcher_outside_the_round_keeps_the_full_view(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        # An admin/recruiter who is not scoring this round has nothing to
        # anchor — the round header must still show them the real numbers.
        _, rd_id, _colleague, _sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        watcher = await _make_extra_user(db, tenant)
        agg = await service.round_aggregate(
            db, tenant.id, rd_id, viewer_user_id=watcher.id
        )
        assert agg["average"] == 4.0
        assert agg["competences"][0]["scorers"]

    async def test_internal_callers_keep_the_unfiltered_aggregate(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id, _colleague, _sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 4.0


class TestSingleSheetAnchoring:
    """Fetching the colleague's sheet by id is the same disclosure."""

    async def test_colleague_sheet_by_id_is_refused(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, _rd_id, _colleague, sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        with pytest.raises(HTTPException) as exc:
            await service.get_assessment(
                db, tenant.id, sheet.id, viewer_user_id=user.id
            )
        assert exc.value.status_code == 403

    async def test_own_sheet_is_always_readable(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id, _colleague, _sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        out = await service.get_assessment(
            db, tenant.id, own.id, viewer_user_id=user.id
        )
        assert out["id"] == own.id

    async def test_colleague_sheet_opens_after_own_submit(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, rd_id, _colleague, sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.submit_assessment(db, tenant.id, user.id, own.id)

        out = await service.get_assessment(
            db, tenant.id, sheet.id, viewer_user_id=user.id
        )
        assert out["id"] == sheet.id

    async def test_a_watcher_outside_the_round_may_read_it(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        _, _rd_id, _colleague, sheet = await _round_scored_by_a_colleague(
            db, tenant, user
        )
        watcher = await _make_extra_user(db, tenant)
        out = await service.get_assessment(
            db, tenant.id, sheet.id, viewer_user_id=watcher.id
        )
        assert out["id"] == sheet.id
