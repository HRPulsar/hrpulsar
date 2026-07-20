"""Unit tests for R4b GDPR export & soft erasure."""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import gdpr_service, service
from app.modules.recruitment.gdpr_service import _gather_candidate_payload
from app.modules.recruitment.models import (
    AIAssessment,
    CandidateFile,
    CandidateQuestion,
    GDPRErasureLog,
    HumanAssessment,
    Interview,
    InterviewSegment,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    InterviewCreate,
    VacancyCreate,
)
from app.modules.recruitment.settings_schemas import (
    GDPRExportRequestCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_candidate_with_data(
    db: AsyncSession, tenant, user, *, with_interview: bool = True
):
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title="GDPR PM")
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Anna",
            last_name="Karenina",
            email=f"anna-{uuid.uuid4().hex[:5]}@example.com",
            phone="+7 999 1234567",
            notes="Strong on systems design.",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(candidate["id"])),
            vacancy_id=uuid.UUID(str(vacancy["id"])),
        ),
    )

    # Resume row (raw_text + parsed_data). HRP-181 REDO: Resume → CandidateFile.
    resume = CandidateFile(
        tenant_id=tenant.id,
        candidate_id=uuid.UUID(str(candidate["id"])),
        file_type="resume",
        original_filename="cv.pdf",
        mime_type="application/pdf",
        file_size=1024,
        raw_text="Full CV text with PII",
        parsed_data={"summary": "Senior dev"},
        parse_status="completed",
    )
    db.add(resume)
    await db.commit()

    # Generated question for this candidate — fields contain free text
    # that must be redacted on erase.
    question = CandidateQuestion(
        tenant_id=tenant.id,
        candidate_id=uuid.UUID(str(candidate["id"])),
        vacancy_id=uuid.UUID(str(vacancy["id"])),
        question_text="Tell me about your last project.",
        good_answer="Mentioned tradeoffs at Acme Corp.",
        acceptable_answer="Listed stack used.",
        poor_answer="Could not describe.",
        purpose="probe leadership",
        priority="should",
    )
    db.add(question)
    await db.commit()

    if with_interview:
        iv_dict = await service.create_interview(
            db,
            tenant.id,
            user.id,
            uuid.UUID(str(cv["id"])),
            InterviewCreate(),
        )
        # Pre-fill transcript so the redaction test is meaningful.
        iv_obj = await db.get(Interview, uuid.UUID(str(iv_dict["id"])))
        iv_obj.transcript = "Original transcript with Anna Karenina PII"
        seg1 = InterviewSegment(
            tenant_id=tenant.id,
            interview_id=iv_obj.id,
            speaker="candidate",
            start_sec=0.0,
            end_sec=5.0,
            text="My name is Anna Karenina and I worked on…",
        )
        seg2 = InterviewSegment(
            tenant_id=tenant.id,
            interview_id=iv_obj.id,
            speaker="interviewer",
            start_sec=5.0,
            end_sec=10.0,
            text="Could you tell me about your experience?",
        )
        db.add_all([seg1, seg2])

        # Human + AI assessments capture the candidate's identity in
        # narrative form; gdpr_erase must redact both.
        ha = HumanAssessment(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            competence_id=uuid.uuid4(),
            evaluator_name="Reviewer Bob",
            score=4.0,
            comment="Anna spoke at length about her time at Acme.",
            version=1,
        )
        ai = AIAssessment(
            tenant_id=tenant.id,
            interview_id=iv_obj.id,
            competence_id=uuid.uuid4(),
            score=4.2,
            status="completed",
            reasoning="Candidate explicitly named Anna Karenina in segment 1.",
            citations=[{"segment_id": str(seg1.id), "quote": "My name is Anna"}],
        )
        db.add_all([ha, ai])
        await db.commit()

    return candidate


class TestGDPRExport:
    async def test_export_404_for_unknown_candidate(
        self, db: AsyncSession, tenant, user
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            await gdpr_service.gdpr_export(
                db,
                tenant.id,
                user.id,
                GDPRExportRequestCreate(candidate_id=uuid.uuid4()),
            )
        assert exc.value.status_code == 404

    async def test_export_payload_includes_all_entities(
        self, db: AsyncSession, tenant, user
    ) -> None:
        candidate = await _make_candidate_with_data(db, tenant, user)
        cand_obj = await db.get(
            __import__(
                "app.modules.recruitment.models", fromlist=["Candidate"]
            ).Candidate,
            uuid.UUID(str(candidate["id"])),
        )
        payload = await _gather_candidate_payload(db, tenant.id, cand_obj)
        assert payload["candidate"]["id"] == str(cand_obj.id)
        assert len(payload["resumes"]) == 1
        assert payload["resumes"][0]["raw_text"] == "Full CV text with PII"
        assert len(payload["candidate_vacancies"]) == 1
        assert len(payload["interviews"]) == 1
        assert len(payload["interview_segments"]) == 2

    async def test_export_dispatches_and_persists_processing_row(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        # Review #44: export is now offloaded to Celery — the request row
        # comes back ``processing`` and the worker task is dispatched.
        candidate = await _make_candidate_with_data(
            db, tenant, user, with_interview=False
        )
        from app.modules.recruitment import tasks as rec_tasks

        dispatched: list[str] = []
        monkeypatch.setattr(
            rec_tasks.run_gdpr_export_task,
            "delay",
            lambda request_id: dispatched.append(request_id),
        )
        req = await gdpr_service.gdpr_export(
            db,
            tenant.id,
            user.id,
            GDPRExportRequestCreate(
                candidate_id=uuid.UUID(str(candidate["id"]))
            ),
        )
        assert req.status == "processing"
        assert req.subject_id == uuid.UUID(str(candidate["id"]))
        assert dispatched == [str(req.id)]

    async def test_perform_export_completes_processing_row(
        self, db: AsyncSession, tenant, user
    ) -> None:
        # The worker body flips the row to completed. S3 disabled in tests →
        # file_id stays None, status still completed.
        from app.modules.recruitment.models import GDPRExportRequest

        candidate = await _make_candidate_with_data(
            db, tenant, user, with_interview=False
        )
        row = GDPRExportRequest(
            tenant_id=tenant.id,
            requested_by=user.id,
            subject_type="candidate",
            subject_id=uuid.UUID(str(candidate["id"])),
            status="processing",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        result = await gdpr_service._perform_gdpr_export(db, row.id)
        assert result["status"] == "completed"
        await db.refresh(row)
        assert row.status == "completed"
        assert row.file_id is None


class TestGDPRErase:
    async def test_soft_erases_pii(
        self, db: AsyncSession, tenant, user
    ) -> None:
        candidate = await _make_candidate_with_data(db, tenant, user)
        cand_id = uuid.UUID(str(candidate["id"]))

        log_row = await gdpr_service.gdpr_erase(
            db, tenant.id, user.id, cand_id
        )
        assert isinstance(log_row, GDPRErasureLog)
        assert log_row.affected["interview_segments"] == 2
        assert log_row.affected["human_assessments"] == 1
        assert log_row.affected["ai_assessments"] == 1
        assert log_row.affected["questions"] == 1
        # HRP-181 REDO: gdpr_erase now blanks the denormalised Candidate
        # columns + the row notes as a single ``candidate`` entry and reports
        # ``storage_files`` for the dropped S3 blobs (zero when there are no
        # File rows under the resumes).
        assert log_row.affected["candidate"] == 1
        assert "storage_files" in log_row.affected

        # Person redacted in place.
        from app.models import Person
        from app.modules.recruitment.models import Candidate

        cand = await db.get(Candidate, cand_id)
        person = await db.get(Person, cand.person_id)
        assert person.first_name == "redacted"
        assert person.last_name == "redacted"
        assert person.email.endswith("@local")
        assert person.phone is None
        # Free-form notes on the candidate row are cleared.
        assert cand.notes is None

        # Resume cleared but row preserved. HRP-181 REDO: Resume → CandidateFile.
        resumes = (
            await db.execute(
                select(CandidateFile).where(
                    CandidateFile.candidate_id == cand_id,
                    CandidateFile.file_type == "resume",
                )
            )
        ).scalars().all()
        assert resumes
        for r in resumes:
            assert r.raw_text is None
            assert r.parsed_data == {"redacted": True}

        # Interview transcript & segments redacted (this tenant only).
        ivs = (
            await db.execute(
                select(Interview).where(Interview.tenant_id == tenant.id)
            )
        ).scalars().all()
        assert ivs
        for iv in ivs:
            assert iv.transcript == "[redacted]"

        segs = (
            await db.execute(
                select(InterviewSegment).where(
                    InterviewSegment.tenant_id == tenant.id
                )
            )
        ).scalars().all()
        assert segs
        for seg in segs:
            assert seg.text == "[redacted]"

        # HumanAssessment.comment redacted.
        has = (
            await db.execute(
                select(HumanAssessment).where(
                    HumanAssessment.tenant_id == tenant.id
                )
            )
        ).scalars().all()
        assert has
        for ha in has:
            assert ha.comment == "[redacted]"

        # AIAssessment.reasoning + citations redacted.
        ais = (
            await db.execute(
                select(AIAssessment).where(AIAssessment.tenant_id == tenant.id)
            )
        ).scalars().all()
        assert ais
        for ai in ais:
            assert ai.reasoning == "[redacted]"
            assert ai.citations == []

        # CandidateQuestion fields redacted.
        qs = (
            await db.execute(
                select(CandidateQuestion).where(
                    CandidateQuestion.candidate_id == cand_id
                )
            )
        ).scalars().all()
        assert qs
        for q in qs:
            assert q.good_answer == "[redacted]"
            assert q.acceptable_answer == "[redacted]"
            assert q.poor_answer == "[redacted]"
            assert q.purpose == "redacted"

    async def test_404_for_other_tenant(
        self, db: AsyncSession, tenant, user
    ) -> None:
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        candidate = await _make_candidate_with_data(
            db, tenant, user, with_interview=False
        )
        with pytest.raises(HTTPException) as exc:
            await gdpr_service.gdpr_erase(
                db,
                other.id,
                user.id,
                uuid.UUID(str(candidate["id"])),
            )
        assert exc.value.status_code == 404
