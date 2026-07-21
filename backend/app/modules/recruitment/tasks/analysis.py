"""Interview transcription and AI analysis tasks (full and resume-only runs).

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging
from datetime import datetime

from app.core.celery_app import celery
from app.modules.recruitment.tasks.demo_analysis import (
    _apply_demo_killswitch_analysis,
)

logger = logging.getLogger(__name__)


def auto_chain_step(interview_id: str, tenant_id: str, step: str) -> bool:
    """HRP-202 REDO: run one hop of the upload→transcribe→analyze auto chain.

    ``step`` is ``"transcribe"`` (called by the AV task after a clean or
    skipped verdict) or ``"analyze"`` (called by the transcribe task after
    a successful transcription). Each hop goes through the corresponding
    ``interview_service`` module attribute so the SaaS billing wrapper
    applies — workers install it via ``ee.celery_extras.extend_celery`` —
    and the analyze hop uses the cache-aware entry point, mirroring the
    manual "Analyze" button exactly.

    Runs on a short-lived async engine (the ``app.modules.ai.tasks``
    pattern). Best-effort: any refusal (402 insufficient credits, 409) or
    failure is logged and ``False`` is returned so the caller can drop the
    ``auto_process`` flag and leave the manual buttons in charge.
    """

    import asyncio
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import settings
    from app.database import make_async_engine
    from app.modules.recruitment import interview_service

    fn = (
        interview_service.enqueue_transcribe
        if step == "transcribe"
        else interview_service.enqueue_analyze_or_cached
    )

    async def _inner() -> None:
        engine = make_async_engine(
            settings.database_url,
            pool_size=1,
            max_overflow=1,
            pool_recycle=300,
            pool_pre_ping=True,
        )
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with session_factory() as adb:
                await fn(adb, uuid.UUID(tenant_id), uuid.UUID(interview_id))
        finally:
            await engine.dispose()

    try:
        asyncio.run(_inner())
        logger.info("Interview %s: auto-chained %s", interview_id, step)
        return True
    except Exception:  # noqa: BLE001
        logger.exception(
            "auto-process %s chain failed for interview %s", step, interview_id
        )
        return False


@celery.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.modules.recruitment.tasks.transcribe_interview_task",
)
def transcribe_interview_task(self, interview_id: str, tenant_id: str) -> dict:
    """Transcribe an uploaded interview recording (R3a, FR-11).

    Steps:
    1. Mark ``interviews.transcription_status='processing'``.
    2. Resolve a tenant-scoped TranscriptionProvider (Whisper / Deepgram).
    3. Build a presigned URL for the uploaded media file and call the
       provider; PII filter is applied to the resulting transcript and
       per-segment text before they are persisted.
    4. Replace any prior segments and store full transcript + duration +
       provider name on the Interview row.
    5. Mark ``transcription_status='completed'``. On any failure, write
       the error to ``transcription_error`` and retry (max 2).
    """

    import asyncio
    import uuid

    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.core.pii_filter import redact_pii
    from app.core.s3 import get_presigned_url
    from app.modules.recruitment.models import (
        Interview,
        InterviewSegment,
    )
    from app.modules.recruitment.transcription_service import (
        get_transcription_provider_sync,
    )
    from app.modules.storage.models import File

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)

    try:
        with Session(engine) as db:
            interview = db.get(Interview, uuid.UUID(interview_id))
            if not interview:
                logger.error("Interview %s not found", interview_id)
                return {"status": "error", "error": "Interview not found"}

            interview.transcription_status = "processing"
            interview.transcription_error = None
            db.commit()

            # HRP-252 (D4) + HRP-276 (C2) + HRP-264 review-fix: demo
            # kill-switch is now opt-in. Real provider calls are the
            # default for demo tenants — the 250-credit budget plus the
            # concurrent-session cap are the primary spend guards.
            # ``DEMO_AI_KILLSWITCH=true`` stays as a panic button: turn
            # it on if abuse spikes and demo tenants will fall back to
            # the bundled Elena transcript instead of hitting the
            # provider.
            from app.config import settings
            from app.modules.company.models import Tenant
            from app.modules.demo.seed_data import load_transcript

            tenant_row = db.get(Tenant, uuid.UUID(tenant_id))
            if (
                tenant_row is not None
                and tenant_row.is_demo
                and settings.demo_ai_killswitch
            ):
                # Wipe any segments from a prior real transcribe run
                # — the seed transcript is a single blob and the
                # stale rows would otherwise reach
                # ``analyze_interview_task`` via segments_payload.
                db.execute(
                    delete(InterviewSegment).where(
                        InterviewSegment.interview_id == interview.id,
                        InterviewSegment.tenant_id == uuid.UUID(tenant_id),
                    )
                )
                interview.transcript = load_transcript()
                interview.transcription_provider = "demo-killswitch"
                if not interview.duration_seconds:
                    interview.duration_seconds = 600
                interview.transcription_status = "completed"
                interviewer_id = interview.interviewer_id
                db.commit()
                # Mirror the real path: emit N-05 transcript_ready so
                # the interviewer still gets a notification.
                try:
                    from app.modules.recruitment.notifications import (
                        notify_sync,
                    )

                    notify_sync(
                        db,
                        event="recruitment.interview.transcript_ready",
                        tenant_id=uuid.UUID(tenant_id),
                        recipient_ids=[interviewer_id] if interviewer_id else [],
                        fallback_admins=True,
                        context={
                            "interview_id": interview_id,
                            "candidate_name": None,
                        },
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "killswitch transcript notification failed for %s",
                        interview_id,
                    )
                logger.info(
                    "Interview %s transcribed via demo-killswitch",
                    interview_id,
                )
                return {
                    "status": "completed",
                    "interview_id": interview_id,
                    "segments": 0,
                    "demo_killswitch": True,
                }

            file_id = interview.audio_file_id or interview.video_file_id
            if not file_id:
                interview.transcription_status = "failed"
                interview.transcription_error = "No media file attached"
                db.commit()
                return {"status": "failed", "error": "No media file attached"}

            file_record = db.get(File, file_id)
            if not file_record:
                interview.transcription_status = "failed"
                interview.transcription_error = "Media file record missing"
                db.commit()
                return {"status": "failed", "error": "File record missing"}

            provider = get_transcription_provider_sync(db, uuid.UUID(tenant_id))

            from app.modules.recruitment.transcription_service import (
                OpenAIWhisperProvider,
            )

            # Whisper downloads the media itself from inside the worker, so
            # its URL must be signed for the internal endpoint; Deepgram
            # fetches from its own cloud and needs the public one.
            is_whisper = isinstance(provider, OpenAIWhisperProvider)
            audio_url = get_presigned_url(
                file_record.path, expires_in=3600, internal=is_whisper
            )
            if not audio_url:
                interview.transcription_status = "failed"
                interview.transcription_error = "Object storage unavailable"
                db.commit()
                return {
                    "status": "failed",
                    "error": "Object storage unavailable",
                }

            # Pre-flight Whisper's 25 MB size cap so we never even start
            # the download for an oversized recording — the client should
            # have used Deepgram instead.
            if (
                is_whisper
                and (file_record.size or 0) > OpenAIWhisperProvider.WHISPER_MAX_BYTES
            ):
                interview.transcription_status = "failed"
                interview.transcription_error = (
                    "Recording exceeds Whisper API 25 MB limit; configure "
                    "Deepgram for tenant or pre-split the audio"
                )
                db.commit()
                return {
                    "status": "failed",
                    "error": "Whisper 25 MB limit exceeded",
                }

            result = asyncio.run(
                provider.transcribe(audio_url, language="ru", diarization=True)
            )

            db.execute(
                delete(InterviewSegment).where(
                    InterviewSegment.interview_id == interview.id,
                    InterviewSegment.tenant_id == uuid.UUID(tenant_id),
                )
            )

            interview.transcript = redact_pii(result.full_text)
            interview.transcription_provider = result.provider
            if result.duration_seconds:
                interview.duration_seconds = int(result.duration_seconds)

            for seg in result.segments:
                db.add(
                    InterviewSegment(
                        tenant_id=uuid.UUID(tenant_id),
                        interview_id=interview.id,
                        speaker=seg.speaker,
                        start_sec=seg.start,
                        end_sec=seg.end,
                        text=redact_pii(seg.text),
                        confidence=seg.confidence,
                    )
                )

            interview.transcription_status = "completed"
            interviewer_id = interview.interviewer_id
            db.commit()
            # R4c N-05: notify the interviewer that the transcript is ready.
            try:
                from app.modules.recruitment.notifications import notify_sync

                notify_sync(
                    db,
                    event="recruitment.interview.transcript_ready",
                    tenant_id=uuid.UUID(tenant_id),
                    recipient_ids=[interviewer_id] if interviewer_id else [],
                    fallback_admins=True,
                    context={
                        "interview_id": interview_id,
                        "candidate_name": None,
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception("transcript notification failed for %s", interview_id)
            logger.info(
                "Interview %s transcribed via %s", interview_id, result.provider
            )
            # HRP-202 REDO: auto-processing chain — the upload was submitted
            # with "transcribe & analyze" on, so hand the finished transcript
            # straight to AI analysis (cache-aware, billed like the manual
            # button). The flag is one-shot: it is consumed here so a later
            # manual re-transcribe never silently re-triggers a billed
            # analysis from stale upload intent.
            if interview.auto_process:
                auto_chain_step(interview_id, tenant_id, "analyze")
                interview.auto_process = False
                db.commit()
            return {
                "status": "completed",
                "interview_id": interview_id,
                "segments": len(result.segments),
            }

    except Exception as exc:
        logger.exception("transcribe_interview_task failed for %s", interview_id)
        try:
            with Session(engine) as db:
                row = db.get(Interview, uuid.UUID(interview_id))
                if row:
                    row.transcription_status = "failed"
                    row.transcription_error = str(exc)[:1000]
                    db.commit()
        except Exception:
            logger.exception("Failed to mark interview %s as failed", interview_id)
        raise self.retry(exc=exc)
    finally:
        engine.dispose()


def _finalize_full_analysis_run(
    db,
    *,
    tenant_id,
    interview,
    cv,
    candidate_name,
    analysis,
) -> None:
    """HRP-204: mirror a successful full analysis into ``ai_analysis_runs``.

    Two cases:

    * **Top-up flow** — ``enqueue_topup_to_full`` already created a
      ``pending`` row with ``mode='full'`` + ``supersedes_id``
      referencing the prior resume-only run. We complete it in place
      and archive the prior row.
    * **Plain interview analyze** — no pre-existing pending row; we
      create a fresh ``mode='full'`` AIAnalysisRun row.

    Either way the candidate_vacancy mirror columns are refreshed.
    """

    from datetime import UTC

    from sqlalchemy import select

    from app.modules.recruitment.models import AIAnalysisRun, VacancyProfile

    if cv is None or interview is None:
        return

    pending = db.execute(
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.tenant_id == tenant_id,
            AIAnalysisRun.candidate_vacancy_id == cv.id,
            AIAnalysisRun.interview_id == interview.id,
            AIAnalysisRun.mode == "full",
            AIAnalysisRun.status.in_(("pending", "processing")),
        )
        .order_by(AIAnalysisRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    profile = db.execute(
        select(VacancyProfile).where(
            VacancyProfile.vacancy_id == cv.vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()

    # HRP-274: ``cv.ai_score`` keeps the raw LLM mean on the canonical
    # 0..1 scale (per-competence scores are clamped at ingestion by the
    # schema validators in ``prompts_interview``). ``cv.ai_score_normalized``
    # rebases it onto the tenant's active scale (identity fallback when
    # no scale is configured) so it is directly comparable with
    # ``manager_score`` — ``compute_score_divergence`` consumes the
    # normalized value, never the raw one.
    from app.modules.recruitment.models import ScaleConfig
    from app.modules.recruitment.score_normalization import (
        clamp_unit_score,
        compute_normalized_ai_score,
    )

    scores = [
        ca.score for ca in analysis.competence_assessments if ca.score is not None
    ]
    ai_score = clamp_unit_score(sum(scores) / len(scores)) if scores else None

    active_scale = db.execute(
        select(ScaleConfig)
        .where(
            ScaleConfig.tenant_id == tenant_id,
            ScaleConfig.is_active.is_(True),
        )
        .order_by(ScaleConfig.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    ai_score_normalized = compute_normalized_ai_score(
        ai_score,
        active_scale.max_value if active_scale is not None else None,
    )

    payload = {
        "mode": "full",
        "data_completeness": analysis.data_completeness,
        "competence_assessments": [
            a.model_dump() for a in analysis.competence_assessments
        ],
        "process_findings": [f.model_dump() for f in analysis.process_findings],
        "blind_spots": [b.model_dump() for b in analysis.blind_spots],
        "red_flags": [r.model_dump() for r in analysis.red_flags],
        # HRP-274: emit the unified verdict alongside ``verdict_summary``
        # so report consumers can switch off the structured field.
        "verdict": analysis.verdict,
        "verdict_summary": analysis.verdict_summary,
        "key_strength": analysis.key_strength,
        "key_risk": analysis.key_risk,
        "risk_mitigation": analysis.risk_mitigation,
    }

    now = datetime.now(UTC)

    if pending is not None:
        # Top-up path — complete the existing row.
        pending.status = "completed"
        pending.data_completeness = analysis.data_completeness
        pending.verdict = analysis.verdict
        pending.verdict_summary = analysis.verdict_summary
        pending.key_strength = analysis.key_strength
        pending.key_risk = analysis.key_risk
        pending.risk_mitigation = analysis.risk_mitigation
        pending.ai_score = ai_score
        pending.analysis_data = payload
        run = pending
        # Archive the supersedes target.
        if run.supersedes_id is not None:
            prior = db.get(AIAnalysisRun, run.supersedes_id)
            if prior is not None and prior.archived_at is None:
                prior.archived_at = now
                prior.replaced_by_id = run.id
        # Top-up may have shadowed older completed runs orthogonal to
        # the supersedes target (e.g. an older full run from a prior
        # interview). Archive those too so the active-run reader
        # never sees two completed-active rows for the same pair.
        prior_active = (
            db.execute(
                select(AIAnalysisRun).where(
                    AIAnalysisRun.tenant_id == tenant_id,
                    AIAnalysisRun.candidate_vacancy_id == cv.id,
                    AIAnalysisRun.id != run.id,
                    AIAnalysisRun.archived_at.is_(None),
                    AIAnalysisRun.status == "completed",
                )
            )
            .scalars()
            .all()
        )
        for p in prior_active:
            p.archived_at = now
            p.replaced_by_id = run.id
    else:
        # Plain analyze path — create a fresh full run, archive any other
        # active runs for the pair.
        run = AIAnalysisRun(
            tenant_id=tenant_id,
            candidate_vacancy_id=cv.id,
            mode="full",
            status="completed",
            interview_id=interview.id,
            vacancy_profile_id=profile.id if profile else None,
            vacancy_profile_version=profile.version if profile else None,
            data_completeness=analysis.data_completeness,
            verdict=analysis.verdict,
            verdict_summary=analysis.verdict_summary,
            key_strength=analysis.key_strength,
            key_risk=analysis.key_risk,
            risk_mitigation=analysis.risk_mitigation,
            ai_score=ai_score,
            analysis_data=payload,
        )
        db.add(run)
        db.flush()

        prior_active = (
            db.execute(
                select(AIAnalysisRun).where(
                    AIAnalysisRun.tenant_id == tenant_id,
                    AIAnalysisRun.candidate_vacancy_id == cv.id,
                    AIAnalysisRun.id != run.id,
                    AIAnalysisRun.archived_at.is_(None),
                    AIAnalysisRun.status == "completed",
                )
            )
            .scalars()
            .all()
        )
        for p in prior_active:
            p.archived_at = now
            p.replaced_by_id = run.id

    # Mirror onto candidate_vacancies for cheap list reads. HRP-274:
    # full mode now mirrors ``analysis.verdict`` onto ``cv.ai_verdict``
    # and writes the raw + normalized AI score so the candidates table
    # surfaces both values consistently across resume-only and full runs.
    cv.ai_analysis_mode = "full"
    cv.ai_data_completeness = analysis.data_completeness
    cv.ai_analysis_completed_at = now
    cv.ai_readiness = "resume_and_transcript"
    cv.ai_score = ai_score
    cv.ai_score_normalized = ai_score_normalized
    cv.ai_verdict = analysis.verdict
    cv.ai_verdict_summary = analysis.verdict_summary
    cv.ai_key_strength = analysis.key_strength
    cv.ai_key_risk = analysis.key_risk
    cv.ai_risk_mitigation = analysis.risk_mitigation


@celery.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.modules.recruitment.tasks.analyze_interview_task",
)
def analyze_interview_task(self, interview_id: str, tenant_id: str) -> dict:
    """Run the AI interview analysis (R3a, FR-14..FR-16).

    Single LLM call returning the full ``InterviewAnalysisResult`` schema.
    Citations are written into ``ai_assessments``; process findings,
    blind spots, red flags and the verdict land in ``interviews.analysis_data``.
    Role-based filtering is applied at read time in
    ``service.get_interview``.
    """

    import asyncio
    import uuid

    from sqlalchemy import create_engine, delete, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.ai.llm_client import generate_json
    from app.modules.recruitment.ai_service import RECRUITMENT_MAX_TOKENS
    from app.modules.recruitment.common import normalize_competence_id
    from app.modules.recruitment.models import (
        AIAnalysisRun,
        AIAssessment,
        Candidate,
        CandidateFile,
        CandidateVacancy,
        Interview,
        InterviewSegment,
        Vacancy,
        VacancyProfile,
    )
    from app.modules.recruitment.prompts_interview import (
        INTERVIEW_ANALYSIS_SYSTEM_PROMPT,
        InterviewAnalysisResult,
        build_interview_analysis_prompt,
    )

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)

    try:
        with Session(engine) as db:
            interview = db.get(Interview, uuid.UUID(interview_id))
            if not interview:
                logger.error("Interview %s not found", interview_id)
                return {"status": "error", "error": "Interview not found"}
            if not interview.transcript:
                interview.analysis_status = "failed"
                interview.analysis_error = "Transcript missing"
                db.commit()
                return {"status": "failed", "error": "Transcript missing"}

            interview.analysis_status = "processing"
            interview.analysis_error = None
            db.commit()

            # HRP-270: locate the in-flight AIAnalysisRun (created by
            # the top-up flow) so the cancel endpoint + InFlightCard
            # can track which stage we're in. We also include
            # ``cancelled`` in the WHERE so the worker honours a cancel
            # that landed between enqueue and pickup. Direct mode='full'
            # calls from the candidate-card split-button don't create a
            # run row, so ``pending_run`` may be None — the rest of the
            # task treats it as a best-effort bookkeeping helper.
            pending_run = db.execute(
                select(AIAnalysisRun)
                .where(
                    AIAnalysisRun.tenant_id == uuid.UUID(tenant_id),
                    AIAnalysisRun.candidate_vacancy_id
                    == interview.candidate_vacancy_id,
                    AIAnalysisRun.mode == "full",
                    AIAnalysisRun.status.in_(("pending", "processing", "cancelled")),
                )
                .order_by(AIAnalysisRun.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if pending_run is not None:
                if pending_run.status == "cancelled":
                    logger.info(
                        "Full analysis run %s already cancelled — skipping",
                        pending_run.id,
                    )
                    # Roll back the interview.analysis_status='processing'
                    # write committed above so the recruiter can retry
                    # without hitting the in-flight guard.
                    interview.analysis_status = "not_started"
                    db.commit()
                    return {"status": "cancelled", "run_id": str(pending_run.id)}
                pending_run.status = "processing"
                pending_run.current_stage = "pre_check"
                db.commit()

            # HRP-252 (D4) + HRP-276 (C2) + HRP-264 review-fix: demo
            # kill-switch is opt-in. Credits + concurrent-session cap
            # are the primary regulators; the panic-button only fires
            # when an operator explicitly flips DEMO_AI_KILLSWITCH on.
            from app.config import settings
            from app.modules.company.models import Tenant

            tenant_row = db.get(Tenant, uuid.UUID(tenant_id))
            if (
                tenant_row is not None
                and tenant_row.is_demo
                and settings.demo_ai_killswitch
            ):
                # HRP-270 review: the killswitch path writes seed data
                # onto the Interview row but never touched the
                # AIAnalysisRun. Without finalising the run row here
                # the InFlightCard polls forever for a demo top-up.
                if pending_run is not None:
                    pending_run.status = "completed"
                    pending_run.current_stage = None
                    db.commit()
                return _apply_demo_killswitch_analysis(
                    db, interview, uuid.UUID(tenant_id)
                )

            cv = db.get(CandidateVacancy, interview.candidate_vacancy_id)
            vacancy = db.get(Vacancy, cv.vacancy_id) if cv else None
            profile = (
                db.execute(
                    select(VacancyProfile).where(
                        VacancyProfile.vacancy_id == cv.vacancy_id
                    )
                ).scalar_one_or_none()
                if cv
                else None
            )
            candidate = db.get(Candidate, cv.candidate_id) if cv else None
            latest_resume = (
                db.execute(
                    select(CandidateFile)
                    .where(
                        CandidateFile.candidate_id == candidate.id,
                        CandidateFile.parse_status == "completed",
                    )
                    .order_by(CandidateFile.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if candidate
                else None
            )
            person = (
                candidate.person
                if candidate and getattr(candidate, "person", None)
                else None
            )
            candidate_name = (
                f"{(person.first_name or '').strip()} {(person.last_name or '').strip()}".strip()
                if person
                else None
            )

            profile_competences = (
                (profile.profile_data or {}).get("competences", []) or []
                if profile
                else []
            )

            segments = (
                db.execute(
                    select(InterviewSegment)
                    .where(InterviewSegment.interview_id == interview.id)
                    .order_by(InterviewSegment.start_sec.asc())
                )
                .scalars()
                .all()
            )
            segments_payload = [
                {
                    "id": str(s.id),
                    "speaker": s.speaker,
                    "start_sec": s.start_sec,
                    "end_sec": s.end_sec,
                    "text": s.text,
                }
                for s in segments
            ]

            prompt = build_interview_analysis_prompt(
                vacancy_title=(vacancy.title if vacancy else ""),
                vacancy_language=(vacancy.language if vacancy else "ru"),
                profile_competences=profile_competences,
                transcript=interview.transcript or "",
                segments=segments_payload,
                candidate_name=candidate_name,
                resume_summary=(
                    str(latest_resume.parsed_data)[:4000]
                    if latest_resume and latest_resume.parsed_data
                    else None
                ),
            )

            if pending_run is not None:
                # HRP-270: ``competences`` is the first LLM-spending
                # stage — cancel post-bump refunds 0%.
                pending_run.current_stage = "competences"
                db.commit()

            analysis_raw = asyncio.run(
                generate_json(
                    prompt=prompt,
                    system=INTERVIEW_ANALYSIS_SYSTEM_PROMPT,
                    schema=InterviewAnalysisResult,
                    temperature=0.2,
                    max_tokens=RECRUITMENT_MAX_TOKENS,
                )
            )
            assert isinstance(analysis_raw, InterviewAnalysisResult)
            analysis: InterviewAnalysisResult = analysis_raw

            # HRP-270 review: re-read the run row under FOR UPDATE before
            # committing the completed payload. A cancel that landed
            # while the LLM call was in flight must not be silently
            # overwritten. ``pending_run`` may be None for the direct
            # full-mode path (no run row created) — in that case there
            # is nothing to cancel, fall through.
            if pending_run is not None:
                locked_run = db.execute(
                    select(AIAnalysisRun)
                    .where(AIAnalysisRun.id == pending_run.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).scalar_one_or_none()
                if locked_run is None or locked_run.status == "cancelled":
                    logger.info(
                        "Full analysis run %s was cancelled mid-LLM — discarding worker output",
                        pending_run.id,
                    )
                    db.commit()
                    return {
                        "status": "cancelled",
                        "run_id": str(pending_run.id),
                    }

            db.execute(
                delete(AIAssessment).where(
                    AIAssessment.interview_id == interview.id,
                    AIAssessment.tenant_id == uuid.UUID(tenant_id),
                )
            )

            for ca in analysis.competence_assessments:
                comp_uuid = normalize_competence_id(ca.competence_id)
                if comp_uuid is None:
                    continue
                db.add(
                    AIAssessment(
                        tenant_id=uuid.UUID(tenant_id),
                        interview_id=interview.id,
                        competence_id=comp_uuid,
                        score=ca.score,
                        status=ca.status,
                        citations=[c.model_dump() for c in ca.citations],
                        reasoning=ca.reasoning,
                    )
                )

            interview.analysis_data = {
                "data_completeness": analysis.data_completeness,
                "process_findings": [f.model_dump() for f in analysis.process_findings],
                "blind_spots": [b.model_dump() for b in analysis.blind_spots],
                "red_flags": [r.model_dump() for r in analysis.red_flags],
                "verdict_summary": analysis.verdict_summary,
                "key_strength": analysis.key_strength,
                "key_risk": analysis.key_risk,
                "risk_mitigation": analysis.risk_mitigation,
                "competence_assessments": [
                    a.model_dump() for a in analysis.competence_assessments
                ],
            }
            if pending_run is not None:
                # HRP-270: clear the active marker so the InFlightCard
                # disappears as soon as the row flips to completed.
                pending_run.current_stage = None

            interview.analysis_status = "completed"
            # HRP-275: bump the ETag-tracked version on the real path too
            # so cache-hit (``apply_cached_analysis``) and LLM-real-path
            # both invalidate ``If-None-Match`` polls identically. Prior
            # asymmetry left the real path serving 304s after the row
            # already changed underneath. Uses ``or 1`` to match every
            # other version writer in interview_service.py.
            interview.version = (interview.version or 1) + 1
            interviewer_id = interview.interviewer_id

            # HRP-204: mirror the full analysis as an ``AIAnalysisRun``
            # so the unified history endpoint sees resume-only AND full
            # runs in one timeline. The row is either an already-pending
            # top-up run (created by ``enqueue_topup_to_full`` — we
            # complete it in-place) or a fresh row stamped here for a
            # plain interview analyze.
            try:
                _finalize_full_analysis_run(
                    db,
                    tenant_id=uuid.UUID(tenant_id),
                    interview=interview,
                    cv=cv,
                    candidate_name=candidate_name,
                    analysis=analysis,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "AIAnalysisRun mirror failed for interview %s",
                    interview_id,
                )

            # HRP-252 (D4): persist the analysis under
            # sha256(transcript + profile.id + profile.version) so a
            # subsequent rerun on an untouched input short-circuits via
            # ``enqueue_analyze_or_cached`` — no LLM call, no credits.
            try:
                from app.modules.recruitment.analysis_cache_service import (
                    compute_cache_key_for_interview_sync,
                    store_cached_analysis_sync,
                )

                cache_key = compute_cache_key_for_interview_sync(
                    db, uuid.UUID(tenant_id), interview
                )
                if cache_key is not None:
                    assessments_payload = [
                        {
                            "competence_id": str(
                                normalize_competence_id(ca.competence_id)
                            ),
                            "score": ca.score,
                            "status": ca.status,
                            "citations": [c.model_dump() for c in ca.citations],
                            "reasoning": ca.reasoning,
                        }
                        for ca in analysis.competence_assessments
                        if normalize_competence_id(ca.competence_id) is not None
                    ]
                    store_cached_analysis_sync(
                        db,
                        uuid.UUID(tenant_id),
                        cache_key,
                        interview.analysis_data,
                        assessments_payload,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("analysis cache store failed for %s", interview_id)

            db.commit()
            # HRP-205 REDO: auto-cover interview questions whose competence
            # was actually assessed in this transcript. Best-effort — a
            # failure here must never mark the analysis itself as failed.
            try:
                from app.modules.recruitment.question_service import (
                    auto_cover_questions_sync,
                )

                assessed_ids = {
                    comp_id
                    for ca in analysis.competence_assessments
                    if ca.status == "assessed"
                    and (comp_id := normalize_competence_id(ca.competence_id))
                    is not None
                }
                covered = auto_cover_questions_sync(
                    db,
                    uuid.UUID(tenant_id),
                    interview.candidate_vacancy_id,
                    assessed_ids,
                )
                if covered:
                    logger.info(
                        "Interview %s: auto-covered %d question(s)",
                        interview_id,
                        covered,
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "question auto-cover failed for interview %s", interview_id
                )
            # R4c N-06: notify the interviewer + recruiter (admin fan-out).
            try:
                from app.modules.recruitment.notifications import notify_sync

                notify_sync(
                    db,
                    event="recruitment.interview.analysis_ready",
                    tenant_id=uuid.UUID(tenant_id),
                    recipient_ids=[interviewer_id] if interviewer_id else [],
                    fallback_admins=True,
                    context={
                        "interview_id": interview_id,
                        "candidate_name": None,
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception("analysis notification failed for %s", interview_id)
            logger.info("Interview %s analyzed", interview_id)
            return {
                "status": "completed",
                "interview_id": interview_id,
                "competences": len(analysis.competence_assessments),
            }

    except Exception as exc:
        logger.exception("analyze_interview_task failed for %s", interview_id)
        try:
            with Session(engine) as db:
                row = db.get(Interview, uuid.UUID(interview_id))
                if row:
                    row.analysis_status = "failed"
                    row.analysis_error = str(exc)[:1000]
                    db.commit()
        except Exception:
            logger.exception(
                "Failed to mark interview %s analysis as failed", interview_id
            )
        raise self.retry(exc=exc)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# analyze_resume_only_task (HRP-204)
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.modules.recruitment.tasks.analyze_resume_only_task",
)
def analyze_resume_only_task(self, run_id: str, tenant_id: str) -> dict:
    """Run a resume-only (pre-interview) AI analysis (HRP-204).

    The run row was created in ``resume_analysis_service.enqueue_resume_only``
    in status ``pending``; this task transitions it to
    ``processing → completed/failed`` and writes the LLM payload into
    ``analysis_data``. Four-of-six pipeline stages execute (Pre-check,
    Competences, Blind spots, Verdict); Citations + Process analysis
    are skipped — no transcript available.

    The verdict is post-processed: ``recommended`` (which the prompt
    forbids) is rewritten to ``needs_check`` with an audit entry.
    """

    import asyncio
    import uuid
    from datetime import UTC

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.ai.llm_client import generate_json
    from app.modules.recruitment.ai_service import RECRUITMENT_MAX_TOKENS
    from app.modules.recruitment.models import (
        AIAnalysisRun,
        Candidate,
        CandidateFile,
        CandidateVacancy,
        Vacancy,
        VacancyProfile,
    )
    from app.modules.recruitment.prompts_interview import (
        RESUME_ONLY_ANALYSIS_SYSTEM_PROMPT,
        ResumeOnlyAnalysisResult,
        build_resume_only_analysis_prompt,
    )
    from app.modules.recruitment.resume_analysis_service import (
        apply_resume_only_verdict_guard,
    )

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)

    try:
        with Session(engine) as db:
            run = db.get(AIAnalysisRun, uuid.UUID(run_id))
            if run is None:
                logger.error("AIAnalysisRun %s not found", run_id)
                return {"status": "error", "error": "Run not found"}

            # HRP-270: respect a cancel between enqueue and task pickup.
            if run.status == "cancelled":
                logger.info("Resume-only run %s already cancelled — skipping", run_id)
                return {"status": "cancelled", "run_id": run_id}

            run.status = "processing"
            run.current_stage = "pre_check"
            run.error_message = None
            db.commit()

            cv = db.get(CandidateVacancy, run.candidate_vacancy_id)
            if cv is None:
                run.status = "failed"
                run.error_message = "candidate_vacancy missing"
                db.commit()
                return {"status": "failed", "error": "cv missing"}

            vacancy = db.get(Vacancy, cv.vacancy_id) if cv else None
            profile = (
                db.get(VacancyProfile, run.vacancy_profile_id)
                if run.vacancy_profile_id
                else None
            )
            candidate = db.get(Candidate, cv.candidate_id) if cv else None
            resume = (
                db.get(CandidateFile, run.candidate_file_id)
                if run.candidate_file_id
                else None
            )
            if profile is None or resume is None or candidate is None:
                run.status = "failed"
                run.error_message = "missing inputs (profile/resume/candidate)"
                db.commit()
                return {"status": "failed", "error": "missing inputs"}

            person = candidate.person if candidate else None
            candidate_name = (
                f"{(person.first_name or '').strip()} {(person.last_name or '').strip()}".strip()
                if person
                else None
            )

            profile_competences = (profile.profile_data or {}).get(
                "competences", []
            ) or []

            prompt = build_resume_only_analysis_prompt(
                vacancy_title=(vacancy.title if vacancy else ""),
                vacancy_language=(vacancy.language if vacancy else "ru"),
                profile_competences=profile_competences,
                parsed_resume=resume.parsed_data or {},
                resume_raw_text=resume.raw_text,
                candidate_name=candidate_name,
            )

            # HRP-270: each stage commit is a checkpoint for the cancel
            # endpoint's refund decision. ``competences`` is the first
            # LLM-spending stage — once we land here, no refund.
            run.current_stage = "competences"
            db.commit()

            analysis_raw = asyncio.run(
                generate_json(
                    prompt=prompt,
                    system=RESUME_ONLY_ANALYSIS_SYSTEM_PROMPT,
                    schema=ResumeOnlyAnalysisResult,
                    temperature=0.2,
                    max_tokens=RECRUITMENT_MAX_TOKENS,
                )
            )
            assert isinstance(analysis_raw, ResumeOnlyAnalysisResult)
            analysis: ResumeOnlyAnalysisResult = analysis_raw

            # HRP-270 review: re-read the row under FOR UPDATE before
            # writing the completed payload — a cancel that landed
            # while the LLM call was in flight must not be silently
            # overwritten by the worker's stale in-memory copy.
            from sqlalchemy import select as _select_for_cancel_check

            locked = db.execute(
                _select_for_cancel_check(AIAnalysisRun)
                .where(AIAnalysisRun.id == run.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if locked is None or locked.status == "cancelled":
                logger.info(
                    "Resume-only run %s was cancelled mid-LLM — discarding worker output",
                    run_id,
                )
                db.commit()
                return {"status": "cancelled", "run_id": run_id}

            final_verdict, overridden = apply_resume_only_verdict_guard(
                analysis.verdict
            )

            # Aggregate AI score — mean of assessed competences' scores
            # on the canonical 0..1 scale (each score is clamped at
            # ingestion by the ``ResumeOnlyCompetenceAssessment``
            # validator; the mean is clamped again as belt-and-braces).
            from app.modules.recruitment.score_normalization import (
                clamp_unit_score,
            )

            scores = [
                ca.score
                for ca in analysis.competence_assessments
                if ca.score is not None
            ]
            ai_score = clamp_unit_score(sum(scores) / len(scores)) if scores else None

            run.data_completeness = analysis.data_completeness
            run.verdict = final_verdict
            run.verdict_summary = analysis.verdict_summary
            run.key_strength = analysis.key_strength
            run.key_risk = analysis.key_risk
            run.risk_mitigation = analysis.risk_mitigation
            run.recommendation_for_next_step = analysis.recommendation_for_next_step
            run.ai_score = ai_score
            run.status = "completed"
            run.current_stage = None
            run.analysis_data = {
                "mode": "resume_only",
                "data_completeness": analysis.data_completeness,
                "competence_assessments": [
                    ca.model_dump() for ca in analysis.competence_assessments
                ],
                "blind_spots": [b.model_dump() for b in analysis.blind_spots],
                "red_flags": [r.model_dump() for r in analysis.red_flags],
                "verdict": final_verdict,
                "verdict_summary": analysis.verdict_summary,
                "key_strength": analysis.key_strength,
                "key_risk": analysis.key_risk,
                "risk_mitigation": analysis.risk_mitigation,
                "recommendation_for_next_step": (analysis.recommendation_for_next_step),
                "validator_overrode_recommended": overridden,
            }

            # Archive any prior active run for the same pair so the
            # candidate list never reads two active rows.
            from sqlalchemy import select

            prior = (
                db.execute(
                    select(AIAnalysisRun).where(
                        AIAnalysisRun.tenant_id == uuid.UUID(tenant_id),
                        AIAnalysisRun.candidate_vacancy_id == run.candidate_vacancy_id,
                        AIAnalysisRun.id != run.id,
                        AIAnalysisRun.archived_at.is_(None),
                        AIAnalysisRun.status == "completed",
                    )
                )
                .scalars()
                .all()
            )
            now = datetime.now(UTC)
            for p in prior:
                p.archived_at = now
                p.replaced_by_id = run.id

            # HRP-274: surface the raw 0..1 mean alongside its rebase
            # onto the tenant's active scale (identity fallback when no
            # scale is configured), mirroring the full-mode finalizer.
            # ScaleConfig is looked up here (not at task-import time) so
            # a tenant that flips its active scale between the
            # resume-only enqueue and the worker pickup always reads
            # the latest configuration.
            from app.modules.recruitment.models import ScaleConfig
            from app.modules.recruitment.score_normalization import (
                compute_normalized_ai_score,
            )

            active_scale = db.execute(
                select(ScaleConfig)
                .where(
                    ScaleConfig.tenant_id == uuid.UUID(tenant_id),
                    ScaleConfig.is_active.is_(True),
                )
                .order_by(ScaleConfig.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            ai_score_normalized = compute_normalized_ai_score(
                ai_score,
                active_scale.max_value if active_scale is not None else None,
            )

            # Mirror onto candidate_vacancies for cheap list reads.
            cv.ai_analysis_mode = "resume_only"
            cv.ai_data_completeness = analysis.data_completeness
            cv.ai_analysis_completed_at = now
            cv.ai_score = ai_score
            cv.ai_score_normalized = ai_score_normalized
            cv.ai_verdict = final_verdict
            cv.ai_verdict_summary = analysis.verdict_summary
            cv.ai_key_strength = analysis.key_strength
            cv.ai_key_risk = analysis.key_risk
            cv.ai_risk_mitigation = analysis.risk_mitigation
            cv.ai_readiness = "resume_only"

            db.commit()

            # Notify the recruiter (R4c-style notification — reuses the
            # existing notification fan-out).
            try:
                from app.modules.recruitment.notifications import notify_sync

                notify_sync(
                    db,
                    event="recruitment.candidate.resume_analysis_ready",
                    tenant_id=uuid.UUID(tenant_id),
                    recipient_ids=[run.created_by_id] if run.created_by_id else [],
                    fallback_admins=True,
                    context={
                        "candidate_vacancy_id": str(run.candidate_vacancy_id),
                        "candidate_name": candidate_name,
                        "verdict": final_verdict,
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception("resume_analysis notification failed for %s", run_id)

            logger.info(
                "Resume-only analysis %s completed (verdict=%s, override=%s)",
                run_id,
                final_verdict,
                overridden,
            )
            return {
                "status": "completed",
                "run_id": run_id,
                "verdict": final_verdict,
                "overridden_recommended": overridden,
            }

    except Exception as exc:
        logger.exception("analyze_resume_only_task failed for %s", run_id)
        try:
            with Session(engine) as db:
                row = db.get(AIAnalysisRun, uuid.UUID(run_id))
                if row is not None:
                    row.status = "failed"
                    row.error_message = str(exc)[:1000]
                    db.commit()
        except Exception:
            logger.exception("Failed to mark resume-only run %s as failed", run_id)
        raise self.retry(exc=exc)
    finally:
        engine.dispose()
