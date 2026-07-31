"""Unit tests for synchronous AI vacancy profile generation (HRP-134)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.recruitment import service
from app.modules.recruitment.schemas import VacancyCreate
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _vacancy_data(title: str = "Backend Engineer") -> VacancyCreate:
    return VacancyCreate(
        title=title,
        description="Maintain HRPulsar core services.",
        tasks_main={"text": "Build async APIs."},
        tasks_additional={"text": "Mentor juniors."},
        tasks_kpi={"text": "p95 latency under 200ms."},
    )


def _profile_payload(vacancy_id: str) -> dict:
    return {
        "vacancy_id": vacancy_id,
        "language": "fr",
        "competences": [
            {
                "id": "senior-python-skills",
                "group": "Engineering",
                "subgroup": "Backend",
                "name": "Senior Python skills",
                "criticality": "critical",
                "why_important": "core stack",
                "how_manifests": "writes idiomatic async code",
                "indicator_question": "Tell me about a tricky asyncio bug",
                "good_answer": "diagnosed event loop starvation",
                "acceptable_answer": "knew where to look",
                "poor_answer": "never seen one",
            }
        ],
        "coverage_note": "Auto-generated profile.",
    }


class TestExtractTaskText:
    def test_dict_with_text_key(self):
        assert service._extract_task_text({"text": "hello"}) == "hello"

    def test_plain_string(self):
        assert service._extract_task_text("hello") == "hello"

    def test_none(self):
        assert service._extract_task_text(None) == ""

    def test_list(self):
        assert service._extract_task_text([{"text": "one"}, {"text": "two"}]) == (
            "one\ntwo"
        )


class TestGenerateProfileNow:
    async def test_generate_defers_save_to_review(self, db: AsyncSession, tenant, user):
        """HRP-235 REDO (QA case 4): generation parks the result on the
        session row — no ``vacancy_profiles`` row may appear until the
        recruiter applies the reviewed selection via ``save_profile``."""
        from app.modules.recruitment.models import VacancyProfile

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        payload = _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = payload
            result = await service.generate_profile_now(
                db, tenant.id, user.id, vacancy["id"]
            )

        assert result["status"] == "ready"
        assert result["vacancy_id"] == vacancy["id"]
        assert result["coverage_note"] == "Auto-generated profile."
        competences = result["profile_data"]["competences"]
        # slug → stable uuid5 mapping
        uuid.UUID(competences[0]["id"])

        # The saved profile is untouched — the payload waits for review.
        saved = (
            await db.execute(
                select(VacancyProfile).where(
                    VacancyProfile.vacancy_id == vacancy["id"],
                    VacancyProfile.tenant_id == tenant.id,
                )
            )
        ).scalar_one_or_none()
        assert saved is None

        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is not None
        assert active["status"] == "ready"
        assert active["result_payload"]["profile_data"]["competences"]

    async def test_second_generate_while_running_conflicts(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-235 REDO (QA case 2): only one generation session per
        vacancy at a time — a second POST while one is running is a 409."""
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        db.add(
            VacancyProfileSession(
                tenant_id=tenant.id,
                vacancy_id=vacancy["id"],
                started_by_id=user.id,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = _profile_payload(str(vacancy["id"]))
            with pytest.raises(HTTPException) as exc_info:
                await service.generate_profile_now(
                    db, tenant.id, user.id, vacancy["id"]
                )
        assert exc_info.value.status_code == 409
        mock_gen.assert_not_called()

    async def test_second_generate_while_ready_pending_conflicts(
        self, db: AsyncSession, tenant, user
    ):
        """A parked (unreviewed) ready result blocks a new generation —
        otherwise the new session would silently orphan the payload the
        Review-for-save banner promised."""
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        payload = _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = payload
            await service.generate_profile_now(db, tenant.id, user.id, vacancy["id"])

            with pytest.raises(HTTPException) as exc_info:
                await service.generate_profile_now(
                    db, tenant.id, user.id, vacancy["id"]
                )
        assert exc_info.value.status_code == 409
        assert "awaiting review" in exc_info.value.detail

    async def test_legacy_ready_session_does_not_block_generate(
        self, db: AsyncSession, tenant, user
    ):
        """Pre-deferred-save ready rows carry no profile_data (their result
        already landed in the profile) — they must not lock the vacancy
        out of new generations forever."""
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        db.add(
            VacancyProfileSession(
                tenant_id=tenant.id,
                vacancy_id=vacancy["id"],
                started_by_id=user.id,
                status="ready",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                result_payload={"profile_version": 3, "coverage_note": None},
            )
        )
        await db.commit()

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = _profile_payload(str(vacancy["id"]))
            result = await service.generate_profile_now(
                db, tenant.id, user.id, vacancy["id"]
            )
        assert result["status"] == "ready"


class TestApplyProfileSession:
    """HRP-235 REDO (QA case 4): the review dialog's Apply path."""

    async def _generate(self, db, tenant, user, vacancy):
        payload = _profile_payload(str(vacancy["id"]))
        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = payload
            return await service.generate_profile_now(
                db, tenant.id, user.id, vacancy["id"]
            )

    async def test_apply_persists_profile_with_ai_provenance(
        self, db: AsyncSession, tenant, user
    ):
        """Apply must restore everything the old inline save used to set:
        generated_by="ai", language from the vacancy, coverage_note
        column — and retire the session as ``applied``."""
        from app.modules.recruitment.schemas import (
            VacancyCreate,
            VacancyProfileUpdate,
        )

        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(title="Senior Backend", language="en"),
        )
        result = await self._generate(db, tenant, user, vacancy)

        saved = await service.apply_profile_session(
            db,
            tenant.id,
            vacancy["id"],
            result["session_id"],
            VacancyProfileUpdate(profile_data=result["profile_data"]),
        )
        assert saved["version"] == 1
        assert saved["generated_by"] == "ai"
        assert saved["language"] == "en"
        assert saved["coverage_note"] == "Auto-generated profile."
        assert saved["profile_data"]["competences"][0]["name"] == (
            "Senior Python skills"
        )

        # The session is spent — the banner query must not surface it.
        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is None

    async def test_apply_increments_version_on_regenerate(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.schemas import VacancyProfileUpdate

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        first = await self._generate(db, tenant, user, vacancy)
        await service.apply_profile_session(
            db,
            tenant.id,
            vacancy["id"],
            first["session_id"],
            VacancyProfileUpdate(profile_data=first["profile_data"]),
        )
        second = await self._generate(db, tenant, user, vacancy)
        saved = await service.apply_profile_session(
            db,
            tenant.id,
            vacancy["id"],
            second["session_id"],
            VacancyProfileUpdate(profile_data=second["profile_data"]),
        )
        assert saved["version"] == 2
        assert saved["generated_by"] == "ai"

    async def test_apply_rejects_non_ready_session(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.schemas import VacancyProfileUpdate

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        result = await self._generate(db, tenant, user, vacancy)
        await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"], session_id=result["session_id"]
        )

        with pytest.raises(HTTPException) as exc:
            await service.apply_profile_session(
                db,
                tenant.id,
                vacancy["id"],
                result["session_id"],
                VacancyProfileUpdate(profile_data=result["profile_data"]),
            )
        assert exc.value.status_code == 409

    async def test_apply_unknown_session_returns_404(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.schemas import VacancyProfileUpdate

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        with pytest.raises(HTTPException) as exc:
            await service.apply_profile_session(
                db,
                tenant.id,
                vacancy["id"],
                uuid.uuid4(),
                VacancyProfileUpdate(profile_data={"competences": []}),
            )
        assert exc.value.status_code == 404

    async def test_apply_endpoint_roundtrip(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        result = await self._generate(db, tenant, user, vacancy)

        response = await auth_client.post(
            f"/api/recruitment/vacancies/{vacancy['id']}/profile/sessions/apply",
            json={
                "session_id": str(result["session_id"]),
                "profile_data": result["profile_data"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["generated_by"] == "ai"
        assert body["version"] == 1

        profile_response = await auth_client.get(
            f"/api/recruitment/vacancies/{vacancy['id']}/profile"
        )
        assert profile_response.json()["generated_by"] == "ai"


class TestActiveSessionResultVisibility:
    """HRP-235 REDO: the unapproved matrix is stripped for callers who
    cannot open the review dialog; everyone still gets the pending flag."""

    async def test_include_result_false_strips_profile_data(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        payload = _profile_payload(str(vacancy["id"]))
        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = payload
            await service.generate_profile_now(db, tenant.id, user.id, vacancy["id"])

        stripped = await service.get_active_profile_session(
            db, tenant.id, vacancy["id"], include_result=False
        )
        assert stripped is not None
        assert stripped["has_pending_result"] is True
        assert "profile_data" not in (stripped["result_payload"] or {})

        full = await service.get_active_profile_session(
            db, tenant.id, vacancy["id"], include_result=True
        )
        assert full["result_payload"]["profile_data"]["competences"]

    async def test_generate_passes_resolved_titles(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.dictionary.models import DictionaryItem

        spec = DictionaryItem(
            type="specialization", title="Backend", tenant_id=tenant.id
        )
        grade = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
        db.add_all([spec, grade])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)

        vac_create = VacancyCreate(
            title="Senior Backend Engineer",
            description="Lead service work.",
            specialization_id=spec.id,
            grade_id=grade.id,
            tasks_main={"text": "ship things"},
        )
        vacancy = await service.create_vacancy(db, tenant.id, user.id, vac_create)

        captured: dict = {}

        async def fake_gen(data, **kwargs):
            captured.update(data)
            return _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            side_effect=fake_gen,
        ):
            await service.generate_profile_now(db, tenant.id, user.id, vacancy["id"])

        assert captured["specialization"] == "Backend"
        assert captured["grade"] == "Senior"
        assert captured["tasks_main"] == "ship things"
        assert captured["description"] == "Lead service work."

    async def test_generate_raises_502_on_llm_failure(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = RuntimeError("LLM 500")
            with pytest.raises(HTTPException) as exc_info:
                await service.generate_profile_now(
                    db, tenant.id, user.id, vacancy["id"]
                )
        assert exc_info.value.status_code == 502
        assert "LLM 500" in exc_info.value.detail

    async def test_generate_rejects_non_dict_payload(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = "not a dict"
            with pytest.raises(HTTPException) as exc_info:
                await service.generate_profile_now(
                    db, tenant.id, user.id, vacancy["id"]
                )
        assert exc_info.value.status_code == 502

    async def test_generate_returns_404_for_other_tenant(
        self, db: AsyncSession, tenant, user
    ):
        other_tenant_vacancy_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await service.generate_profile_now(
                db, tenant.id, user.id, other_tenant_vacancy_id
            )
        assert exc_info.value.status_code == 404


class TestGenerateProfileEndpoint:
    async def test_endpoint_returns_pending_result(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        payload = _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = payload
            response = await auth_client.post(
                f"/api/recruitment/vacancies/{vacancy['id']}/profile/generate"
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ready"
        assert body["profile_data"]["competences"][0]["name"] == "Senior Python skills"

        # QA case 4: GET /profile still reports no saved profile — the
        # result is pending review on the session row.
        profile_response = await auth_client.get(
            f"/api/recruitment/vacancies/{vacancy['id']}/profile"
        )
        assert profile_response.status_code == 200
        assert profile_response.json() == {"profile": None}

    async def test_endpoint_propagates_llm_error(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = RuntimeError("boom")
            response = await auth_client.post(
                f"/api/recruitment/vacancies/{vacancy['id']}/profile/generate"
            )

        assert response.status_code == 502
        assert "boom" in response.json()["detail"]


class TestProfileGenerationSession:
    """HRP-134: session row tracks every generate_profile_now call."""

    async def test_session_marked_ready_on_success(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        payload = _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = payload
            await service.generate_profile_now(db, tenant.id, user.id, vacancy["id"])

        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is not None
        assert active["status"] == "ready"
        assert active["completed_at"] is not None
        assert active["error_message"] is None
        # HRP-235 REDO (QA case 4): the generated payload rides on the
        # session so the review dialog can load it without a saved profile.
        assert active["result_payload"]["profile_data"]["competences"]
        assert active["result_payload"]["coverage_note"] == ("Auto-generated profile.")

    async def test_session_marked_failed_on_llm_error(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = RuntimeError("boom")
            with pytest.raises(HTTPException) as exc:
                await service.generate_profile_now(
                    db, tenant.id, user.id, vacancy["id"]
                )
            assert exc.value.status_code == 502

        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is not None
        assert active["status"] == "failed"
        assert "boom" in (active["error_message"] or "")

    async def test_get_active_returns_none_when_no_runs(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        assert (
            await service.get_active_profile_session(db, tenant.id, vacancy["id"])
            is None
        )


class TestCancelProfileSession:
    """HRP-235: dismiss banner by marking the running session cancelled."""

    async def test_cancel_marks_running_session(self, db: AsyncSession, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        # Seed a running session row directly so we can cancel it without
        # awaiting a real (slow) LLM call.
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        session = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.commit()

        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"]
        )
        assert result["status"] == "cancelled"

        # After cancel the active-session endpoint returns None — the
        # banner-driving query filters cancelled rows out.
        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is None

    async def test_cancel_retires_ready_session(self, db: AsyncSession, tenant, user):
        """HRP-235 REDO (QA case 4): Discard (and the cleanup after Apply)
        retire a ``ready`` session so the Review-for-save banner stops
        surfacing the pending result."""
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        session = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="ready",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            result_payload={
                "profile_data": _profile_payload(str(vacancy["id"])),
                "coverage_note": "Auto-generated profile.",
            },
        )
        db.add(session)
        await db.commit()
        session_id = session.id

        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"], session_id=session_id
        )
        assert result["status"] == "cancelled"
        assert result["prior_status"] == "ready"

        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is None

    async def test_bodyless_cancel_does_not_touch_ready_session(
        self, db: AsyncSession, tenant, user
    ):
        """A ``ready`` (pending-review) result may only be retired by a
        pinned session_id — the legacy bodyless latest-match cancel from
        an older client must not silently discard it."""
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        ready = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="ready",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            result_payload={
                "profile_data": _profile_payload(str(vacancy["id"])),
                "coverage_note": None,
            },
        )
        db.add(ready)
        await db.commit()

        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"]
        )
        assert result["status"] == "no_active_session"

        await db.refresh(ready)
        assert ready.status == "ready"

    async def test_cancel_is_idempotent_when_nothing_running(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"]
        )
        assert result["status"] == "no_active_session"

    async def test_cancel_unknown_vacancy_returns_404(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.cancel_active_profile_session(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_cancel_dismisses_failed_session(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-134 REDO (Viktoriya 2026-06-26): dismissing the inline
        failure banner must also flip the failed session row to
        ``cancelled`` so the next ``/sessions/active`` poll does not
        resurrect the banner. Otherwise the recruiter sees the error
        message reappear on the regular polling cadence and assumes the
        Dismiss button is broken."""
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        session = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="failed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            error_message="AI returned non-dict payload",
        )
        db.add(session)
        await db.commit()

        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"]
        )
        assert result["status"] == "cancelled"
        assert result.get("prior_status") == "failed"

        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is None

    async def test_cancel_with_session_id_targets_exact_session(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-134 REDO race fix: dismissing an old failed banner while a
        newer generation is running (second tab / second recruiter) must
        cancel the failed session only. The legacy latest-match cancel
        grabbed the newer running row instead — the healthy run got
        killed and the failed banner resurrected on the next poll."""
        from datetime import datetime, timedelta, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        now = datetime.now(timezone.utc)
        failed = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="failed",
            started_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=4),
            error_message="AI returned non-dict payload",
        )
        running = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="running",
            started_at=now,
        )
        db.add_all([failed, running])
        await db.commit()
        failed_id = failed.id
        running_id = running.id

        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"], session_id=failed_id
        )
        assert result["status"] == "cancelled"
        assert result["session_id"] == failed_id
        assert result["prior_status"] == "failed"

        # The newer running session must be untouched — the banner keeps
        # showing Generating… and the in-flight save can still land.
        await db.refresh(running)
        assert running.status == "running"
        active = await service.get_active_profile_session(db, tenant.id, vacancy["id"])
        assert active is not None
        assert active["id"] == running_id
        assert active["status"] == "running"

    async def test_cancel_with_unknown_session_id_is_noop(
        self, db: AsyncSession, tenant, user
    ):
        """A pinned session_id that matches no cancellable row keeps the
        idempotent no_active_session response and touches nothing."""
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        running = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(running)
        await db.commit()

        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"], session_id=uuid.uuid4()
        )
        assert result["status"] == "no_active_session"

        await db.refresh(running)
        assert running.status == "running"

    async def test_cancel_without_session_id_keeps_latest_match(
        self, db: AsyncSession, tenant, user
    ):
        """Legacy bodyless cancel still targets the latest cancellable
        session (backward compatibility for old clients)."""
        from datetime import datetime, timedelta, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        now = datetime.now(timezone.utc)
        failed = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="failed",
            started_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=4),
            error_message="boom",
        )
        running = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="running",
            started_at=now,
        )
        db.add_all([failed, running])
        await db.commit()
        running_id = running.id

        result = await service.cancel_active_profile_session(
            db, tenant.id, vacancy["id"]
        )
        assert result["status"] == "cancelled"
        assert result["session_id"] == running_id
        assert result["prior_status"] == "running"

        await db.refresh(failed)
        assert failed.status == "failed"


class TestCancelSessionEndpoint:
    """Route-level contract for the cancel body: absent, ``{}`` and a
    pinned ``{"session_id": …}`` must all parse — legacy clients send
    bodyless/empty requests and must never see a 422."""

    async def _running_session(self, db: AsyncSession, tenant, user):
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        running = VacancyProfileSession(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            started_by_id=user.id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(running)
        await db.commit()
        return vacancy, running

    async def test_absent_body_cancels_latest(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        vacancy, running = await self._running_session(db, tenant, user)
        response = await auth_client.post(
            f"/api/recruitment/vacancies/{vacancy['id']}/profile/sessions/cancel"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "cancelled"
        assert body["session_id"] == str(running.id)

    async def test_empty_object_body_cancels_latest(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        vacancy, running = await self._running_session(db, tenant, user)
        response = await auth_client.post(
            f"/api/recruitment/vacancies/{vacancy['id']}/profile/sessions/cancel",
            json={},
        )
        assert response.status_code == 200, response.text
        assert response.json()["session_id"] == str(running.id)

    async def test_pinned_session_id_body(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        vacancy, running = await self._running_session(db, tenant, user)
        response = await auth_client.post(
            f"/api/recruitment/vacancies/{vacancy['id']}/profile/sessions/cancel",
            json={"session_id": str(running.id)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "cancelled"
        assert body["session_id"] == str(running.id)
        assert body["prior_status"] == "running"


class TestCancelMidGenerationRace:
    """HRP-134 REDO: a cancel issued while the LLM call is in flight must
    block the result from landing on top of the dismissed banner.

    Before the fix ``generate_profile_now`` happily wrote
    ``status="ready"`` over the freshly-committed ``status="cancelled"``
    row and persisted the profile — the banner reappeared on the next
    poll and the recruiter's dismiss was effectively undone."""

    async def test_cancel_during_llm_blocks_save(self, db: AsyncSession, tenant, user):
        from app.modules.recruitment.models import VacancyProfileSession

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        # Pin scalar primary keys before the race scenario: the cancel
        # branch performs a rollback that expires ORM fixtures, after
        # which any attribute access (``tenant.id``) would trigger a
        # sync lazy load and explode inside the async driver.
        tenant_id = tenant.id
        user_id = user.id
        vacancy_id = vacancy["id"]
        payload = _profile_payload(str(vacancy_id))

        # Side-effect on the mocked LLM call mimics a concurrent cancel:
        # a separate request marks the running session as cancelled while
        # we're "waiting" for the model. The cancel handler commits on
        # its own connection so the new status is visible to the
        # re-fetch in generate_profile_now.
        async def cancel_then_return(_data, **kwargs):
            await service.cancel_active_profile_session(db, tenant_id, vacancy_id)
            return payload

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            side_effect=cancel_then_return,
        ):
            result = await service.generate_profile_now(
                db, tenant_id, user_id, vacancy_id
            )
            # Returns a ``cancelled`` marker (not 409) so the EE billing
            # wrapper still credits the tenant for the LLM tokens we paid
            # for. Frontend ignores the body and relies on polling.
            assert result.get("cancelled") is True

        # No VacancyProfile row should have been created — the dismiss
        # must beat the in-flight save.
        from app.modules.recruitment.models import VacancyProfile

        existing = (
            await db.execute(
                select(VacancyProfile).where(
                    VacancyProfile.vacancy_id == vacancy_id,
                    VacancyProfile.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        assert existing is None

        # And the session row must stay ``cancelled`` — not get flipped
        # back to ``ready`` by the late save.
        session_row = (
            await db.execute(
                select(VacancyProfileSession).where(
                    VacancyProfileSession.vacancy_id == vacancy_id,
                )
            )
        ).scalar_one()
        assert session_row.status == "cancelled"


class TestClarificationContext:
    """HRP-134 REDO: free-form recruiter clarification from the matrix
    modal must reach the prompt builder."""

    async def test_clarification_passed_to_prompt(self, db: AsyncSession, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        captured: dict = {}

        async def fake_generate(data: dict, **kwargs) -> dict:
            captured.update(data)
            return _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new=fake_generate,
        ):
            await service.generate_profile_now(
                db,
                tenant.id,
                user.id,
                vacancy["id"],
                clarification="Focus on backend leads. Skip junior soft skills.",
            )

        assert captured["clarification"] == (
            "Focus on backend leads. Skip junior soft skills."
        )

    async def test_clarification_none_yields_empty_string(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        captured: dict = {}

        async def fake_generate(data: dict, **kwargs) -> dict:
            captured.update(data)
            return _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new=fake_generate,
        ):
            await service.generate_profile_now(db, tenant.id, user.id, vacancy["id"])

        assert captured["clarification"] == ""


class TestProfilePromptContext:
    """HRP-135 REDO: the AI prompt receives requirements / responsibilities /
    conditions and any attachment text alongside the title/tasks block."""

    async def test_prompt_receives_manual_text_fields(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.schemas import VacancyCreate

        vacancy = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(
                title="Senior Python",
                description="Maintain core services.",
                requirements="5+ years Python",
                responsibilities="Own async APIs",
                conditions="Remote, USD",
            ),
        )
        captured: dict = {}

        async def fake_generate(data: dict, **kwargs) -> dict:
            captured.update(data)
            return _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new=fake_generate,
        ):
            await service.generate_profile_now(db, tenant.id, user.id, vacancy["id"])

        assert captured["requirements"] == "5+ years Python"
        assert captured["responsibilities"] == "Own async APIs"
        assert captured["conditions"] == "Remote, USD"
        # Empty when there are no attachments — keeps the prompt clean.
        assert captured["attachments_text"] == ""

    async def test_prompt_lists_attachments_when_present(
        self, db: AsyncSession, tenant, user
    ):
        from datetime import datetime, timezone

        from app.modules.recruitment.models import VacancyAttachment
        from app.modules.recruitment.schemas import VacancyCreate

        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="Backend")
        )
        # Attachment without a backing storage file — body cannot be
        # extracted, but the header (filename + mime) must still reach
        # the prompt so the LLM at least knows it exists.
        attachment = VacancyAttachment(
            tenant_id=tenant.id,
            vacancy_id=vacancy["id"],
            file_id=None,
            filename="jd.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            uploaded_by=user.id,
            uploaded_at=datetime.now(timezone.utc),
        )
        db.add(attachment)
        await db.commit()

        captured: dict = {}

        async def fake_generate(data: dict, **kwargs) -> dict:
            captured.update(data)
            return _profile_payload(str(vacancy["id"]))

        with patch(
            "app.modules.recruitment.ai_service.generate_vacancy_profile",
            new=fake_generate,
        ):
            await service.generate_profile_now(db, tenant.id, user.id, vacancy["id"])

        assert "jd.pdf" in captured["attachments_text"]
        assert "application/pdf" in captured["attachments_text"]
