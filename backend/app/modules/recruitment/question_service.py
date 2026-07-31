"""HRP-205: per-candidate individual interview question sets.

Owns the new ``question_sets`` / ``questions`` tables. The legacy
``candidate_questions`` table from R1 lives alongside in
``assessment_service.py`` and is unaffected — both APIs coexist while
the recruitment UI migrates over.

Generation goes through three modes:

* ``initial`` — first set for a candidate-vacancy. Sees only resume +
  vacancy profile.
* ``regenerated`` — overwrites an existing set. AI-generated questions
  are replaced; manual / from_competency_indicator entries survive.
* ``dynamic_next`` — new set after one or more interview rounds. Sees
  the prior sets (covered state included) + transcripts + blind spots
  so the next round does not repeat answered ground and turns flagged
  blind spots into ``from_blind_spot`` questions.

Manager scores are intentionally NOT passed to the LLM — see
``QUESTION_SET_SYSTEM_PROMPT``. The dynamic mode does see *its own*
prior question sets but never any human assessment numbers.

Billing: ``generate_question_set`` is wired into ``ee/billing.py``
``BILLABLE`` at 8 credits. ``generate_sample_question_set`` is exempt —
when a tenant's balance is below threshold the UI can fall back to a
static preview without spending credits.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.ai.llm_client import generate_json
from app.modules.recruitment.ai_service import RECRUITMENT_MAX_TOKENS
from app.modules.recruitment.common import _publish_event, normalize_competence_id
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
    CandidateVacancy,
    Interview,
    Question,
    QuestionSet,
    Vacancy,
    VacancyProfile,
)
from app.modules.recruitment.prompts_interview import (
    QUESTION_SET_SYSTEM_PROMPT,
    GeneratedQuestionSet,
    build_question_set_prompt,
)
from app.modules.recruitment.schemas import (
    GenerateQuestionSetRequest,
    QuestionCreate2,
    QuestionUpdate2,
)

logger = logging.getLogger(__name__)


GENERATE_COST_CREDITS = 8


# ---------------------------------------------------------------------------
# Read paths
# ---------------------------------------------------------------------------


def _set_to_dict(qs: QuestionSet) -> dict:
    return {
        "id": qs.id,
        "candidate_vacancy_id": qs.candidate_vacancy_id,
        "round_id": qs.round_id,
        "set_type": qs.set_type,
        "name": qs.name,
        "status": qs.status,
        "generation_mode": qs.generation_mode,
        "source_round_ids": qs.source_round_ids,
        "llm_provider": qs.llm_provider,
        "llm_model": qs.llm_model,
        "coverage_note": qs.coverage_note,
        "created_by": qs.created_by,
        "archived_at": qs.archived_at,
        "version": qs.version,
        "created_at": qs.created_at,
        "questions": [
            _question_to_dict(q) for q in qs.questions if q.status == "active"
        ],
    }


def _question_to_dict(q: Question) -> dict:
    return {
        "id": q.id,
        "question_set_id": q.question_set_id,
        "text": q.text,
        "goal": q.goal,
        "priority": q.priority,
        "competence_id": q.competence_id,
        "resume_anchor_jsonb": q.resume_anchor_jsonb,
        "expected_answer_indicators": q.expected_answer_indicators or [],
        "follow_ups": q.follow_ups or [],
        "rationale": q.rationale,
        "source": q.source,
        "source_blind_spot_id": q.source_blind_spot_id,
        "sort_order": q.sort_order,
        "status": q.status,
        "covered_at": q.covered_at,
        "covered_by": q.covered_by,
        "covered_method": q.covered_method,
        "version": q.version,
    }


async def list_question_sets(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    vacancy_id: uuid.UUID | None = None,
) -> list[dict]:
    """List question sets for a candidate, optionally filtered by vacancy.

    Sets are returned newest-first; the active (non-archived) ones come
    first so the frontend tab-bar lights up the latest set by default.
    """
    cv_query = select(CandidateVacancy).where(
        CandidateVacancy.candidate_id == candidate_id,
        CandidateVacancy.tenant_id == tenant_id,
    )
    if vacancy_id is not None:
        cv_query = cv_query.where(CandidateVacancy.vacancy_id == vacancy_id)
    cvs = (await db.execute(cv_query)).scalars().all()
    if not cvs:
        return []
    cv_ids = [cv.id for cv in cvs]

    sets = (
        (
            await db.execute(
                select(QuestionSet)
                .where(
                    QuestionSet.tenant_id == tenant_id,
                    QuestionSet.candidate_vacancy_id.in_(cv_ids),
                )
                .order_by(
                    QuestionSet.archived_at.is_(None).desc(),
                    QuestionSet.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [_set_to_dict(qs) for qs in sets]


async def get_question_set(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_set_id: uuid.UUID,
) -> QuestionSet:
    """Fetch a question set scoped to ``tenant_id`` or raise 404."""
    qs = (
        await db.execute(
            select(QuestionSet).where(
                QuestionSet.id == question_set_id,
                QuestionSet.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if qs is None:
        raise AppError("question_set_not_found", status.HTTP_404_NOT_FOUND)
    return qs


async def _load_candidate_vacancy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
) -> CandidateVacancy:
    cv = (
        await db.execute(
            select(CandidateVacancy).where(
                CandidateVacancy.id == cv_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cv is None:
        raise AppError("candidate_vacancy_not_found", status.HTTP_404_NOT_FOUND)
    return cv


async def _load_parsed_resume(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> dict | None:
    """Most recent parsed resume payload for a candidate, or None."""
    resume = (
        await db.execute(
            select(CandidateFile)
            .where(
                CandidateFile.candidate_id == candidate_id,
                CandidateFile.tenant_id == tenant_id,
                CandidateFile.parse_status == "completed",
            )
            .order_by(CandidateFile.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if resume is None:
        return None
    return resume.parsed_data


async def _load_profile_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
) -> list[dict]:
    profile = (
        await db.execute(
            select(VacancyProfile).where(
                VacancyProfile.vacancy_id == vacancy_id,
                VacancyProfile.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if profile is None or not profile.profile_data:
        return []
    competences = profile.profile_data.get("competences") or []
    return [c for c in competences if isinstance(c, dict)]


async def _load_transcripts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    round_ids: list[uuid.UUID],
) -> list[dict]:
    """Fetch transcripts for the rounds the dynamic_next set covers.

    Returns plain text; segments + speaker labels stay opaque here so
    the prompt stays small.
    """
    if not round_ids:
        return []
    interviews = (
        (
            await db.execute(
                select(Interview).where(
                    Interview.id.in_(round_ids),
                    Interview.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {"interview_id": str(iv.id), "text": iv.transcript or ""}
        for iv in interviews
        if iv.transcript
    ]


async def _previous_sets_payload(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    *,
    exclude_set_id: uuid.UUID | None = None,
) -> list[dict]:
    """Compact payload for the LLM: prior sets with question text +
    covered state + source. Manager scores are intentionally omitted.
    """
    sets = (
        (
            await db.execute(
                select(QuestionSet)
                .where(
                    QuestionSet.candidate_vacancy_id == cv_id,
                    QuestionSet.tenant_id == tenant_id,
                )
                .order_by(QuestionSet.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    payload = []
    for s in sets:
        if exclude_set_id is not None and s.id == exclude_set_id:
            continue
        payload.append(
            {
                "set_id": str(s.id),
                "set_type": s.set_type,
                "generation_mode": s.generation_mode,
                "questions": [
                    {
                        "text": q.text,
                        "source": q.source,
                        "priority": q.priority,
                        "covered": q.covered_at is not None,
                    }
                    for q in s.questions
                    if q.status == "active"
                ],
            }
        )
    return payload


async def _collect_blind_spots(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    round_ids: list[uuid.UUID],
) -> list[dict]:
    """Pull blind-spot suggestions stored by the interview analysis.

    The interview-analysis task stores its full payload (including
    ``blind_spots``) in ``interviews.analysis_data``. We don't bind to a
    Pydantic shape here — pull verbatim and let the prompt deal with it.
    """
    if not round_ids:
        return []
    interviews = (
        (
            await db.execute(
                select(Interview).where(
                    Interview.id.in_(round_ids),
                    Interview.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    blind_spots: list[dict] = []
    for iv in interviews:
        data = iv.analysis_data or {}
        if isinstance(data, dict):
            spots = data.get("blind_spots") or []
            for s in spots:
                if isinstance(s, dict):
                    blind_spots.append(
                        {
                            "competence_id": s.get("competence_id"),
                            "suggested_question": s.get("suggested_question"),
                            "round_id": str(iv.id),
                        }
                    )
    return blind_spots


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


def _competence_id_by_name(
    competences: list[dict],
) -> dict[str, uuid.UUID]:
    """Lower-cased name → competence UUID for matching LLM output.

    AI-generated profiles use kebab-case slugs as competence ids;
    ``normalize_competence_id`` maps those deterministically (uuid5) —
    the SAME mapping ``analyze_interview_task`` uses for ``AIAssessment``
    rows, so auto-cover can join questions to assessed competences
    (HRP-205 REDO; previously slug ids were skipped and every question
    carried ``competence_id=None``).
    """
    out: dict[str, uuid.UUID] = {}
    for c in competences:
        name = (c.get("name") or "").strip().lower()
        normalized = normalize_competence_id(c.get("id"))
        if not name or normalized is None:
            continue
        out[name] = normalized
    return out


def _build_questions(
    generated: GeneratedQuestionSet,
    *,
    tenant_id: uuid.UUID,
    question_set_id: uuid.UUID,
    competence_lookup: dict[str, uuid.UUID],
) -> list[Question]:
    items: list[Question] = []
    for idx, gq in enumerate(generated.questions):
        comp_id: uuid.UUID | None = None
        if gq.competence_name:
            comp_id = competence_lookup.get(gq.competence_name.strip().lower())
        anchor: dict | None = None
        if gq.resume_anchor and gq.resume_anchor.quote:
            anchor = {
                "quote": gq.resume_anchor.quote,
                "section": gq.resume_anchor.section,
            }
        items.append(
            Question(
                tenant_id=tenant_id,
                question_set_id=question_set_id,
                text=gq.text,
                goal=gq.goal,
                priority=gq.priority,
                competence_id=comp_id,
                resume_anchor_jsonb=anchor,
                expected_answer_indicators=list(gq.expected_answer_indicators or []),
                follow_ups=list(gq.follow_ups or []),
                rationale=gq.rationale,
                source=gq.source,
                sort_order=idx,
                status="active",
            )
        )
    return items


def _validate_question_count(generated: GeneratedQuestionSet) -> None:
    """FR-12: 8-15 questions. Anything outside the window is a failure."""
    n = len(generated.questions)
    if not 8 <= n <= 15:
        raise AppError(
            "question_count_out_of_range",
            status.HTTP_502_BAD_GATEWAY,
            count=n,
        )


async def _call_llm(
    *,
    db: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
    vacancy: Vacancy,
    profile_competences: list[dict],
    resume_data: dict,
    previous_questions: list[dict],
    transcripts: list[dict],
    blind_spots: list[dict],
    generation_mode: str,
) -> GeneratedQuestionSet:
    prompt = build_question_set_prompt(
        vacancy_title=vacancy.title,
        language=vacancy.language or "en",
        profile_competences=profile_competences,
        resume_data=resume_data,
        previous_questions=previous_questions,
        transcripts=transcripts,
        blind_spots=blind_spots,
        generation_mode=generation_mode,
    )
    raw = await generate_json(
        prompt,
        system=QUESTION_SET_SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=RECRUITMENT_MAX_TOKENS,
        schema=GeneratedQuestionSet,
        db=db,
        tenant_id=tenant_id,
    )
    if isinstance(raw, GeneratedQuestionSet):
        return raw
    # Loose-mode fallback when callers (tests) pre-mock generate_json
    # without a schema response.
    return GeneratedQuestionSet.model_validate(raw)


async def generate_question_set(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    data: GenerateQuestionSetRequest,
    *,
    current_user_id: uuid.UUID | None = None,
) -> dict:
    """Generate or regenerate a question set for a candidate-vacancy.

    Billable. Wrapped by ``ee.billing.register_billing`` at 8 credits per
    call.
    """
    cv = await _load_candidate_vacancy(db, tenant_id, cv_id)
    candidate = await db.get(Candidate, cv.candidate_id)
    vacancy = await db.get(Vacancy, cv.vacancy_id)
    if candidate is None or vacancy is None:
        raise AppError("candidate_or_vacancy_missing", status.HTTP_404_NOT_FOUND)

    resume_data = await _load_parsed_resume(db, tenant_id, cv.candidate_id)
    if resume_data is None:
        raise AppError("parsed_resume_required", status.HTTP_409_CONFLICT)

    profile_competences = await _load_profile_competences(db, tenant_id, cv.vacancy_id)

    if data.mode == "regenerated":
        if data.target_set_id is None:
            raise AppError("target_set_id_required", status.HTTP_400_BAD_REQUEST)
        target = await get_question_set(db, tenant_id, data.target_set_id)
        if target.candidate_vacancy_id != cv.id:
            raise AppError(
                "target_set_not_in_candidate_vacancy", status.HTTP_400_BAD_REQUEST
            )
        previous_questions = await _previous_sets_payload(
            db, tenant_id, cv.id, exclude_set_id=target.id
        )
        transcripts: list[dict] = []
        blind_spots: list[dict] = []
    elif data.mode == "dynamic_next":
        round_ids = data.source_round_ids or ([data.round_id] if data.round_id else [])
        round_ids = [r for r in round_ids if r is not None]
        previous_questions = await _previous_sets_payload(db, tenant_id, cv.id)
        transcripts = await _load_transcripts(db, tenant_id, round_ids)
        blind_spots = await _collect_blind_spots(db, tenant_id, round_ids)
        target = None
    else:  # initial
        previous_questions = []
        transcripts = []
        blind_spots = []
        target = None

    notify_ctx = {
        "tenant_id": str(tenant_id),
        "candidate_id": str(cv.candidate_id),
        "candidate_name": candidate.full_name,
        "vacancy_id": str(cv.vacancy_id),
        "vacancy_title": vacancy.title,
        "requested_by": str(current_user_id) if current_user_id else None,
        "mode": data.mode,
        "link": f"/recruitment/candidates/{cv.candidate_id}?vacancyId={cv.vacancy_id}",
    }
    try:
        generated = await _call_llm(
            db=db,
            tenant_id=tenant_id,
            vacancy=vacancy,
            profile_competences=profile_competences,
            resume_data=resume_data,
            previous_questions=previous_questions,
            transcripts=transcripts,
            blind_spots=blind_spots,
            generation_mode=data.mode,
        )
        _validate_question_count(generated)
    except Exception:
        # HRP-205 REDO: N-question_set_failed with a deep link back to the
        # candidate page so the requester can retry. Published before the
        # error propagates to the client.
        await _publish_event("recruitment.question_set.failed", notify_ctx)
        raise

    competence_lookup = _competence_id_by_name(profile_competences)

    if data.mode == "regenerated" and target is not None:
        # Keep manual + from_competency_indicator entries; replace the
        # AI-generated ones. ``status=removed`` rows are dropped so the
        # set reflects the new world; they were soft-deleted before
        # regeneration and the spec says removed questions stay removed.
        kept: list[Question] = []
        for q in list(target.questions):
            if q.source in {"manual", "from_competency_indicator"}:
                kept.append(q)
            else:
                await db.delete(q)
        new_items = _build_questions(
            generated,
            tenant_id=tenant_id,
            question_set_id=target.id,
            competence_lookup=competence_lookup,
        )
        # Re-number sort_order so kept manuals come first.
        for idx, q in enumerate(kept):
            q.sort_order = idx
        for idx, q in enumerate(new_items, start=len(kept)):
            q.sort_order = idx
            db.add(q)
        target.coverage_note = generated.coverage_note
        target.generation_mode = "regenerated"
        target.version = (target.version or 1) + 1
        target.created_by = current_user_id
        await db.commit()
        await db.refresh(target)
        saved = target
    else:
        saved = QuestionSet(
            tenant_id=tenant_id,
            candidate_vacancy_id=cv.id,
            round_id=data.round_id,
            set_type=data.set_type,
            name=data.name or _default_set_name(data.mode, data.set_type),
            status="ready",
            generation_mode=data.mode,
            source_round_ids=data.source_round_ids,
            coverage_note=generated.coverage_note,
            created_by=current_user_id,
        )
        db.add(saved)
        await db.flush()
        for q in _build_questions(
            generated,
            tenant_id=tenant_id,
            question_set_id=saved.id,
            competence_lookup=competence_lookup,
        ):
            db.add(q)
        await db.commit()
        await db.refresh(saved)

    await _publish_event(
        "recruitment.question_set.ready",
        {**notify_ctx, "question_set_id": str(saved.id), "set_name": saved.name},
    )
    return _set_to_dict(saved)


def _default_set_name(mode: str, set_type: str) -> str:
    if mode == "dynamic_next":
        return "Next round"
    if mode == "regenerated":
        return "Regenerated set"
    if set_type == "final":
        return "Final round"
    return "Pre-interview set"


# ---------------------------------------------------------------------------
# Sample mode — free, static, never persisted
# ---------------------------------------------------------------------------


SAMPLE_QUESTION_SET: dict[str, Any] = {
    "id": None,
    "candidate_vacancy_id": None,
    "round_id": None,
    "set_type": "pre_interview",
    "name": "Sample set",
    "status": "sample",
    "generation_mode": "initial",
    "source_round_ids": None,
    "llm_provider": None,
    "llm_model": None,
    "coverage_note": (
        "Sample mode: this is a static preview shown when the tenant "
        "balance is below the generation threshold. No credits charged."
    ),
    "created_by": None,
    "archived_at": None,
    "version": 1,
    "created_at": None,
    "questions": [
        {
            "id": None,
            "question_set_id": None,
            "text": (
                "You wrote you led a payment-platform migration in 2022. "
                "What was the riskiest call you made during that project?"
            ),
            "goal": "depth",
            "priority": "must",
            "competence_id": None,
            "resume_anchor_jsonb": {
                "quote": "Led the payment-platform migration in 2022",
                "section": "experience",
            },
            "expected_answer_indicators": [
                "Names a specific decision under uncertainty",
                "Trade-offs articulated with business impact",
                "Shows ownership rather than blame-shifting",
            ],
            "follow_ups": [
                "What would you do differently today?",
                "How did the team react?",
            ],
            "rationale": (
                "The resume claims platform leadership; we need a concrete "
                "decision moment to verify depth of ownership."
            ),
            "source": "ai_generated",
            "source_blind_spot_id": None,
            "sort_order": 0,
            "status": "active",
            "covered_at": None,
            "covered_by": None,
            "covered_method": None,
            "version": 1,
        }
    ],
}


def get_sample_question_set() -> dict:
    """Return the static sample set used when credits are insufficient.

    Free for the tenant (not billable). The returned payload is shaped
    like ``QuestionSetRead`` so the frontend can render it through the
    same components.
    """
    return SAMPLE_QUESTION_SET


# ---------------------------------------------------------------------------
# Question CRUD
# ---------------------------------------------------------------------------


async def add_question_to_set(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_set_id: uuid.UUID,
    data: QuestionCreate2,
    *,
    current_user_id: uuid.UUID | None = None,
) -> dict:
    qs = await get_question_set(db, tenant_id, question_set_id)
    next_order = (
        max((q.sort_order for q in qs.questions if q.status == "active"), default=-1)
        + 1
    )
    q = Question(
        tenant_id=tenant_id,
        question_set_id=qs.id,
        text=data.text,
        goal=data.goal,
        priority=data.priority,
        competence_id=data.competence_id,
        resume_anchor_jsonb=data.resume_anchor_jsonb,
        expected_answer_indicators=list(data.expected_answer_indicators or []),
        follow_ups=list(data.follow_ups or []),
        rationale=data.rationale,
        source=data.source,
        sort_order=next_order,
        status="active",
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return _question_to_dict(q)


async def _get_question(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_id: uuid.UUID,
) -> Question:
    q = (
        await db.execute(
            select(Question).where(
                Question.id == question_id,
                Question.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if q is None:
        raise AppError("question_not_found", status.HTTP_404_NOT_FOUND)
    return q


async def update_question_v2(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_id: uuid.UUID,
    data: QuestionUpdate2,
    *,
    current_user_id: uuid.UUID | None = None,
) -> dict:
    q = await _get_question(db, tenant_id, question_id)

    payload = data.model_dump(exclude_unset=True)
    move_to = payload.pop("move_to_set_id", None)
    covered = payload.pop("covered", None)

    for field, value in payload.items():
        setattr(q, field, value)

    if covered is True:
        from datetime import UTC, datetime

        q.covered_at = datetime.now(UTC)
        q.covered_method = "manual"
        q.covered_by = current_user_id
    elif covered is False:
        q.covered_at = None
        q.covered_method = None
        q.covered_by = None

    if move_to is not None:
        target = await get_question_set(db, tenant_id, move_to)
        if target.candidate_vacancy_id != q.question_set.candidate_vacancy_id:
            raise AppError(
                "question_move_cross_candidate_vacancy", status.HTTP_400_BAD_REQUEST
            )
        q.question_set_id = target.id

    q.version = (q.version or 1) + 1
    await db.commit()
    await db.refresh(q)
    return _question_to_dict(q)


async def soft_delete_question(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_id: uuid.UUID,
) -> None:
    """Soft-delete: keeps the row so regenerate logic can avoid resurrecting it."""
    q = await _get_question(db, tenant_id, question_id)
    q.status = "removed"
    q.version = (q.version or 1) + 1
    await db.commit()


def auto_cover_questions_sync(
    db: Any,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    assessed_competence_ids: set[uuid.UUID],
) -> int:
    """HRP-205 REDO: auto-cover questions after an interview AI analysis.

    Called from the sync Celery ``analyze_interview_task`` right after the
    analysis commit. A question counts as covered when its competence was
    actually assessed in the transcript (``status='assessed'`` in the
    analysis output) — blind spots and insufficient-evidence competences
    stay open so the next round can pick them up.

    ``db`` is a sync :class:`sqlalchemy.orm.Session`. Returns the number
    of questions newly stamped ``auto_from_transcript``.
    """
    if not assessed_competence_ids:
        return 0
    from datetime import UTC, datetime

    sets = (
        db.execute(
            select(QuestionSet).where(
                QuestionSet.candidate_vacancy_id == cv_id,
                QuestionSet.tenant_id == tenant_id,
                QuestionSet.archived_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    if not sets:
        return 0
    questions = (
        db.execute(
            select(Question).where(
                Question.question_set_id.in_([s.id for s in sets]),
                Question.tenant_id == tenant_id,
                Question.status == "active",
                Question.covered_at.is_(None),
                Question.competence_id.in_(assessed_competence_ids),
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for q in questions:
        q.covered_at = now
        q.covered_method = "auto_from_transcript"
        q.version = (q.version or 1) + 1
    if questions:
        db.commit()
    return len(questions)


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


async def export_question_set_pdf(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_set_id: uuid.UUID,
    *,
    fmt: str = "compact",
    include_indicators: bool = True,
    include_follow_ups: bool = True,
    include_rationale: bool = False,
    include_resume_anchor: bool = True,
    sort: str = "sort_order",
) -> bytes:
    """Render a question set as PDF in one of three layouts.

    ``compact``: text + goal + priority. One line per question.
    ``full``: adds indicators, follow-ups, rationale, anchor — interviewer prep.
    ``cards``: one card per question, indicators visible. Hands-out for the
    interviewer kit.
    """
    qs = await get_question_set(db, tenant_id, question_set_id)
    from app.modules.recruitment.question_pdf import render_question_set_pdf

    active = [q for q in qs.questions if q.status == "active"]
    if sort == "priority":
        order = {"must": 0, "should": 1, "nice_to_ask": 2}
        active.sort(key=lambda q: (order.get(q.priority, 99), q.sort_order))
    elif sort == "competence":
        active.sort(
            key=lambda q: (
                str(q.competence_id) if q.competence_id else "~",
                q.sort_order,
            )
        )
    else:
        active.sort(key=lambda q: q.sort_order)

    return render_question_set_pdf(
        set_name=qs.name,
        questions=[_question_to_dict(q) for q in active],
        fmt=fmt,
        include_indicators=include_indicators,
        include_follow_ups=include_follow_ups,
        include_rationale=include_rationale,
        include_resume_anchor=include_resume_anchor,
    )
