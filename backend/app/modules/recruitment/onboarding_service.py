"""R4c onboarding service (SCR-A1..A5).

The recruitment dashboard nudges new tenants through their first
recruitment milestone — create a vacancy, attach a candidate, run an
interview, review a report. To make that walkthrough feel real before
the user has uploaded anything, a single endpoint seeds demo fixtures
that look like a live pipeline (one vacancy, three candidates spread
across stages, an interview with a preset transcript and AI analysis).

State lives in :attr:`Tenant.recruitment_onboarding` as a JSONB blob
with ``step`` / ``dismissed_at`` / ``demo_seeded_at`` keys. The wizard
client reads ``GET /recruitment/onboarding`` after every meaningful
mutation and advances the step when prerequisites are satisfied.

Demo rows are tagged with ``source='demo'`` (Candidate) /
``extra={"demo": true}`` (Vacancy notes) and a tenant-wide cleanup
endpoint deletes them. The Celery beat
:func:`app.modules.recruitment.tasks.cleanup_demo_recruitment_data_task`
prunes any row whose ``demo_seeded_at`` is older than 14 days.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Person
from app.modules.company.models import Tenant
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
    Vacancy,
    VacancyProfile,
)

DEMO_VACANCY_TITLE = "Senior Python Developer (demo)"
DEMO_CANDIDATES = (
    ("Alice", "Chen", "candidate", "alice.demo@example.com"),
    ("Bob", "Ivanov", "interview", "bob.demo@example.com"),
    ("Diana", "Petrova", "offer", "diana.demo@example.com"),
)
DEMO_TRANSCRIPT = (
    "[Recruiter] Tell me about a recent project.\n"
    "[Candidate] We migrated a monolith to FastAPI on AWS. "
    "I owned the data-pipeline rewrite end-to-end.\n"
    "[Recruiter] What challenged you the most?\n"
    "[Candidate] Coordinating two teams across timezones."
)
DEMO_AI_ANALYSIS: dict[str, Any] = {
    "data_completeness": "medium",
    "process_findings": [],
    "blind_spots": [],
    "red_flags": [],
    "verdict_summary": "Strong technical background, needs a follow-up on system-design depth.",
    "key_strength": "End-to-end ownership of a non-trivial migration.",
    "key_risk": "Limited evidence of cross-team leadership at scale.",
    "risk_mitigation": "Probe further in a technical panel.",
    "competence_assessments": [],
}


# ---------------------------------------------------------------------------
# Onboarding state
# ---------------------------------------------------------------------------


def _coerce_state(blob: Any) -> dict[str, Any]:
    if isinstance(blob, dict):
        return dict(blob)
    return {}


async def _get_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise AppError("tenant_not_found", status.HTTP_404_NOT_FOUND)
    return tenant


def _initial_state() -> dict[str, Any]:
    return {"step": "welcome", "dismissed_at": None, "demo_seeded_at": None}


async def _save_state(
    db: AsyncSession, tenant: Tenant, state: dict[str, Any]
) -> dict[str, Any]:
    tenant.recruitment_onboarding = state
    await db.commit()
    await db.refresh(tenant, attribute_names=["recruitment_onboarding"])
    return _coerce_state(tenant.recruitment_onboarding)


async def _detect_step(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    """Infer the next wizard step from the data the tenant already has."""

    has_vacancy = (
        await db.execute(
            select(Vacancy.id).where(Vacancy.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    if not has_vacancy:
        return "welcome"

    has_candidate = (
        await db.execute(
            select(CandidateVacancy.id)
            .where(CandidateVacancy.tenant_id == tenant_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not has_candidate:
        return "vacancy_created"

    has_interview = (
        await db.execute(
            select(Interview.id).where(Interview.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    if not has_interview:
        return "candidate_invited"

    has_completed_interview = (
        await db.execute(
            select(Interview.id)
            .where(
                Interview.tenant_id == tenant_id,
                Interview.analysis_status == "completed",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if not has_completed_interview:
        return "interview_scheduled"

    from app.modules.recruitment.models import ConsolidatedReport

    has_report = (
        await db.execute(
            select(ConsolidatedReport.id)
            .where(
                ConsolidatedReport.tenant_id == tenant_id,
                ConsolidatedReport.status == "completed",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if not has_report:
        return "report_reviewed"

    return "done"


async def get_state(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    tenant = await _get_tenant(db, tenant_id)
    state = _coerce_state(tenant.recruitment_onboarding) or _initial_state()
    inferred_step = await _detect_step(db, tenant_id)
    state["step"] = inferred_step
    state.setdefault("dismissed_at", None)
    state.setdefault("demo_seeded_at", None)
    return state


async def dismiss(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    tenant = await _get_tenant(db, tenant_id)
    state = _coerce_state(tenant.recruitment_onboarding) or _initial_state()
    state["dismissed_at"] = datetime.now(timezone.utc).isoformat()
    return await _save_state(db, tenant, state)


# ---------------------------------------------------------------------------
# Demo seeding
# ---------------------------------------------------------------------------


async def _has_demo_data(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    row = (
        await db.execute(
            select(Candidate.id)
            .where(
                Candidate.tenant_id == tenant_id, Candidate.source == "demo"
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def seed_demo(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    """Insert demo fixtures so the dashboard has something to render."""
    tenant = await _get_tenant(db, tenant_id)
    if await _has_demo_data(db, tenant_id):
        raise AppError("demo_data_already_seeded", status.HTTP_409_CONFLICT)

    now = datetime.now(timezone.utc)
    suffix = secrets.token_hex(3)

    vacancy = Vacancy(
        tenant_id=tenant_id,
        title=DEMO_VACANCY_TITLE,
        description="Demo vacancy for onboarding (auto-cleanup after 14 days).",
        status="published",
        owner_id=user_id,
        language="en",
        tasks_main={"demo": True, "suffix": suffix},
    )
    db.add(vacancy)
    await db.flush()

    profile = VacancyProfile(
        tenant_id=tenant_id,
        vacancy_id=vacancy.id,
        profile_data={
            "competences": [
                {"id": "python-core", "name": "Python core", "must_have": True},
                {"id": "system-design", "name": "System design", "must_have": False},
            ]
        },
        version=1,
        language="en",
        generated_by="demo",
    )
    db.add(profile)

    candidate_rows: list[Candidate] = []
    cv_rows: list[CandidateVacancy] = []
    for first, last, _stage_hint, email in DEMO_CANDIDATES:
        person = Person(
            first_name=first,
            last_name=last,
            email=f"{first.lower()}.{suffix}@demo.local",
        )
        db.add(person)
        await db.flush()
        candidate = Candidate(
            tenant_id=tenant_id,
            person_id=person.id,
            full_name=f"{first} {last}",
            email=person.email,
            source="demo",
            notes="Demo candidate (auto-cleanup after 14 days).",
        )
        db.add(candidate)
        await db.flush()
        candidate_rows.append(candidate)

        cv = CandidateVacancy(
            tenant_id=tenant_id,
            candidate_id=candidate.id,
            vacancy_id=vacancy.id,
            status="new",
            status_history=[],
            attached_by=user_id,
        )
        db.add(cv)
        await db.flush()
        cv_rows.append(cv)
        # Keep the candidate-side email aware that this is demo.
        _ = email

    # Interview with preset transcript on the second candidate.
    interview = Interview(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv_rows[1].id,
        interviewer_id=user_id,
        interview_date=now - timedelta(days=1),
        transcript=DEMO_TRANSCRIPT,
        status="completed",
        transcription_status="completed",
        analysis_status="completed",
        analysis_data=DEMO_AI_ANALYSIS,
        notes="Demo interview",
    )
    db.add(interview)

    state = _coerce_state(tenant.recruitment_onboarding) or _initial_state()
    state["demo_seeded_at"] = now.isoformat()
    state["step"] = "report_reviewed"
    tenant.recruitment_onboarding = state

    await db.commit()

    return {
        "vacancy_id": vacancy.id,
        "candidate_ids": [c.id for c in candidate_rows],
        "interview_id": interview.id,
        "demo_seeded_at": now,
    }


async def cleanup_demo(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Remove all rows produced by :func:`seed_demo` for a tenant."""
    candidates = (
        await db.execute(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id, Candidate.source == "demo"
            )
        )
    ).scalars().all()

    removed = {"candidates": 0, "vacancies": 0}
    vacancy_ids: set[uuid.UUID] = set()
    for candidate in candidates:
        for cv in (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.candidate_id == candidate.id
                )
            )
        ).scalars().all():
            vacancy_ids.add(cv.vacancy_id)
            await db.delete(cv)
        await db.delete(candidate)
        removed["candidates"] += 1

    # Delete demo vacancies (and only demo vacancies — recognised by the
    # demo title or the ``tasks_main.demo`` flag).
    for vac_id in vacancy_ids:
        vac = (
            await db.execute(select(Vacancy).where(Vacancy.id == vac_id))
        ).scalar_one_or_none()
        if vac is None:
            continue
        demo_flag = isinstance(vac.tasks_main, dict) and vac.tasks_main.get(
            "demo"
        )
        if vac.title == DEMO_VACANCY_TITLE or demo_flag:
            await db.delete(vac)
            removed["vacancies"] += 1

    tenant = await _get_tenant(db, tenant_id)
    state = _coerce_state(tenant.recruitment_onboarding) or _initial_state()
    state["demo_seeded_at"] = None
    tenant.recruitment_onboarding = state

    await db.commit()
    return removed
