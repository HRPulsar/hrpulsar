"""GDPR erasure scope and completeness, retention sweep.

HRP-977: erasure in one tenant leaves other tenants and user accounts alone.
HRP-978: after erasure the candidate's name, email, phone and AI texts are in
no table and no storage key; expired export files are deleted.
HRP-983: retention settings erase what is past its window, nothing else, and
never touch the recruitment audit log.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.core.errors import AppError
from app.models import Person
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.notification.models import (
    EmailLog,
    Notification,
    NotificationTemplate,
)
from app.modules.recruitment import gdpr_service, service
from app.modules.recruitment.analysis_cache_service import (
    compute_cache_key_for_interview,
)
from app.modules.recruitment.manager_assessment_models import (
    AssessmentCompetenceScore,
    AssessmentRound,
    RecruitmentAssessment,
)
from app.modules.recruitment.models import (
    AIAnalysisRun,
    AIAssessment,
    AssessmentInvite,
    Candidate,
    CandidateFile,
    CandidateQuestion,
    CandidateVacancy,
    ConsentRequest,
    ConsentTemplate,
    ConsolidatedReport,
    GDPRErasureLog,
    GDPRExportRequest,
    GDPRPendingBlobDelete,
    HumanAssessment,
    Interview,
    InterviewAnalysisCache,
    InterviewSegment,
    Question,
    QuestionSet,
    RecruitmentAuditLog,
    RecruitmentRetentionConfig,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateManualCreate,
    CandidateVacancyCreate,
    InterviewCreate,
    VacancyCreate,
)
from app.modules.storage.models import File
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def fake_s3(monkeypatch) -> set[str]:
    """Object keys "in the bucket"; deletes remove them."""
    bucket: set[str] = set()
    monkeypatch.setattr(settings, "s3_endpoint", "http://fake-s3")
    monkeypatch.setattr(
        gdpr_service, "s3_delete_file", lambda key: bucket.discard(key) or True
    )
    return bucket


async def _other_tenant(db: AsyncSession) -> Tenant:
    t = Tenant(name=f"Other {uuid.uuid4().hex[:6]}", slug=f"o-{uuid.uuid4().hex[:8]}")
    db.add(t)
    await db.commit()
    return t


async def _candidate(db, tenant_id, user_id, email, first="Anna", last="Shared"):
    created = await service.create_candidate(
        db,
        tenant_id,
        user_id,
        CandidateCreate(first_name=first, last_name=last, email=email, phone="+100"),
    )
    return await db.get(Candidate, uuid.UUID(str(created["id"])))


async def _stored_file(db, tenant_id, bucket: set[str], name: str, by) -> File:
    path = f"{tenant_id}/{name}/{uuid.uuid4().hex}"
    row = File(
        tenant_id=tenant_id,
        name=name,
        original_name=name,
        path=path,
        size=1,
        mime_type="application/octet-stream",
        uploaded_by=by,
    )
    db.add(row)
    await db.flush()
    bucket.add(path)
    return row


async def _tables_containing(db: AsyncSession, needle: str) -> list[str]:
    """Every table with a row whose text form contains ``needle``."""
    tables = (
        await db.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
    ).scalars()
    hits = []
    for table in tables:
        found = await db.scalar(
            text(f'SELECT count(*) FROM "{table}" t WHERE t::text ILIKE :p'),
            {"p": f"%{needle}%"},
        )
        if found:
            hits.append(table)
    return hits


class TestErasureScope:
    """HRP-977."""

    async def test_shared_person_of_other_tenant_untouched(
        self, db: AsyncSession, tenant, user
    ) -> None:
        other = await _other_tenant(db)
        email = f"shared-{uuid.uuid4().hex[:8]}@example.com"
        mine = await _candidate(db, tenant.id, user.id, email)
        theirs = await _candidate(db, other.id, user.id, email)
        person_id = mine.person_id
        assert theirs.person_id == person_id

        log = await gdpr_service.gdpr_erase(db, tenant.id, user.id, mine.id)

        assert log.affected["person_unlinked"] == 1
        person = await db.get(Person, person_id, populate_existing=True)
        assert (person.first_name, person.last_name) == ("Anna", "Shared")
        assert person.email == email
        assert person.phone == "+100"
        theirs = await db.get(Candidate, theirs.id, populate_existing=True)
        assert theirs.person_id == person_id
        assert theirs.full_name == "Anna Shared"
        assert theirs.email == email
        mine = await db.get(Candidate, mine.id, populate_existing=True)
        assert mine.person_id is None
        assert mine.full_name == "redacted"

    async def test_person_of_a_user_account_untouched(
        self, db: AsyncSession, tenant, user
    ) -> None:
        person = Person(first_name="Uma", last_name="Account", email=f"u-{user.email}")
        db.add(person)
        await db.flush()
        account = await db.get(User, user.id, populate_existing=True)
        account.person_id = person.id
        await db.commit()
        candidate = await _candidate(db, tenant.id, user.id, person.email)
        assert candidate.person_id == person.id

        await gdpr_service.gdpr_erase(db, tenant.id, user.id, candidate.id)

        account = await db.get(User, user.id, populate_existing=True)
        assert account.person_id == person.id
        assert (account.first_name, account.email) == ("Test", user.email)
        person = await db.get(Person, person.id, populate_existing=True)
        assert (person.first_name, person.last_name) == ("Uma", "Account")
        assert (
            await db.get(Candidate, candidate.id, populate_existing=True)
        ).person_id is None


class TestErasureCompleteness:
    """HRP-978: nothing of the candidate is left in any table or key."""

    async def test_no_pii_or_ai_text_left_anywhere(
        self, db: AsyncSession, tenant, user, fake_s3
    ) -> None:
        tok = uuid.uuid4().hex[:10]
        first, last = f"Zelda{tok}", f"Quist{tok}"
        name = f"{first} {last}"
        email = f"zq-{tok}@example.com"
        phone = f"+49 30 {int(tok, 16) % 10**9:09d}"
        ai_text = f"AIVERDICT{tok}"

        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title=f"Role {tok}")
        )
        vacancy_id = uuid.UUID(str(vacancy["id"]))
        created = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name=first,
                last_name=last,
                email=email,
                phone=phone,
                notes=f"{name} is great",
            ),
        )
        cand_id = uuid.UUID(str(created["id"]))
        cv_dict = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=cand_id, vacancy_id=vacancy_id),
        )
        cv_id = uuid.UUID(str(cv_dict["id"]))
        if (
            await db.scalar(
                select(VacancyProfile).where(VacancyProfile.vacancy_id == vacancy_id)
            )
        ) is None:
            db.add(
                VacancyProfile(
                    tenant_id=tenant.id, vacancy_id=vacancy_id, profile_data={}
                )
            )

        resume_file = await _stored_file(db, tenant.id, fake_s3, "resume", user.id)
        db.add(
            CandidateFile(
                tenant_id=tenant.id,
                candidate_id=cand_id,
                file_id=resume_file.id,
                file_type="resume",
                original_filename=f"{first}.pdf",
                mime_type="application/pdf",
                file_size=1,
                raw_text=f"{name} {email} {phone}",
                parsed_data={"name": name},
                parse_status="completed",
            )
        )
        cv = await db.get(CandidateVacancy, cv_id, populate_existing=True)
        cv.ai_verdict_summary = ai_text
        cv.ai_key_strength = ai_text
        cv.ai_key_risk = ai_text
        cv.ai_risk_mitigation = ai_text
        cv.status_history = [{"to_stage_id": None, "comment": f"{first} declined"}]
        db.add(
            AIAnalysisRun(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_id,
                mode="resume_only",
                status="completed",
                verdict_summary=ai_text,
                key_strength=ai_text,
                key_risk=ai_text,
                risk_mitigation=ai_text,
                analysis_data={"verdict_summary": ai_text},
            )
        )
        await db.commit()

        iv_dict = await service.create_interview(
            db, tenant.id, user.id, cv_id, InterviewCreate(title=f"Call {first}")
        )
        iv = await db.get(Interview, uuid.UUID(str(iv_dict["id"])))
        audio = await _stored_file(db, tenant.id, fake_s3, "audio", user.id)
        iv.audio_file_id = audio.id
        iv.file_s3_key = audio.path
        iv.transcript = f"[Candidate] I am {name}"
        iv.notes = f"{first} was late"
        iv.analysis_data = {"summary": ai_text}
        db.add(
            InterviewSegment(
                tenant_id=tenant.id,
                interview_id=iv.id,
                speaker="candidate",
                start_sec=0,
                end_sec=1,
                text=f"I am {name}",
            )
        )
        db.add(
            AIAssessment(
                tenant_id=tenant.id,
                interview_id=iv.id,
                competence_id=uuid.uuid4(),
                status="completed",
                reasoning=ai_text,
                citations=[{"quote": name}],
            )
        )
        await db.flush()
        cache_key = await compute_cache_key_for_interview(db, tenant.id, iv)
        assert cache_key is not None
        db.add(
            InterviewAnalysisCache(
                tenant_id=tenant.id,
                cache_key=cache_key,
                analysis_data={"summary": ai_text},
                assessments=[],
            )
        )
        db.add(
            HumanAssessment(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_id,
                competence_id=uuid.uuid4(),
                evaluator_name="Rev",
                score=3,
                comment=f"{first} knows SQL",
            )
        )
        rnd = AssessmentRound(
            tenant_id=tenant.id, candidate_vacancy_id=cv_id, type="final"
        )
        db.add(rnd)
        await db.flush()
        sheet = RecruitmentAssessment(
            tenant_id=tenant.id,
            round_id=rnd.id,
            evaluator_user_id=user.id,
            final_notes=f"Hire {name}",
        )
        db.add(sheet)
        await db.flush()
        db.add(
            AssessmentCompetenceScore(
                tenant_id=tenant.id,
                assessment_id=sheet.id,
                competence_id=uuid.uuid4(),
                score_value=3,
                comment=f"{first} is solid",
            )
        )
        db.add(
            AssessmentInvite(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_id,
                token=uuid.uuid4().hex,
                email="evaluator@example.com",
                expires_at=datetime.now(timezone.utc) + timedelta(days=3),
                personal_message=f"Please look at {name}",
            )
        )
        db.add(
            CandidateQuestion(
                tenant_id=tenant.id,
                candidate_id=cand_id,
                vacancy_id=vacancy_id,
                question_text=f"{first}, tell us about Acme",
                good_answer="x",
                acceptable_answer="x",
                poor_answer="x",
                resume_fragment=f"{name} worked at Acme",
            )
        )
        qset = QuestionSet(tenant_id=tenant.id, candidate_vacancy_id=cv_id, name="Set")
        db.add(qset)
        await db.flush()
        db.add(
            Question(
                tenant_id=tenant.id,
                question_set_id=qset.id,
                text=f"{first}, why Acme?",
                rationale=ai_text,
                resume_anchor_jsonb={"quote": name},
            )
        )
        template = ConsentTemplate(tenant_id=tenant.id, name="T", body="B")
        db.add(template)
        await db.flush()
        consent = ConsentRequest(
            tenant_id=tenant.id,
            candidate_id=cand_id,
            template_id=template.id,
            token=uuid.uuid4().hex,
            email=email,
            expires_at=datetime.now(timezone.utc) + timedelta(days=3),
            status="signed",
            signed_at=datetime.now(timezone.utc),
            signed_ip="203.0.113.9",
        )
        db.add(consent)
        report_file = await _stored_file(db, tenant.id, fake_s3, "report", user.id)
        db.add(
            ConsolidatedReport(
                tenant_id=tenant.id,
                vacancy_id=vacancy_id,
                file_id=report_file.id,
                report_data={"audience": "recruiter"},
                status="completed",
            )
        )
        export_file = await _stored_file(db, tenant.id, fake_s3, "export", user.id)
        db.add(
            GDPRExportRequest(
                tenant_id=tenant.id,
                subject_type="candidate",
                subject_id=cand_id,
                status="completed",
                file_id=export_file.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
        )
        await db.flush()
        db.add_all(
            [
                RecruitmentAuditLog(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    action="candidate.update",
                    entity_type="candidate",
                    entity_id=cand_id,
                    payload_diff={"email": email},
                ),
                RecruitmentAuditLog(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    action="vacancy.update",
                    entity_type="vacancy",
                    entity_id=vacancy_id,
                    payload_diff={"note": f"shortlisted {name}"},
                ),
                RecruitmentAuditLog(
                    tenant_id=tenant.id,
                    user_id=None,
                    action="consent.sign",
                    entity_type="consent",
                    entity_id=consent.id,
                    payload_diff={"signed_ip": "203.0.113.9"},
                    ip="203.0.113.9",
                ),
            ]
        )
        ntpl = NotificationTemplate(
            code=f"test.privacy.{tok}", subject_template="s", body_template="b"
        )
        db.add(ntpl)
        await db.flush()
        db.add(
            Notification(
                tenant_id=tenant.id,
                template_id=ntpl.id,
                recipient_id=user.id,
                context={"candidate_name": name, "candidate_id": str(cand_id)},
            )
        )
        db.add(
            EmailLog(
                tenant_id=tenant.id,
                recipient=email,
                subject=f"Consent request for {name}",
                template_code="recruitment.consent_request",
            )
        )
        await db.commit()
        candidate_keys = set(fake_s3)
        needles = (first, last, email, phone, ai_text, "203.0.113.9")
        for needle in needles:  # the scan below would pass on an empty seed
            assert await _tables_containing(db, needle), needle
        audit_before = await db.scalar(
            select(text("count(*)"))
            .select_from(RecruitmentAuditLog)
            .where(RecruitmentAuditLog.tenant_id == tenant.id)
        )

        log = await gdpr_service.gdpr_erase(db, tenant.id, user.id, cand_id)

        assert log.affected["reports"] == 1
        assert log.affected["export_files"] == 1
        assert log.affected["storage_files"] == 4
        assert not fake_s3 & candidate_keys
        # The events stay; only what they carried about the candidate goes.
        assert (
            await db.scalar(
                select(text("count(*)"))
                .select_from(RecruitmentAuditLog)
                .where(RecruitmentAuditLog.tenant_id == tenant.id)
            )
            == audit_before
        )
        for needle in needles:
            hits = await _tables_containing(db, needle)
            assert hits == [], f"{needle!r} still in {hits}"


class TestErasureLeavesOthersAlone:
    """Review 04.10: scrubbing by text hits the candidate and nobody else."""

    async def _logs(self, db, tenant, user, vacancy_id, texts: list[str]):
        tpl = NotificationTemplate(
            code=f"test.privacy.{uuid.uuid4().hex[:10]}",
            subject_template="s",
            body_template="b",
        )
        db.add(tpl)
        await db.flush()
        rows = []
        for text_ in texts:
            audit = RecruitmentAuditLog(
                tenant_id=tenant.id,
                user_id=user.id,
                action="vacancy.update",
                entity_type="vacancy",
                entity_id=vacancy_id,
                payload_diff={"note": text_},
            )
            note = Notification(
                tenant_id=tenant.id,
                template_id=tpl.id,
                recipient_id=user.id,
                context={"candidate_name": text_},
            )
            mail = EmailLog(
                tenant_id=tenant.id, recipient="hr@example.com", subject=text_
            )
            db.add_all([audit, note, mail])
            rows.append((audit, note, mail))
        await db.commit()
        return rows

    async def _texts(self, db, rows) -> list[tuple[str, str, str]]:
        out = []
        for audit, note, mail in rows:
            audit = await db.get(RecruitmentAuditLog, audit.id, populate_existing=True)
            note = await db.get(Notification, note.id, populate_existing=True)
            mail = await db.get(EmailLog, mail.id, populate_existing=True)
            out.append(
                (
                    audit.payload_diff["note"],
                    note.context["candidate_name"],
                    mail.subject,
                )
            )
        return out

    async def test_one_word_name_is_not_a_needle(
        self, db: AsyncSession, tenant, user
    ) -> None:
        tok = uuid.uuid4().hex[:8]
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="Scrub")
        )
        # ``_`` in the address: a raw ILIKE would read it as a wildcard.
        email = f"anna_{tok}@example.com"
        anna = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(full_name="Anna", email=email),
        )
        others = [
            "Joanna Smith joined",
            "Hannah moved to onsite",
            "Anna Karlsson was promoted",
            f"Reply from annaX{tok}@example.com",
        ]
        rows = await self._logs(
            db,
            tenant,
            user,
            uuid.UUID(str(vacancy["id"])),
            [*others, f"Mail {email} bounced"],
        )

        await gdpr_service.gdpr_erase(
            db, tenant.id, user.id, uuid.UUID(str(anna["id"]))
        )

        texts = await self._texts(db, rows)
        for original, after in zip(others, texts[:-1], strict=True):
            assert after == (original, original, original)
        assert texts[-1] == ("Mail [redacted] bounced",) * 3

    async def test_name_matches_whole_words_only(
        self, db: AsyncSession, tenant, user
    ) -> None:
        tok = uuid.uuid4().hex[:8]
        name = f"Lee {tok}"
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="Scrub")
        )
        cand = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            CandidateManualCreate(full_name=name, email=f"l-{tok}@example.com"),
        )
        rows = await self._logs(
            db,
            tenant,
            user,
            uuid.UUID(str(vacancy["id"])),
            [f"Shortlisted {name} today", f"Colee {tok}x is someone else"],
        )

        await gdpr_service.gdpr_erase(
            db, tenant.id, user.id, uuid.UUID(str(cand["id"]))
        )

        mine, theirs = await self._texts(db, rows)
        assert mine == ("Shortlisted [redacted] today",) * 3
        assert theirs == (f"Colee {tok}x is someone else",) * 3


class TestErasureMatchesEveryFormOfIt:
    """Re-review 04.10: quoted names, longer addresses, formatted phones."""

    async def _erase(self, db, tenant, user, data, texts):
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="Scrub")
        )
        cand = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], data
        )
        helper = TestErasureLeavesOthersAlone()
        rows = await helper._logs(
            db, tenant, user, uuid.UUID(str(vacancy["id"])), texts
        )
        await gdpr_service.gdpr_erase(
            db, tenant.id, user.id, uuid.UUID(str(cand["id"]))
        )
        return [t[0] for t in await helper._texts(db, rows)]

    async def test_a_name_with_quotes_is_found_in_json(
        self, db: AsyncSession, tenant, user
    ) -> None:
        tok = uuid.uuid4().hex[:8]
        name = f'John "Jack" Smith{tok}'
        texts = await self._erase(
            db,
            tenant,
            user,
            CandidateManualCreate(full_name=name, email=f"j-{tok}@example.com"),
            [f"Met {name} today"],
        )
        assert texts == ["Met [redacted] today"]

    async def test_a_longer_address_is_someone_else(
        self, db: AsyncSession, tenant, user
    ) -> None:
        tok = uuid.uuid4().hex[:8]
        email = f"anna_x{tok}@example.com"
        texts = await self._erase(
            db,
            tenant,
            user,
            CandidateManualCreate(full_name="Anna", email=email),
            [
                f"Mail {email} bounced.",
                f"Copy to {email}.au",
                f"Copy to joe.{email}",
            ],
        )
        assert texts == [
            "Mail [redacted] bounced.",
            f"Copy to {email}.au",
            f"Copy to joe.{email}",
        ]

    async def test_a_phone_is_found_without_its_formatting(
        self, db: AsyncSession, tenant, user
    ) -> None:
        digits = f"{uuid.uuid4().int % 10**7:07d}"
        formatted = f"+7 (999) {digits[:3]}-{digits[3:5]}-{digits[5:]}"
        texts = await self._erase(
            db,
            tenant,
            user,
            CandidateManualCreate(
                full_name="Phone Owner",
                email=f"p-{digits}@example.com",
                phone=formatted,
            ),
            [f"Called +7999{digits}", f"Called {formatted}"],
        )
        assert texts == ["Called +[redacted]", "Called [redacted]"]


class TestErasureStopsProcessing:
    """Review 05.10 (E3): an erasure withdraws consent and waits for the
    workers holding the candidate's data."""

    async def _consented(self, db, tenant, user):
        from app.modules.recruitment import consent_service

        cand = await _candidate(
            db, tenant.id, user.id, f"busy-{uuid.uuid4().hex[:8]}@example.com"
        )
        await consent_service._record_signed_consent(db, tenant.id, cand)
        await db.commit()
        return cand

    async def test_erasure_withdraws_consent(
        self, db: AsyncSession, tenant, user
    ) -> None:
        from app.modules.recruitment import consent_service

        cand = await self._consented(db, tenant, user)
        cand_id = cand.id
        assert await consent_service.has_active_consent(db, tenant.id, cand_id)

        await gdpr_service.gdpr_erase(db, tenant.id, user.id, cand_id)

        assert not await consent_service.has_active_consent(db, tenant.id, cand_id)

    @pytest.mark.parametrize(
        "field", ["transcription_status", "analysis_status", "run"]
    )
    async def test_refused_while_a_worker_runs(
        self, db: AsyncSession, tenant, user, field
    ) -> None:
        cand = await self._consented(db, tenant, user)
        cand_id = cand.id
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="Busy")
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=cand_id, vacancy_id=uuid.UUID(str(vacancy["id"]))
            ),
        )
        cv_id = uuid.UUID(str(cv["id"]))
        if field == "run":
            db.add(
                AIAnalysisRun(
                    tenant_id=tenant.id,
                    candidate_vacancy_id=cv_id,
                    mode="resume_only",
                    status="processing",
                )
            )
        else:
            db.add(
                Interview(
                    tenant_id=tenant.id,
                    candidate_vacancy_id=cv_id,
                    transcript="live words",
                    **{field: "processing"},
                )
            )
        await db.commit()

        with pytest.raises(AppError) as exc:
            await gdpr_service.gdpr_erase(db, tenant.id, user.id, cand_id)

        assert exc.value.code == "gdpr_erasure_in_progress"
        assert exc.value.status_code == 409
        await db.rollback()
        cand = await db.get(Candidate, cand_id, populate_existing=True)
        assert cand.full_name != "redacted"


async def test_erase_drops_stale_cache_rows_of_the_pair(
    db: AsyncSession, tenant, user
) -> None:
    """Review 05.10 (E5): a cache row keyed on an older transcript is not
    found by recomputing the key; the pair column finds it."""
    cand = await _candidate(
        db, tenant.id, user.id, f"cache-{uuid.uuid4().hex[:8]}@example.com"
    )
    cand_id = cand.id
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title="Cache")
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=cand_id, vacancy_id=uuid.UUID(str(vacancy["id"]))
        ),
    )
    stale = InterviewAnalysisCache(
        tenant_id=tenant.id,
        cache_key=uuid.uuid4().hex,
        candidate_vacancy_id=uuid.UUID(str(cv["id"])),
        analysis_data={"verdict_summary": "old verdict"},
        assessments=[],
    )
    db.add(stale)
    await db.commit()
    stale_id = stale.id

    await gdpr_service.gdpr_erase(db, tenant.id, user.id, cand_id)

    assert (
        await db.get(InterviewAnalysisCache, stale_id, populate_existing=True) is None
    )


async def test_export_holds_everything_about_the_candidate(
    db: AsyncSession, tenant, user
) -> None:
    """Review 05.10 (E7): card fields, AI verdicts, evaluator sheets,
    stage comments and question sets are all in the export."""
    email = f"exp-{uuid.uuid4().hex[:8]}@example.com"
    cand = await _candidate(db, tenant.id, user.id, email)
    cand.linkedin_url = "https://linkedin.example/anna"
    cand.parsed_resume_jsonb = {"summary": "resume summary"}
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title="Export")
    )
    cv_dict = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=cand.id, vacancy_id=uuid.UUID(str(vacancy["id"]))
        ),
    )
    cv = await db.get(CandidateVacancy, uuid.UUID(str(cv_dict["id"])))
    cv.ai_verdict_summary = "card verdict"
    cv.status_history = [{"status": "screening", "comment": "stage comment"}]
    rnd = AssessmentRound(tenant_id=tenant.id, candidate_vacancy_id=cv.id, type="final")
    qset = QuestionSet(tenant_id=tenant.id, candidate_vacancy_id=cv.id, name="Set")
    db.add_all(
        [
            rnd,
            qset,
            AIAnalysisRun(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv.id,
                mode="resume_only",
                status="completed",
                verdict_summary="run verdict",
            ),
        ]
    )
    await db.flush()
    sheet = RecruitmentAssessment(
        tenant_id=tenant.id,
        round_id=rnd.id,
        evaluator_user_id=user.id,
        final_notes="sheet notes",
    )
    db.add_all(
        [
            sheet,
            Question(tenant_id=tenant.id, question_set_id=qset.id, text="set question"),
        ]
    )
    await db.flush()
    db.add(
        AssessmentCompetenceScore(
            tenant_id=tenant.id,
            assessment_id=sheet.id,
            competence_id=uuid.uuid4(),
            score_value=3,
            comment="score comment",
        )
    )
    await db.commit()

    payload = await gdpr_service._gather_candidate_payload(db, tenant.id, cand)

    card = payload["candidate"]
    assert (card["full_name"], card["email"], card["phone"]) == (
        cand.full_name,
        email,
        "+100",
    )
    assert card["linkedin_url"] == "https://linkedin.example/anna"
    assert card["parsed_resume"] == {"summary": "resume summary"}
    dumped = str(payload)
    for text_ in (
        "card verdict",
        "stage comment",
        "run verdict",
        "sheet notes",
        "score comment",
        "set question",
    ):
        assert text_ in dumped, text_


class TestStorageFailure:
    """A blob the storage refuses to delete is queued and retried, never
    reported as gone."""

    async def test_refused_delete_is_queued_and_retried(
        self, db: AsyncSession, tenant, user, fake_s3, monkeypatch
    ) -> None:
        cand = await _candidate(
            db, tenant.id, user.id, f"s3-{uuid.uuid4().hex[:8]}@example.com"
        )
        blob = await _stored_file(db, tenant.id, fake_s3, "resume", user.id)
        db.add(
            CandidateFile(
                tenant_id=tenant.id,
                candidate_id=cand.id,
                file_id=blob.id,
                file_type="resume",
                original_filename="cv.pdf",
                mime_type="application/pdf",
                file_size=1,
            )
        )
        await db.commit()
        key, cand_id = blob.path, cand.id
        monkeypatch.setattr(gdpr_service, "s3_delete_file", lambda _key: False)

        log = await gdpr_service.gdpr_erase(db, tenant.id, user.id, cand_id)

        assert log.affected["storage_files"] == 0
        assert log.affected["storage_pending"] == 1
        assert key in fake_s3
        pending = (
            (
                await db.execute(
                    select(GDPRPendingBlobDelete).where(
                        GDPRPendingBlobDelete.tenant_id == tenant.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [p.path for p in pending] == [key]

        # Storage still down: the key stays queued.
        await gdpr_service.apply_retention(db)
        row = await db.get(GDPRPendingBlobDelete, pending[0].id, populate_existing=True)
        assert row.attempts == 2

        monkeypatch.setattr(
            gdpr_service, "s3_delete_file", lambda k: fake_s3.discard(k) or True
        )
        totals = await gdpr_service.apply_retention(db)
        assert totals["pending_blobs_deleted"] >= 1
        assert key not in fake_s3
        assert await db.get(GDPRPendingBlobDelete, row.id) is None


class TestRetention:
    """HRP-983 + the export-file expiry of HRP-978."""

    async def _seed(self, db, tenant, user, fake_s3, age_days: int) -> dict:
        """One interview, resume, consent and report created ``age_days`` ago."""
        created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
        cand = await _candidate(
            db, tenant.id, user.id, f"ret-{uuid.uuid4().hex[:8]}@example.com"
        )
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="Retention")
        )
        vacancy_id = uuid.UUID(str(vacancy["id"]))
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=cand.id, vacancy_id=vacancy_id),
        )
        media = await _stored_file(db, tenant.id, fake_s3, "media", user.id)
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcript="old transcript",
            analysis_data={"summary": "verdict"},
            audio_file_id=media.id,
            created_at=created_at,
        )
        resume_blob = await _stored_file(db, tenant.id, fake_s3, "resume", user.id)
        resume = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=cand.id,
            file_id=resume_blob.id,
            file_type="resume",
            original_filename="cv.pdf",
            mime_type="application/pdf",
            file_size=1,
            raw_text="resume text",
            parsed_data={"summary": "x"},
            parse_status="completed",
            created_at=created_at,
        )
        template = ConsentTemplate(tenant_id=tenant.id, name="T", body="B")
        db.add_all([interview, resume, template])
        await db.flush()
        consent = ConsentRequest(
            tenant_id=tenant.id,
            candidate_id=cand.id,
            template_id=template.id,
            token=uuid.uuid4().hex,
            email=cand.email,
            expires_at=created_at,
            status="signed",
            signed_at=created_at,
            signed_ip="198.51.100.1",
            created_at=created_at,
        )
        report_blob = await _stored_file(db, tenant.id, fake_s3, "report", user.id)
        report = ConsolidatedReport(
            tenant_id=tenant.id,
            vacancy_id=vacancy_id,
            file_id=report_blob.id,
            status="completed",
            created_at=created_at,
        )
        db.add_all([consent, report])
        cand.parsed_resume_jsonb = {"summary": "x"}
        await db.commit()
        return {
            "candidate": cand.id,
            "interview": interview.id,
            "resume": resume.id,
            "consent": consent.id,
            "report": report.id,
            "keys": {media.path, resume_blob.path, report_blob.path},
        }

    async def _retention(self, db, tenant, days: int) -> None:
        cfg = await db.scalar(
            select(RecruitmentRetentionConfig).where(
                RecruitmentRetentionConfig.tenant_id == tenant.id
            )
        )
        if cfg is None:
            cfg = RecruitmentRetentionConfig(tenant_id=tenant.id)
            db.add(cfg)
        cfg.interviews_days = cfg.resumes_days = days
        cfg.consents_days = cfg.reports_days = days
        await db.commit()

    async def _assert_erased(self, db, seeded, fake_s3) -> None:
        iv = await db.get(Interview, seeded["interview"], populate_existing=True)
        assert iv.transcript == "[redacted]"
        assert iv.analysis_data == {"redacted": True}
        assert iv.audio_file_id is None
        resume = await db.get(CandidateFile, seeded["resume"], populate_existing=True)
        assert resume.raw_text is None and resume.file_id is None
        assert (
            await db.get(Candidate, seeded["candidate"], populate_existing=True)
        ).parsed_resume_jsonb is None
        consent = await db.get(
            ConsentRequest, seeded["consent"], populate_existing=True
        )
        assert consent.email.startswith("redacted-")
        assert consent.signed_ip is None
        assert consent.status == "signed"  # still proof of consent
        assert (
            await db.get(ConsolidatedReport, seeded["report"], populate_existing=True)
            is None
        )
        assert not fake_s3 & seeded["keys"]

    async def _assert_kept(self, db, seeded, fake_s3) -> None:
        assert (
            await db.get(Interview, seeded["interview"], populate_existing=True)
        ).transcript == "old transcript"
        assert (
            await db.get(CandidateFile, seeded["resume"], populate_existing=True)
        ).raw_text == "resume text"
        assert (
            await db.get(ConsentRequest, seeded["consent"], populate_existing=True)
        ).signed_ip
        assert (
            await db.get(ConsolidatedReport, seeded["report"], populate_existing=True)
            is not None
        )
        assert seeded["keys"] <= fake_s3

    async def test_due_erased_fresh_kept_audit_untouched(
        self, db: AsyncSession, tenant, user, fake_s3
    ) -> None:
        await self._retention(db, tenant, 30)
        old = await self._seed(db, tenant, user, fake_s3, age_days=40)
        fresh = await self._seed(db, tenant, user, fake_s3, age_days=5)
        audit_rows = (
            await db.execute(
                text(
                    "SELECT id, action, payload_diff::text, ip FROM recruitment_audit_log"
                    " WHERE tenant_id = :t ORDER BY id"
                ),
                {"t": tenant.id},
            )
        ).all()

        totals = await gdpr_service.apply_retention(db)

        assert totals["interviews"] >= 1
        await self._assert_erased(db, old, fake_s3)
        await self._assert_kept(db, fresh, fake_s3)
        log = await db.scalar(
            select(GDPRErasureLog).where(
                GDPRErasureLog.tenant_id == tenant.id,
                GDPRErasureLog.subject_type == "retention",
            )
        )
        assert log.affected["interviews"] == 1
        assert log.affected["reports"] == 1
        assert log.requested_by is None
        after = (
            await db.execute(
                text(
                    "SELECT id, action, payload_diff::text, ip FROM recruitment_audit_log"
                    " WHERE tenant_id = :t ORDER BY id"
                ),
                {"t": tenant.id},
            )
        ).all()
        assert after == audit_rows
        # A second run finds nothing left to erase.
        await gdpr_service.apply_retention(db)
        logs = (
            (
                await db.execute(
                    select(GDPRErasureLog).where(
                        GDPRErasureLog.tenant_id == tenant.id,
                        GDPRErasureLog.subject_type == "retention",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1

    @pytest.mark.parametrize("field", ["transcription_status", "analysis_status"])
    async def test_interview_in_flight_waits_for_the_next_night(
        self, db: AsyncSession, tenant, user, fake_s3, field
    ) -> None:
        await self._retention(db, tenant, 30)
        seeded = await self._seed(db, tenant, user, fake_s3, age_days=40)
        iv = await db.get(Interview, seeded["interview"])
        setattr(iv, field, "processing")
        await db.commit()

        await gdpr_service.apply_retention(db)
        iv = await db.get(Interview, seeded["interview"], populate_existing=True)
        assert iv.transcript == "old transcript"

        setattr(iv, field, "completed")
        await db.commit()
        await gdpr_service.apply_retention(db)
        iv = await db.get(Interview, seeded["interview"], populate_existing=True)
        assert iv.transcript == "[redacted]"

    async def test_changed_setting_applies_on_next_run(
        self, db: AsyncSession, tenant, user, fake_s3
    ) -> None:
        await self._retention(db, tenant, 60)
        seeded = await self._seed(db, tenant, user, fake_s3, age_days=40)
        await gdpr_service.apply_retention(db)
        await self._assert_kept(db, seeded, fake_s3)

        await self._retention(db, tenant, 30)
        await gdpr_service.apply_retention(db)
        await self._assert_erased(db, seeded, fake_s3)

    async def test_tenant_without_settings_untouched(
        self, db: AsyncSession, tenant, user, fake_s3
    ) -> None:
        seeded = await self._seed(db, tenant, user, fake_s3, age_days=4000)
        await gdpr_service.apply_retention(db)
        await self._assert_kept(db, seeded, fake_s3)

    async def test_last_resume_takes_its_derivatives_along(
        self, db: AsyncSession, tenant, user, fake_s3
    ) -> None:
        """Review 05.10 (E6)."""
        await self._retention(db, tenant, 30)
        seeded = await self._seed(db, tenant, user, fake_s3, age_days=40)
        cv = await db.scalar(
            select(CandidateVacancy).where(
                CandidateVacancy.candidate_id == seeded["candidate"]
            )
        )
        cv.ai_verdict_summary = "resume verdict"
        run = AIAnalysisRun(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv.id,
            mode="resume_only",
            status="completed",
            verdict_summary="resume verdict",
            analysis_data={"verdict_summary": "resume verdict"},
        )
        cq = CandidateQuestion(
            tenant_id=tenant.id,
            candidate_id=seeded["candidate"],
            vacancy_id=cv.vacancy_id,
            question_text="q",
            good_answer="x",
            acceptable_answer="x",
            poor_answer="x",
            resume_fragment="worked at Acme",
        )
        qset = QuestionSet(tenant_id=tenant.id, candidate_vacancy_id=cv.id, name="S")
        db.add_all([run, cq, qset])
        await db.flush()
        question = Question(
            tenant_id=tenant.id,
            question_set_id=qset.id,
            text="why Acme?",
            resume_anchor_jsonb={"quote": "Acme"},
        )
        db.add(question)
        await db.commit()
        ids = (cv.id, run.id, cq.id, question.id)

        await gdpr_service.apply_retention(db)

        cv = await db.get(CandidateVacancy, ids[0], populate_existing=True)
        assert cv.ai_verdict_summary is None
        run = await db.get(AIAnalysisRun, ids[1], populate_existing=True)
        assert run.verdict_summary is None
        assert run.analysis_data == {"redacted": True}
        cq = await db.get(CandidateQuestion, ids[2], populate_existing=True)
        assert cq.resume_fragment is None
        question = await db.get(Question, ids[3], populate_existing=True)
        assert question.resume_anchor_jsonb is None

    async def test_erases_in_batches_under_one_log_row(
        self, db: AsyncSession, tenant, user, fake_s3, monkeypatch
    ) -> None:
        """Review 05.10 (E10): a batch per transaction, one log row."""
        monkeypatch.setattr(gdpr_service, "_RETENTION_BATCH", 1)
        await self._retention(db, tenant, 30)
        seeded = [
            await self._seed(db, tenant, user, fake_s3, age_days=40) for _ in range(3)
        ]
        commits = 0
        real_commit = db.commit

        async def counting_commit():
            nonlocal commits
            commits += 1
            await real_commit()

        monkeypatch.setattr(db, "commit", counting_commit)

        await gdpr_service.apply_retention(db)

        for data in seeded:
            await self._assert_erased(db, data, fake_s3)
        assert commits >= 3
        logs = (
            (
                await db.execute(
                    select(GDPRErasureLog).where(
                        GDPRErasureLog.tenant_id == tenant.id,
                        GDPRErasureLog.subject_type == "retention",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        assert logs[0].affected["interviews"] == 3
        assert logs[0].affected["reports"] == 3

    async def test_failed_tenant_does_not_stall_the_rest(
        self, db: AsyncSession, tenant, user, fake_s3, monkeypatch
    ) -> None:
        other = await _other_tenant(db)
        seeded = {}
        for t in (tenant, other):
            await self._retention(db, t, 30)
            seeded[t.id] = await self._seed(db, t, user, fake_s3, age_days=40)
        blob = await _stored_file(db, tenant.id, fake_s3, "export", user.id)
        export = GDPRExportRequest(
            tenant_id=tenant.id,
            subject_type="candidate",
            subject_id=uuid.uuid4(),
            status="completed",
            file_id=blob.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add(export)
        await db.commit()
        blob_path = blob.path
        # The failed tenant's rollback expires every loaded object.
        ids = {tenant.id, other.id}

        real = gdpr_service._apply_tenant_retention
        calls: list[uuid.UUID] = []

        async def first_fails(db_, cfg, now):
            calls.append(cfg.tenant_id)
            if len(calls) == 1:
                await db_.flush()
                raise RuntimeError("boom")
            return await real(db_, cfg, now)

        monkeypatch.setattr(gdpr_service, "_apply_tenant_retention", first_fails)
        await gdpr_service.apply_retention(db)

        assert ids <= set(calls)
        for tenant_id, data in seeded.items():
            if tenant_id == calls[0]:
                await self._assert_kept(db, data, fake_s3)
            else:
                await self._assert_erased(db, data, fake_s3)
        assert blob_path not in fake_s3

    async def test_expired_export_file_deleted(
        self, db: AsyncSession, tenant, user, fake_s3
    ) -> None:
        now = datetime.now(timezone.utc)
        rows = []
        for expires_at in (now - timedelta(hours=1), now + timedelta(days=6)):
            blob = await _stored_file(db, tenant.id, fake_s3, "export", user.id)
            row = GDPRExportRequest(
                tenant_id=tenant.id,
                subject_type="candidate",
                subject_id=uuid.uuid4(),
                status="completed",
                file_id=blob.id,
                expires_at=expires_at,
            )
            db.add(row)
            rows.append((row, blob.id, blob.path))
        await db.commit()

        await gdpr_service.apply_retention(db)

        (expired, expired_file, expired_key), (live, live_file, live_key) = rows
        assert (
            await db.get(GDPRExportRequest, expired.id, populate_existing=True)
        ).file_id is None
        assert await db.get(File, expired_file, populate_existing=True) is None
        assert expired_key not in fake_s3
        assert (
            await db.get(GDPRExportRequest, live.id, populate_existing=True)
        ).file_id == live_file
        assert live_key in fake_s3


def test_retention_runs_daily_on_a_utc_crontab() -> None:
    from app.core.celery_app import celery
    from app.modules.recruitment.tasks import apply_recruitment_retention_task
    from celery.schedules import crontab

    entry = celery.conf.beat_schedule["apply-recruitment-retention"]
    assert isinstance(entry["schedule"], crontab)
    assert entry["task"] == apply_recruitment_retention_task.name


def test_retention_task_runs_the_sweep() -> None:
    from app.modules.recruitment.tasks import apply_recruitment_retention_task

    result = apply_recruitment_retention_task.run()
    assert result["status"] == "ok"
    assert "export_files" in result
