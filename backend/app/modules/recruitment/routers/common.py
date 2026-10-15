"""Shared infrastructure for the recruitment sub-routers."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, status
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.rate_limit import make_limiter
from app.core.sections import matrix_levels, require_section
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.recruitment.manager_assessment_models import (
    AssessmentRound,
    AssessmentRoundEvaluator,
    RecruitmentAssessment,
)
from app.modules.recruitment.manager_assessment_service import _round_is_closed
from app.modules.recruitment.scope import round_scope


def resolve_page_params(
    skip: int,
    limit: int,
    page: int | None,
    page_size: int | None,
) -> tuple[int, int]:
    """Resolve the two pagination dialects into (skip, limit).

    The frontend list pages send ``page``/``page_size`` while the original
    API contract (and scripted clients) speak ``skip``/``limit``. When both
    are given, ``page``/``page_size`` win (HRP-363).
    """
    if page_size is not None:
        limit = page_size
    if page is not None:
        skip = (page - 1) * limit
    return skip, limit


# Per-IP rate limiter for public token-based endpoints (R4d security audit).
# Magic-link consent, invited-evaluator canvas, and shared-report views all
# accept opaque 256-bit tokens — high entropy by themselves, but without a
# rate limit an attacker could grind through tokens or replay a stale link
# at high QPS. 60/minute is generous for a real recruiter clicking
# through their inbox, tight for a botnet.
# key_style="endpoint" is load-bearing: slowapi's default ("url") buckets by
# the FULL request path, so every distinct {token} value would get its own
# fresh bucket and token grinding would never be throttled (review [26]).
recruitment_public_limiter = make_limiter(get_remote_address)


# HRP-830: who may do what in recruitment is the section access matrix.
# Reading needs ``view`` - the global gate answers that, and
# ``recruitment.scope`` narrows it to the caller's vacancies. The section
# is self-guarded, so each write asks for itself with one of these (or
# keeps its admin / hr role for the tenant settings and GDPR):
#
# * ``runs_hiring`` - ``manage``, which also sees the whole workspace.
#   Used to be the admin/recruiter role list.
# * ``evaluates`` - ``manage`` or the ``hiring_manager`` role: human
#   scores, the candidate's stage and the question PDF exports on a vacancy
#   in scope. The role keeps it at ``view`` (Maxim, 25.09), in its own
#   column of the scores: another evaluator's cell is ``manage``'s. Writing
#   the interview questions is ``manage``'s (HRP-630): at ``view`` the
#   hiring manager reads and exports them.
# * ``runs_rounds`` - ``manage`` or the ``manager`` role: hiring rounds,
#   their evaluators, scores and invites. ``manager`` sits on hiring
#   rounds (``ELIGIBLE_EVALUATOR_ROLES``) and keeps them at ``view``.
#   One's own sheet on a round is ``sheet_owner_checker``'s.
runs_hiring = require_section("recruitment", "manage")


async def runs_hiring_level(db: AsyncSession, user: User) -> bool:
    return (await matrix_levels(db, user))["recruitment"] == "manage"


def _manage_or_role(role: str) -> Callable:
    async def section_or_role_checker(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if role in {r.code for r in current_user.roles}:
            return current_user
        if await runs_hiring_level(db, current_user):
            return current_user
        raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)

    return section_or_role_checker


evaluates = _manage_or_role("hiring_manager")
runs_rounds = _manage_or_role("manager")


async def sheet_owner_checker(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """HRP-630: a round's internal evaluator fills in their own sheet at any
    level the section is open to them - a hiring manager at ``view`` named
    on the round included. Any other sheet stays ``runs_rounds``'s; the
    service still refuses a colleague's user sheet to everyone."""
    if "manager" in {r.code for r in current_user.roles} or await runs_hiring_level(
        db, current_user
    ):
        return current_user
    owner = await db.scalar(
        select(RecruitmentAssessment.evaluator_user_id).where(
            RecruitmentAssessment.id == assessment_id,
            RecruitmentAssessment.tenant_id == current_user.tenant_id,
        )
    )
    if owner is None or owner != current_user.id:
        raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)
    return current_user


async def reads_round_aggregate(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Scope first: an out-of-scope round answers the same whether it is live
    # or closed, so the refusal does not tell its status.
    _scope: None = Depends(round_scope),
) -> User:
    """HRP-629 / HRP-630 REDO (QA 12.10): who reads a round's averages.

    ``runs_rounds`` at any time, as before. Below it the round's own
    evaluators read them - behind the HRP-373 anchoring gate the service
    applies - and every other reader of the round once it is completed or
    archived: its scores are final, and the sheets themselves are already
    open to them. A live round's averages stay closed to a non-evaluator.
    The vacancy scope guard on the route still fences all of this.
    """
    if "manager" in {r.code for r in current_user.roles} or await runs_hiring_level(
        db, current_user
    ):
        return current_user
    rd = await db.scalar(
        select(AssessmentRound).where(
            AssessmentRound.id == round_id,
            AssessmentRound.tenant_id == current_user.tenant_id,
        )
    )
    if rd is not None and _round_is_closed(rd):
        return current_user
    on_round = await db.scalar(
        select(AssessmentRoundEvaluator.user_id).where(
            AssessmentRoundEvaluator.round_id == round_id,
            AssessmentRoundEvaluator.user_id == current_user.id,
        )
    )
    if on_round is None:
        raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)
    return current_user


# The two reads behind the admin's own settings pages that the section
# also runs on (the consent templates, the branding): the admin role keeps
# its page at any level, ``manage`` keeps what it read before.
reads_hiring_settings = _manage_or_role("admin")
