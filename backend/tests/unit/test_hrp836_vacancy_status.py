"""HRP-427 / HRP-836: the vacancy status model.

* the first candidate opens a draft vacancy on every attach path, and
  removing the last one does not send it back;
* Publish (draft → open) needs a filled "Competences & indicators" block;
* open → paused | closed | cancelled, paused → open | closed | cancelled,
  anything else is 409;
* Close takes a resolution that has to match the funnel;
* a paused / closed / cancelled vacancy freezes its surfaces (409 on the
  mutation entry points), a closed / cancelled one its own edit too.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

import pytest
from app.core.errors import AppError
from app.main import app
from app.modules.recruitment import service, vacancy_service
from app.modules.recruitment.common import (
    VACANCY_LOCKED_SURFACES,
    ensure_vacancy_unlocked,
    vacancy_locks,
)
from app.modules.recruitment.models import (
    CandidateFile,
    CandidateVacancy,
    Vacancy,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    BatchFinalizeFile,
    BatchFinalizeRequest,
    CandidateCreate,
    CandidateManualCreate,
    CandidateVacancyCreate,
    CandidateVacancyPatch,
    InterviewCreate,
    VacancyCloseData,
    VacancyCreate,
    VacancyStatusChange,
    VacancyUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


async def _vacancy(db: AsyncSession, tenant, user) -> uuid.UUID:
    await vacancy_service.seed_default_recruitment_stages(db, tenant.id)
    v = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    return uuid.UUID(str(v["id"]))


async def _status(db: AsyncSession, vacancy_id: uuid.UUID) -> str:
    row = await db.get(Vacancy, vacancy_id)
    await db.refresh(row)
    return row.status


async def _attach(db: AsyncSession, tenant, user, vacancy_id) -> uuid.UUID:
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="C", last_name="D", email=f"{uuid.uuid4().hex[:8]}@x.com"
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(candidate["id"])), vacancy_id=vacancy_id
        ),
    )
    return uuid.UUID(str(cv["id"]))


async def _set_status(db: AsyncSession, vacancy_id: uuid.UUID, value: str) -> None:
    row = await db.get(Vacancy, vacancy_id)
    row.status = value
    await db.commit()


async def _give_competences(db: AsyncSession, tenant, vacancy_id) -> None:
    db.add(
        VacancyProfile(
            tenant_id=tenant.id,
            vacancy_id=vacancy_id,
            profile_data={"competences": [{"id": "python", "name": "Python"}]},
            version=1,
        )
    )
    await db.commit()


async def _move_to(db, tenant, vacancy_id, cv_id, code: str) -> None:
    stages = {
        s["code"]: s["id"]
        for s in await service.get_effective_vacancy_stages(db, tenant.id, vacancy_id)
    }
    await service.patch_candidate_vacancy(
        db, tenant.id, cv_id, CandidateVacancyPatch(stage_id=stages[code])
    )


class TestFirstCandidateOpensDraft:
    async def test_attach_opens_and_detach_keeps_open(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        assert await _status(db, vacancy_id) == "draft"
        cv_id = await _attach(db, tenant, user, vacancy_id)
        assert await _status(db, vacancy_id) == "open"

        await service.delete_candidate_vacancy(db, tenant.id, cv_id)
        assert await _status(db, vacancy_id) == "open"

    async def test_auto_open_leaves_the_command_trail(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """Review m6: the automatic draft -> open is logged and versioned like
        the Publish command."""
        from app.modules.recruitment import audit_service

        vacancy_id = await _vacancy(db, tenant, user)
        version = (await db.get(Vacancy, vacancy_id)).version
        await _attach(db, tenant, user, vacancy_id)
        row = await db.get(Vacancy, vacancy_id)
        await db.refresh(row)
        assert row.version == version + 1

        items, _ = await audit_service.list_events(
            db, tenant.id, action="vacancy.change_status", entity_id=vacancy_id
        )
        assert len(items) == 1
        assert items[0]["user_id"] == user.id
        assert items[0]["payload_diff"] == {
            "status": {"before": "draft", "after": "open"}
        }

        # A second candidate changes nothing.
        await _attach(db, tenant, user, vacancy_id)
        items, _ = await audit_service.list_events(
            db, tenant.id, action="vacancy.change_status", entity_id=vacancy_id
        )
        assert len(items) == 1

    async def test_manual_add_opens(self, db: AsyncSession, tenant, user) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy_id,
            CandidateManualCreate(
                full_name="Manual One", email=f"{uuid.uuid4().hex[:8]}@x.com"
            ),
        )
        assert await _status(db, vacancy_id) == "open"

    async def test_resume_import_opens(self, db: AsyncSession, tenant, user) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cf = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=None,
            original_filename="cv.pdf",
            mime_type="application/pdf",
            file_size=100,
            parse_status="completed",
            parsed_data={
                "first_name": "Res",
                "last_name": "Ume",
                "contacts": {"email": f"{uuid.uuid4().hex[:8]}@x.com"},
            },
        )
        db.add(cf)
        await db.commit()
        await service.finalize_candidates_from_parsed(
            db,
            tenant.id,
            user.id,
            vacancy_id,
            BatchFinalizeRequest(files=[BatchFinalizeFile(file_id=cf.id)]),
        )
        assert await _status(db, vacancy_id) == "open"

    async def test_attach_leaves_other_statuses_alone(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        await _set_status(db, vacancy_id, "paused")
        await _attach(db, tenant, user, vacancy_id)
        assert await _status(db, vacancy_id) == "paused"


class TestPublish:
    async def test_needs_competences(self, db: AsyncSession, tenant, user) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        with pytest.raises(AppError) as exc:
            await service.change_vacancy_status(
                db, tenant.id, vacancy_id, VacancyStatusChange(status="open")
            )
        assert exc.value.code == "vacancy_publish_requires_competences"
        assert await _status(db, vacancy_id) == "draft"

        await _give_competences(db, tenant, vacancy_id)
        out = await service.change_vacancy_status(
            db, tenant.id, vacancy_id, VacancyStatusChange(status="open")
        )
        assert out["status"] == "open"


class TestTransitions:
    @pytest.mark.parametrize(
        ("start", "target"),
        [
            ("open", "paused"),
            ("open", "cancelled"),
            ("paused", "open"),
            ("paused", "cancelled"),
        ],
    )
    async def test_allowed(self, db: AsyncSession, tenant, user, start, target) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        await _set_status(db, vacancy_id, start)
        out = await service.change_vacancy_status(
            db, tenant.id, vacancy_id, VacancyStatusChange(status=target)
        )
        assert out["status"] == target

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            ("draft", "paused"),
            ("draft", "cancelled"),
            ("open", "open"),
            ("paused", "paused"),
            ("closed", "open"),
            ("cancelled", "open"),
            ("cancelled", "paused"),
        ],
    )
    async def test_refused(self, db: AsyncSession, tenant, user, start, target) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        await _set_status(db, vacancy_id, start)
        with pytest.raises(AppError) as exc:
            await service.change_vacancy_status(
                db, tenant.id, vacancy_id, VacancyStatusChange(status=target)
            )
        assert exc.value.status_code == 409
        assert exc.value.code == "vacancy_status_transition_invalid"
        assert await _status(db, vacancy_id) == start

    @pytest.mark.parametrize("start", ["draft", "closed", "cancelled"])
    async def test_close_only_from_open_or_paused(
        self, db: AsyncSession, tenant, user, start
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        await _set_status(db, vacancy_id, start)
        with pytest.raises(AppError) as exc:
            await service.close_vacancy(
                db, tenant.id, vacancy_id, VacancyCloseData(resolution="closed_no_hire")
            )
        assert exc.value.code == "vacancy_status_transition_invalid"

    @pytest.mark.parametrize("command", ["close", "pause"])
    async def test_concurrent_command_sees_the_committed_status(
        self, db: AsyncSession, tenant, user, session_factory, command
    ) -> None:
        """Review B2: the status is read under a row lock, so a command
        racing a Cancel waits for it and then refuses, instead of
        overwriting ``cancelled`` from the stale ``open`` it read."""
        vacancy_id = await _vacancy(db, tenant, user)
        await _set_status(db, vacancy_id, "open")

        async with session_factory() as first, session_factory() as second:
            row = await first.scalar(
                select(Vacancy).where(Vacancy.id == vacancy_id).with_for_update()
            )
            row.status = "cancelled"  # a Cancel, not committed yet
            await first.flush()

            if command == "close":
                call = service.close_vacancy(
                    second,
                    tenant.id,
                    vacancy_id,
                    VacancyCloseData(resolution="closed_no_hire"),
                )
            else:
                call = service.change_vacancy_status(
                    second, tenant.id, vacancy_id, VacancyStatusChange(status="paused")
                )
            racer = asyncio.create_task(call)
            await asyncio.sleep(0.3)
            assert not racer.done()
            await first.commit()

            with pytest.raises(AppError) as exc:
                await asyncio.wait_for(racer, timeout=10)
            assert exc.value.code == "vacancy_status_transition_invalid"
        assert await _status(db, vacancy_id) == "cancelled"

    def test_cancelled_is_not_a_close_resolution(self) -> None:
        with pytest.raises(ValueError):
            VacancyCloseData(resolution="cancelled")  # type: ignore[arg-type]

    def test_edit_payload_has_no_status(self) -> None:
        assert "status" not in VacancyUpdate.model_fields


class TestCloseResolution:
    async def test_with_hiring_needs_a_terminal_positive_candidate(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _attach(db, tenant, user, vacancy_id)
        with pytest.raises(AppError) as exc:
            await service.close_vacancy(
                db, tenant.id, vacancy_id, VacancyCloseData(resolution="hired")
            )
        assert exc.value.code == "vacancy_close_requires_hire"

        # Probation completed is terminal-positive too (HRP-790).
        await _move_to(db, tenant, vacancy_id, cv_id, "probation_completed")
        out = await service.close_vacancy(
            db, tenant.id, vacancy_id, VacancyCloseData(resolution="hired")
        )
        assert (out["status"], out["close_resolution"]) == ("closed", "hired")

    async def test_without_hiring_refused_when_someone_was_hired(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _attach(db, tenant, user, vacancy_id)
        await _move_to(db, tenant, vacancy_id, cv_id, "hired")
        with pytest.raises(AppError) as exc:
            await service.close_vacancy(
                db, tenant.id, vacancy_id, VacancyCloseData(resolution="closed_no_hire")
            )
        assert exc.value.code == "vacancy_close_has_hire"
        assert await _status(db, vacancy_id) == "open"

    async def test_without_hiring_from_paused(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _attach(db, tenant, user, vacancy_id)
        await _move_to(db, tenant, vacancy_id, cv_id, "rejected")
        await _set_status(db, vacancy_id, "paused")
        out = await service.close_vacancy(
            db, tenant.id, vacancy_id, VacancyCloseData(resolution="closed_no_hire")
        )
        assert out["close_resolution"] == "closed_no_hire"

    async def test_named_hire_counts_and_records_the_closer(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _attach(db, tenant, user, vacancy_id)
        cv = await db.get(CandidateVacancy, cv_id)
        await service.close_vacancy(
            db,
            tenant.id,
            vacancy_id,
            VacancyCloseData(resolution="hired", hired_candidate_id=cv.candidate_id),
            user_id=user.id,
        )
        await db.refresh(cv)
        assert cv.status_history[-1]["changed_by"] == str(user.id)


class TestReadOnly:
    def test_matrix(self) -> None:
        paused = {"questions", "interviews", "manager_assessments"}
        ended = paused | {"vacancy", "ai_insights"}
        expected = {"paused": paused, "closed": ended, "cancelled": ended}
        assert expected == VACANCY_LOCKED_SURFACES
        for status in ("draft", "open", None):
            assert not vacancy_locks(status, "interviews")

    async def test_edit_refused_when_closed_or_cancelled(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        await _set_status(db, vacancy_id, "paused")
        await service.update_vacancy(
            db, tenant.id, vacancy_id, VacancyUpdate(title="P")
        )
        for status in ("closed", "cancelled"):
            await _set_status(db, vacancy_id, status)
            with pytest.raises(AppError) as exc:
                await service.update_vacancy(
                    db, tenant.id, vacancy_id, VacancyUpdate(title="X")
                )
            assert exc.value.code == "vacancy_status_read_only"

    async def test_guard_resolves_every_id_kind(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _attach(db, tenant, user, vacancy_id)
        interview = await service.create_interview(
            db, tenant.id, user.id, cv_id, InterviewCreate(notes="x")
        )
        interview_id = uuid.UUID(str(interview["id"]))
        await _set_status(db, vacancy_id, "paused")

        for kwargs in (
            {"vacancy_id": vacancy_id},
            {"cv_id": cv_id},
            {"interview_id": interview_id},
        ):
            with pytest.raises(AppError):
                await ensure_vacancy_unlocked(db, tenant.id, "interviews", **kwargs)
            # Paused leaves AI Insights open.
            await ensure_vacancy_unlocked(db, tenant.id, "ai_insights", **kwargs)

        await _set_status(db, vacancy_id, "open")
        await ensure_vacancy_unlocked(db, tenant.id, "interviews", cv_id=cv_id)

    async def test_http_create_interview_refused_on_paused_vacancy(
        self, db: AsyncSession, tenant, user, auth_client
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _attach(db, tenant, user, vacancy_id)
        await _set_status(db, vacancy_id, "paused")
        resp = await auth_client.post(
            f"/api/recruitment/candidate-vacancies/{cv_id}/interviews", json={}
        )
        assert resp.status_code == 409, resp.text

        await _set_status(db, vacancy_id, "open")
        resp = await auth_client.post(
            f"/api/recruitment/candidate-vacancies/{cv_id}/interviews", json={}
        )
        assert resp.status_code == 201, resp.text

    async def test_http_status_endpoint(
        self, db: AsyncSession, tenant, user, auth_client
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        await _set_status(db, vacancy_id, "open")
        resp = await auth_client.post(
            f"/api/recruitment/vacancies/{vacancy_id}/status", json={"status": "paused"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "paused"


class TestSeededVacanciesAreOpen:
    """Review M1: the demo seed and the onboarding sample used to write
    ``published``, a status the commands do not know - their vacancies had
    no Pause / Close / Cancel and closing them answered 409."""

    async def test_demo_seed(
        self, db: AsyncSession, tenant, user, skill_levels
    ) -> None:
        from app.modules.demo.seed import clone_seed_into_demo_tenant
        from app.modules.recruitment import analytics_service
        from app.modules.recruitment.vacancy_service import VACANCY_TRANSITIONS

        tenant.is_demo = True
        await db.commit()
        await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
        await db.commit()

        rows = (
            (await db.execute(select(Vacancy).where(Vacancy.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        statuses = {v.status for v in rows}
        assert "published" not in statuses
        assert statuses <= set(VACANCY_TRANSITIONS) | {"closed", "cancelled"}

        live = next(v for v in rows if v.status == "open")
        assert VACANCY_TRANSITIONS["open"] == {"paused", "closed", "cancelled"}
        await service.change_vacancy_status(
            db, tenant.id, live.id, VacancyStatusChange(status="paused")
        )
        hired = (await analytics_service.vacancy_analytics(db, tenant.id, live.id))[
            "win_loss"
        ]["hired"]
        out = await service.close_vacancy(
            db,
            tenant.id,
            live.id,
            VacancyCloseData(resolution="hired" if hired else "closed_no_hire"),
        )
        assert out["status"] == "closed"

    async def test_onboarding_sample(self, db: AsyncSession, tenant, user) -> None:
        from app.modules.recruitment import onboarding_service

        await onboarding_service.seed_demo(db, tenant.id, user.id)
        rows = (
            (await db.execute(select(Vacancy).where(Vacancy.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        assert rows and {v.status for v in rows} == {"open"}


@pytest.mark.skipif(not _FRONTEND.exists(), reason="frontend tree not present")
def test_the_dialog_calls_mounted_urls() -> None:
    source = (
        _FRONTEND
        / "src/app/(dashboard)/recruitment/requisitions/_components/VacancyStatusDialog.tsx"
    ).read_text(encoding="utf-8")
    called = {
        "/api" + re.sub(r"\$\{[^}]*\}", "{}", raw)
        for raw in re.findall(r"`(/recruitment/vacancies/\$\{[^}]+\}/[a-z]+)`", source)
    }
    mounted = {re.sub(r"\{[^}]*\}", "{}", getattr(r, "path", "")) for r in app.routes}
    assert {
        "/api/recruitment/vacancies/{}/status",
        "/api/recruitment/vacancies/{}/close",
    } <= called
    assert called <= mounted
