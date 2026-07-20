"""Demo-killswitch analysis: deterministic seed-based interview analysis without LLM calls.

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging
import uuid as _uuid

logger = logging.getLogger(__name__)


_DEMO_VERDICT_TO_SCORE = {
    "strong": 0.85,
    "partial": 0.55,
    "weak": 0.25,
    "unknown": 0.0,
}


# Demo seed verdicts predate the typed schema; map them onto the
# Literal["assessed", "not_covered", "insufficient"] values that
# ``AIAssessment.status`` actually carries in production so UI badges
# and GROUP-BY-status queries don't see a parallel vocabulary.
_DEMO_VERDICT_TO_STATUS = {
    "strong": "assessed",
    "partial": "assessed",
    "weak": "insufficient",
    "unknown": "not_covered",
}


def _wrap_demo_finding_strings(items: list, finding_type: str) -> list[dict]:
    """Coerce seed string entries into the dict shape real LLM output emits.

    ``_role_filter_analysis`` and the frontend both call ``.get()`` on
    each item — string entries crash the HM-role filter and the
    rendered card alike. Real-path keys are kept (``finding_type``,
    ``positive_reframe``); the seed sentence lands in ``evidence`` so
    it isn't lost.

    PII redaction is assumed to be done at fixture-curation time.
    """
    out: list[dict] = []
    for s in items or []:
        if isinstance(s, dict):
            out.append(s)
            continue
        out.append(
            {
                "finding_type": finding_type,
                "evidence": s,
                "positive_reframe": s,
            }
        )
    return out


def _apply_demo_killswitch_analysis(db, interview, tenant_id: _uuid.UUID) -> dict:
    """Persist a deterministic seed-based analysis without calling the LLM.

    Picks the Elena fixture for the canonical first-screen candidate,
    Tomás for his entry, Elena as the fallback. Wipes any prior
    AIAssessment rows on the interview and synthesises new ones from
    the seed fixture so ``interview.analysis_data`` and the assessments
    table both stay consistent with the real-path output shape.

    PII redaction is assumed to be done at fixture-curation time — the
    seed transcripts and analyses ship in the public repo, so they're
    already curated for distribution.
    """
    from sqlalchemy import delete

    from app.modules.demo.seed_data import (
        DEMO_FIRST_SCREEN_CANDIDATE_EMAIL,
        ELENA_INTERVIEW_ANALYSIS,
        TOMAS_INTERVIEW_ANALYSIS,
    )
    from app.modules.recruitment.common import normalize_competence_id
    from app.modules.recruitment.models import (
        AIAssessment,
        Candidate,
        CandidateVacancy,
    )

    candidate_email = None
    if interview.candidate_vacancy_id is not None:
        cv = db.get(CandidateVacancy, interview.candidate_vacancy_id)
        if cv is not None:
            candidate = db.get(Candidate, cv.candidate_id)
            if candidate is not None:
                # HRP-281 review: the demo seed deliberately leaves
                # Candidate.person_id NULL (HRP-276 H2) so a Person.email
                # lookup always misses. Read the denormalised email column
                # off Candidate directly, then fall back to Person for any
                # real (non-demo) candidate that lacks the denorm field.
                direct_email = (candidate.email or "").lower() or None
                person = getattr(candidate, "person", None)
                person_email = (
                    (person.email or "").lower() if person and person.email else None
                )
                candidate_email = direct_email or person_email

    if candidate_email == "tomas.becker@example.com":
        seed_src: dict = TOMAS_INTERVIEW_ANALYSIS
    elif candidate_email == DEMO_FIRST_SCREEN_CANDIDATE_EMAIL.lower():
        seed_src = ELENA_INTERVIEW_ANALYSIS
    else:
        # Unknown demo candidate — Elena is the canonical fallback so the
        # UI always renders a full report instead of an empty state.
        seed_src = ELENA_INTERVIEW_ANALYSIS

    # Build a writable copy with the same shape as the real LLM payload:
    # list[str] entries in process_findings / blind_spots / red_flags are
    # promoted to dicts so ``_role_filter_analysis`` and the frontend
    # cards don't crash on ``.get()``.
    seed = dict(seed_src)
    seed["process_findings"] = _wrap_demo_finding_strings(
        seed_src.get("process_findings") or [], finding_type="positive"
    )
    seed["blind_spots"] = _wrap_demo_finding_strings(
        seed_src.get("blind_spots") or [], finding_type="positive"
    )
    seed["red_flags"] = _wrap_demo_finding_strings(
        seed_src.get("red_flags") or [], finding_type="risk"
    )

    interview.analysis_data = seed
    interview.analysis_status = "completed"
    interview.analysis_error = None

    db.execute(
        delete(AIAssessment).where(
            AIAssessment.interview_id == interview.id,
            AIAssessment.tenant_id == tenant_id,
        )
    )
    for ca in seed.get("competence_assessments", []):
        label = ca.get("competence") or ""
        # The seed carries slug ids (e.g. ``python-advanced``) under
        # ``competence_id`` so the UUID minted here matches what
        # ``VacancyProfile.competences`` records, and the Compact matrix
        # (HRP-265) can resolve every column. A missing slug means the
        # fixture drifted from the vacancy profile — refuse to silently
        # fall back to the label-derived UUID (the exact pre-HRP-275
        # bug) and log the drift instead.
        slug = (ca.get("competence_id") or "").strip()
        verdict = (ca.get("verdict") or "unknown").lower()
        evidence = ca.get("evidence") or ""
        if not slug:
            logger.warning(
                "demo killswitch: skipping competence %r — missing competence_id slug",
                label,
            )
            continue
        comp_uuid = normalize_competence_id(slug)
        if comp_uuid is None:
            continue
        db.add(
            AIAssessment(
                tenant_id=tenant_id,
                interview_id=interview.id,
                competence_id=comp_uuid,
                score=_DEMO_VERDICT_TO_SCORE.get(verdict, 0.0),
                status=_DEMO_VERDICT_TO_STATUS.get(verdict, "not_covered"),
                citations=[
                    {
                        "competence": label,
                        "quote": evidence,
                        "verdict": verdict,
                    }
                ],
                reasoning=evidence,
            )
        )

    # Mirror the ``or 1`` idiom every other version writer in
    # interview_service.py uses so the bump semantics stay symmetric
    # across paths (Interview.version is non-null with server default 1).
    interview.version = (interview.version or 1) + 1
    interviewer_id = interview.interviewer_id
    db.commit()

    # Mirror the real path: emit N-06 analysis_ready so the interviewer
    # still sees a notification after a killswitch replay.
    try:
        from app.modules.recruitment.notifications import notify_sync

        notify_sync(
            db,
            event="recruitment.interview.analysis_ready",
            tenant_id=tenant_id,
            recipient_ids=[interviewer_id] if interviewer_id else [],
            fallback_admins=True,
            context={
                "interview_id": str(interview.id),
                "candidate_name": None,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("killswitch analysis notification failed for %s", interview.id)
    logger.info(
        "Interview %s analyzed via demo-killswitch (candidate=%s)",
        interview.id,
        candidate_email,
    )
    return {
        "status": "completed",
        "interview_id": str(interview.id),
        "competences": len(seed.get("competence_assessments", [])),
        "demo_killswitch": True,
    }
