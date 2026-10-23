"""Who sees which vacancy — and everything hanging off it (HRP-629).

The section access matrix (HRP-830) decides whether a caller may open
the hiring surface at all. It does not decide *how much* of it: a
division head picks up the ``manager`` role automatically the moment
``company.service`` makes them a division manager, which used to leave
them reading candidate contacts, resumes and interview transcripts for
every vacancy in the workspace, including a neighbouring department's.

The rule now: an admin-level role or the ``recruiter`` role keeps the whole
tenant - at ``view`` read-only, at ``manage`` running it (HRP-830 REDO, QA
14.10). Everyone else - the manager, the hiring manager, at ``manage`` too -
sees a vacancy only when

* it belongs to a division they manage (their subtree), or
* they are its named hiring manager

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
from collections.abc import Callable, Mapping
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
from app.core.sections import matrix_levels
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.recruitment.manager_assessment_models import (
    AssessmentRound,
    RecruitmentAssessment,
)
from app.modules.recruitment.models import (
    AIAnalysisRun,
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

#: HRP-830 REDO (QA 14.10): who reads all of hiring - the admin level, and the
#: recruiter at whatever level the section opens to them. ``manage`` alone no
#: longer does: the manager runs hiring on their divisions, the hiring manager
#: on the vacancies they are named on. Unfenced (HRP-971) is the same set.
UNRESTRICTED_ROLE_CODES = ADMIN_ROLE_CODES | {"recruiter"}


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
    #: ``manage`` on recruitment - runs hiring, inside the scope when scoped.
    manages: bool = False

    @property
    def full_payload(self) -> bool:
        """The full AI payload (``resolve_user_role``): whoever sees all of
        hiring or runs it - a manager at ``manage`` on their own vacancies."""
        return self.unrestricted or self.manages

    def vacancy_filter(self) -> ColumnElement[bool]:
        """A condition on ``Vacancy``; only valid when not unrestricted.

        Returned as a condition rather than a set of ids on purpose — a
        workspace can hold thousands of vacancies, and every caller of
        this narrows an existing query that already joins ``Vacancy``.

        ``hiring_manager_id`` is an FK to ``users``, not to ``employees`` —
        the division subtree is the only part of this that goes through the
        employee record. A vacancy the caller is a candidate on drops out
        whatever else reaches it (HRP-971).

        HRP-830 REDO (QA 14.10): authorship no longer reaches a vacancy - a
        manager's are their subtree's, a hiring manager's those naming them.
        """
        clauses: list[ColumnElement[bool]] = [
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
    # HRP-830 REDO: the whole workspace is the admin level's and the
    # recruiter's; ``manage`` runs hiring inside the scope below it.
    if any(r.code in UNRESTRICTED_ROLE_CODES for r in current_user.roles):
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
        manages=(await matrix_levels(db, current_user))["recruitment"] == "manage",
    )


async def fenced_off_vacancy(
    db: AsyncSession, user: User, vacancy_id: uuid.UUID
) -> bool:
    """HRP-971: the vacancy is out of ``user``'s reach because they are a
    candidate on it. The notifications ask this, the queries ask
    ``vacancy_filter``; unfenced is what ``resolve_recruitment_scope``
    calls unrestricted."""
    if any(r.code in UNRESTRICTED_ROLE_CODES for r in user.roles):
        return False
    emp = await get_current_employee(db, user)
    own = own_candidacy(vacancy_id, user.person_id, user.email, emp.id if emp else None)
    return own is not None and bool((await db.execute(select(own))).scalar())


def fenced_off_vacancy_sync(db: Session, user: User, vacancy_id: uuid.UUID) -> bool:
    """``fenced_off_vacancy`` for the Celery side."""
    # Imported here: the employee module sits above this one.
    from app.modules.employee.models import Employee

    emp_id = db.scalar(
        select(Employee.id).where(
            Employee.user_id == user.id, Employee.tenant_id == user.tenant_id
        )
    )
    if {r.code for r in user.roles} & UNRESTRICTED_ROLE_CODES:
        return False
    own = own_candidacy(vacancy_id, user.person_id, user.email, emp_id)
    return own is not None and bool(db.execute(select(own)).scalar())


async def fenced_users(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> list[User]:
    """HRP-971: the users the fence keeps off the vacancy - its candidates
    and whoever reacted to its talent-market twin, outside
    ``UNRESTRICTED_ROLE_CODES``. None of them interviews or evaluates on it: they could
    open neither the interview nor the sheet, and would sit on their own or
    a rival's."""
    # Imported here: the employee module sits above this one.
    from app.modules.employee.models import Employee

    # ``own_candidacy`` correlated with ``User`` instead of asked per user
    # (HRP-1018): the same keys - their Person, their email in SQL lower
    # case (an empty one matches nothing), their employee row of the
    # tenant ``get_current_employee`` reads - so no second check is needed.
    candidacy = (
        select(Candidate.id)
        .join(CandidateVacancy, CandidateVacancy.candidate_id == Candidate.id)
        .where(
            CandidateVacancy.vacancy_id == vacancy_id,
            or_(
                Candidate.person_id == User.person_id,
                and_(
                    User.email != "",
                    func.lower(Candidate.email) == func.lower(User.email),
                ),
            ),
        )
    )
    reaction = (
        select(Employee.id)
        .join(TalentCandidate, TalentCandidate.employee_id == Employee.id)
        .join(Vacancy, Vacancy.talent_card_id == TalentCandidate.card_id)
        .where(
            Employee.user_id == User.id,
            Employee.tenant_id == User.tenant_id,
            Vacancy.id == vacancy_id,
            TalentCandidate.response_at.isnot(None),
        )
    )
    rows = await db.scalars(
        select(User)
        .options(selectinload(User.roles))
        .where(User.tenant_id == tenant_id, or_(candidacy.exists(), reaction.exists()))
    )
    # The unrestricted roles stay unfenced, as in ``fenced_off_vacancy``.
    return [u for u in rows if not {r.code for r in u.roles} & UNRESTRICTED_ROLE_CODES]


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


def _by_ai_run(run_id: uuid.UUID) -> Select:
    return _CV_TO_VACANCY.join(
        AIAnalysisRun, AIAnalysisRun.candidate_vacancy_id == CandidateVacancy.id
    ).where(AIAnalysisRun.id == run_id)


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


# HRP-830 REDO: ``manage`` runs hiring inside the scope, so whatever a
# ``manage`` route names in its path must be in it. One path key, one way
# back to the vacancy. ``assessment_id`` and ``question_id`` name two
# tables each and are left to the routes' own guards.
PATH_SCOPE_KEYS: dict[str, Callable[[uuid.UUID], Select]] = {
    "vacancy_id": _by_vacancy,
    "candidate_id": _by_candidate,
    "cv_id": _by_candidate_vacancy,
    "candidate_vacancy_id": _by_candidate_vacancy,
    "interview_id": _by_interview,
    "resume_id": _by_candidate_file,
    "export_id": _by_report,
    "report_id": _by_report,
    "round_id": _by_round,
    "set_id": _by_question_set,
    "invite_id": _by_invite,
    "run_id": _by_ai_run,
}


async def assert_path_in_scope(
    db: AsyncSession,
    current_user: User,
    scope: RecruitmentScope,
    path_params: Mapping[str, str],
) -> None:
    """403 ``outside_recruitment_scope`` unless every hiring resource named
    in the path reaches a vacancy in scope (``runs_hiring``)."""
    if scope.unrestricted:
        return
    for key, raw in path_params.items():
        by = PATH_SCOPE_KEYS.get(key)
        if by is None:
            continue
        try:
            resource_id = uuid.UUID(raw)
        except ValueError:
            continue  # the route's own parameter answers 422
        await assert_in_scope(db, current_user, scope, by(resource_id))


async def assert_vacancy_placement(
    db: AsyncSession,
    current_user: User,
    scope: RecruitmentScope,
    division_id: uuid.UUID | None,
    hiring_manager_id: uuid.UUID | None,
    vacancy_id: uuid.UUID | None = None,
) -> None:
    """HRP-830 REDO: where a scoped caller may put a vacancy they create or
    re-home - a division in their subtree, or, holding the hiring_manager
    role, themselves as its hiring manager. Authorship does not count: it
    is what would let a vacancy leave the scope and stay readable.

    ``vacancy_id`` is an edit: unchanged placement passes, so a vacancy
    already in scope keeps taking its other edits.
    """
    if scope.unrestricted:
        return
    if vacancy_id is not None:
        current = await db.get(Vacancy, vacancy_id)
        if current is not None and (
            current.division_id,
            current.hiring_manager_id,
        ) == (division_id, hiring_manager_id):
            return
    if division_id is not None and division_id in scope.division_ids:
        return
    holds_hm = "hiring_manager" in {r.code for r in current_user.roles}
    if holds_hm and hiring_manager_id == current_user.id:
        return
    if holds_hm and not scope.division_ids:
        # Their only way to keep it in scope: say so, not "your division".
        raise AppError(
            "vacancy_hiring_manager_must_be_you",
            status.HTTP_403_FORBIDDEN,
            detail_extra={},
            detail_code_key="error_code",
        )
    raise _outside()


async def candidate_reachable(
    db: AsyncSession,
    current_user: User,
    scope: RecruitmentScope,
    candidate_id: uuid.UUID,
) -> bool:
    """The candidate hangs off at least one vacancy in scope."""
    if scope.unrestricted:
        return True
    stmt = (
        _by_candidate(candidate_id)
        .where(Vacancy.tenant_id == current_user.tenant_id, scope.vacancy_filter())
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


def _outside() -> AppError:
    return AppError(
        "outside_recruitment_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


async def hidden_duplicate(
    db: AsyncSession,
    current_user: User,
    scope: RecruitmentScope,
    exc: AppError,
) -> AppError | None:
    """HRP-830 REDO review: the 409 that names an existing candidate
    (``candidate_email_conflict``, ``candidate_archived``) as a scoped caller
    may hear it - the same conflict without the id when that candidate is
    out of their reach; ``None`` keeps the original. The email being taken
    stays visible: that is the price of one candidate per email."""
    existing = (exc.detail_extra or {}).get("existing_candidate_id")
    if (
        exc.code not in ("candidate_email_conflict", "candidate_archived")
        or not existing
    ):
        return None
    if await candidate_reachable(db, current_user, scope, uuid.UUID(str(existing))):
        return None
    return AppError("candidate_email_taken_elsewhere", status.HTTP_409_CONFLICT)


async def assert_candidate_linkable(
    db: AsyncSession,
    current_user: User,
    scope: RecruitmentScope,
    candidate_id: uuid.UUID,
) -> None:
    """HRP-830 REDO review: linking an existing candidate to a vacancy hands
    their whole card and every resume over, so a scoped caller links only a
    candidate already in their scope - fail-closed. Someone applying to their
    vacancy who is already a candidate elsewhere is attached by a recruiter
    or HR, who see the whole workspace (one candidate per email, HRP-1078)."""
    if not await candidate_reachable(db, current_user, scope, candidate_id):
        raise _outside()


async def assert_every_application_in_scope(
    db: AsyncSession,
    current_user: User,
    scope: RecruitmentScope,
    candidate_id: uuid.UUID,
) -> None:
    """HRP-830 REDO review: archiving a candidate takes them off every
    vacancy in the tenant, so a scoped caller archives only a candidate whose
    every application is theirs; one on someone else's vacancy too is
    detached from their own (``DELETE /candidate-vacancies/{cv_id}``)."""
    if scope.unrestricted:
        return
    applications = (
        select(func.count())
        .select_from(CandidateVacancy)
        .join(Vacancy, Vacancy.id == CandidateVacancy.vacancy_id)
        .where(
            CandidateVacancy.candidate_id == candidate_id,
            Vacancy.tenant_id == current_user.tenant_id,
        )
    )
    total = await db.scalar(applications)
    inside = await db.scalar(applications.where(scope.vacancy_filter()))
    if total != inside:
        raise _outside()
