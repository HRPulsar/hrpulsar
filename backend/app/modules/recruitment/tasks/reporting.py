"""Consolidated report generation task.

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging
from datetime import datetime, timezone

from app.core.celery_app import celery

logger = logging.getLogger(__name__)

# CandidateVacancy statuses that mean the candidate left the funnel; the
# report's implicit "All active" scope (no whitelist) excludes them.
TERMINAL_CV_STATUSES = frozenset({"hired", "rejected", "withdrew"})


# ---------------------------------------------------------------------------
# generate_report_task (R4a, FR-23/24)
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    max_retries=0,
    default_retry_delay=30,
    name="app.modules.recruitment.tasks.generate_report_task",
)
def generate_report_task(self, export_id: str, tenant_id: str) -> dict:
    """Render an XLSX consolidated recruitment report and store it in S3.

    The export row (``consolidated_reports``) is created in the
    ``pending`` state by the API handler; this task transitions
    pending → processing → completed/failed. The XLSX is uploaded
    to S3 and a ``files`` row is inserted; the export row gains the
    ``file_id`` and ``completed_at`` timestamp on success.
    """

    import uuid

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.core.s3 import upload_file
    from app.models import Person
    from app.modules.company.models import Tenant
    from app.modules.recruitment.common import (
        candidate_display_name,
        normalize_competence_id,
    )
    from app.modules.recruitment.models import (
        AIAssessment,
        Candidate,
        CandidateVacancy,
        ConsolidatedReport,
        HumanAssessment,
        Interview,
        Vacancy,
        VacancyProfile,
        VacancyStage,
    )
    from app.modules.recruitment.report_xlsx import render_report_xlsx
    from app.modules.storage.models import File

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)

    try:
        with Session(engine) as db:
            export = db.get(ConsolidatedReport, uuid.UUID(export_id))
            if not export:
                logger.error("Report export %s not found", export_id)
                return {"status": "error", "error": "Export not found"}
            if str(export.tenant_id) != tenant_id:
                logger.error("Tenant mismatch for export %s", export_id)
                return {"status": "error", "error": "Tenant mismatch"}

            if export.generated_by is None:
                # files.uploaded_by is FK users.id NOT NULL, so we cannot
                # render an export whose requesting user has been deleted
                # (ConsolidatedReport.generated_by is ON DELETE SET NULL).
                # Fail fast before doing any S3 / LLM work.
                export.status = "failed"
                export.error = "Cannot render report: requesting user no longer exists"
                db.commit()
                return {
                    "status": "failed",
                    "error": "Requesting user no longer exists",
                }

            export.status = "processing"
            export.error = None
            db.commit()

            vacancy = db.get(Vacancy, export.vacancy_id)
            if not vacancy:
                export.status = "failed"
                export.error = "Vacancy not found"
                db.commit()
                return {"status": "failed", "error": "Vacancy not found"}

            # HRP-521: the sheet set comes from the Generate-report
            # dialog (``sections``). Rows written before HRP-521 carry
            # legacy section codes that no longer map to a sheet — an
            # empty intersection means "render everything" so an old
            # export can still be regenerated.
            requested_sections = {str(code) for code in (export.sections or [])}
            known_sections = {
                "summary_ranking",
                "competency_matrix",
                "detailed_analysis",
                "incomplete_data",
            }
            selected_sections = requested_sections & known_sections
            if not selected_sections:
                selected_sections = set(known_sections)

            profile = db.execute(
                select(VacancyProfile).where(VacancyProfile.vacancy_id == vacancy.id)
            ).scalar_one_or_none()

            cvs = (
                db.execute(
                    select(CandidateVacancy).where(
                        CandidateVacancy.vacancy_id == vacancy.id,
                        CandidateVacancy.tenant_id == vacancy.tenant_id,
                    )
                )
                .scalars()
                .all()
            )
            cv_ids = [cv.id for cv in cvs]

            persons_by_candidate: dict[uuid.UUID, Person] = {}
            candidate_ids = {cv.candidate_id for cv in cvs}
            if candidate_ids:
                cand_rows = (
                    db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
                    .scalars()
                    .all()
                )
                person_ids = {c.person_id for c in cand_rows if c.person_id}
                persons: dict[uuid.UUID, Person] = {}
                if person_ids:
                    persons = {
                        p.id: p
                        for p in db.execute(
                            select(Person).where(Person.id.in_(person_ids))
                        )
                        .scalars()
                        .all()
                    }
                for c in cand_rows:
                    if c.person_id and c.person_id in persons:
                        persons_by_candidate[c.id] = persons[c.person_id]

            stage_names: dict[uuid.UUID, str] = {}
            stage_ids = {cv.stage_id for cv in cvs if cv.stage_id}
            if stage_ids:
                stage_rows = (
                    db.execute(
                        select(VacancyStage).where(VacancyStage.id.in_(stage_ids))
                    )
                    .scalars()
                    .all()
                )
                stage_names = {s.id: s.name for s in stage_rows}

            candidates_payload: list[dict] = []
            for cv in cvs:
                person = persons_by_candidate.get(cv.candidate_id)
                name = (
                    (
                        f"{(person.first_name or '').strip()} "
                        f"{(person.last_name or '').strip()}"
                    ).strip()
                    if person
                    else ""
                )
                candidates_payload.append(
                    {
                        "candidate_id": cv.candidate_id,
                        "candidate_vacancy_id": cv.id,
                        "name": name or "Unknown",
                        "email": getattr(person, "email", None) if person else None,
                        "phone": getattr(person, "phone", None) if person else None,
                        "status": cv.status,
                        "stage_name": (
                            stage_names.get(cv.stage_id) if cv.stage_id else None
                        ),
                        "ranking_score": cv.ranking_score,
                        "source": None,
                    }
                )

            interviews = (
                db.execute(
                    select(Interview).where(
                        Interview.candidate_vacancy_id.in_(cv_ids),
                        Interview.tenant_id == vacancy.tenant_id,
                    )
                )
                .scalars()
                .all()
                if cv_ids
                else []
            )
            interview_payload: list[dict] = []
            findings_payload: list[dict] = []
            red_flags_payload: list[dict] = []
            verdict_rows: list[dict] = []
            for iv in interviews:
                iv_cv = next((c for c in cvs if c.id == iv.candidate_vacancy_id), None)
                if iv_cv is None:
                    continue
                person = persons_by_candidate.get(iv_cv.candidate_id)
                cand_name = (
                    (
                        f"{(person.first_name or '').strip()} "
                        f"{(person.last_name or '').strip()}"
                    ).strip()
                    if person
                    else ""
                )
                analysis = iv.analysis_data or {}
                interview_payload.append(
                    {
                        "candidate_name": cand_name or "Unknown",
                        "interview_date": (
                            iv.interview_date.isoformat() if iv.interview_date else None
                        ),
                        "interviewer_name": None,
                        "duration_seconds": iv.duration_seconds,
                        "analysis": analysis,
                    }
                )
                for f in analysis.get("process_findings") or []:
                    if isinstance(f, dict):
                        findings_payload.append(
                            {**f, "candidate_name": cand_name or "Unknown"}
                        )
                for r in analysis.get("red_flags") or []:
                    if isinstance(r, dict):
                        red_flags_payload.append(
                            {**r, "candidate_name": cand_name or "Unknown"}
                        )
                if analysis.get("verdict_summary") or analysis.get("key_strength"):
                    verdict_rows.append(
                        {
                            "candidate_name": cand_name or "Unknown",
                            "verdict_summary": analysis.get("verdict_summary"),
                            "key_strength": analysis.get("key_strength"),
                            "key_risk": analysis.get("key_risk"),
                            "risk_mitigation": analysis.get("risk_mitigation"),
                        }
                    )

            # Comparison grid (covers SCR-56) — averages over evaluators on
            # the human side, falls back to AI when no human scores exist.
            human_rows = (
                db.execute(
                    select(HumanAssessment).where(
                        HumanAssessment.candidate_vacancy_id.in_(cv_ids),
                        HumanAssessment.tenant_id == vacancy.tenant_id,
                    )
                )
                .scalars()
                .all()
                if cv_ids
                else []
            )
            interview_cv_map = {iv.id: iv.candidate_vacancy_id for iv in interviews}
            ai_rows = (
                db.execute(
                    select(AIAssessment).where(
                        AIAssessment.interview_id.in_([iv.id for iv in interviews]),
                        AIAssessment.tenant_id == vacancy.tenant_id,
                    )
                )
                .scalars()
                .all()
                if interviews
                else []
            )
            human_buckets: dict[uuid.UUID, dict[str, list[float]]] = {}
            for hs in human_rows:
                if hs.score is None:
                    continue
                target_cv = next(
                    (c for c in cvs if c.id == hs.candidate_vacancy_id), None
                )
                if not target_cv:
                    continue
                bucket = human_buckets.setdefault(
                    target_cv.candidate_id, {}
                ).setdefault(str(hs.competence_id), [])
                bucket.append(float(hs.score))
            ai_buckets: dict[uuid.UUID, dict[str, list[float]]] = {}
            for ai in ai_rows:
                if ai.score is None:
                    continue
                cv_id = interview_cv_map.get(ai.interview_id)
                target_cv = next((c for c in cvs if c.id == cv_id), None)
                if not target_cv:
                    continue
                bucket = ai_buckets.setdefault(target_cv.candidate_id, {}).setdefault(
                    str(ai.competence_id), []
                )
                bucket.append(float(ai.score))

            comparison_competences: list[dict] = []
            profile_competences = (
                (profile.profile_data or {}).get("competences", []) if profile else []
            )

            def _candidate_display_name(cv: CandidateVacancy) -> str:
                person = persons_by_candidate.get(cv.candidate_id)
                if not person:
                    return "Unknown"
                return (
                    f"{person.first_name or ''} {person.last_name or ''}".strip()
                    or "Unknown"
                )

            comparison_candidates_payload = [
                {"id": cv.candidate_id, "name": _candidate_display_name(cv)}
                for cv in cvs
            ]
            for comp in profile_competences:
                if not isinstance(comp, dict):
                    continue
                cid = normalize_competence_id(comp.get("id") or comp.get("name") or "")
                if cid is None:
                    continue
                comp_key = str(cid)
                cells = []
                scored = []
                for cand in comparison_candidates_payload:
                    cand_id = cand["id"]
                    if not isinstance(cand_id, uuid.UUID):
                        continue
                    human_vals = human_buckets.get(cand_id, {}).get(comp_key)
                    score: float | None = None
                    if human_vals:
                        score = sum(human_vals) / len(human_vals)
                    else:
                        ai_vals = ai_buckets.get(cand_id, {}).get(comp_key)
                        if ai_vals:
                            score = sum(ai_vals) / len(ai_vals)
                    if score is not None:
                        scored.append(score)
                    cells.append({"candidate_id": cand_id, "score": score})
                divergence = (
                    round(max(scored) - min(scored), 2) if len(scored) >= 2 else None
                )
                comparison_competences.append(
                    {
                        "name": comp.get("name") or comp.get("id"),
                        "cells": cells,
                        "divergence": divergence,
                    }
                )

            # Human assessments listing (one row per (candidate, comp)).
            comp_name_by_id: dict[str, str] = {}
            for comp in profile_competences:
                if isinstance(comp, dict):
                    cid = normalize_competence_id(
                        comp.get("id") or comp.get("name") or ""
                    )
                    if cid is not None:
                        comp_name_by_id[str(cid)] = (
                            comp.get("name") or comp.get("id") or ""
                        )
            assessments_payload: list[dict] = []
            for hs in human_rows:
                target_cv = next(
                    (c for c in cvs if c.id == hs.candidate_vacancy_id), None
                )
                if not target_cv:
                    continue
                person = persons_by_candidate.get(target_cv.candidate_id)
                cand_name = (
                    (
                        f"{(person.first_name or '').strip()} "
                        f"{(person.last_name or '').strip()}"
                    ).strip()
                    if person
                    else ""
                )
                assessments_payload.append(
                    {
                        "candidate_name": cand_name or "Unknown",
                        "competence_name": comp_name_by_id.get(str(hs.competence_id))
                        or str(hs.competence_id),
                        "evaluator_name": hs.evaluator_name or "",
                        "score": hs.score,
                        "comment": hs.comment or "",
                    }
                )

            tenant = db.get(Tenant, vacancy.tenant_id)
            branding: dict = {"tenant_name": tenant.name if tenant else None}
            if tenant and tenant.logo_file_id:
                logo_file = db.get(File, tenant.logo_file_id)
                if logo_file:
                    # Branding is best-effort: a hung S3 must not pin the
                    # worker. Use a dedicated client with explicit socket
                    # timeouts (the shared get_s3_client() inherits the
                    # boto3 default of unbounded).
                    try:
                        import boto3
                        from botocore.config import Config as BotoConfig

                        logo_client = boto3.client(
                            "s3",
                            endpoint_url=settings.s3_endpoint,
                            aws_access_key_id=settings.s3_access_key,
                            aws_secret_access_key=settings.s3_secret_key,
                            config=BotoConfig(
                                connect_timeout=5,
                                read_timeout=10,
                                retries={"max_attempts": 1},
                            ),
                        )
                        obj = logo_client.get_object(
                            Bucket=settings.s3_bucket, Key=logo_file.path
                        )
                        branding["logo_png"] = obj["Body"].read()
                    except Exception:  # noqa: BLE001 - logo is optional, logged
                        logger.warning(
                            "Failed to load tenant logo for export %s",
                            export_id,
                        )

            # HRP-523 — the Summary / Matrix headers carry the vacancy's
            # position and division, so resolve the two FK titles here
            # rather than shipping the placeholders the sheets used to
            # render as empty.
            specialization_title: str | None = None
            if vacancy.specialization_id:
                from app.modules.dictionary.models import DictionaryItem

                spec_row = db.get(DictionaryItem, vacancy.specialization_id)
                specialization_title = spec_row.title if spec_row else None

            division_name: str | None = None
            if vacancy.division_id:
                from app.modules.company.models import Division

                div_row = db.get(Division, vacancy.division_id)
                division_name = div_row.name if div_row else None

            vacancy_payload = {
                "title": vacancy.title,
                "status": vacancy.status,
                "specialization_title": specialization_title,
                "grade_title": None,
                "division_name": division_name,
                "location": vacancy.location,
                "employment_type": vacancy.employment_type,
                "salary_min": (
                    float(vacancy.salary_min)
                    if vacancy.salary_min is not None
                    else None
                ),
                "salary_max": (
                    float(vacancy.salary_max)
                    if vacancy.salary_max is not None
                    else None
                ),
                "salary_currency": vacancy.salary_currency,
                "owner_name": None,
                "created_at": (
                    vacancy.created_at.isoformat() if vacancy.created_at else None
                ),
                "description": vacancy.description,
            }
            # HRP-268 — assemble the 4-sheet consolidated payload.
            report_meta = export.report_data or {}
            audience = (
                str(report_meta.get("audience") or "recruiter")
                .lower()
                .replace("-", "_")
            )
            cv_filter_raw = report_meta.get("candidate_vacancy_ids") or []
            cv_filter: set[uuid.UUID] = set()
            for raw in cv_filter_raw:
                try:
                    cv_filter.add(uuid.UUID(str(raw)))
                except (TypeError, ValueError):
                    continue
            # No whitelist means the wizard's "All active" scope: hired,
            # rejected and withdrawn candidates stay out of the report.
            # An explicit list (Finalists / Custom) is taken verbatim.
            selected_cvs = (
                [cv for cv in cvs if cv.id in cv_filter]
                if cv_filter
                else [
                    cv
                    for cv in cvs
                    if (cv.status or "").lower() not in TERMINAL_CV_STATUSES
                ]
            )
            selected_cv_ids = {cv.id for cv in selected_cvs}

            # Tenant divergence threshold + active scale max (HRP-265).
            divergence_threshold = 1.0
            max_score = 5.0
            tenant_row = db.get(Tenant, vacancy.tenant_id)
            if tenant_row is not None:
                matrix_settings = tenant_row.recruitment_matrix_settings or {}
                # Use explicit ``is not None`` instead of truthy ``or`` so a
                # tenant who deliberately set threshold=0 ("flag any gap")
                # is not silently bumped to the 1.0 default.
                raw_threshold = matrix_settings.get("divergence_threshold")
                if raw_threshold is not None:
                    try:
                        divergence_threshold = float(raw_threshold)
                    except (TypeError, ValueError):
                        logger.warning(
                            "Tenant %s has a malformed divergence_threshold: %r",
                            vacancy.tenant_id,
                            raw_threshold,
                        )
            from app.modules.recruitment.models import ScaleConfig

            active_scale = db.execute(
                select(ScaleConfig).where(
                    ScaleConfig.tenant_id == vacancy.tenant_id,
                    ScaleConfig.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if active_scale is not None:
                max_score = float(active_scale.max_value)

            comp_keys: list[str] = []
            comp_meta_by_key: dict[str, dict] = {}
            for comp in profile_competences:
                if not isinstance(comp, dict):
                    continue
                cid = normalize_competence_id(comp.get("id") or comp.get("name") or "")
                if cid is None:
                    continue
                ckey = str(cid)
                comp_keys.append(ckey)
                comp_meta_by_key[ckey] = {
                    "id": cid,
                    "name": comp.get("name") or comp.get("id") or "",
                    "group": comp.get("group"),
                    "criticality": comp.get("criticality"),
                }

            # Latest AI per (cv, comp) so the Matrix / Detail sheets do not
            # double-count earlier top-ups (HRP-265 parity). A tz-aware
            # EPOCH guards the tuple compare against NULL updated_at rows
            # (legacy / manual fix paths) — without it the whole report
            # crashes on the first None side.
            tz_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            ai_latest: dict[tuple[uuid.UUID, str], dict] = {}
            for ai in ai_rows:
                target_cv_id = interview_cv_map.get(ai.interview_id)
                if target_cv_id not in selected_cv_ids:
                    continue
                key = (target_cv_id, str(ai.competence_id))
                existing = ai_latest.get(key)
                anchor = (ai.updated_at or tz_epoch, ai.id)
                if existing is None or anchor > (
                    existing["updated_at"] or tz_epoch,
                    existing["ai_id"],
                ):
                    ai_latest[key] = {
                        "score": ai.score,
                        "status": (ai.status or "").lower(),
                        "reasoning": ai.reasoning or "",
                        "citations": ai.citations or [],
                        "updated_at": ai.updated_at,
                        "ai_id": ai.id,
                    }

            interviews_by_cv: dict[uuid.UUID, list[Interview]] = {}
            for iv in interviews:
                if iv.candidate_vacancy_id in selected_cv_ids:
                    interviews_by_cv.setdefault(iv.candidate_vacancy_id, []).append(iv)

            def _cv_display_name(cv_obj: CandidateVacancy) -> str:
                # HRP-525 — resume-sourced candidates have no Person row
                # (person_id is optional since HRP-181 REDO), so keying
                # the name off ``persons_by_candidate`` rendered every one
                # of them as "Unknown" — including in the Detail sheet
                # title. ``candidate_display_name`` prefers the
                # denormalised ``Candidate.full_name`` and only then falls
                # back to the linked person.
                return candidate_display_name(cv_obj.candidate)

            # Per-candidate aggregates (Manager % + AI %, with not_covered
            # dropping out of the AI denominator per HRP-265 spec).
            per_cv_aggregates: dict[uuid.UUID, dict] = {}
            for cv in selected_cvs:
                manager_sum = 0.0
                manager_scored = 0
                ai_sum = 0.0
                ai_scored = 0
                ai_not_covered = 0
                divergence_count = 0
                cells_for_matrix: list[dict] = []
                for ckey in comp_keys:
                    human_vals = human_buckets.get(cv.candidate_id, {}).get(ckey)
                    manager_score: float | None = None
                    if human_vals:
                        manager_score = sum(human_vals) / len(human_vals)
                        manager_sum += manager_score
                        manager_scored += 1
                    ai_entry = ai_latest.get((cv.id, ckey))
                    ai_score: float | None = None
                    ai_status = "missing"
                    if ai_entry is not None:
                        raw_status = ai_entry["status"]
                        if raw_status in {"ready", "ok", "completed", "assessed"}:
                            ai_status = "ready"
                        elif raw_status in {
                            "not_covered",
                            "insufficient",
                            "skipped",
                        }:
                            ai_status = "not_covered"
                        else:
                            ai_status = raw_status or "missing"
                        if ai_entry["score"] is not None and ai_status == "ready":
                            ai_score = float(ai_entry["score"])
                            ai_sum += ai_score
                            ai_scored += 1
                        elif ai_status == "not_covered":
                            # Only the explicit not-covered family drops out
                            # of the AI denominator — failed / error / unknown
                            # statuses count as a miss against the denominator
                            # so a broken pipeline does not silently inflate
                            # the candidate's AI %.
                            ai_not_covered += 1
                    divergence = False
                    if manager_score is not None and ai_score is not None:
                        divergence = (
                            abs(manager_score - ai_score) >= divergence_threshold
                        )
                        if divergence:
                            divergence_count += 1
                    cells_for_matrix.append(
                        {
                            "candidate_id": cv.candidate_id,
                            "competence_key": ckey,
                            "manager_score": manager_score,
                            "ai_score": ai_score,
                            "ai_status": ai_status,
                            "divergence": divergence,
                        }
                    )

                manager_denominator = max_score * len(comp_keys)
                ai_denominator = max_score * max(len(comp_keys) - ai_not_covered, 0)
                # HRP-523 REDO — two different manager percentages, for two
                # different questions. ``manager_percent`` keeps the full
                # denominator: it is the coverage-aware figure the Summary and
                # Matrix totals display. ``manager_scored_percent`` divides by
                # what the manager actually rated, and only that one feeds the
                # recommendation — otherwise a candidate scored 5/5 on 3 of 10
                # competences reads as 30% and gets "Not recommended" for the
                # manager's unfinished work rather than for their answers.
                manager_scored_denominator = max_score * manager_scored
                per_cv_aggregates[cv.id] = {
                    "manager_total": manager_sum,
                    "manager_scored": manager_scored,
                    "manager_percent": (
                        round(manager_sum / manager_denominator * 100, 1)
                        if manager_scored > 0 and manager_denominator > 0
                        else None
                    ),
                    "manager_scored_percent": (
                        round(manager_sum / manager_scored_denominator * 100, 1)
                        if manager_scored > 0 and manager_scored_denominator > 0
                        else None
                    ),
                    "ai_total": ai_sum,
                    "ai_scored": ai_scored,
                    "ai_not_covered": ai_not_covered,
                    "ai_percent": (
                        round(ai_sum / ai_denominator * 100, 1)
                        if ai_scored > 0 and ai_denominator > 0
                        else None
                    ),
                    "divergence_count": divergence_count,
                    "cells": cells_for_matrix,
                }

            # Sheet 1 — Summary rows (HRP-523).
            summary_rows = []
            # Manager / AI percentages at or above this count as "high"
            # for the recommendation rule below.
            strong_percent = 70.0
            for cv in selected_cvs:
                agg = per_cv_aggregates[cv.id]
                manager_text = (
                    (
                        f"{round(agg['manager_total'], 1)}/"
                        f"{round(max_score * len(comp_keys), 1)}"
                        + (
                            f" ({agg['manager_percent']}%)"
                            if agg["manager_percent"] is not None
                            else ""
                        )
                    )
                    if agg["manager_scored"] > 0
                    else "—"
                )

                readiness = (cv.ai_readiness or "none").lower()
                # ``ai_readiness`` is the candidate-level record of which
                # inputs the model actually saw, so it — not the score
                # count — decides the wording of the empty AI cell.
                if readiness == "resume_and_transcript":
                    readiness_text = "Full data"
                elif readiness == "resume_only":
                    readiness_text = "No transcript"
                else:
                    readiness_text = "No data"

                if agg["ai_scored"] > 0:
                    ai_text = (
                        f"{round(agg['ai_total'], 1)}/"
                        f"{round(max_score * (len(comp_keys) - agg['ai_not_covered']), 1)}"
                        + (
                            f" ({agg['ai_percent']}%)"
                            if agg["ai_percent"] is not None
                            else ""
                        )
                    )
                    if agg["ai_not_covered"]:
                        ai_text += "*"
                elif readiness == "resume_only":
                    ai_text = "— (no transcript)"
                else:
                    ai_text = "— (no data)"

                verdict = (cv.ai_verdict or "pending").lower()
                # HRP-523 REDO — strength is judged on the competences the
                # manager actually rated; coverage is a separate question,
                # answered by the ``manager_partial`` branch below.
                manager_pct = agg["manager_scored_percent"]
                ai_pct = agg["ai_percent"]
                manager_strong = (
                    manager_pct is not None and manager_pct >= strong_percent
                )
                ai_strong = ai_pct is not None and ai_pct >= strong_percent
                has_divergence = agg["divergence_count"] > 0
                manager_partial = 0 < agg["manager_scored"] < len(comp_keys)

                if agg["manager_scored"] == 0:
                    recommendation = "Awaiting manager review"
                elif not manager_strong or verdict == "not_recommended":
                    recommendation = "Not recommended"
                elif manager_partial:
                    # Strong on what was rated, but the sheet is unfinished —
                    # not enough evidence to recommend, not a reason to reject.
                    recommendation = "Additional check"
                elif (
                    ai_strong
                    and readiness == "resume_and_transcript"
                    and verdict == "recommended"
                    and not has_divergence
                ):
                    recommendation = "Recommended"
                else:
                    recommendation = "Additional check"

                # Profile snippet: the AI verdict summary is the sharper
                # read when it exists, otherwise fall back to the parsed
                # resume summary. Both capped so the column stays legible.
                parsed_summary = (
                    (cv.candidate.parsed_resume_jsonb or {}).get("summary")
                    if cv.candidate and cv.candidate.parsed_resume_jsonb
                    else None
                )
                profile_source = cv.ai_verdict_summary or parsed_summary or ""
                profile_summary = profile_source.strip()
                if len(profile_summary) > 100:
                    profile_summary = profile_summary[:97].rstrip() + "…"

                # Footnote — only attached when the AI figure carries the
                # asterisk (partial coverage) or diverges from the manager.
                note: str | None = None
                if agg["ai_not_covered"] and has_divergence:
                    note = (
                        f"AI {round(agg['ai_total'], 1)}/"
                        f"{round(max_score * (len(comp_keys) - agg['ai_not_covered']), 1)}"
                        f" — diverges from the manager on "
                        f"{agg['divergence_count']} competence(s); "
                        f"{agg['ai_not_covered']} competence(s) were not "
                        "verified at the interview and drop out of the "
                        "AI denominator."
                    )
                elif agg["ai_not_covered"]:
                    note = (
                        f"{agg['ai_not_covered']} competence(s) were not "
                        "covered by the interview and drop out of the AI "
                        "denominator."
                    )
                elif has_divergence:
                    note = (
                        f"Manager and AI diverge on "
                        f"{agg['divergence_count']} competence(s)."
                    )

                summary_rows.append(
                    {
                        "candidate_name": _cv_display_name(cv),
                        "profile_summary": profile_summary,
                        "manager_score_text": manager_text,
                        "ai_score_text": ai_text,
                        "data_readiness": readiness_text,
                        "recommendation": recommendation,
                        "note": note,
                    }
                )

            # Sheet 2 — Matrix payload (competences × candidates).
            # HRP-524 — each column header needs to know whether the
            # candidate's AI run saw a transcript (the ✅ marker), and the
            # Total row needs the per-candidate denominators + percentages
            # so it can render "39/44 (89%)" and pick a threshold colour.
            matrix_candidates = [
                {
                    "id": cv.candidate_id,
                    "name": _cv_display_name(cv),
                    "ai_full_data": (cv.ai_readiness or "").lower()
                    == "resume_and_transcript",
                    "manager_denominator": round(max_score * len(comp_keys), 1),
                    "ai_denominator": round(
                        max_score
                        * max(
                            len(comp_keys) - per_cv_aggregates[cv.id]["ai_not_covered"],
                            0,
                        ),
                        1,
                    ),
                    "manager_percent": per_cv_aggregates[cv.id]["manager_percent"],
                    "ai_percent": per_cv_aggregates[cv.id]["ai_percent"],
                }
                for cv in selected_cvs
            ]
            matrix_competences = []
            for ckey in comp_keys:
                meta = comp_meta_by_key[ckey]
                cells = []
                for cv in selected_cvs:
                    agg = per_cv_aggregates[cv.id]
                    cell = next(
                        (c for c in agg["cells"] if c["competence_key"] == ckey),
                        None,
                    )
                    if cell is None:
                        continue
                    cells.append(
                        {
                            "candidate_id": cv.candidate_id,
                            "manager_score": cell["manager_score"],
                            "ai_score": cell["ai_score"],
                            "ai_status": cell["ai_status"],
                            "divergence": cell["divergence"],
                        }
                    )
                matrix_competences.append({**meta, "cells": cells})

            matrix_payload = {
                "candidates": matrix_candidates,
                "competences": matrix_competences,
                "max_score": max_score,
                "vacancy_title": vacancy.title,
                "data_disclaimer": (
                    "Data sources: Manager column is the mean across all "
                    "evaluators who scored the competence; AI column is the "
                    "latest completed interview analysis. Cells marked ⚠ are "
                    "where the two disagree; 'n/a' means the AI did not cover "
                    "the competence and it drops out of the AI denominator."
                ),
                "scale_disclaimer": (
                    f"Scale: {active_scale.name if active_scale else 'default'} "
                    f"(max {round(max_score, 1)} per competence). "
                    f"Divergence threshold: {divergence_threshold}."
                ),
            }

            # Sheet 3 — Detail per candidate.
            details_payload: list[dict] = []
            for cv in selected_cvs:
                agg = per_cv_aggregates[cv.id]
                cv_interviews = interviews_by_cv.get(cv.id, [])
                latest_interview = max(
                    cv_interviews,
                    key=lambda iv: (
                        iv.created_at or datetime.min.replace(tzinfo=timezone.utc)
                    ),
                    default=None,
                )
                analysis = (
                    latest_interview.analysis_data
                    if latest_interview and latest_interview.analysis_data
                    else {}
                )
                scores_table: list[dict] = []
                for cell in agg["cells"]:
                    meta = comp_meta_by_key[cell["competence_key"]]
                    ai_entry = ai_latest.get((cv.id, cell["competence_key"]))
                    citations_raw = (ai_entry or {}).get("citations") or []
                    citation_lines: list[str] = []
                    for c in citations_raw[:3]:
                        if isinstance(c, dict):
                            citation_lines.append(c.get("quote") or c.get("text") or "")
                        elif isinstance(c, str):
                            citation_lines.append(c)
                    scores_table.append(
                        {
                            # HRP-525 — the Scores table shows the group
                            # as well as the competence, so a reader can
                            # tell which block a low score sits in.
                            "competence_group": meta.get("group") or "—",
                            "competence_name": meta["name"],
                            "manager_score": cell["manager_score"],
                            "ai_score": cell["ai_score"],
                            "citations": [line for line in citation_lines if line],
                            "reasoning": (ai_entry or {}).get("reasoning") or "",
                        }
                    )

                resume_summary = ""
                if cv.candidate and cv.candidate.parsed_resume_jsonb:
                    resume_summary = (
                        cv.candidate.parsed_resume_jsonb.get("summary") or ""
                    )

                # Resume parser stores the current role under
                # ``current_position`` (top-level) and under
                # ``experience[0].position``; the ``position`` top-level
                # key does not exist — so fall back through both shapes.
                position_value: str | None = None
                if cv.candidate is not None:
                    parsed = (
                        cv.candidate.parsed_resume_jsonb
                        if isinstance(cv.candidate.parsed_resume_jsonb, dict)
                        else None
                    )
                    if parsed:
                        position_value = parsed.get("current_position")
                        if not position_value:
                            experience = parsed.get("experience") or []
                            if (
                                isinstance(experience, list)
                                and experience
                                and isinstance(experience[0], dict)
                            ):
                                position_value = experience[0].get(
                                    "position"
                                ) or experience[0].get("title")
                    if not position_value:
                        position_value = getattr(cv.candidate, "current_position", None)

                details_payload.append(
                    {
                        "candidate_name": _cv_display_name(cv),
                        "position": position_value,
                        # HRP-525 — the header shows the funnel stage the
                        # candidate actually sits in; ``cv.status`` is only
                        # the active/removed flag and read as noise.
                        "status": (
                            stage_names.get(cv.stage_id) if cv.stage_id else None
                        )
                        or cv.status,
                        "resume_summary": resume_summary,
                        "scores": scores_table,
                        "blind_spots": analysis.get("blind_spots") or [],
                        "process_findings": analysis.get("process_findings") or [],
                        "red_flags": analysis.get("red_flags") or [],
                        "verdict": {
                            "verdict_summary": analysis.get("verdict_summary"),
                            "verdict": analysis.get("verdict"),
                            "key_strength": analysis.get("key_strength"),
                            "key_risk": analysis.get("key_risk"),
                            "risk_mitigation": analysis.get("risk_mitigation"),
                            "recommendation_for_next_step": analysis.get(
                                "recommendation_for_next_step"
                            ),
                        },
                    }
                )

            # Sheet 4 — Incomplete data (always emitted).
            incomplete_rows: list[dict] = []
            for cv in selected_cvs:
                agg = per_cv_aggregates[cv.id]
                if cv.candidate is None or not getattr(
                    cv.candidate, "parsed_resume_jsonb", None
                ):
                    incomplete_rows.append(
                        {
                            "candidate_name": _cv_display_name(cv),
                            "missing": "Resume not parsed",
                            "action": "Upload + parse the resume so the AI run can use it.",
                        }
                    )
                    continue
                if agg["manager_scored"] == 0:
                    incomplete_rows.append(
                        {
                            "candidate_name": _cv_display_name(cv),
                            "missing": "Manager scoring missing",
                            "action": "Request the hiring manager to fill the scoring sheet.",
                        }
                    )
                if agg["ai_scored"] == 0:
                    incomplete_rows.append(
                        {
                            "candidate_name": _cv_display_name(cv),
                            "missing": "AI analysis missing",
                            "action": "Launch the AI analysis (resume-only or full).",
                        }
                    )
                elif agg["ai_not_covered"] > 0:
                    incomplete_rows.append(
                        {
                            "candidate_name": _cv_display_name(cv),
                            "missing": (
                                f"AI partial — {agg['ai_not_covered']} "
                                "competences not covered"
                            ),
                            "action": "Upload a full interview transcript and re-run the AI.",
                        }
                    )

            xlsx_bytes = render_report_xlsx(
                vacancy=vacancy_payload,
                branding=branding,
                summary_rows=summary_rows,
                matrix=matrix_payload,
                details=details_payload,
                incomplete=incomplete_rows,
                audience=audience,
                sections=sorted(selected_sections),
            )

            file_id = uuid.uuid4()
            path = f"reports/{tenant_id}/{file_id}.xlsx"
            uploaded = upload_file(
                xlsx_bytes,
                path,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            if not uploaded:
                # Without S3 we cannot deliver the file; surface a hard
                # failure so the UI shows a real error instead of a row
                # that hangs in "completed" with no download link.
                export.status = "failed"
                export.error = "Object storage unavailable"
                db.commit()
                return {
                    "status": "failed",
                    "error": "Object storage unavailable",
                }

            file_row = File(
                id=file_id,
                tenant_id=vacancy.tenant_id,
                name=f"vacancy_{vacancy.id}_report.xlsx",
                original_name=f"vacancy_{vacancy.title[:60]}_report.xlsx",
                path=path,
                size=len(xlsx_bytes),
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                uploaded_by=export.generated_by,
                entity_type="recruitment.report",
                entity_id=export.id,
            )
            db.add(file_row)
            # Flush the File first so the FK on ConsolidatedReport.file_id
            # has a row to reference before we UPDATE the export. Without
            # this, SQLAlchemy fires the UPDATE before the INSERT and the
            # FK check rejects it.
            db.flush()
            export.file_id = file_id
            export.status = "completed"
            export.completed_at = datetime.now(timezone.utc)
            export.error = None
            generated_by = export.generated_by
            vacancy_obj = db.get(Vacancy, export.vacancy_id)
            vacancy_title = vacancy_obj.title if vacancy_obj else None
            db.commit()

            # R4c N-07: notify the user who triggered the export.
            try:
                from app.modules.recruitment.notifications import notify_sync

                notify_sync(
                    db,
                    event="recruitment.report.generated",
                    tenant_id=uuid.UUID(tenant_id),
                    recipient_ids=[generated_by] if generated_by else [],
                    fallback_admins=True,
                    context={
                        "report_id": export_id,
                        "vacancy_id": str(export.vacancy_id),
                        "vacancy_title": vacancy_title,
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception("report notification failed for %s", export_id)

            logger.info(
                "Report export %s completed (%d bytes)", export_id, len(xlsx_bytes)
            )
            return {
                "status": "completed",
                "export_id": export_id,
                "file_id": str(file_id),
                "size_bytes": len(xlsx_bytes),
            }

    except Exception as exc:
        logger.exception("generate_report_task failed for %s", export_id)
        try:
            with Session(engine) as db:
                export = db.get(ConsolidatedReport, uuid.UUID(export_id))
                if export:
                    export.status = "failed"
                    export.error = str(exc)[:1000]
                    db.commit()
                    # R4c N-AI: tasks with max_retries=0 (this one) never
                    # reach the task_failure-based notification path, so we
                    # publish here too.
                    try:
                        from app.modules.recruitment.notifications import notify_sync

                        notify_sync(
                            db,
                            event="recruitment.ai.task_failed",
                            tenant_id=uuid.UUID(tenant_id),
                            recipient_ids=[],
                            fallback_admins=True,
                            context={
                                "task_type": "generate_report_task",
                                "entity_id": export_id,
                                "error": str(exc)[:200],
                            },
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "ai_task_failed notify failed for %s", export_id
                        )
        except Exception:
            logger.exception("Failed to mark report export %s as failed", export_id)
        # No retry: report failures are typically deterministic (bad
        # template, missing profile). The UI surfaces the error so the
        # user can fix and re-trigger.
        return {"status": "failed", "error": str(exc)[:200]}
    finally:
        engine.dispose()
