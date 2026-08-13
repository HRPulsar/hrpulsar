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
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.ai.llm_client import generate_json
from app.modules.recruitment.ai_service import RECRUITMENT_MAX_TOKENS
from app.modules.recruitment.common import (
    _get_vacancy,
    _publish_event,
    normalize_competence_id,
)
from app.modules.recruitment.models import (
    AIAssessment,
    Candidate,
    CandidateFile,
    CandidateVacancy,
    HumanAssessment,
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
        "assessment_round_id": qs.assessment_round_id,
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


async def list_vacancy_question_sets(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
) -> dict:
    """Everything the vacancy Questions tab needs, in one payload.

    HRP-504: the tab used to fan out one request per candidate against
    the legacy ``candidate_questions`` table — which the candidate page
    stopped writing when HRP-205 introduced question sets — and built its
    filters from props, so the candidate dropdown fell back to raw UUIDs
    and the competence dropdown compared profile slugs against uuid5
    keys and matched nothing.

    This returns, per candidate, the latest live question set (that is
    what "latest set" means on the tab), each question carrying its
    resolved competence name, plus the vacancy's full competence list so
    the filter can offer every competence — including ones no question
    touched yet.
    """
    from app.modules.recruitment.common import candidate_display_name

    await _get_vacancy(db, tenant_id, vacancy_id)

    cvs = (
        (
            await db.execute(
                select(CandidateVacancy)
                .options(selectinload(CandidateVacancy.candidate))
                .where(
                    CandidateVacancy.vacancy_id == vacancy_id,
                    CandidateVacancy.tenant_id == tenant_id,
                )
                .order_by(CandidateVacancy.added_at.desc())
            )
        )
        .scalars()
        .unique()
        .all()
    )

    competences: list[dict] = []
    competence_names: dict[str, str] = {}
    profile = (
        await db.execute(
            select(VacancyProfile).where(
                VacancyProfile.vacancy_id == vacancy_id,
                VacancyProfile.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    for comp in (profile.profile_data or {}).get("competences", []) if profile else []:
        if not isinstance(comp, dict):
            continue
        name = comp.get("name") or comp.get("id") or ""
        # Profiles written before HRP-348 still key competences by slug;
        # questions always store the uuid5 of that slug, so fold both onto
        # the same key here rather than in the browser.
        comp_uuid = normalize_competence_id(comp.get("id") or name)
        if comp_uuid is None:
            continue
        key = str(comp_uuid)
        if key in competence_names:
            continue
        competence_names[key] = name
        competences.append({"id": comp_uuid, "name": name})

    sets_by_cv: dict[uuid.UUID, QuestionSet] = {}
    if cvs:
        rows = (
            (
                await db.execute(
                    select(QuestionSet)
                    .where(
                        QuestionSet.tenant_id == tenant_id,
                        QuestionSet.candidate_vacancy_id.in_([cv.id for cv in cvs]),
                        QuestionSet.archived_at.is_(None),
                    )
                    # Sets generated inside one transaction share a
                    # created_at to the microsecond, so the id breaks the
                    # tie — otherwise "the latest set" was whichever row
                    # the scan happened to return first.
                    .order_by(QuestionSet.created_at.desc(), QuestionSet.id.desc())
                )
            )
            .scalars()
            .unique()
            .all()
        )
        for qs in rows:
            sets_by_cv.setdefault(qs.candidate_vacancy_id, qs)

    candidates: list[dict] = []
    for cv in cvs:
        latest = sets_by_cv.get(cv.id)
        question_set = _set_to_dict(latest) if latest is not None else None
        if question_set is not None:
            for question in question_set["questions"]:
                comp_id = question.get("competence_id")
                question["competence_name"] = (
                    competence_names.get(str(comp_id)) if comp_id else None
                )
        candidates.append(
            {
                "candidate_id": cv.candidate_id,
                "candidate_vacancy_id": cv.id,
                "candidate_name": candidate_display_name(cv.candidate, fallback=""),
                "question_set": question_set,
            }
        )

    return {
        "vacancy_id": vacancy_id,
        "competences": competences,
        "candidates": candidates,
    }


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

    "Transcribed" means what it means everywhere else (HRP-444): a
    finished transcription on a live interview. Text alone is not
    enough — a run still in progress can already hold a partial
    transcript, and an archived interview should not seed a new round.
    """
    if not round_ids:
        return []
    interviews = (
        (
            await db.execute(
                select(Interview).where(
                    Interview.id.in_(round_ids),
                    Interview.tenant_id == tenant_id,
                    Interview.transcription_status == "completed",
                    Interview.archived_at.is_(None),
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


async def _collect_prior_analyses(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    round_ids: list[uuid.UUID],
) -> list[dict]:
    """Per-round AI analysis digest for the dynamic_next prompt (HRP-444).

    Carries competence assessments (with status/confidence so the model
    can deepen shallow coverage) and red flags. Human manager scores are
    NOT included here — the anti-bias rule in the system prompt only
    holds if they never reach the model.
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
    out: list[dict] = []
    for iv in interviews:
        data = iv.analysis_data or {}
        if not isinstance(data, dict) or not data:
            continue
        assessments = [
            {
                "competence_id": a.get("competence_id"),
                "status": a.get("status"),
                "confidence": a.get("confidence"),
            }
            for a in (data.get("competence_assessments") or [])
            if isinstance(a, dict)
        ]
        red_flags = [
            {
                "flag_type": f.get("flag_type"),
                "severity": f.get("severity"),
                "description": f.get("description"),
            }
            for f in (data.get("red_flags") or [])
            if isinstance(f, dict)
        ]
        out.append(
            {
                "round_id": str(iv.id),
                "round_title": iv.title,
                "data_completeness": data.get("data_completeness"),
                "competence_assessments": assessments,
                "red_flags": red_flags,
            }
        )
    return out


async def _collect_manager_divergence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    round_ids: list[uuid.UUID],
) -> list[dict]:
    """Competences humans and the AI read differently (HRP-444).

    Anti-bias by construction: this emits the *fact* of a disagreement
    and nothing else — no scores, no evaluator identity, not even which
    side scored higher. A competence two sides disagree on deserves
    another, evidence-seeking question; the direction of that
    disagreement is exactly what must not steer the model.
    """
    if not round_ids:
        return []

    # Local import: settings_service reads no question_service symbols,
    # but importing it at module level closes a cycle through
    # ``recruitment.settings_service`` → ``company`` → back here.
    from app.modules.recruitment import settings_service

    human_rows = (
        (
            await db.execute(
                select(HumanAssessment).where(
                    HumanAssessment.candidate_vacancy_id == cv_id,
                    HumanAssessment.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    ai_rows = (
        (
            await db.execute(
                select(AIAssessment).where(
                    AIAssessment.interview_id.in_(round_ids),
                    AIAssessment.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not human_rows or not ai_rows:
        return []

    human_scores: dict[str, list[float]] = {}
    for hs in human_rows:
        if hs.score is None:
            continue
        human_scores.setdefault(str(hs.competence_id), []).append(float(hs.score))

    # Latest AI verdict wins when several rounds scored the same
    # competence — the older one has already been superseded.
    ai_latest: dict[str, tuple[Any, float]] = {}
    for ai in ai_rows:
        if ai.score is None:
            continue
        key = str(ai.competence_id)
        stamp = ai.updated_at or ai.created_at
        prior = ai_latest.get(key)
        if prior is None or (
            stamp is not None and prior[0] is not None and stamp >= prior[0]
        ):
            ai_latest[key] = (stamp, float(ai.score))

    threshold = await settings_service.get_divergence_threshold(db, tenant_id)
    out: list[dict] = []
    for comp_id, scores in human_scores.items():
        entry = ai_latest.get(comp_id)
        if entry is None or not scores:
            continue
        manager_mean = sum(scores) / len(scores)
        if abs(manager_mean - entry[1]) >= threshold:
            out.append({"competence_id": comp_id, "disagreed": True})
    return out


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
    prior_analyses: list[dict],
    manager_divergence: list[dict],
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
        prior_analyses=prior_analyses,
        manager_divergence=manager_divergence,
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


async def _resolve_target_round(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    data: GenerateQuestionSetRequest,
    *,
    current_user_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, str | None]:
    """Assessment round a dynamic_next set is for (HRP-444).

    Either an existing round that does not have a set yet, or — with
    ``create_round`` — the next ``Interview N`` opened on the fly, which
    is what happens when a candidate has only the Pre-interview round so
    far. Returns ``(round_id, label)``, both ``None`` when the caller
    bound no round at all.

    Creation is delegated to ``manager_assessment_service.create_round``
    so round numbering, the one-per-type guards and the audit event stay
    in one place. That commits before the LLM runs, so a failed
    generation leaves the round behind — deliberately: the round is real
    either way, and the retry path picks it up as "created without a
    set" rather than opening a duplicate.
    """
    from app.modules.recruitment import manager_assessment_service
    from app.modules.recruitment.manager_assessment_models import AssessmentRound
    from app.modules.recruitment.manager_assessment_schemas import RoundCreate

    if data.create_round:
        created = await manager_assessment_service.create_round(
            db, tenant_id, current_user_id, cv_id, RoundCreate(type="interview")
        )
        return created["id"], _round_label("interview", created.get("round_number"))

    if data.assessment_round_id is None:
        return None, None

    round_row = (
        await db.execute(
            select(AssessmentRound).where(
                AssessmentRound.id == data.assessment_round_id,
                AssessmentRound.tenant_id == tenant_id,
                AssessmentRound.candidate_vacancy_id == cv_id,
            )
        )
    ).scalar_one_or_none()
    if round_row is None:
        raise AppError("assessment_round_not_found", status.HTTP_404_NOT_FOUND)

    taken = (
        (
            await db.execute(
                select(QuestionSet).where(
                    QuestionSet.assessment_round_id == round_row.id,
                    QuestionSet.tenant_id == tenant_id,
                    QuestionSet.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
    if taken is not None:
        raise AppError("round_already_has_question_set", status.HTTP_409_CONFLICT)
    return round_row.id, _round_label(round_row.type, round_row.round_number)


def _round_label(round_type: str | None, round_number: int | None) -> str:
    """Human label for a round — the same shape the UI renders.

    ``recruitment_assessment_rounds`` has no name column; everywhere else
    the label is derived from type + number, so a set named after its
    round must derive it the same way.
    """
    if round_type == "interview" and round_number:
        return f"Interview {round_number}"
    if round_type == "pre_interview":
        return "Pre-interview"
    if round_type == "final":
        return "Final"
    return "Next round"


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
        prior_analyses: list[dict] = []
        manager_divergence: list[dict] = []
        assessment_round_id = target.assessment_round_id
        round_label = None
        set_type = target.set_type
    elif data.mode == "dynamic_next":
        round_ids = data.source_round_ids or ([data.round_id] if data.round_id else [])
        round_ids = [r for r in round_ids if r is not None]
        # HRP-444: a next-round set is derived from a transcript, never
        # generated from scratch.
        transcripts = await _load_transcripts(db, tenant_id, round_ids)
        if not transcripts:
            raise AppError("transcribed_round_required", status.HTTP_409_CONFLICT)
        assessment_round_id, round_label = await _resolve_target_round(
            db, tenant_id, cv.id, data, current_user_id=current_user_id
        )
        previous_questions = await _previous_sets_payload(db, tenant_id, cv.id)
        blind_spots = await _collect_blind_spots(db, tenant_id, round_ids)
        prior_analyses = await _collect_prior_analyses(db, tenant_id, round_ids)
        manager_divergence = await _collect_manager_divergence(
            db, tenant_id, cv.id, round_ids
        )
        target = None
        # A set built on a transcript is a round set by definition — the
        # caller does not get to label it pre_interview.
        set_type = "interview_round"
    else:  # initial
        previous_questions = []
        transcripts = []
        blind_spots = []
        prior_analyses = []
        manager_divergence = []
        target = None
        # Binding a round is optional for a first set, but when a caller
        # does bind one the one-set-per-round rule still has to hold —
        # otherwise the guard is only as good as the UI that calls it.
        if data.assessment_round_id is not None:
            assessment_round_id, round_label = await _resolve_target_round(
                db, tenant_id, cv.id, data, current_user_id=current_user_id
            )
        else:
            assessment_round_id, round_label = None, None
        set_type = data.set_type

    notify_ctx = {
        "tenant_id": str(tenant_id),
        "candidate_id": str(cv.candidate_id),
        "candidate_name": candidate.full_name,
        "vacancy_id": str(cv.vacancy_id),
        "vacancy_title": vacancy.title,
        "requested_by": str(current_user_id) if current_user_id else None,
        "mode": data.mode,
        # Failure has no set to open yet — the ready event re-links below
        # with the generated set so the email lands on the right tab.
        "link": candidate_question_deep_link(cv.candidate_id, cv.vacancy_id),
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
            prior_analyses=prior_analyses,
            manager_divergence=manager_divergence,
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
            assessment_round_id=assessment_round_id,
            set_type=set_type,
            # A round set is named after the round it prepares, so the
            # tab bar reads "Interview 2" rather than "Next round".
            name=data.name or round_label or _default_set_name(data.mode, set_type),
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
        {
            **notify_ctx,
            "question_set_id": str(saved.id),
            "set_name": saved.name,
            "link": candidate_question_deep_link(
                cv.candidate_id, cv.vacancy_id, saved.id
            ),
        },
    )
    return _set_to_dict(saved)


def candidate_question_deep_link(
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    question_set_id: uuid.UUID | None = None,
) -> str:
    """Deep link to the Interview questions block (HRP-442, HRP-460).

    ``vacancyId`` is the query key the candidate page already reads, the
    fragment scrolls to the block, and ``questionSet`` tells the tab-bar
    which set to open. Relative on purpose: in-app notifications route on
    it directly, and the email dispatcher prefixes the absolute base.
    """
    query = f"?vacancyId={vacancy_id}"
    if question_set_id is not None:
        query += f"&questionSet={question_set_id}"
    return f"/recruitment/candidates/{candidate_id}{query}#interview-questions"


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
            "goal": "verify_skill",
            "priority": "must_ask",
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
        order = {"must_ask": 0, "should_ask": 1, "nice_to_ask": 2}
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
