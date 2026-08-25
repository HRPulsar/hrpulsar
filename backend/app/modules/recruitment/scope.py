"""Who sees which vacancy — and everything hanging off it (HRP-629).

``RECRUITMENT_VIEWER_ROLES`` (HRP-615) decides whether a caller may open
the hiring surface at all. It does not decide *how much* of it: a
division head picks up the ``manager`` role automatically the moment
``company.service`` makes them a division manager, which used to leave
them reading candidate contacts, resumes and interview transcripts for
every vacancy in the workspace, including a neighbouring department's.

The rule now: ``admin`` / ``platform_admin`` / ``hr`` / ``recruiter``
keep the whole tenant, everyone else sees a vacancy only when

* it belongs to a division they manage (their subtree), or
* they are its named hiring manager, or
* they created it.

Everything else in recruitment — candidates, resumes, interviews,
reports, assessment rounds — is reachable only through a vacancy, so the
same predicate answers for all of them: resolve the resource back to the
vacancies it hangs off and ask whether any of them is in scope.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, status
from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import get_current_employee, get_managed_division_ids
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.recruitment.manager_assessment_models import (
    AssessmentRound,
    RecruitmentAssessment,
)
from app.modules.recruitment.models import (
    CandidateFile,
    CandidateVacancy,
    ConsolidatedReport,
    Interview,
    Vacancy,
)

# Roles that own hiring for the whole workspace. Kept separate from
# ``RECRUITMENT_VIEWER_ROLES``: that tuple answers "may you be here",
# this one answers "do you see all of it".
#
# Membership must cover every role that appears in a recruitment
# ``require_role`` gate but is not a division role — otherwise that role
# reaches the route and is then scoped to a subtree it does not manage,
# which is a 403 on a surface explicitly granted to it.
#
# ``common._FULL_ROLES`` holds the same codes minus ``platform_admin`` for
# a different question — who sees the unredacted AI analysis payload.
# Overlapping members, different meaning; do not merge them.
FULL_RECRUITMENT_ROLES = frozenset({"admin", "platform_admin", "hr", "recruiter"})


@dataclass(frozen=True)
class RecruitmentScope:
    """Resolved answer to "which vacancies may this caller see"."""

    unrestricted: bool
    division_ids: tuple[uuid.UUID, ...]
    user_id: uuid.UUID

    def vacancy_filter(self) -> ColumnElement[bool]:
        """A condition on ``Vacancy``; only valid when not unrestricted.

        Returned as a condition rather than a set of ids on purpose — a
        workspace can hold thousands of vacancies, and every caller of
        this narrows an existing query that already joins ``Vacancy``.

        ``hiring_manager_id`` and ``owner_id`` are both FKs to ``users``,
        not to ``employees`` — the division subtree is the only part of
        this that goes through the employee record.
        """
        clauses: list[ColumnElement[bool]] = [
            Vacancy.owner_id == self.user_id,
            Vacancy.hiring_manager_id == self.user_id,
        ]
        if self.division_ids:
            clauses.append(Vacancy.division_id.in_(self.division_ids))
        return or_(*clauses)


async def resolve_recruitment_scope(
    db: AsyncSession, current_user: User
) -> RecruitmentScope:
    codes = {r.code for r in current_user.roles}
    if codes & FULL_RECRUITMENT_ROLES:
        return RecruitmentScope(
            unrestricted=True, division_ids=(), user_id=current_user.id
        )

    emp = await get_current_employee(db, current_user)
    division_ids: tuple[uuid.UUID, ...] = ()
    if emp is not None:
        division_ids = tuple(
            await get_managed_division_ids(db, current_user.tenant_id, emp.id)
        )
    return RecruitmentScope(
        unrestricted=False, division_ids=division_ids, user_id=current_user.id
    )


async def assert_in_scope(
    db: AsyncSession,
    current_user: User,
    scope: RecruitmentScope,
    resource_query: Select,
) -> None:
    """403 unless ``resource_query`` reaches a vacancy the caller may see.

    ``resource_query`` selects ``Vacancy.id`` with whatever joins lead
    from the resource in hand back to its vacancy; tenant and scope
    filters are appended here so no call site can forget either.

    A resource that does not exist is refused rather than reported as
    missing: telling a division head that candidate X exists but is not
    theirs is itself a leak. The same fail-closed rule applies to a
    resource that reaches no vacancy at all — a ``CandidateFile`` whose
    ``candidate_id`` is still NULL mid bulk-upload, say. Nobody's
    division owns it, so no scoped caller gets it.
    """
    if scope.unrestricted:
        return
    stmt = resource_query.where(
        Vacancy.tenant_id == current_user.tenant_id,
        scope.vacancy_filter(),
    ).limit(1)
    if (await db.execute(stmt)).first() is None:
        raise AppError(
            "outside_recruitment_scope",
            status.HTTP_403_FORBIDDEN,
            detail_extra={},
            detail_code_key="error_code",
        )


# --- Resource → vacancy queries ------------------------------------------
#
# One per way into the hiring data. Each starts at ``Vacancy`` and joins
# down to the resource the route is keyed by.

_CV_TO_VACANCY = select(Vacancy.id).join(
    CandidateVacancy, CandidateVacancy.vacancy_id == Vacancy.id
)


def _by_vacancy(vacancy_id: uuid.UUID) -> Select:
    return select(Vacancy.id).where(Vacancy.id == vacancy_id)


def _by_candidate(candidate_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.where(CandidateVacancy.candidate_id == candidate_id)


def _by_candidate_vacancy(cv_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.where(CandidateVacancy.id == cv_id)


def _by_interview(interview_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.join(
        Interview, Interview.candidate_vacancy_id == CandidateVacancy.id
    ).where(Interview.id == interview_id)


def _by_candidate_file(file_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.join(
        CandidateFile, CandidateFile.candidate_id == CandidateVacancy.candidate_id
    ).where(CandidateFile.id == file_id)


def _by_report(report_id: uuid.UUID) -> Select:
    return (
        select(Vacancy.id)
        .join(ConsolidatedReport, ConsolidatedReport.vacancy_id == Vacancy.id)
        .where(ConsolidatedReport.id == report_id)
    )


def _by_round(round_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.join(
        AssessmentRound, AssessmentRound.candidate_vacancy_id == CandidateVacancy.id
    ).where(AssessmentRound.id == round_id)


def _by_assessment(assessment_id: uuid.UUID) -> Select:
    return (
        _CV_TO_VACANCY.join(
            AssessmentRound,
            AssessmentRound.candidate_vacancy_id == CandidateVacancy.id,
        )
        .join(
            RecruitmentAssessment, RecruitmentAssessment.round_id == AssessmentRound.id
        )
        .where(RecruitmentAssessment.id == assessment_id)
    )


# --- FastAPI dependencies -------------------------------------------------
#
# These are guards, not gates: each route keeps whatever ``require_role``
# it already had and adds one of these as an extra parameter. Roles answer
# "may you be in recruitment at all", scope answers "is this particular
# vacancy yours" — keeping them separate means adding scope to a route
# never quietly widens the roles that reach it.
#
# Every guard goes through ``recruitment_scope``, so FastAPI's per-request
# dependency cache resolves the caller's scope exactly once even on a route
# carrying two guards. Resolution is not free: it loads the tenant's whole
# division tree and walks it.
#
# A guard's parameter name must match the route's, which is why ``cv_id``
# and ``candidate_vacancy_id`` get one each — the routes spell the same
# thing two ways — and why the query-parameter variants are separate from
# the path ones.


async def recruitment_scope(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecruitmentScope:
    return await resolve_recruitment_scope(db, current_user)


async def vacancy_scope(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_vacancy(vacancy_id))


async def candidate_scope(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_candidate(candidate_id))


async def cv_scope(
    cv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_candidate_vacancy(cv_id))


async def candidate_vacancy_scope(
    candidate_vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(
        db, current_user, scope, _by_candidate_vacancy(candidate_vacancy_id)
    )


async def interview_scope(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_interview(interview_id))


async def resume_scope(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_candidate_file(resume_id))


async def export_scope(
    export_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_report(export_id))


async def report_scope(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_report(report_id))


async def round_scope(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_round(round_id))


async def assessment_scope(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_assessment(assessment_id))


# Query-parameter variants. A list route that accepts ``?vacancy_id=`` is
# as good a way into another division's hiring as the path — narrowing a
# list to a foreign vacancy confirms who is on it. Optional, so ``None``
# means "no filter asked for" and the list's own scope filter decides.


async def vacancy_query_scope(
    vacancy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    if vacancy_id is not None:
        await assert_in_scope(db, current_user, scope, _by_vacancy(vacancy_id))


async def candidate_vacancy_query_scope(
    candidate_vacancy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    if candidate_vacancy_id is not None:
        await assert_in_scope(
            db, current_user, scope, _by_candidate_vacancy(candidate_vacancy_id)
        )


async def list_scope_filter(
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> ColumnElement[bool] | None:
    """Condition for a list query that joins ``Vacancy``; ``None`` = all.

    Carries the tenant predicate itself so the list paths are filtered as
    strictly as ``assert_in_scope`` filters the keyed ones.
    """
    if scope.unrestricted:
        return None
    return and_(Vacancy.tenant_id == current_user.tenant_id, scope.vacancy_filter())
