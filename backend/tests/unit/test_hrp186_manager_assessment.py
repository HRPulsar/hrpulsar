"""HRP-186: manager assessment + invited evaluator unit coverage."""

from __future__ import annotations

import uuid

import pytest
from app.models import Person
from app.modules.recruitment import (
    manager_assessment_public as public_service,
)
from app.modules.recruitment import (
    manager_assessment_service as service,
)
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    IndicatorScoreIn,
    ManagerAssessmentInviteCreate,
    ManagerAssessmentInviteIn,
    RoundCreate,
    ScaleCreate,
    ScaleLevelIn,
    ScaleUpdate,
)
from app.modules.recruitment.models import (
    AssessmentInvite,
    Candidate,
    CandidateVacancy,
    Vacancy,
    VacancyProfile,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_vacancy(db: AsyncSession, tenant) -> Vacancy:
    v = Vacancy(tenant_id=tenant.id, title=f"V {uuid.uuid4().hex[:6]}", status="open")
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


DEFAULT_PROFILE_COMPETENCES = [
    {
        "id": "communication",
        "name": "Communication",
        "criticality": "critical",
        "indicators": ["Clear writing", "Active listening"],
    },
    {
        "id": "sales",
        "name": "Sales",
        "criticality": "important",
        "indicators": [],
    },
]


async def _make_profile(
    db: AsyncSession, tenant, vacancy: Vacancy, *, competences=None
) -> VacancyProfile:
    """Vacancy profile with competences — required to send invites (HRP-352)."""
    profile = VacancyProfile(
        tenant_id=tenant.id,
        vacancy_id=vacancy.id,
        profile_data={
            "competences": (
                DEFAULT_PROFILE_COMPETENCES if competences is None else competences
            ),
            "salary": {"min": 1, "max": 2},
        },
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def _make_candidate_vacancy(
    db: AsyncSession, tenant, vacancy: Vacancy
) -> CandidateVacancy:
    person = Person(
        first_name=f"F{uuid.uuid4().hex[:4]}",
        last_name=f"L{uuid.uuid4().hex[:4]}",
    )
    db.add(person)
    await db.flush()
    candidate = Candidate(
        tenant_id=tenant.id,
        person_id=person.id,
        full_name=f"{person.first_name} {person.last_name}",
    )
    db.add(candidate)
    await db.flush()
    cv = CandidateVacancy(
        tenant_id=tenant.id,
        candidate_id=candidate.id,
        vacancy_id=vacancy.id,
    )
    db.add(cv)
    await db.commit()
    await db.refresh(cv)
    return cv


async def _make_extra_user(db: AsyncSession, tenant):
    """Create a second authenticated user for parallel-evaluator tests."""
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User

    u = User(
        email=f"extra-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Extra",
        last_name="Eval",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def _in_a_week():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(days=7)


async def _external_sheet(db: AsyncSession, tenant, cv, round_id, *, name: str):
    """An invited (external) evaluator with their own sheet on a round."""
    invite = AssessmentInvite(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        token=uuid.uuid4().hex,
        token_hash=uuid.uuid4().hex,
        email=f"{uuid.uuid4().hex[:6]}@example.com",
        evaluator_name=name,
        status="pending",
        expires_at=_in_a_week(),
        round_id=round_id,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return await service.get_or_create_assessment(
        db, tenant.id, round_id, evaluator_invite_id=invite.id
    )


def _scale_payload(name: str = "Standard") -> ScaleCreate:
    return ScaleCreate(
        name=name,
        description="test scale",
        is_default=True,
        levels=[
            ScaleLevelIn(value=1, label="L1", weight=0),
            ScaleLevelIn(value=2, label="L2", weight=33),
            ScaleLevelIn(value=3, label="L3", weight=66),
            ScaleLevelIn(value=4, label="L4", weight=100),
        ],
    )


# ---------------------------------------------------------------------------
# Scales
# ---------------------------------------------------------------------------


class TestScales:
    async def test_create_scale_requires_2_to_10_levels(
        self, db: AsyncSession, tenant, user
    ):
        with pytest.raises(ValueError):
            ScaleCreate(name="x", levels=[ScaleLevelIn(value=1, label="x", weight=0)])
        with pytest.raises(ValueError):
            ScaleCreate(
                name="x",
                levels=[
                    ScaleLevelIn(value=i, label=str(i), weight=i) for i in range(11)
                ],
            )

    async def test_create_scale_with_duplicate_values_rejected(
        self, db: AsyncSession, tenant, user
    ):
        with pytest.raises(ValueError):
            ScaleCreate(
                name="x",
                levels=[
                    ScaleLevelIn(value=1, label="a", weight=0),
                    ScaleLevelIn(value=1, label="b", weight=50),
                ],
            )

    async def test_only_one_default_scale_per_tenant(
        self, db: AsyncSession, tenant, user
    ):
        first = await service.create_scale(db, tenant.id, user.id, _scale_payload("A"))
        await service.create_scale(db, tenant.id, user.id, _scale_payload("B"))
        # Both started with is_default=True but only the latest stays default.
        first_id = uuid.UUID(str(first["id"]))
        scales = {str(s["id"]): s for s in await service.list_scales(db, tenant.id)}
        defaults = [s for s in scales.values() if s["is_default"]]
        assert len(defaults) == 1
        assert str(defaults[0]["id"]) != str(first_id)

    async def test_default_scale_is_seeded_when_missing(
        self, db: AsyncSession, tenant, user
    ):
        scales = await service.list_scales(db, tenant.id)
        assert len(scales) == 1
        assert scales[0]["is_default"] is True
        assert len(scales[0]["levels"]) == 4


# ---------------------------------------------------------------------------
# Vacancy snapshot
# ---------------------------------------------------------------------------


class TestVacancyScale:
    async def test_snapshot_locked_after_first_score(
        self, db: AsyncSession, tenant, user
    ):
        scale = await service.create_scale(db, tenant.id, user.id, _scale_payload())
        other = await service.create_scale(
            db, tenant.id, user.id, _scale_payload("Other")
        )
        vacancy = await _make_vacancy(db, tenant)
        await service.set_vacancy_scale(
            db, tenant.id, user.id, vacancy.id, uuid.UUID(str(scale["id"]))
        )
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db,
            tenant.id,
            user.id,
            cv.id,
            RoundCreate(type="pre_interview"),
        )
        a = await service.get_or_create_assessment(
            db,
            tenant.id,
            uuid.UUID(str(rd["id"])),
            evaluator_user_id=user.id,
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            uuid.uuid4(),
            CompetenceScoreIn(score_value=3),
        )
        # Snapshot is now frozen; switching scales fails.
        with pytest.raises(HTTPException) as ei:
            await service.set_vacancy_scale(
                db,
                tenant.id,
                user.id,
                vacancy.id,
                uuid.UUID(str(other["id"])),
            )
        assert ei.value.status_code == 409


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


class TestRounds:
    async def test_pre_interview_unique_per_cv(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="pre_interview")
        )
        with pytest.raises(HTTPException) as ei:
            await service.create_round(
                db,
                tenant.id,
                user.id,
                cv.id,
                RoundCreate(type="pre_interview"),
            )
        assert ei.value.status_code == 409

    async def test_interview_rounds_increment(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        r1 = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        r2 = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        assert r1["round_number"] == 1
        assert r2["round_number"] == 2


# ---------------------------------------------------------------------------
# Parallel evaluators
# ---------------------------------------------------------------------------


class TestParallelEvaluators:
    async def test_separate_sheets_per_evaluator(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd_dict = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        rd_id = uuid.UUID(str(rd_dict["id"]))

        a1 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        # Different evaluator → different sheet
        other_user = await _make_extra_user(db, tenant)
        other_user_id = other_user.id
        a2 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=other_user_id
        )
        assert a1.id != a2.id

        cid = uuid.uuid4()
        await service.set_competence_score(
            db, tenant.id, user.id, a1.id, cid, CompetenceScoreIn(score_value=3)
        )
        await service.set_competence_score(
            db, tenant.id, other_user_id, a2.id, cid, CompetenceScoreIn(score_value=1)
        )

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        scores_by_competence = {c["competence_id"]: c for c in agg["competences"]}
        entry = scores_by_competence[str(cid)]
        assert entry["min"] == 1
        assert entry["max"] == 3
        # The default divergence threshold (2) marks spread ≥2 as divergent.
        assert entry["diverges"] is True


# ---------------------------------------------------------------------------
# Pre-interview: single evaluator (HRP-369)
# ---------------------------------------------------------------------------


class TestPreInterviewSingleEvaluator:
    async def _make_pre_interview_round(self, db, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="pre_interview")
        )
        return uuid.UUID(str(rd["id"])), cv

    async def test_first_evaluator_can_start_scoring(
        self, db: AsyncSession, tenant, user
    ):
        # HRP-369: the guard used to reject even the FIRST "Start scoring
        # this round" click.
        rd_id, _cv = await self._make_pre_interview_round(db, tenant, user)
        result = await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
        assert result is not None

        sheet = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        assert sheet.evaluator_user_id == user.id

    async def test_same_evaluator_readd_is_idempotent(
        self, db: AsyncSession, tenant, user
    ):
        rd_id, _cv = await self._make_pre_interview_round(db, tenant, user)
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
        # Second click by the same user must not raise.
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

    async def test_second_evaluator_rejected(self, db: AsyncSession, tenant, user):
        rd_id, _cv = await self._make_pre_interview_round(db, tenant, user)
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

        other = await _make_extra_user(db, tenant)
        with pytest.raises(HTTPException) as ei:
            await service.add_evaluator(db, tenant.id, other.id, rd_id, other.id)
        assert ei.value.status_code == 409
        assert "single evaluator" in ei.value.detail

    async def test_invited_sheet_blocks_internal_evaluator(
        self, db: AsyncSession, tenant, user
    ):
        # An external (invited) evaluator sheet also occupies the single
        # pre_interview slot.
        from datetime import datetime, timedelta, timezone

        rd_id, cv = await self._make_pre_interview_round(db, tenant, user)
        invite = AssessmentInvite(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv.id,
            token=f"tok-{uuid.uuid4().hex}",
            token_hash=f"hash-{uuid.uuid4().hex}",
            email="ext@test.com",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            round_id=rd_id,
        )
        db.add(invite)
        await db.commit()
        await db.refresh(invite)
        await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_invite_id=invite.id
        )

        with pytest.raises(HTTPException) as ei:
            await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
        assert ei.value.status_code == 409

    async def test_multi_evaluator_rounds_unaffected(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        rd_id = uuid.UUID(str(rd["id"]))
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
        other = await _make_extra_user(db, tenant)
        await service.add_evaluator(db, tenant.id, other.id, rd_id, other.id)

    def _invite_row(self, tenant, cv, rd_id, **overrides):
        from datetime import datetime, timedelta, timezone

        fields = {
            "tenant_id": tenant.id,
            "candidate_vacancy_id": cv.id,
            "token": f"tok-{uuid.uuid4().hex}",
            "token_hash": f"hash-{uuid.uuid4().hex}",
            "email": "ext@test.com",
            "status": "pending",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
            "round_id": rd_id,
        }
        fields.update(overrides)
        return AssessmentInvite(**fields)

    async def test_internal_evaluator_blocks_invite_acceptance(
        self, db: AsyncSession, tenant, user
    ):
        # Reverse direction of test_invited_sheet_blocks_internal_evaluator:
        # the consent-acceptance sheet creation must respect the slot too.
        rd_id, cv = await self._make_pre_interview_round(db, tenant, user)
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

        invite = self._invite_row(tenant, cv, rd_id)
        db.add(invite)
        await db.commit()
        await db.refresh(invite)
        with pytest.raises(HTTPException) as ei:
            await service.get_or_create_assessment(
                db, tenant.id, rd_id, evaluator_invite_id=invite.id
            )
        assert ei.value.status_code == 409

    async def test_internal_evaluator_blocks_new_invite(
        self, db: AsyncSession, tenant, user
    ):
        rd_id, cv = await self._make_pre_interview_round(db, tenant, user)
        await _make_profile(db, tenant, await db.get(Vacancy, cv.vacancy_id))
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

        with pytest.raises(HTTPException) as ei:
            await service.create_invites(
                db,
                tenant.id,
                user.id,
                cv.id,
                ManagerAssessmentInviteCreate(
                    round_id=rd_id,
                    invitees=[
                        ManagerAssessmentInviteIn(email="ext@test.com", name="Ext Eval")
                    ],
                ),
            )
        assert ei.value.status_code == 409

    async def test_multiple_invitees_rejected_for_pre_interview(
        self, db: AsyncSession, tenant, user
    ):
        rd_id, cv = await self._make_pre_interview_round(db, tenant, user)
        await _make_profile(db, tenant, await db.get(Vacancy, cv.vacancy_id))

        with pytest.raises(HTTPException) as ei:
            await service.create_invites(
                db,
                tenant.id,
                user.id,
                cv.id,
                ManagerAssessmentInviteCreate(
                    round_id=rd_id,
                    invitees=[
                        ManagerAssessmentInviteIn(email="a@test.com", name="Eval A"),
                        ManagerAssessmentInviteIn(email="b@test.com", name="Eval B"),
                    ],
                ),
            )
        assert ei.value.status_code == 409

    async def test_live_invite_blocks_second_invite(
        self, db: AsyncSession, tenant, user
    ):
        rd_id, cv = await self._make_pre_interview_round(db, tenant, user)
        await _make_profile(db, tenant, await db.get(Vacancy, cv.vacancy_id))
        db.add(self._invite_row(tenant, cv, rd_id))
        await db.commit()

        with pytest.raises(HTTPException) as ei:
            await service.create_invites(
                db,
                tenant.id,
                user.id,
                cv.id,
                ManagerAssessmentInviteCreate(
                    round_id=rd_id,
                    invitees=[
                        ManagerAssessmentInviteIn(email="b@test.com", name="Eval B")
                    ],
                ),
            )
        assert ei.value.status_code == 409

    async def test_pending_invite_does_not_block_start_scoring(
        self, db: AsyncSession, tenant, user
    ):
        # An invitation alone doesn't claim the slot — only a sheet does;
        # whoever materializes first wins, the other gets the 409.
        rd_id, cv = await self._make_pre_interview_round(db, tenant, user)
        db.add(self._invite_row(tenant, cv, rd_id))
        await db.commit()

        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

    async def test_revoked_invite_sheet_frees_the_slot(
        self, db: AsyncSession, tenant, user
    ):
        # A revoked invite's sheet must not brick the round forever.
        rd_id, cv = await self._make_pre_interview_round(db, tenant, user)
        invite = self._invite_row(tenant, cv, rd_id)
        db.add(invite)
        await db.commit()
        await db.refresh(invite)
        await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_invite_id=invite.id
        )
        await service.revoke_invite(db, tenant.id, user.id, invite.id)

        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)


# ---------------------------------------------------------------------------
# Indicator → Overall computed
# ---------------------------------------------------------------------------


class TestIndicators:
    async def test_indicator_score_promotes_overall_computed(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd_dict = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        rd_id = uuid.UUID(str(rd_dict["id"]))
        a = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        comp_id = uuid.uuid4()
        ind1, ind2 = uuid.uuid4(), uuid.uuid4()
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            ind1,
            IndicatorScoreIn(competence_id=comp_id, score_value=2),
        )
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            ind2,
            IndicatorScoreIn(competence_id=comp_id, score_value=4),
        )
        sheet = await service.get_assessment(db, tenant.id, a.id)
        overall = [
            c
            for c in sheet["competence_scores"]
            if str(c["competence_id"]) == str(comp_id)
        ]
        assert overall, "Overall row must exist after indicator scoring"
        assert overall[0]["score_source"] == "computed_from_indicators"
        assert overall[0]["score_value"] == 3

    async def test_clearing_all_indicators_clears_computed_overall(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-348: un-scoring the last indicator must not leave a stale
        computed overall keeping the competence 'assessed'."""
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd_dict = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        rd_id = uuid.UUID(str(rd_dict["id"]))
        a = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        comp_id = uuid.uuid4()
        ind = uuid.uuid4()
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            ind,
            IndicatorScoreIn(competence_id=comp_id, score_value=4),
        )
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            ind,
            IndicatorScoreIn(competence_id=comp_id, score_value=None),
        )
        sheet = await service.get_assessment(db, tenant.id, a.id)
        overall = [
            c
            for c in sheet["competence_scores"]
            if str(c["competence_id"]) == str(comp_id)
        ]
        assert overall
        assert overall[0]["score_value"] is None

    async def test_manual_overall_survives_indicator_clear(
        self, db: AsyncSession, tenant, user
    ):
        """A manually chosen overall is never wiped by indicator edits."""
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd_dict = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        rd_id = uuid.UUID(str(rd_dict["id"]))
        a = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        comp_id = uuid.uuid4()
        ind = uuid.uuid4()
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(score_value=2, score_source="manual"),
        )
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            ind,
            IndicatorScoreIn(competence_id=comp_id, score_value=None),
        )
        sheet = await service.get_assessment(db, tenant.id, a.id)
        overall = [
            c
            for c in sheet["competence_scores"]
            if str(c["competence_id"]) == str(comp_id)
        ]
        assert overall
        assert overall[0]["score_value"] == 2
        assert overall[0]["score_source"] == "manual"


# ---------------------------------------------------------------------------
# Aggregation — last completed round wins
# ---------------------------------------------------------------------------


class TestAggregation:
    async def test_last_complete_round_wins(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        scale = await service.create_scale(db, tenant.id, user.id, _scale_payload())
        await service.set_vacancy_scale(
            db, tenant.id, user.id, vacancy.id, uuid.UUID(str(scale["id"]))
        )

        r1 = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        a1 = await service.get_or_create_assessment(
            db, tenant.id, uuid.UUID(str(r1["id"])), evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a1.id,
            uuid.uuid4(),
            CompetenceScoreIn(score_value=4),
        )
        await service.update_round_status(
            db, tenant.id, user.id, uuid.UUID(str(r1["id"])), "complete"
        )

        r2 = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        a2 = await service.get_or_create_assessment(
            db, tenant.id, uuid.UUID(str(r2["id"])), evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a2.id,
            uuid.uuid4(),
            CompetenceScoreIn(score_value=2),
        )
        await service.update_round_status(
            db, tenant.id, user.id, uuid.UUID(str(r2["id"])), "complete"
        )

        await db.refresh(cv)
        assert cv.manager_score == 2.0
        assert cv.manager_score_source_round_id == uuid.UUID(str(r2["id"]))


# ---------------------------------------------------------------------------
# Invites + token hashing + public flow
# ---------------------------------------------------------------------------


class TestInvitesPublic:
    async def test_invite_token_hashed_in_db(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await _make_profile(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )

        results = await service.create_invites(
            db,
            tenant.id,
            user.id,
            cv.id,
            ManagerAssessmentInviteCreate(
                invitees=[
                    ManagerAssessmentInviteIn(
                        email="ext@example.com", name="External Eval"
                    )
                ],
                round_id=uuid.UUID(str(rd["id"])),
                expires_in_days=5,
            ),
        )
        invite_id = uuid.UUID(str(results[0]["id"]))
        # Load directly to inspect both token and token_hash columns.
        from sqlalchemy import select

        row = (
            await db.execute(
                select(AssessmentInvite).where(AssessmentInvite.id == invite_id)
            )
        ).scalar_one()
        assert row.token_hash is not None
        assert row.token is not None
        # The plaintext token in the row matches the hash function output.
        assert row.token_hash == service.hash_token(row.token)

    async def test_public_resolves_by_token_and_logs_open(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await _make_profile(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        results = await service.create_invites(
            db,
            tenant.id,
            user.id,
            cv.id,
            ManagerAssessmentInviteCreate(
                invitees=[
                    ManagerAssessmentInviteIn(email="ext@example.com", name="External")
                ],
                round_id=uuid.UUID(str(rd["id"])),
                expires_in_days=5,
            ),
        )
        invite_id = uuid.UUID(str(results[0]["id"]))
        from sqlalchemy import select

        row = (
            await db.execute(
                select(AssessmentInvite).where(AssessmentInvite.id == invite_id)
            )
        ).scalar_one()
        token = row.token

        ctx = await public_service.public_get_context(db, token, ip="1.1.1.1")
        assert ctx["status"] in {"pending", "opened"}
        await public_service.public_accept_consent(db, token, ip="1.1.1.1")

        # Re-fetch
        row = (
            await db.execute(
                select(AssessmentInvite).where(AssessmentInvite.id == invite_id)
            )
        ).scalar_one()
        assert row.status == "opened"
        assert row.opened_at is not None

    async def test_invalid_token_returns_410_and_increments_block(
        self, db: AsyncSession, tenant, user
    ):
        ip = "203.0.113.10"
        for _ in range(public_service.PUBLIC_RATE_LIMIT_INVALID_THRESHOLD):
            with pytest.raises(HTTPException) as ei:
                await public_service.public_get_context(db, "bogus-token", ip=ip)
            assert ei.value.status_code == 410
        # Now the IP is blocked; even a syntactically valid lookup returns 429.
        with pytest.raises(HTTPException) as ei:
            await public_service.public_get_context(db, "another-bogus", ip=ip)
        assert ei.value.status_code == 429

    async def test_revoked_invite_returns_410(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await _make_profile(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        results = await service.create_invites(
            db,
            tenant.id,
            user.id,
            cv.id,
            ManagerAssessmentInviteCreate(
                invitees=[
                    ManagerAssessmentInviteIn(email="ext@example.com", name="External")
                ],
                round_id=uuid.UUID(str(rd["id"])),
                expires_in_days=5,
            ),
        )
        invite_id = uuid.UUID(str(results[0]["id"]))
        await service.revoke_invite(db, tenant.id, user.id, invite_id)
        from sqlalchemy import select

        row = (
            await db.execute(
                select(AssessmentInvite).where(AssessmentInvite.id == invite_id)
            )
        ).scalar_one()
        with pytest.raises(HTTPException) as ei:
            await public_service.public_get_context(db, row.token, ip="9.9.9.9")
        assert ei.value.status_code == 410

    async def test_public_submit_marks_invite_and_assessment(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await _make_profile(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        results = await service.create_invites(
            db,
            tenant.id,
            user.id,
            cv.id,
            ManagerAssessmentInviteCreate(
                invitees=[
                    ManagerAssessmentInviteIn(email="ext@example.com", name="External")
                ],
                round_id=uuid.UUID(str(rd["id"])),
                expires_in_days=5,
            ),
        )
        invite_id = uuid.UUID(str(results[0]["id"]))
        from sqlalchemy import select

        row = (
            await db.execute(
                select(AssessmentInvite).where(AssessmentInvite.id == invite_id)
            )
        ).scalar_one()
        token = row.token

        await public_service.public_accept_consent(db, token, ip="2.2.2.2")
        await public_service.public_set_competence_score(
            db,
            token,
            uuid.uuid4(),
            score_value=3,
            comment=None,
            ip="2.2.2.2",
        )
        out = await public_service.public_submit(
            db, token, ip="2.2.2.2", final_notes="ok"
        )
        assert out["status"] == "submitted"
        # invite status flips, manager_score recomputes for the CV
        row = (
            await db.execute(
                select(AssessmentInvite).where(AssessmentInvite.id == invite_id)
            )
        ).scalar_one()
        assert row.status == "submitted"
        await db.refresh(cv)
        assert cv.manager_score is not None


# ---------------------------------------------------------------------------
# HRP-350/351/352/358/359 — invite guard, email, status model, public sheet
# ---------------------------------------------------------------------------


async def _invite_with_token(
    db: AsyncSession, tenant, user, *, allow_reediting: bool = True, **kwargs
):
    """Create vacancy+profile+cv+round+invite; return (cv, round_id, invite_row)."""
    from sqlalchemy import select

    vacancy = await _make_vacancy(db, tenant)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    await _make_profile(db, tenant, vacancy)
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
    )
    results = await service.create_invites(
        db,
        tenant.id,
        user.id,
        cv.id,
        ManagerAssessmentInviteCreate(
            invitees=[
                ManagerAssessmentInviteIn(email="ext@example.com", name="External Eval")
            ],
            round_id=uuid.UUID(str(rd["id"])),
            expires_in_days=5,
            allow_reediting=allow_reediting,
            **kwargs,
        ),
    )
    row = (
        await db.execute(
            select(AssessmentInvite).where(
                AssessmentInvite.id == uuid.UUID(str(results[0]["id"]))
            )
        )
    ).scalar_one()
    return cv, uuid.UUID(str(rd["id"])), row


class TestInviteGuard:
    async def test_create_invites_requires_profile_competences(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-352: no competences in the vacancy profile → 400, no email."""
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        with pytest.raises(HTTPException) as ei:
            await service.create_invites(
                db,
                tenant.id,
                user.id,
                cv.id,
                ManagerAssessmentInviteCreate(
                    invitees=[
                        ManagerAssessmentInviteIn(
                            email="ext@example.com", name="External"
                        )
                    ],
                    round_id=uuid.UUID(str(rd["id"])),
                ),
            )
        assert ei.value.status_code == 400
        assert "no competences" in ei.value.detail

    async def test_empty_competence_list_also_rejected(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        await _make_profile(db, tenant, vacancy, competences=[])
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        with pytest.raises(HTTPException) as ei:
            await service.create_invites(
                db,
                tenant.id,
                user.id,
                cv.id,
                ManagerAssessmentInviteCreate(
                    invitees=[
                        ManagerAssessmentInviteIn(
                            email="ext@example.com", name="External"
                        )
                    ],
                    round_id=uuid.UUID(str(rd["id"])),
                ),
            )
        assert ei.value.status_code == 400

    async def test_invite_email_rejects_invalid_address(self):
        """HRP-350: server-side email format validation, not just length."""
        with pytest.raises(ValueError):
            ManagerAssessmentInviteIn(email="Aaa", name="External")


class TestInviteEmail:
    async def test_email_names_candidate_and_carries_message(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        """HRP-351: subject/body name the candidate, body carries the
        personal message and links to the new public page."""
        sent: list[tuple[str, str, str]] = []

        def fake_enqueue(to, subject, html_body, **kwargs):
            sent.append((to, subject, html_body))

        import app.core.email as email_mod

        monkeypatch.setattr(email_mod, "enqueue_email", fake_enqueue)

        cv, _rd_id, row = await _invite_with_token(
            db,
            tenant,
            user,
            personal_message="Please focus on system design.",
        )
        assert len(sent) == 1
        to, subject, body = sent[0]
        candidate = await db.get(Candidate, cv.candidate_id)
        assert to == "ext@example.com"
        assert candidate.full_name in subject
        assert "External Eval" not in subject
        assert candidate.full_name in body
        assert "Please focus on system design." in body
        assert f"/public/assessments/{row.token}" in body
        assert "/recruitment/invite/" not in body

    async def test_email_failure_marks_delivery_failed(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        import app.core.email as email_mod

        def boom(*args, **kwargs):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(email_mod, "enqueue_email", boom)
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        assert row.delivery_status == "delivery_failed"


class TestInviteStatusModel:
    async def test_link_open_flips_pending_to_opened(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-358 case 1 step 8: following the link (GET context) is enough."""
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        assert row.status == "pending"
        ctx = await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        assert ctx["status"] == "opened"
        assert ctx["consent_accepted"] is False
        await db.refresh(row)
        assert row.status == "opened"
        assert row.opened_at is not None
        assert row.consent_accepted_at is None

    async def test_consent_accept_is_recorded_separately(
        self, db: AsyncSession, tenant, user
    ):
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        out = await public_service.public_accept_consent(db, row.token, ip="1.2.3.4")
        assert out["consent_accepted"] is True
        await db.refresh(row)
        assert row.consent_accepted_at is not None
        assert row.status == "opened"

    async def test_first_score_flips_to_in_progress(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-358 case 1 step 11: first saved score → in_progress."""
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        await public_service.public_set_competence_score(
            db, row.token, uuid.uuid4(), score_value=3, comment=None, ip="1.2.3.4"
        )
        await db.refresh(row)
        assert row.status == "in_progress"

    async def test_indicator_score_also_flips_to_in_progress(
        self, db: AsyncSession, tenant, user
    ):
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_set_indicator_score(
            db,
            row.token,
            uuid.uuid4(),
            uuid.uuid4(),
            score_value=2,
            ip="1.2.3.4",
        )
        await db.refresh(row)
        assert row.status == "in_progress"

    async def test_clearing_score_does_not_flip_status(
        self, db: AsyncSession, tenant, user
    ):
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        await public_service.public_set_competence_score(
            db, row.token, uuid.uuid4(), score_value=None, comment="n/a", ip="1.2.3.4"
        )
        await db.refresh(row)
        assert row.status == "opened"

    async def test_expired_invite_derived_in_list(self, db: AsyncSession, tenant, user):
        """HRP-358 case 2 step 8: the recruiter list shows expired even
        when the evaluator never visited the link after the deadline."""
        from datetime import datetime, timedelta, timezone

        cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()
        invites = await service.list_manager_invites(db, tenant.id, cv.id)
        assert invites[0]["status"] == "expired"
        # The stored status stays lazy until a token resolve happens.
        await db.refresh(row)
        assert row.status == "pending"

    async def test_submitted_invite_never_shows_expired(
        self, db: AsyncSession, tenant, user
    ):
        from datetime import datetime, timedelta, timezone

        cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_submit(db, row.token, ip="1.2.3.4")
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()
        invites = await service.list_manager_invites(db, tenant.id, cv.id)
        assert invites[0]["status"] == "submitted"

    async def test_expired_link_visit_keeps_submitted_status(
        self, db: AsyncSession, tenant, user
    ):
        """A late link visit must not clobber a terminal status to expired —
        it would show a completed evaluation as expired and let extend_invite
        bypass its submitted-guard."""
        from datetime import datetime, timedelta, timezone

        cv, _rd_id, row = await _invite_with_token(
            db, tenant, user, allow_reediting=False
        )
        await public_service.public_submit(db, row.token, ip="1.2.3.4")
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()
        with pytest.raises(HTTPException) as ei:
            await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        assert ei.value.status_code == 410
        await db.refresh(row)
        assert row.status == "submitted"
        invites = await service.list_manager_invites(db, tenant.id, cv.id)
        assert invites[0]["status"] == "submitted"
        # extend_invite's submitted-guard still holds after the late visit.
        with pytest.raises(HTTPException) as ei:
            await service.extend_invite(db, tenant.id, user.id, row.id, 5)
        assert ei.value.status_code == 409

    async def test_decline_after_submit_rejected(self, db: AsyncSession, tenant, user):
        """A stale consent tab cannot demote a submitted evaluation."""
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_submit(db, row.token, ip="1.2.3.4")
        with pytest.raises(HTTPException) as ei:
            await public_service.public_decline(db, row.token, ip="1.2.3.4")
        assert ei.value.status_code == 409
        await db.refresh(row)
        assert row.status == "submitted"

    async def test_extend_declined_invite_rejected(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-359 (review): extending a declined invite would silently
        succeed while the token stays dead — reject it like submitted."""
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_decline(db, row.token, ip="1.2.3.4")
        with pytest.raises(HTTPException) as ei:
            await service.extend_invite(db, tenant.id, user.id, row.id, 5)
        assert ei.value.status_code == 409

    async def test_declined_invite_is_terminal(self, db: AsyncSession, tenant, user):
        """HRP-359 REDO: declining kills the token — refreshing the stub
        page must not resurface the consent screen, and no score write can
        revive the invite."""
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_decline(db, row.token, ip="1.2.3.4")

        with pytest.raises(HTTPException) as ei:
            await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        assert ei.value.status_code == 410

        with pytest.raises(HTTPException) as ei:
            await public_service.public_accept_consent(db, row.token, ip="1.2.3.4")
        assert ei.value.status_code == 410

        with pytest.raises(HTTPException) as ei:
            await public_service.public_set_competence_score(
                db, row.token, uuid.uuid4(), score_value=2, comment=None, ip="1.2.3.4"
            )
        assert ei.value.status_code == 410

        await db.refresh(row)
        assert row.status == "declined"

    async def test_expired_token_visit_returns_410(
        self, db: AsyncSession, tenant, user
    ):
        from datetime import datetime, timedelta, timezone

        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()
        with pytest.raises(HTTPException) as ei:
            await public_service.public_get_context(db, row.token, ip="5.5.5.5")
        assert ei.value.status_code == 410
        await db.refresh(row)
        assert row.status == "expired"


class TestPublicSheet:
    async def test_context_is_slim_before_consent(self, db: AsyncSession, tenant, user):
        """Candidate PII must not leave the API until consent is accepted —
        the consent gate is server-side, not just a frontend modal."""
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        ctx = await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        assert ctx["consent_accepted"] is False
        assert "candidate_name" not in ctx
        assert "resume_url" not in ctx
        assert "questions" not in ctx
        assert "competences" not in ctx
        assert "assessment" not in ctx
        # The consent screen still gets what it renders.
        assert ctx["evaluator_name"] == "External Eval"
        assert ctx["tenant_name"] == tenant.name

    async def test_context_includes_sheet_payload(self, db: AsyncSession, tenant, user):
        """HRP-359: the public context carries everything the page renders."""
        cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_accept_consent(db, row.token, ip="1.2.3.4")
        ctx = await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        candidate = await db.get(Candidate, cv.candidate_id)
        assert ctx["tenant_name"] == tenant.name
        assert ctx["candidate_name"] == candidate.full_name
        assert ctx["vacancy_title"]
        assert [c["name"] for c in ctx["competences"]] == [
            "Communication",
            "Sales",
        ]
        assert ctx["competences"][0]["criticality"] == "critical"
        assert ctx["competences"][0]["indicators"] == [
            "Clear writing",
            "Active listening",
        ]
        # profile_data extras (salary) must never leak
        assert "salary" not in str(ctx["competences"])
        assert ctx["scale_levels"], "scale snapshot levels expected"
        assert ctx["critical_submit_threshold"] == 0.5
        assert ctx["assessment"] is not None
        assert ctx["assessment"]["status"] == "draft"
        assert ctx["recruiter_email"] == user.email

    async def test_public_indicator_scores_compute_overall(
        self, db: AsyncSession, tenant, user
    ):
        _cv, _rd_id, row = await _invite_with_token(db, tenant, user)
        await public_service.public_accept_consent(db, row.token, ip="1.2.3.4")
        comp_id = uuid.uuid4()
        await public_service.public_set_indicator_score(
            db, row.token, uuid.uuid4(), comp_id, score_value=2, ip="1.2.3.4"
        )
        await public_service.public_set_indicator_score(
            db, row.token, uuid.uuid4(), comp_id, score_value=4, ip="1.2.3.4"
        )
        ctx = await public_service.public_get_context(db, row.token, ip="1.2.3.4")
        overall = [
            c
            for c in ctx["assessment"]["competence_scores"]
            if str(c["competence_id"]) == str(comp_id)
        ]
        assert overall
        assert overall[0]["score_value"] == 3
        assert overall[0]["score_source"] == "computed_from_indicators"


class TestReediting:
    async def test_reediting_disabled_blocks_edits_after_submit(
        self, db: AsyncSession, tenant, user
    ):
        _cv, _rd_id, row = await _invite_with_token(
            db, tenant, user, allow_reediting=False
        )
        await public_service.public_submit(db, row.token, ip="1.2.3.4")
        for call in (
            public_service.public_set_competence_score(
                db, row.token, uuid.uuid4(), score_value=1, comment=None, ip="1.2.3.4"
            ),
            public_service.public_set_indicator_score(
                db, row.token, uuid.uuid4(), uuid.uuid4(), score_value=1, ip="1.2.3.4"
            ),
            public_service.public_save_final_notes(
                db, row.token, "late edit", ip="1.2.3.4"
            ),
            public_service.public_submit(db, row.token, ip="1.2.3.4"),
        ):
            with pytest.raises(HTTPException) as ei:
                await call
            assert ei.value.status_code == 409

    async def test_reediting_enabled_keeps_form_editable(
        self, db: AsyncSession, tenant, user
    ):
        _cv, _rd_id, row = await _invite_with_token(
            db, tenant, user, allow_reediting=True
        )
        await public_service.public_submit(db, row.token, ip="1.2.3.4")
        await public_service.public_set_competence_score(
            db, row.token, uuid.uuid4(), score_value=4, comment=None, ip="1.2.3.4"
        )
        await db.refresh(row)
        # Terminal status survives the re-edit.
        assert row.status == "submitted"


# ---------------------------------------------------------------------------
# Scale update lock
# ---------------------------------------------------------------------------


class TestScaleLocking:
    async def test_levels_cannot_change_after_snapshot(
        self, db: AsyncSession, tenant, user
    ):
        scale = await service.create_scale(db, tenant.id, user.id, _scale_payload())
        vacancy = await _make_vacancy(db, tenant)
        await service.set_vacancy_scale(
            db, tenant.id, user.id, vacancy.id, uuid.UUID(str(scale["id"]))
        )
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="pre_interview")
        )
        a = await service.get_or_create_assessment(
            db,
            tenant.id,
            uuid.UUID(str(rd["id"])),
            evaluator_user_id=user.id,
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            uuid.uuid4(),
            CompetenceScoreIn(score_value=3),
        )
        # Snapshot frozen — editing levels is now refused.
        with pytest.raises(HTTPException) as ei:
            await service.update_scale(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(scale["id"])),
                ScaleUpdate(
                    levels=[
                        ScaleLevelIn(value=1, label="x", weight=0),
                        ScaleLevelIn(value=2, label="y", weight=100),
                    ]
                ),
            )
        assert ei.value.status_code == 409


# ---------------------------------------------------------------------------
# HRP-378: overall <-> indicators stay mutually exclusive
# ---------------------------------------------------------------------------


async def _sheet_rows(db: AsyncSession, tenant, assessment_id, comp_id):
    """Return ``(overall_row_or_None, indicator_rows)`` for one competence."""
    sheet = await service.get_assessment(db, tenant.id, assessment_id)
    overall = [
        c
        for c in sheet["competence_scores"]
        if str(c["competence_id"]) == str(comp_id)
    ]
    indicators = [
        i
        for i in sheet["indicator_scores"]
        if str(i["competence_id"]) == str(comp_id)
    ]
    return (overall[0] if overall else None), indicators


class TestOverallIndicatorOverride:
    async def _fixture(self, db, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        a = await service.get_or_create_assessment(
            db, tenant.id, uuid.UUID(str(rd["id"])), evaluator_user_id=user.id
        )
        return a

    async def test_indicators_override_a_manual_overall(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-378 §7.2: scoring indicators re-derives the overall even when
        the evaluator had already picked one by hand."""
        a = await self._fixture(db, tenant, user)
        comp_id = uuid.uuid4()
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(score_value=1, score_source="manual"),
        )
        for value in (4, 4):
            await service.set_indicator_score(
                db,
                tenant.id,
                user.id,
                a.id,
                uuid.uuid4(),
                IndicatorScoreIn(competence_id=comp_id, score_value=value),
            )
        overall, _ = await _sheet_rows(db, tenant, a.id, comp_id)
        assert overall is not None
        assert overall["score_value"] == 4
        assert overall["score_source"] == "computed_from_indicators"

    async def test_manual_overall_clears_indicator_answers(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-378 §7.4: editing the overall by hand drops the indicator
        answers entirely — not to 'Not assessed', to nothing selected."""
        a = await self._fixture(db, tenant, user)
        comp_id = uuid.uuid4()
        for value in (2, 4):
            await service.set_indicator_score(
                db,
                tenant.id,
                user.id,
                a.id,
                uuid.uuid4(),
                IndicatorScoreIn(competence_id=comp_id, score_value=value),
            )
        overall, indicators = await _sheet_rows(db, tenant, a.id, comp_id)
        assert overall["score_value"] == 3
        assert len(indicators) == 2

        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(score_value=1, score_source="manual"),
        )
        overall, indicators = await _sheet_rows(db, tenant, a.id, comp_id)
        assert overall["score_value"] == 1
        assert overall["score_source"] == "manual"
        assert indicators == []

    async def test_other_competences_keep_their_indicators(
        self, db: AsyncSession, tenant, user
    ):
        """The reset is scoped to the edited competence."""
        a = await self._fixture(db, tenant, user)
        comp_a, comp_b = uuid.uuid4(), uuid.uuid4()
        for comp in (comp_a, comp_b):
            await service.set_indicator_score(
                db,
                tenant.id,
                user.id,
                a.id,
                uuid.uuid4(),
                IndicatorScoreIn(competence_id=comp, score_value=3),
            )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_a,
            CompetenceScoreIn(score_value=1, score_source="manual"),
        )
        _, indicators_a = await _sheet_rows(db, tenant, a.id, comp_a)
        _, indicators_b = await _sheet_rows(db, tenant, a.id, comp_b)
        assert indicators_a == []
        assert len(indicators_b) == 1

    async def test_comment_only_save_keeps_indicator_answers(
        self, db: AsyncSession, tenant, user
    ):
        """A comment-only PATCH sends no score fields, so it can never be
        mistaken for a manual overall edit — whatever the client believes
        the current score to be."""
        a = await self._fixture(db, tenant, user)
        comp_id = uuid.uuid4()
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            uuid.uuid4(),
            IndicatorScoreIn(competence_id=comp_id, score_value=3),
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(comment="Solid answers"),
        )
        overall, indicators = await _sheet_rows(db, tenant, a.id, comp_id)
        assert overall["comment"] == "Solid answers"
        # The derived overall is untouched by a note.
        assert overall["score_value"] == 3
        assert overall["score_source"] == "computed_from_indicators"
        assert len(indicators) == 1

    async def test_comment_save_with_a_stale_client_score_is_harmless(
        self, db: AsyncSession, tenant, user
    ):
        """Regression: a note typed while an indicator save is still in
        flight used to arrive carrying the client's pre-indicator score and
        `manual` source, which deleted every indicator answer. Score fields
        the client did not send are now simply not written."""
        a = await self._fixture(db, tenant, user)
        comp_id = uuid.uuid4()
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            uuid.uuid4(),
            IndicatorScoreIn(competence_id=comp_id, score_value=4),
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(comment="typed while saving"),
        )
        overall, indicators = await _sheet_rows(db, tenant, a.id, comp_id)
        assert overall["score_value"] == 4
        assert overall["score_source"] == "computed_from_indicators"
        assert len(indicators) == 1

    async def test_score_save_does_not_clear_an_existing_comment(
        self, db: AsyncSession, tenant, user
    ):
        """The two fields are independent: a score PATCH omits the comment."""
        a = await self._fixture(db, tenant, user)
        comp_id = uuid.uuid4()
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(comment="Keep me"),
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(score_value=4, score_source="manual"),
        )
        overall, _ = await _sheet_rows(db, tenant, a.id, comp_id)
        assert overall["score_value"] == 4
        assert overall["comment"] == "Keep me"

    async def test_repeating_the_same_manual_score_is_not_a_reset(
        self, db: AsyncSession, tenant, user
    ):
        """Re-picking the level already stored manually changes nothing, so
        there is no indicator answer to discard."""
        a = await self._fixture(db, tenant, user)
        comp_id = uuid.uuid4()
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(score_value=2, score_source="manual"),
        )
        await service.set_indicator_score(
            db,
            tenant.id,
            user.id,
            a.id,
            uuid.uuid4(),
            IndicatorScoreIn(competence_id=comp_id, score_value=2),
        )
        # The indicators have since re-derived the overall to the same 2.
        overall, _ = await _sheet_rows(db, tenant, a.id, comp_id)
        assert overall["score_source"] == "computed_from_indicators"
        # Re-sending that identical derived state is a no-op.
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            comp_id,
            CompetenceScoreIn(
                score_value=2, score_source="computed_from_indicators"
            ),
        )
        _, indicators = await _sheet_rows(db, tenant, a.id, comp_id)
        assert len(indicators) == 1


# ---------------------------------------------------------------------------
# HRP-374: round Average score + per-competence divergence
# ---------------------------------------------------------------------------


class TestRoundAverageScore:
    async def _round(self, db, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        scale = await service.create_scale(db, tenant.id, user.id, _scale_payload())
        await service.set_vacancy_scale(
            db, tenant.id, user.id, vacancy.id, uuid.UUID(str(scale["id"]))
        )
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        return cv, uuid.UUID(str(rd["id"]))

    async def test_average_is_none_until_something_is_scored(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-374 §1: the header shows an em dash, not 0."""
        _, rd_id = await self._round(db, tenant, user)
        await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] is None
        assert agg["average_weight"] is None
        assert agg["competences"] == []

    async def test_average_appears_with_one_competence_from_one_evaluator(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await self._round(db, tenant, user)
        a = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, a.id, uuid.uuid4(), CompetenceScoreIn(score_value=3)
        )
        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 3.0
        # Level 3 carries weight 66 on the seeded scale.
        assert agg["average_weight"] == 66.0

    async def test_average_spans_all_evaluators_and_competences(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await self._round(db, tenant, user)
        other = await _make_extra_user(db, tenant)
        comp = uuid.uuid4()
        a1 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        a2 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=other.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, a1.id, comp, CompetenceScoreIn(score_value=2)
        )
        await service.set_competence_score(
            db, tenant.id, other.id, a2.id, comp, CompetenceScoreIn(score_value=4)
        )
        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 3.0
        assert len(agg["competences"]) == 1
        assert agg["competences"][0]["average"] == 3.0

    async def test_unsubmitted_external_sheet_is_not_counted(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-374 §3: an external evaluator only counts once submitted;
        an internal draft counts immediately."""
        cv, rd_id = await self._round(db, tenant, user)
        comp = uuid.uuid4()
        internal = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, internal.id, comp, CompetenceScoreIn(score_value=4)
        )
        external = await _external_sheet(
            db, tenant, cv, rd_id, name="Ivan Petrov"
        )
        await service.set_competence_score(
            db, tenant.id, None, external.id, comp, CompetenceScoreIn(score_value=2)
        )

        draft_avg = await service.round_aggregate(db, tenant.id, rd_id)
        assert draft_avg["average"] == 4.0, "external draft must not move the average"

        await service.submit_assessment(db, tenant.id, None, external.id)
        submitted_avg = await service.round_aggregate(db, tenant.id, rd_id)
        assert submitted_avg["average"] == 3.0

    async def test_divergence_flags_and_names_both_evaluator_kinds(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-374 §2/§3: a spread >= the scale threshold marks the
        competence and the tooltip data names internal + external alike."""
        cv, rd_id = await self._round(db, tenant, user)
        comp = uuid.uuid4()
        internal = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, internal.id, comp, CompetenceScoreIn(score_value=4)
        )
        external = await _external_sheet(
            db, tenant, cv, rd_id, name="Ivan Petrov"
        )
        await service.set_competence_score(
            db, tenant.id, None, external.id, comp, CompetenceScoreIn(score_value=2)
        )
        await service.submit_assessment(db, tenant.id, None, external.id)

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["divergence_threshold"] == 2
        row = agg["competences"][0]
        assert row["diverges"] is True
        assert row["min"] == 2 and row["max"] == 4
        kinds = {s["evaluator_type"] for s in row["scorers"]}
        assert kinds == {"internal", "external"}
        names = {s["evaluator"] for s in row["scorers"]}
        assert "Ivan Petrov" in names

    async def test_single_evaluator_never_diverges(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await self._round(db, tenant, user)
        a = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, a.id, uuid.uuid4(), CompetenceScoreIn(score_value=4)
        )
        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["competences"][0]["diverges"] is False

    async def test_spread_below_threshold_is_not_divergent(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await self._round(db, tenant, user)
        other = await _make_extra_user(db, tenant)
        comp = uuid.uuid4()
        a1 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        a2 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=other.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, a1.id, comp, CompetenceScoreIn(score_value=3)
        )
        await service.set_competence_score(
            db, tenant.id, other.id, a2.id, comp, CompetenceScoreIn(score_value=4)
        )
        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["competences"][0]["diverges"] is False

    async def test_threshold_follows_the_scale_setting(
        self, db: AsyncSession, tenant, user
    ):
        """The N in 'differ by >= N levels' is the scale's own setting."""
        vacancy = await _make_vacancy(db, tenant)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        payload = _scale_payload("Strict")
        payload.divergence_threshold = 3
        scale = await service.create_scale(db, tenant.id, user.id, payload)
        await service.set_vacancy_scale(
            db, tenant.id, user.id, vacancy.id, uuid.UUID(str(scale["id"]))
        )
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        rd_id = uuid.UUID(str(rd["id"]))
        other = await _make_extra_user(db, tenant)
        comp = uuid.uuid4()
        a1 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        a2 = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=other.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, a1.id, comp, CompetenceScoreIn(score_value=2)
        )
        await service.set_competence_score(
            db, tenant.id, other.id, a2.id, comp, CompetenceScoreIn(score_value=4)
        )
        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["divergence_threshold"] == 3
        # Spread of 2 no longer clears the raised bar.
        assert agg["competences"][0]["diverges"] is False
