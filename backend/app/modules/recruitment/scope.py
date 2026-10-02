"""Who sees which vacancy — and everything hanging off it (HRP-629).

The section access matrix (HRP-830) decides whether a caller may open
the hiring surface at all. It does not decide *how much* of it: a
division head picks up the ``manager`` role automatically the moment
``company.service`` makes them a division manager, which used to leave
them reading candidate contacts, resumes and interview transcripts for
every vacancy in the workspace, including a neighbouring department's.

The rule now: an admin-level role or ``manage`` on ``recruitment`` keeps
the whole tenant (by default admin, hr and recruiter - the roles that
used to be listed here), everyone else sees a vacancy only when

* it belongs to a division they manage (their subtree), or
* they are its named hiring manager, or
* they created it,

and never a vacancy they are a candidate on themselves (HRP-971): a deputy
applying for their own head's seat would otherwise read their rivals'
resumes, transcripts, verdicts and scores and, running rounds, score them.
The fence holds after the vacancy closes and outranks being its creator
or hiring manager; the admin level and ``manage`` stay unfenced.

Everything else in recruitment — candidates, resumes, interviews,
reports, assessment rounds — is reachable only through a vacancy, so the
same predicate answers for all of them: resolve the resource back to the
vacancies it hangs off and ask whether any of them is in scope.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, status
from sqlalchemy import ColumnElement, Select, and_, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased, selectinload

from app.core.access_scope import (
    ADMIN_ROLE_CODES,
    get_current_employee,
    get_managed_division_ids,
)
from app.core.errors import AppError
from app.core.sections import effective_levels, matrix_levels
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.recruitment.manager_assessment_models import (
    AssessmentRound,
    RecruitmentAssessment,
)
from app.modules.recruitment.models import (
    AssessmentInvite,
    Candidate,
    CandidateFile,
    CandidateQuestion,
    CandidateVacancy,
    ConsolidatedReport,
    HumanAssessment,
    Interview,
    Question,
    QuestionSet,
    Vacancy,
)
from app.modules.talent_market.models import TalentCandidate


def own_candidacy(
    vacancy_id: InstrumentedAttribute[uuid.UUID] | uuid.UUID,
    person_id: uuid.UUID | None,
    email: str | None,
    employee_id: uuid.UUID | None = None,
) -> ColumnElement[bool] | None:
    """HRP-971: "this person applied to the vacancy" - they are a candidate
    on it, or they reacted to its talent-market twin.

    A candidacy is matched by their ``Person`` or their email, the two keys
    an internal candidacy is reused by (HRP-711); a reaction by their
    employee row, before any recruiter has moved them into the pipeline.
    ``None`` when there is nothing to match on - an unset key must never
    match every candidate without one.
    """
    # Aliased so the fence never correlates with a table the enclosing
    # query already selects from; built per call, as a module-level alias
    # would configure every mapper at import time.
    arms: list[ColumnElement[bool]] = []
    keys: list[ColumnElement[bool]] = []
    cand = aliased(Candidate)
    if person_id is not None:
        keys.append(cand.person_id == person_id)
    if email:
        keys.append(func.lower(cand.email) == func.lower(literal(email)))
    if keys:
        cv = aliased(CandidateVacancy)
        arms.append(
            exists().where(
                cv.vacancy_id == vacancy_id, cv.candidate_id == cand.id, or_(*keys)
            )
        )
    if employee_id is not None:
        twin = aliased(Vacancy)
        reaction = aliased(TalentCandidate)
        arms.append(
            exists().where(
                twin.id == vacancy_id,
                reaction.card_id == twin.talent_card_id,
                reaction.employee_id == employee_id,
                reaction.response_at.isnot(None),
            )
        )
    return or_(*arms) if arms else None


@dataclass(frozen=True)
class RecruitmentScope:
    """Resolved answer to "which vacancies may this caller see"."""

    unrestricted: bool
    division_ids: tuple[uuid.UUID, ...]
    user_id: uuid.UUID
    person_id: uuid.UUID | None = None
    email: str | None = None
    employee_id: uuid.UUID | None = None

    def vacancy_filter(self) -> ColumnElement[bool]:
        """A condition on ``Vacancy``; only valid when not unrestricted.

        Returned as a condition rather than a set of ids on purpose — a
        workspace can hold thousands of vacancies, and every caller of
        this narrows an existing query that already joins ``Vacancy``.

        ``hiring_manager_id`` and ``owner_id`` are both FKs to ``users``,
        not to ``employees`` — the division subtree is the only part of
        this that goes through the employee record. A vacancy the caller
        is a candidate on drops out whatever else reaches it (HRP-971).
        """
        clauses: list[ColumnElement[bool]] = [
            Vacancy.owner_id == self.user_id,
            Vacancy.hiring_manager_id == self.user_id,
        ]
        if self.division_ids:
            clauses.append(Vacancy.division_id.in_(self.division_ids))
        own = own_candidacy(Vacancy.id, self.person_id, self.email, self.employee_id)
        if own is None:
            return or_(*clauses)
        return and_(or_(*clauses), ~own)


async def resolve_recruitment_scope(
    db: AsyncSession, current_user: User
) -> RecruitmentScope:
    # HRP-830: the whole workspace is an admin-level role's or the one
    # running hiring (``manage``) - the level replaced the recruiter role,
    # so the section's writes, which carry no scope of their own, need no
    # fence: whoever reaches them sees everything.
    if any(r.code in ADMIN_ROLE_CODES for r in current_user.roles) or (
        (await matrix_levels(db, current_user))["recruitment"] == "manage"
    ):
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
        unrestricted=False,
        division_ids=division_ids,
        user_id=current_user.id,
        person_id=current_user.person_id,
        email=current_user.email,
        employee_id=emp.id if emp is not None else None,
    )


async def fenced_off_vacancy(
    db: AsyncSession, user: User, vacancy_id: uuid.UUID
) -> bool:
    """HRP-971: the vacancy is out of ``user``'s reach because they are a
    candidate on it. The notifications ask this, the queries ask
    ``vacancy_filter``; unfenced is what ``resolve_recruitment_scope``
    calls unrestricted."""
    # The roles first: they cost no query.
    if any(r.code in ADMIN_ROLE_CODES for r in user.roles):
        return False
    emp = await get_current_employee(db, user)
    own = own_candidacy(vacancy_id, user.person_id, user.email, emp.id if emp else None)
    if own is None or not (await db.execute(select(own))).scalar():
        return False
    return (await matrix_levels(db, user))["recruitment"] != "manage"


def fenced_off_vacancy_sync(db: Session, user: User, vacancy_id: uuid.UUID) -> bool:
    """``fenced_off_vacancy`` for the Celery side."""
    # Imported here: the employee module sits above this one.
    from app.modules.employee.models import Employee

    emp_id = db.scalar(
        select(Employee.id).where(
            Employee.user_id == user.id, Employee.tenant_id == user.tenant_id
        )
    )
    codes = {r.code for r in user.roles}
    if codes & ADMIN_ROLE_CODES:
        return False
    own = own_candidacy(vacancy_id, user.person_id, user.email, emp_id)
    if own is None or not db.execute(select(own)).scalar():
        return False
    # Imported here: the company service sits above this module.
    from app.modules.company.service import get_section_overrides_sync

    overrides, hidden = get_section_overrides_sync(db, user.tenant_id)
    return effective_levels(codes, overrides, hidden)["recruitment"] != "manage"


async def fenced_users(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> list[User]:
    """HRP-971: the users the fence keeps off the vacancy - its candidates
    and whoever reacted to its talent-market twin, below the admin level
    and ``manage``. None of them interviews or evaluates on it: they could
    open neither the interview nor the sheet, and would sit on their own or
    a rival's."""
    # Imported here: the employee module sits above this one.
    from app.modules.employee.models import Employee

    cands = (
        await db.execute(
            select(Candidate.person_id, Candidate.email)
            .join(CandidateVacancy, CandidateVacancy.candidate_id == Candidate.id)
            .where(CandidateVacancy.vacancy_id == vacancy_id)
        )
    ).all()
    reactors = (
        select(Employee.user_id)
        .join(TalentCandidate, TalentCandidate.employee_id == Employee.id)
        .join(Vacancy, Vacancy.talent_card_id == TalentCandidate.card_id)
        .where(Vacancy.id == vacancy_id, TalentCandidate.response_at.isnot(None))
    )
    users = (
        await db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(
                User.tenant_id == tenant_id,
                or_(
                    User.person_id.in_({p for p, _ in cands if p is not None}),
                    func.lower(User.email).in_({e.lower() for _, e in cands if e}),
                    User.id.in_(reactors),
                ),
            )
        )
    ).scalars()
    return [u for u in users if await fenced_off_vacancy(db, u, vacancy_id)]


async def refuse_fenced_assignees(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    *,
    user_ids: set[uuid.UUID] | None = None,
    emails: set[str] | None = None,
) -> None:
    """422 when an interviewer, an evaluator or an invited email is one the
    fence keeps off the vacancy - or, for an email invite, any candidate on
    it: its token opens the sheet past the matrix (HRP-971)."""
    fenced = await fenced_users(db, tenant_id, vacancy_id)
    if user_ids and user_ids & {u.id for u in fenced}:
        raise AppError("assignee_fenced_off", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if not emails:
        return
    taken = {u.email.lower() for u in fenced if u.email}
    taken.update(
        e.lower()
        for e in (
            await db.execute(
                select(Candidate.email)
                .join(CandidateVacancy, CandidateVacancy.candidate_id == Candidate.id)
                .where(CandidateVacancy.vacancy_id == vacancy_id)
            )
        ).scalars()
        if e
    )
    if {e.lower() for e in emails} & taken:
        raise AppError("assignee_fenced_off", status.HTTP_422_UNPROCESSABLE_CONTENT)


async def email_fenced_off(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID, email: str
) -> bool:
    """``refuse_fenced_assignees``'s email rule for one address: a candidate
    on the vacancy, or a user the fence keeps off it (HRP-971). Asked of a
    token already out, whose addressee may have applied since it was sent."""
    own = own_candidacy(vacancy_id, None, email)
    if own is not None and (await db.execute(select(own))).scalar():
        return True
    user = await db.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.tenant_id == tenant_id, func.lower(User.email) == email.lower())
    )
    return user is not None and await fenced_off_vacancy(db, user, vacancy_id)


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


def _by_human_assessment(assessment_id: uuid.UUID) -> Select:
    """``HumanAssessment``, not ``RecruitmentAssessment`` (HRP-630).

    Two unrelated tables answer to "an assessment": the manager-assessment
    sheet (``recruitment_assessments``, reached by ``_by_assessment``) and
    the per-competence human score behind
    ``PATCH /recruitment/assessments/{assessment_id}``. Same path word,
    different rows — pointing the wrong guard at either one refuses every
    scoped caller, since no id is ever found in the other table.
    """
    return _CV_TO_VACANCY.join(
        HumanAssessment, HumanAssessment.candidate_vacancy_id == CandidateVacancy.id
    ).where(HumanAssessment.id == assessment_id)


def _by_candidate_question(question_id: uuid.UUID) -> Select:
    """The R3-era interview question, keyed straight off its vacancy."""
    return (
        select(Vacancy.id)
        .join(CandidateQuestion, CandidateQuestion.vacancy_id == Vacancy.id)
        .where(CandidateQuestion.id == question_id)
    )


def _by_question_set(set_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.join(
        QuestionSet, QuestionSet.candidate_vacancy_id == CandidateVacancy.id
    ).where(QuestionSet.id == set_id)


def _by_question(question_id: uuid.UUID) -> Select:
    """The HRP-486 question, which hangs off a set rather than a vacancy."""
    return (
        _CV_TO_VACANCY.join(
            QuestionSet, QuestionSet.candidate_vacancy_id == CandidateVacancy.id
        )
        .join(Question, Question.question_set_id == QuestionSet.id)
        .where(Question.id == question_id)
    )


def _by_invite(invite_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.join(
        AssessmentInvite, AssessmentInvite.candidate_vacancy_id == CandidateVacancy.id
    ).where(AssessmentInvite.id == invite_id)


# --- FastAPI dependencies -------------------------------------------------
#
# These are guards, not gates: each route keeps whatever level or role
# check it already had and adds one of these as an extra parameter. The
# level answers "may you be in recruitment at all", scope answers "is this
# particular vacancy yours" — keeping them separate means adding scope to
# a route never quietly widens who reaches it.
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


async def human_assessment_scope(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    """Guard for ``/recruitment/assessments/{assessment_id}``.

    Deliberately not ``assessment_scope``: that one is keyed by the same
    parameter name but resolves a different table — see
    ``_by_human_assessment``.
    """
    await assert_in_scope(db, current_user, scope, _by_human_assessment(assessment_id))


async def candidate_question_scope(
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_candidate_question(question_id))


async def question_set_scope(
    set_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_question_set(set_id))


async def question_scope(
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_question(question_id))


async def invite_scope(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: RecruitmentScope = Depends(recruitment_scope),
) -> None:
    await assert_in_scope(db, current_user, scope, _by_invite(invite_id))


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
