"""HRP-982: the recruitment audit trail names who did it.

* a stage move writes ``changed_by`` into ``status_history`` and an audit
  row with the user and the stage before / after;
* the stage-change notification names the mover, not ``attached_by``;
* the AI entry points name their caller ``actor_user_id`` /
  ``current_user_id`` - the audit wrapper reads those too;
* the worker's upload -> transcribe -> analyze chain runs without a request
  user and is attributed to whoever uploaded the media;
* the worker installs the audit wrappers;
* an AI analysis never moves the candidate.
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.recruitment import (
    audit_registry,
    audit_service,
    interview_service,
    service,
    vacancy_service,
)
from app.modules.recruitment.models import (
    CandidateVacancy,
    Interview,
    InterviewAnalysisCache,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    CandidateVacancyPatch,
    CandidateVacancyStatusUpdate,
    InterviewCreate,
    VacancyCreate,
)
from app.modules.storage.models import File
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._consent import sign_consent

BACKEND = Path(__file__).resolve().parents[2]


async def _second_user(db: AsyncSession, tenant) -> User:
    other = User(
        email=f"mover-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Mona",
        last_name="Mover",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(other)
    await db.commit()
    await db.refresh(other)
    return other


async def _cv(db: AsyncSession, tenant, user) -> tuple[uuid.UUID, dict]:
    await vacancy_service.seed_default_recruitment_stages(db, tenant.id)
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Ann", last_name="Lee", email=f"{uuid.uuid4().hex[:8]}@x.com"
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
    stages = {
        s["code"]: uuid.UUID(str(s["id"]))
        for s in await service.get_effective_vacancy_stages(
            db, tenant.id, uuid.UUID(str(vacancy["id"]))
        )
    }
    return uuid.UUID(str(cv["id"])), stages


async def _stage_events(db: AsyncSession, tenant, cv_id: uuid.UUID) -> list[dict]:
    items, _ = await audit_service.list_events(
        db, tenant.id, action="candidate.update_stage", entity_id=cv_id
    )
    return items


class TestStageMoveAuthor:
    async def test_patch_writes_author_to_history_and_audit(
        self, db: AsyncSession, tenant, user
    ) -> None:
        cv_id, stages = await _cv(db, tenant, user)
        mover = await _second_user(db, tenant)

        await service.patch_candidate_vacancy(
            db,
            tenant.id,
            cv_id,
            CandidateVacancyPatch(stage_id=stages["screening"]),
            user_id=mover.id,
        )

        row = await db.get(CandidateVacancy, cv_id)
        await db.refresh(row)
        assert row.status_history[-1]["changed_by"] == str(mover.id)

        events = await _stage_events(db, tenant, cv_id)
        assert events[0]["user_id"] == mover.id
        diff = events[0]["payload_diff"]["stage"]
        assert diff["before"]["id"] == str(stages["new"])
        assert diff["after"] == {"id": str(stages["screening"]), "name": "Screening"}

    async def test_status_endpoint_writes_author_and_names_mover_in_notification(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        cv_id, stages = await _cv(db, tenant, user)
        mover = await _second_user(db, tenant)
        published: list[tuple[str, dict]] = []

        async def capture(event, payload, **_kw):
            published.append((event, payload))

        from app.modules.recruitment import candidate_service

        monkeypatch.setattr(candidate_service, "_publish_event", capture)
        await service.change_candidate_status(
            db,
            tenant.id,
            cv_id,
            CandidateVacancyStatusUpdate(stage_id=stages["offer"]),
            user_id=mover.id,
        )

        row = await db.get(CandidateVacancy, cv_id)
        await db.refresh(row)
        assert row.status_history[-1]["changed_by"] == str(mover.id)
        assert (await _stage_events(db, tenant, cv_id)) == []  # its own action
        items, _ = await audit_service.list_events(
            db, tenant.id, action="candidate.change_status", entity_id=cv_id
        )
        assert items[0]["user_id"] == mover.id
        assert items[0]["payload_diff"]["stage"]["after"]["id"] == str(stages["offer"])

        ((event, payload),) = [p for p in published if p[0].endswith("stage_changed")]
        assert payload["actor_id"] == str(mover.id)
        assert payload["actor_name"] == "Mona Mover"
        # Recipients are unchanged: the owner and whoever attached them.
        assert payload["attached_by_id"] == str(user.id)


class TestUserParamNames:
    @pytest.mark.parametrize("name", ["actor_user_id", "current_user_id"])
    async def test_ai_entry_point_names_are_read(self, name: str) -> None:
        uid = uuid.uuid4()
        assert audit_registry._extract_user_id({name: uid}) == uid


class TestAnnotate:
    async def test_annotated_author_and_diff_reach_the_row(self, monkeypatch) -> None:
        recorded: list[dict] = []

        async def record_event(_db, **kwargs):
            recorded.append(kwargs)

        monkeypatch.setattr(audit_service, "record_event", record_event)
        author = uuid.uuid4()

        async def fake(db, tenant_id, entity_id, *, user_id=None):
            audit_registry.annotate(user_id=author, payload_diff={"x": 1})
            return {"id": entity_id}

        wrapped = audit_registry._wrap_with_audit(fake, "thing.do")
        await wrapped(object(), uuid.uuid4(), uuid.uuid4())
        assert recorded[0]["user_id"] == author
        assert recorded[0]["payload_diff"] == {"x": 1}

        # An explicit caller wins over the annotation.
        caller = uuid.uuid4()
        await wrapped(object(), uuid.uuid4(), uuid.uuid4(), user_id=caller)
        assert recorded[1]["user_id"] == caller

    def test_annotate_outside_a_wrapped_call_is_a_no_op(self) -> None:
        audit_registry.annotate(user_id=uuid.uuid4())


async def _interview_uploaded_by(db, tenant, user, uploader: User) -> uuid.UUID:
    cv_id, _ = await _cv(db, tenant, user)
    # HRP-979: an upload and the AI chain after it need the candidate's consent.
    cv_row = await db.get(CandidateVacancy, cv_id)
    await sign_consent(db, tenant.id, cv_row.candidate_id)
    interview = await service.create_interview(
        db, tenant.id, user.id, cv_id, InterviewCreate(notes="x")
    )
    media = File(
        tenant_id=tenant.id,
        name="a.mp3",
        original_name="a.mp3",
        path=f"interviews/{uuid.uuid4().hex}.mp3",
        size=10,
        mime_type="audio/mpeg",
        uploaded_by=uploader.id,
        entity_type="interview",
        entity_id=uuid.UUID(str(interview["id"])),
    )
    db.add(media)
    await db.flush()
    row = await db.get(Interview, uuid.UUID(str(interview["id"])))
    row.audio_file_id = media.id
    row.transcription_status = "completed"
    row.transcript = "hello"
    await db.commit()
    return row.id


class TestWorkerChainAuthor:
    async def test_transcribe_without_user_is_attributed_to_the_uploader(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        uploader = await _second_user(db, tenant)
        interview_id = await _interview_uploaded_by(db, tenant, user, uploader)
        from app.modules.recruitment import tasks, transcription_service

        monkeypatch.setattr(
            transcription_service, "get_transcription_chain_sync", lambda *_a: ["x"]
        )
        monkeypatch.setattr(
            tasks.transcribe_interview_task,
            "delay",
            lambda *_a: SimpleNamespace(id="task-1"),
        )
        await interview_service.enqueue_transcribe(db, tenant.id, interview_id)

        items, _ = await audit_service.list_events(
            db, tenant.id, action="interview.transcribe", entity_id=interview_id
        )
        assert items[0]["user_id"] == uploader.id

    async def test_analyze_hop_passes_the_uploader_on(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        uploader = await _second_user(db, tenant)
        interview_id = await _interview_uploaded_by(db, tenant, user, uploader)
        from app.modules.recruitment import analysis_cache_service

        seen: list[uuid.UUID | None] = []

        async def fake_analyze(_db, _tenant_id, _interview_id, *, user_id=None):
            seen.append(user_id)
            return {"status": "queued"}

        async def no_cache(*_a, **_kw):
            return None

        monkeypatch.setattr(
            analysis_cache_service, "compute_cache_key_for_interview", no_cache
        )
        monkeypatch.setattr(interview_service, "enqueue_analyze", fake_analyze)
        await interview_service.enqueue_analyze_or_cached(db, tenant.id, interview_id)
        assert seen == [uploader.id]

    async def test_cache_hit_is_logged_with_the_author(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        uploader = await _second_user(db, tenant)
        interview_id = await _interview_uploaded_by(db, tenant, user, uploader)
        from app.modules.recruitment import analysis_cache_service

        cached = InterviewAnalysisCache(
            tenant_id=tenant.id,
            cache_key=f"t-{uuid.uuid4().hex}"[:64],
            analysis_data={"verdict_summary": "ok", "competence_assessments": []},
            assessments=[],
        )
        db.add(cached)
        await db.commit()

        async def key(*_a, **_kw):
            return cached.cache_key

        async def lookup(*_a, **_kw):
            return cached

        monkeypatch.setattr(
            analysis_cache_service, "compute_cache_key_for_interview", key
        )
        monkeypatch.setattr(analysis_cache_service, "lookup_cached_analysis", lookup)
        out = await interview_service.enqueue_analyze_or_cached(
            db, tenant.id, interview_id
        )
        assert out == {"status": "completed", "cached": True}

        items, _ = await audit_service.list_events(
            db, tenant.id, action="interview.analyze", entity_id=interview_id
        )
        assert items[0]["user_id"] == uploader.id
        assert items[0]["payload_diff"] == {"cached": True}

    def test_worker_installs_the_audit_wrappers(self) -> None:
        code = (
            "from app.modules.recruitment import interview_service as m\n"
            "assert not hasattr(m.enqueue_transcribe, '_audit_action')\n"
            "from app.core.celery_app import on_worker_init\n"
            "on_worker_init()\n"
            "assert m.enqueue_transcribe._audit_action == 'interview.transcribe'\n"
            "assert m.enqueue_analyze._audit_action == 'interview.analyze'\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", code],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert done.returncode == 0, done.stderr[-2000:]


class TestAnalysisLeavesTheStage:
    async def test_cached_analysis_does_not_move_the_candidate(
        self, db: AsyncSession, tenant, user
    ) -> None:
        from app.modules.recruitment.analysis_cache_service import (
            apply_cached_analysis,
        )

        uploader = await _second_user(db, tenant)
        interview_id = await _interview_uploaded_by(db, tenant, user, uploader)
        interview = await db.get(Interview, interview_id)
        cv = await db.get(CandidateVacancy, interview.candidate_vacancy_id)
        stage_before, history_before = cv.stage_id, list(cv.status_history or [])

        cached = InterviewAnalysisCache(
            tenant_id=tenant.id,
            cache_key=f"t-{uuid.uuid4().hex}"[:64],
            analysis_data={"verdict_summary": "ok", "competence_assessments": []},
            assessments=[],
        )
        db.add(cached)
        await db.commit()
        await apply_cached_analysis(db, tenant.id, interview, cached)
        await db.commit()

        await db.refresh(cv)
        assert cv.stage_id == stage_before
        assert list(cv.status_history or []) == history_before

    def test_no_ai_writer_touches_the_stage(self) -> None:
        writers = [
            "app/modules/recruitment/tasks/analysis.py",
            "app/modules/recruitment/resume_analysis_service.py",
            "app/modules/recruitment/analysis_cache_service.py",
            "app/modules/recruitment/ai_service.py",
        ]
        pattern = re.compile(r"\.(stage_id|status_history)\s*=[^=]")
        for rel in writers:
            text = (BACKEND / rel).read_text(encoding="utf-8")
            assert not pattern.search(text), rel
