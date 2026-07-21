"""AI generation tasks: candidate questions and vacancy profile.

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.modules.recruitment.tasks.generate_questions_task",
)
def generate_questions_task(
    self, candidate_id: str, vacancy_id: str, tenant_id: str
) -> dict:
    """Generate individual interview questions for a candidate.

    Steps:
    1. Fetch candidate's latest parsed resume
    2. Fetch vacancy profile (competences)
    3. Call generate_individual_questions() via LLM
    4. Save results to candidate_questions table
    """
    import asyncio
    import uuid

    from sqlalchemy import create_engine, delete, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.recruitment.models import (
        Candidate,
        CandidateFile,
        CandidateQuestion,
        Vacancy,
        VacancyProfile,
    )

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)

    try:
        with Session(engine) as db:
            candidate = db.get(Candidate, uuid.UUID(candidate_id))
            if not candidate:
                logger.error("Candidate %s not found", candidate_id)
                return {"status": "error", "error": "Candidate not found"}

            vacancy = db.get(Vacancy, uuid.UUID(vacancy_id))
            if not vacancy:
                logger.error("Vacancy %s not found", vacancy_id)
                return {"status": "error", "error": "Vacancy not found"}

            # Get latest parsed resume
            resume = db.execute(
                select(CandidateFile)
                .where(
                    CandidateFile.candidate_id == candidate.id,
                    CandidateFile.parse_status == "completed",
                )
                .order_by(CandidateFile.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if not resume or not resume.parsed_data:
                logger.error("No parsed resume for candidate %s", candidate_id)
                return {"status": "error", "error": "No parsed resume found"}

            # Get vacancy profile
            profile = db.execute(
                select(VacancyProfile).where(VacancyProfile.vacancy_id == vacancy.id)
            ).scalar_one_or_none()

            if not profile or not profile.profile_data:
                logger.error("No profile for vacancy %s", vacancy_id)
                return {"status": "error", "error": "No vacancy profile found"}

            # Generate questions via LLM
            from app.modules.recruitment.ai_service import (
                generate_individual_questions,
            )

            questions = asyncio.run(
                generate_individual_questions(
                    resume_data=resume.parsed_data,
                    profile_data=profile.profile_data,
                    vacancy_title=vacancy.title,
                    language=vacancy.language or "en",
                )
            )

            # Delete existing AI-generated questions for this candidate+vacancy
            db.execute(
                delete(CandidateQuestion).where(
                    CandidateQuestion.candidate_id == candidate.id,
                    CandidateQuestion.vacancy_id == vacancy.id,
                    CandidateQuestion.tenant_id == uuid.UUID(tenant_id),
                )
            )

            # Build a name → competence_id map from the vacancy profile so
            # we can attach each question to a real (normalized) competence.
            from app.modules.recruitment.common import normalize_competence_id

            comp_by_name: dict[str, uuid.UUID] = {}
            for c in (profile.profile_data or {}).get("competences", []) or []:
                if isinstance(c, dict):
                    name = (c.get("name") or "").strip().lower()
                    cid = normalize_competence_id(c.get("id") or c.get("name"))
                    if name and cid is not None:
                        comp_by_name[name] = cid

            # Save new questions
            for idx, q in enumerate(questions):
                comp_name = (q.get("competence_name") or "").strip().lower()
                cq = CandidateQuestion(
                    tenant_id=uuid.UUID(tenant_id),
                    candidate_id=candidate.id,
                    vacancy_id=vacancy.id,
                    competence_id=comp_by_name.get(comp_name),
                    question_text=q.get("question_text", ""),
                    good_answer=q.get("good_answer", ""),
                    acceptable_answer=q.get("acceptable_answer", ""),
                    poor_answer=q.get("poor_answer", ""),
                    resume_fragment=q.get("resume_fragment"),
                    sort_order=idx,
                    purpose=q.get("question_purpose", "clarification"),
                    priority=q.get("priority", "should"),
                )
                db.add(cq)

            db.commit()
            logger.info(
                "Generated %d questions for candidate %s on vacancy %s",
                len(questions),
                candidate_id,
                vacancy_id,
            )
            return {
                "status": "completed",
                "candidate_id": candidate_id,
                "vacancy_id": vacancy_id,
                "questions_count": len(questions),
            }

    except Exception as exc:
        logger.exception(
            "generate_questions_task failed for candidate %s", candidate_id
        )
        raise self.retry(exc=exc)
    finally:
        engine.dispose()


@celery.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.modules.recruitment.tasks.generate_profile_task",
)
def generate_profile_task(self, vacancy_id: str, tenant_id: str) -> dict:
    """Generate competency profile for a vacancy via LLM.

    Steps:
    1. Fetch Vacancy from DB
    2. Build vacancy data dict
    3. Call generate_vacancy_profile() via LLM
    4. Create/update VacancyProfile record (increment version if existing)
    """
    import asyncio
    import json
    import uuid

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.recruitment.models import Vacancy, VacancyProfile

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)

    try:
        with Session(engine) as db:
            vacancy = db.get(Vacancy, uuid.UUID(vacancy_id))
            if not vacancy:
                logger.error("Vacancy %s not found", vacancy_id)
                return {"status": "error", "error": "Vacancy not found"}

            vacancy_data = {
                "vacancy_id": str(vacancy.id),
                "title": vacancy.title,
                "specialization": "",
                "grade": "",
                "description": vacancy.description or "",
                "tasks_main": (
                    json.dumps(vacancy.tasks_main) if vacancy.tasks_main else ""
                ),
                "tasks_additional": (
                    json.dumps(vacancy.tasks_additional)
                    if vacancy.tasks_additional
                    else ""
                ),
                "tasks_kpi": json.dumps(vacancy.tasks_kpi) if vacancy.tasks_kpi else "",
                "language": vacancy.language or "en",
            }

            from app.modules.recruitment.ai_service import generate_vacancy_profile

            profile_data = asyncio.run(generate_vacancy_profile(vacancy_data))

            # Normalize each competence id to a stable UUID so canvas/score
            # writes can reference it via uuid columns without an FK on the
            # curated competence library (see migration r2c1d2e3f4a5).
            from app.modules.recruitment.common import normalize_competence_id

            for c in profile_data.get("competences", []) or []:
                if isinstance(c, dict):
                    raw = c.get("id") or c.get("name") or ""
                    normalized = normalize_competence_id(raw)
                    if normalized is not None:
                        c["id"] = str(normalized)

            # Check for existing profile
            existing = db.execute(
                select(VacancyProfile).where(VacancyProfile.vacancy_id == vacancy.id)
            ).scalar_one_or_none()

            if existing:
                existing.profile_data = profile_data
                existing.version = existing.version + 1
                existing.generated_by = "ai"
                if profile_data.get("coverage_note"):
                    existing.coverage_note = profile_data["coverage_note"]
            else:
                new_profile = VacancyProfile(
                    vacancy_id=vacancy.id,
                    tenant_id=vacancy.tenant_id,
                    profile_data=profile_data,
                    version=1,
                    language=vacancy.language or "en",
                    coverage_note=profile_data.get("coverage_note"),
                    generated_by="ai",
                )
                db.add(new_profile)

            db.commit()
            logger.info("Profile generated for vacancy %s", vacancy_id)
            return {"status": "completed", "vacancy_id": vacancy_id}

    except Exception as exc:
        logger.exception("generate_profile_task failed for %s", vacancy_id)
        raise self.retry(exc=exc)
    finally:
        engine.dispose()
