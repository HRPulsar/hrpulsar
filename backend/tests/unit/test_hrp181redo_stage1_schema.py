"""HRP-181 REDO Stage 1 — canonical candidate schema.

Covers the database-level invariants introduced by
``hrp181redo01_candidates_canonical`` and ``hrp181redo02_seed_default_stages``:

- ``Candidate`` accepts ``person_id = NULL`` (external candidates).
- Partial unique index on ``(tenant_id, lower(email))`` rejects active
  duplicates but tolerates an archived twin so the same address can be
  re-imported once the previous row is soft-deleted.
- ``CandidateVacancy`` lands with the spec-mandated AI defaults
  (``ai_readiness='none'``, ``ai_verdict='pending'``, ``version=1``)
  and a sensible ``added_at``.
- ``CandidateFile`` renames ``resumes`` and tags new rows with
  ``file_type='resume'`` by default.
- ``seed_default_recruitment_stages`` seeds the 9 spec stages exactly
  once per tenant and is safely re-runnable.
- ``auth.service.register`` invokes the seed hook so new tenants get
  the funnel out of the box.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import register
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
    CandidateVacancy,
    Vacancy,
    VacancyStage,
)
from app.modules.recruitment.vacancy_service import (
    DEFAULT_RECRUITMENT_STAGES,
    seed_default_recruitment_stages,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestCandidateSchema:
    async def test_candidate_allows_null_person(
        self, db: AsyncSession, tenant
    ) -> None:
        c = Candidate(
            tenant_id=tenant.id,
            person_id=None,
            full_name="External Resume Lead",
            email="lead@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        assert c.id is not None
        assert c.person_id is None
        assert c.email == "lead@example.com"

    async def test_partial_email_index_rejects_active_duplicate(
        self, db: AsyncSession, tenant
    ) -> None:
        db.add(
            Candidate(
                tenant_id=tenant.id,
                full_name="Anna Smirnova",
                email="anna@example.com",
            )
        )
        await db.commit()

        db.add(
            Candidate(
                tenant_id=tenant.id,
                full_name="Anna Smirnova (duplicate)",
                email="ANNA@example.com",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_partial_email_index_allows_archived_twin(
        self, db: AsyncSession, tenant
    ) -> None:
        from datetime import datetime, timezone

        archived = Candidate(
            tenant_id=tenant.id,
            full_name="Old Anna",
            email="anna@example.com",
            archived_at=datetime.now(timezone.utc),
        )
        db.add(archived)
        await db.commit()

        fresh = Candidate(
            tenant_id=tenant.id,
            full_name="New Anna",
            email="anna@example.com",
        )
        db.add(fresh)
        await db.commit()
        assert fresh.id != archived.id


@pytest.mark.asyncio
class TestCandidateVacancyDefaults:
    async def test_ai_defaults_and_version(
        self, db: AsyncSession, tenant, user
    ) -> None:
        candidate = Candidate(
            tenant_id=tenant.id, full_name="X", email="x@example.com"
        )
        vacancy = Vacancy(tenant_id=tenant.id, title="Backend")
        db.add_all([candidate, vacancy])
        await db.flush()

        cv = CandidateVacancy(
            tenant_id=tenant.id,
            candidate_id=candidate.id,
            vacancy_id=vacancy.id,
        )
        db.add(cv)
        await db.commit()
        await db.refresh(cv)

        assert cv.ai_readiness == "none"
        assert cv.ai_verdict == "pending"
        assert cv.ai_score is None
        assert cv.version == 1
        assert cv.added_at is not None


@pytest.mark.asyncio
class TestCandidateFile:
    async def test_candidate_file_has_canonical_tablename(self) -> None:
        assert CandidateFile.__tablename__ == "candidate_files"

    async def test_file_type_defaults_to_resume(
        self, db: AsyncSession, tenant
    ) -> None:
        candidate = Candidate(
            tenant_id=tenant.id, full_name="Y", email="y@example.com"
        )
        db.add(candidate)
        await db.flush()

        f = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=candidate.id,
            original_filename="resume.pdf",
            mime_type="application/pdf",
            file_size=1024,
        )
        db.add(f)
        await db.commit()
        await db.refresh(f)
        assert f.file_type == "resume"


@pytest.mark.asyncio
class TestDefaultStagesSeed:
    async def test_seed_creates_nine_stages_per_tenant(
        self, db: AsyncSession, tenant
    ) -> None:
        # Existing rows from the migration may already cover this tenant
        # if the test DB was migrated. Strip them to assert seed behaviour.
        await db.execute(
            VacancyStage.__table__.delete().where(
                VacancyStage.tenant_id == tenant.id,
                VacancyStage.vacancy_id.is_(None),
            )
        )
        await db.commit()

        inserted = await seed_default_recruitment_stages(db, tenant.id)
        await db.commit()
        assert inserted == 9

        result = await db.execute(
            select(VacancyStage)
            .where(
                VacancyStage.tenant_id == tenant.id,
                VacancyStage.vacancy_id.is_(None),
            )
            .order_by(VacancyStage.sort_order)
        )
        rows = list(result.scalars().all())
        assert [r.code for r in rows] == [s[0] for s in DEFAULT_RECRUITMENT_STAGES]
        assert [r.stage_type for r in rows] == [
            s[3] for s in DEFAULT_RECRUITMENT_STAGES
        ]
        terminal = [r for r in rows if r.stage_type != "active"]
        assert {r.code for r in terminal} == {"hired", "rejected", "withdrew"}

    async def test_seed_is_idempotent(
        self, db: AsyncSession, tenant
    ) -> None:
        await seed_default_recruitment_stages(db, tenant.id)
        await db.commit()
        second = await seed_default_recruitment_stages(db, tenant.id)
        await db.commit()
        assert second == 0


@pytest.mark.asyncio
class TestRegisterTenantSeedsStages:
    async def test_register_seeds_default_funnel(
        self, db: AsyncSession, monkeypatch
    ) -> None:
        # Suppress the verification email side-effect — we're testing
        # the seed hook, not delivery.
        monkeypatch.setattr(
            "app.modules.auth.service.send_verification_email", lambda *a, **k: None
        )

        slug_hint = uuid.uuid4().hex[:8]
        await register(
            db,
            RegisterRequest(
                company_name=f"Acme {slug_hint}",
                email=f"founder-{slug_hint}@example.com",
                password="VeryStrong123!",
                first_name="F",
                last_name="L",
            ),
        )

        from app.modules.company.models import Tenant

        tenant_row = await db.execute(
            select(Tenant).where(Tenant.slug.like(f"acme-{slug_hint.lower()}%"))
        )
        new_tenant = tenant_row.scalar_one()

        count = await db.execute(
            select(func.count())
            .select_from(VacancyStage)
            .where(
                VacancyStage.tenant_id == new_tenant.id,
                VacancyStage.vacancy_id.is_(None),
            )
        )
        assert count.scalar_one() == 9
