"""Audit registry for recruitment services (FR-28, R4b.1).

Wraps every mutating service function with a hook that records an
audit row AFTER the underlying call has committed. Mirrors the
shape of ``ee/billing.py:BILLABLE`` / ``BILLING_EXEMPT`` so the same
coverage-style invariant ("every mutation must be declared") can be
enforced by a unit test.

Wrapper contract:

  1. Caller invokes the wrapped service ``await func(*args, **kw)``.
  2. ``func`` performs its own ``db.commit()`` — same as without the
     wrapper. Once it returns, the parent transaction is already
     persisted.
  3. The wrapper then calls :func:`audit_service.record_event`. That
     call commits exactly one new row; it never reverts the prior
     mutation because the prior mutation is already committed.

Failures inside ``record_event`` are swallowed (see its docstring) so a
broken audit table can never block the business operation.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from functools import wraps
from typing import Any

from app.core.service_patch import apply_service_patches, declared_keys
from app.modules.recruitment import audit_service

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Map: module → [(func_name, action_template)]
#
# ``action_template`` is the audit-log action string. ``entity_type`` is
# derived as ``action.split(".")[0]`` so "vacancy.create" → "vacancy".
# ---------------------------------------------------------------------------

AUDITED: dict[str, list[tuple[str, str]]] = {
    # project-review #7 split: entries follow the canonical home of each
    # function (vacancy / vacancy-profile / candidate / assessment) so the
    # wrapper attaches to the right namespace; ``service`` keeps delegating
    # attribute access to these canonical homes.
    "app.modules.recruitment.vacancy_service": [
        # vacancies
        ("create_vacancy", "vacancy.create"),
        ("update_vacancy", "vacancy.update"),
        ("close_vacancy", "vacancy.close"),
        ("archive_vacancy", "vacancy.archive"),
        ("restore_vacancy", "vacancy.restore"),
        ("delete_vacancy", "vacancy.delete"),
        # HRP-136 vacancy competences
        ("set_vacancy_competences", "vacancy.set_competences"),
        # HRP-135 attachments
        ("upload_vacancy_attachment", "vacancy.upload_attachment"),
        ("delete_vacancy_attachment", "vacancy.delete_attachment"),
        # stages
        ("replace_vacancy_stages_override", "vacancy.stages.update"),
        ("create_stage", "stage.create"),
        ("update_stage", "stage.update"),
        ("delete_stage", "stage.delete"),
        ("create_vacancy_stage_override", "stage.override"),
    ],
    "app.modules.recruitment.vacancy_profile_service": [
        ("save_profile", "vacancy.save_profile"),
        ("generate_profile_now", "vacancy.generate_profile"),
        ("apply_profile_session", "vacancy.apply_profile"),
        ("cancel_active_profile_session", "vacancy.cancel_profile_session"),
    ],
    "app.modules.recruitment.candidate_service": [
        # HRP-181 REDO Stage 2 — canonical candidate flow
        ("add_candidate_to_vacancy_manual", "candidate.add"),
        ("finalize_candidates_from_parsed", "candidate.add_from_resume"),
        ("patch_candidate_vacancy", "candidate.update_stage"),
        ("patch_candidate", "candidate.update"),
        ("archive_candidate", "candidate.archive"),
        ("delete_candidate_vacancy", "candidate.delete_vacancy_link"),
        # candidates
        ("create_candidate", "candidate.create"),
        ("update_candidate", "candidate.update"),
        ("attach_candidate", "candidate.attach"),
        ("change_candidate_status", "candidate.change_status"),
        # HRP-181 REDO Stage 3 — bulk resume upload (detached parsing).
        ("bulk_upload_resumes", "candidate.bulk_upload_resumes"),
        ("update_resume_parsed_data", "candidate.update_resume"),
    ],
    "app.modules.recruitment.assessment_service": [
        # questions
        ("add_question", "question.create"),
        ("update_question", "question.update"),
        ("delete_question", "question.delete"),
        # assessments
        # HRP-266: record/update/revert write a rich payload_diff
        # ({old_score, new_score, evaluator_id, ...}) inline so the
        # Versions panel can render and revert from a single source —
        # the generic decorator would emit a sibling empty-payload row
        # and confuse the timeline, so these three live in AUDIT_EXEMPT.
        ("create_assessment_invite", "assessment.invite"),
    ],
    # M-5 split (R4d): interview / consent / report logic was extracted
    # into dedicated modules. Audit entries follow the canonical home of
    # each function so the wrapper attaches to the right namespace.
    "app.modules.recruitment.interview_service": [
        ("create_interview", "interview.create"),
        ("update_interview", "interview.update"),
        ("update_transcript", "interview.update_transcript"),
        ("update_segment", "interview.update_segment"),
        ("init_interview_upload", "interview.upload_init"),
        ("complete_interview_upload", "interview.upload_complete"),
        ("abort_interview_upload", "interview.upload_abort"),
        ("enqueue_transcribe", "interview.transcribe"),
        ("enqueue_analyze", "interview.analyze"),
        # HRP-202 lifecycle
        ("paste_text_transcript", "interview.transcript_paste"),
        ("archive_interview", "interview.archive"),
        ("restore_interview", "interview.restore"),
        ("replace_interview_file", "interview.replace_file"),
        ("record_av_scan_result", "interview.av_scan"),
    ],
    # HRP-204: resume-only / top-up / bulk AI analysis entry points.
    # HRP-270 added the cancel-flow.
    "app.modules.recruitment.resume_analysis_service": [
        ("enqueue_resume_only_analysis", "ai.analyze_resume_only"),
        ("enqueue_topup_to_full", "ai.analyze_topup_to_full"),
        ("enqueue_bulk_resume_only", "ai.bulk_analyze_resume_only"),
        ("cancel_ai_analysis_run", "ai.analyze_cancelled"),
    ],
    "app.modules.recruitment.consent_service": [
        ("create_consent_template", "consent.template_create"),
        ("update_consent_template", "consent.template_update"),
        ("send_consent_request", "consent.send"),
    ],
    "app.modules.recruitment.report_service": [
        ("enqueue_report", "report.generate"),
        ("delete_report", "report.delete"),
        ("create_report_template", "report.template_create"),
        ("update_report_template", "report.template_update"),
        ("delete_report_template", "report.template_delete"),
    ],
    # R4c: onboarding mutations
    "app.modules.recruitment.onboarding_service": [
        ("dismiss", "onboarding.dismiss"),
        ("seed_demo", "onboarding.demo_seed"),
        ("cleanup_demo", "onboarding.demo_cleanup"),
    ],
}

# Mutating-but-not-audited functions. Anything that does not write business
# data (intermediate technical helpers, public-token lookups that should
# not leak per-request audit rows) lives here so the coverage scanner can
# tell "declared as exempt" from "forgot to declare".
AUDIT_EXEMPT: set[str] = {
    # The audit writer itself — wrapping it would recurse.
    "app.modules.recruitment.audit_service:record_event",
    # HRP-252: cache-aware analyze wrapper — the inner ``enqueue_analyze``
    # is already audited (``interview.analyze``); the cache shim must not
    # double-record. A cache hit returns synchronously without business
    # mutations beyond copying the cached payload onto the interview row.
    "app.modules.recruitment.interview_service:enqueue_analyze_or_cached",
    # HRP-204: helpers in resume_analysis_service — these are pure
    # read-checks and bookkeeping invoked by the audited entry points
    # above, not user-facing mutations of their own.
    "app.modules.recruitment.resume_analysis_service:evaluate_topup_eligibility",
    "app.modules.recruitment.resume_analysis_service:list_runs_for_cv",
    "app.modules.recruitment.resume_analysis_service:apply_resume_only_verdict_guard",
    "app.modules.recruitment.resume_analysis_service:finalize_topup_after_full_analysis",
    # HRP-181 REDO: tenant-create seed for the recruitment funnel.
    # Idempotent infrastructural insert invoked from auth.register;
    # there's no per-user mutation to audit and the row already exists
    # in the alembic migration for pre-existing tenants.
    "app.modules.recruitment.vacancy_service:seed_default_recruitment_stages",
    # Cross-tenant — no tenant_id in signature, can't record a tenant-scoped row.
    "app.modules.recruitment.candidate_service:update_person",
    # Public token-based flows — tenant_id is resolved inside the function
    # body from the invite/consent row, not present in the signature. The
    # generic wrapper can't see it, so each of these calls
    # ``audit_service.record_event`` in-body after the tenant is known.
    "app.modules.recruitment.consent_service:sign_consent",
    "app.modules.recruitment.assessment_service:record_invite_assessment",
    # Settings hub: writes are audited explicitly by settings_router so the
    # decorator stays out of the way (router emits redacted payload_diff).
    "app.modules.recruitment.settings_service:create_scale",
    "app.modules.recruitment.settings_service:update_scale",
    "app.modules.recruitment.settings_service:delete_scale",
    "app.modules.recruitment.settings_service:create_llm_provider",
    "app.modules.recruitment.settings_service:update_llm_provider",
    "app.modules.recruitment.settings_service:delete_llm_provider",
    "app.modules.recruitment.settings_service:create_transcription_provider",
    "app.modules.recruitment.settings_service:update_transcription_provider",
    "app.modules.recruitment.settings_service:delete_transcription_provider",
    "app.modules.recruitment.settings_service:update_branding",
    "app.modules.recruitment.settings_service:update_retention",
    # HRP-265: matrix-settings PUT — router writes a dedicated audit row
    # ("matrix_settings.update") with a redacted payload_diff, no need
    # for the generic decorator to chime in with a second event.
    "app.modules.recruitment.settings_service:update_matrix_settings",
    # GDPR: router emits the audit row with rich payload (affected dict /
    # failed status / etc) — adding a duplicate generic row would only
    # confuse the timeline.
    "app.modules.recruitment.gdpr_service:gdpr_export",
    "app.modules.recruitment.gdpr_service:gdpr_erase",
    # Functionally read-only (returns bytes/url) — billed because the work
    # is non-trivial but the data state is not mutated.
    "app.modules.recruitment.assessment_service:export_questions_pdf",
    "app.modules.recruitment.interview_service:get_upload_part_url",
    "app.modules.recruitment.interview_service:get_interview_media_url",
    # HRP-202: chunk ack and cleanup are internal bookkeeping, not user
    # mutations worth a per-event audit row.
    "app.modules.recruitment.interview_service:ack_uploaded_chunk",
    "app.modules.recruitment.interview_service:cleanup_orphan_upload_sessions",
    "app.modules.recruitment.candidate_service:get_resume_download_url",
    "app.modules.recruitment.assessment_service:get_invite_canvas",
    "app.modules.recruitment.assessment_service:get_invite_context",
    "app.modules.recruitment.assessment_service:get_invite_by_token",
    "app.modules.recruitment.consent_service:get_consent_by_token",
    "app.modules.recruitment.consent_service:get_latest_consent",
    "app.modules.recruitment.assessment_service:get_canvas",
    # HRP-265: aggregated matrix + cell drill-down are read-only.
    "app.modules.recruitment.assessment_service:get_assessment_matrix",
    "app.modules.recruitment.assessment_service:get_assessment_matrix_cell_detail",
    # HRP-266: assessment writes emit their own audit rows inline with a
    # rich payload_diff so the Versions panel can power Revert from a
    # single source. ``list_assessment_history`` is the read-side view
    # of that same log and stays free.
    "app.modules.recruitment.assessment_service:record_human_assessment",
    "app.modules.recruitment.assessment_service:update_human_assessment",
    "app.modules.recruitment.assessment_service:revert_human_assessment",
    "app.modules.recruitment.assessment_service:list_assessment_history",
    "app.modules.recruitment.report_service:compare_candidates",
    # R4c: share-service writes its own audit rows (report.shared,
    # report.share_revoked, report.share_opened) with richer payload so
    # the generic decorator stays out of the way.
    "app.modules.recruitment.share_service:create_share",
    "app.modules.recruitment.share_service:revoke_share",
    "app.modules.recruitment.share_service:open_share",
}


# ---------------------------------------------------------------------------
# Argument introspection
# ---------------------------------------------------------------------------

_USER_ID_PARAMS = ("user_id", "initiator_id", "author_id", "inviter_id")

# Common id-suffix arg names we use when the result lacks an id.
_ENTITY_ID_FALLBACK_PARAMS = (
    "entity_id",
    "vacancy_id",
    "candidate_id",
    "interview_id",
    "stage_id",
    "template_id",
    "config_id",
    "scale_id",
    "report_id",
    "export_id",
    "resume_id",
    "assessment_id",
    "consent_id",
    "cv_id",
)


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            return None
    return None


def _extract_entity_id(result: Any, arguments: dict[str, Any]) -> uuid.UUID | None:
    """Best-effort: pull the entity uuid from the result or the bound args."""
    if isinstance(result, dict):
        candidate = result.get("id")
        coerced = _coerce_uuid(candidate)
        if coerced is not None:
            return coerced
    elif result is not None:
        candidate = getattr(result, "id", None)
        coerced = _coerce_uuid(candidate)
        if coerced is not None:
            return coerced

    for name in _ENTITY_ID_FALLBACK_PARAMS:
        if name in arguments:
            coerced = _coerce_uuid(arguments[name])
            if coerced is not None:
                return coerced
    return None


def _extract_user_id(arguments: dict[str, Any]) -> uuid.UUID | None:
    for name in _USER_ID_PARAMS:
        if name in arguments:
            coerced = _coerce_uuid(arguments[name])
            if coerced is not None:
                return coerced
    return None


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------


def _wrap_with_audit(func: Any, action: str) -> Any:
    """Wrap a service function with a post-success audit hook."""
    entity_type = action.split(".", 1)[0]
    # Cache once at wrap time — ``inspect.signature`` walks ``__wrapped__``
    # through the billing wrapper to recover the original signature. Doing
    # that on every call adds ~100µs per service invocation.
    sig = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # HRP-181 REDO Sweep E6: bind the audit context BEFORE the wrapped
        # call so we can record a failure row even when the service raises
        # after partial side effects (e.g. files committed to S3 + Celery
        # task enqueued before a later validation raises HTTPException).
        # Previously the audit row was only written on clean return,
        # leaving partial-success / raise paths un-audited.
        db = None
        tenant_id: uuid.UUID | None = None
        user_id: uuid.UUID | None = None
        entity_id_from_args: uuid.UUID | None = None
        try:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            db = bound.arguments.get("db")
            tenant_id = _coerce_uuid(bound.arguments.get("tenant_id"))
            user_id = _extract_user_id(bound.arguments)
            entity_id_from_args = _extract_entity_id(None, bound.arguments)
        except Exception:  # pragma: no cover — defence in depth
            log.exception("audit_hook.bind_failed", extra={"action": action})

        try:
            result = await func(*args, **kwargs)
        except Exception:
            if db is not None and tenant_id is not None:
                try:
                    await audit_service.record_event(
                        db,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        action=action,
                        entity_type=entity_type,
                        entity_id=entity_id_from_args,
                        payload_diff={"outcome": "raised"},
                    )
                except Exception:  # noqa: BLE001 — audit must not mask root cause
                    log.exception(
                        "audit_hook.failure_record_failed",
                        extra={"action": action},
                    )
            raise

        if db is None or tenant_id is None:
            log.debug(
                "audit_hook.missing_context",
                extra={"action": action, "has_db": db is not None},
            )
            return result

        try:
            entity_id = _extract_entity_id(result, {})
            if entity_id is None:
                entity_id = entity_id_from_args
        except Exception:  # pragma: no cover  # noqa: BLE001
            entity_id = entity_id_from_args

        if entity_id is None:
            log.debug("audit_hook.no_entity_id", extra={"action": action})

        await audit_service.record_event(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_diff=None,
        )
        return result

    wrapper._audit_action = action  # type: ignore[attr-defined]
    return wrapper


def register_audit_hooks() -> None:
    """Patch service functions with audit wrappers. Idempotent."""
    apply_service_patches(
        AUDITED,
        make_wrapper=lambda original, entry: _wrap_with_audit(original, entry[1]),
        marker="_audit_action",
        kind="Audit",
    )


# ---------------------------------------------------------------------------
# Introspection helpers (for tests)
# ---------------------------------------------------------------------------


def audited_keys() -> set[str]:
    """All ``module:func`` keys declared in AUDITED."""
    return declared_keys(AUDITED)
