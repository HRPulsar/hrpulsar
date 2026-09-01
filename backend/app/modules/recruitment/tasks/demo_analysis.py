"""Demo-killswitch analysis: deterministic seed-based interview analysis without LLM calls.

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging
import uuid as _uuid

logger = logging.getLogger(__name__)


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

    # Replays must speak the same language as the seeded analysis rows
    # (white-label deployments localize the demo seed at clone time).
    from app.modules.demo.seed_i18n import localize as localize_seed

    seed_src = localize_seed(seed_src)

    # HRP-598: the fixture already carries the shape the real LLM path
    # writes (``InterviewAnalysisResult``), so it goes onto the row as-is
    # — the coercion pass that used to sit here existed only because the
    # seed held a legacy shape. Still copied: on the English locale
    # ``localize`` hands back the module-level fixture itself, which must
    # never become the JSONB value some later writer could mutate.
    seed = dict(seed_src)

    interview.analysis_data = seed
    interview.analysis_status = "completed"
    interview.analysis_error = None

    db.execute(
        delete(AIAssessment).where(
            AIAssessment.interview_id == interview.id,
            AIAssessment.tenant_id == tenant_id,
        )
    )
    # HRP-598: one row builder for every writer of the demo fixture
    # (seed, cache pre-population, this replay) so the matrix reads back
    # the same slug-derived competence UUIDs from all three.
    from app.modules.demo.seed import _build_seed_assessment_rows

    for row in _build_seed_assessment_rows(seed):
        db.add(
            AIAssessment(
                tenant_id=tenant_id,
                interview_id=interview.id,
                competence_id=_uuid.UUID(row["competence_id"]),
                score=row["score"],
                status=row["status"],
                citations=row["citations"],
                reasoning=row["reasoning"],
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
