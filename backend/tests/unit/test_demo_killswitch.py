"""HRP-252 (D4): ``DEMO_AI_KILLSWITCH`` short-circuits AI tasks for demo
tenants.

When ``settings.demo_ai_killswitch`` is True AND the interview belongs
to an ``is_demo`` tenant, the recruitment Celery tasks must NOT call
the real LLM / transcription providers. Instead they replay the seed
fixtures from ``app.modules.demo.seed_data``. Production tenants
always take the real path regardless of the flag.

The Celery tasks open their own sync DB session via ``create_engine``
on ``settings.database_url``, so we point that at the test database
just like ``test_recruitment_notifications.py`` does.
"""

from __future__ import annotations

import uuid

import pytest
from app.config import settings as app_settings
from app.modules.company.models import Tenant
from app.modules.demo.seed_data import (
    DEMO_FIRST_SCREEN_CANDIDATE_EMAIL,
    ELENA_INTERVIEW_ANALYSIS,
)
from app.modules.recruitment.models import (
    AIAssessment,
    Candidate,
    CandidateVacancy,
    Interview,
    InterviewSegment,
    Vacancy,
)
from app.modules.recruitment.tasks import (
    analyze_interview_task,
    transcribe_interview_task,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_demo_setup(
    db: AsyncSession,
    *,
    is_demo: bool,
    candidate_email: str = DEMO_FIRST_SCREEN_CANDIDATE_EMAIL,
) -> Interview:
    """Build the minimum (Tenant, Vacancy, Candidate, Interview) row set."""
    from app.models import Person

    suffix = uuid.uuid4().hex[:6]
    tenant = Tenant(
        name=f"Demo {suffix}", slug=f"demo-{suffix}", is_demo=is_demo
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    vacancy = Vacancy(
        tenant_id=tenant.id,
        title="Demo Vacancy",
        language="en",
    )
    db.add(vacancy)
    await db.commit()
    await db.refresh(vacancy)

    person = Person(
        email=candidate_email,
        first_name="Elena",
        last_name="Volkov",
    )
    db.add(person)
    await db.commit()
    await db.refresh(person)

    candidate = Candidate(
        tenant_id=tenant.id,
        person_id=person.id,
        full_name=f"{person.first_name} {person.last_name}",
        email=person.email,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    cv = CandidateVacancy(
        tenant_id=tenant.id,
        vacancy_id=vacancy.id,
        candidate_id=candidate.id,
    )
    db.add(cv)
    await db.commit()
    await db.refresh(cv)

    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        transcript="Sample transcript for the demo interview.",
        transcription_status="completed",
        analysis_status="pending",
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return interview, tenant


@pytest.fixture
def killswitch_on(monkeypatch):
    """Flip the kill-switch flag and pin the sync engine to the test DB."""
    monkeypatch.setattr(app_settings, "demo_ai_killswitch", True)
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)


@pytest.fixture
def killswitch_off(monkeypatch):
    monkeypatch.setattr(app_settings, "demo_ai_killswitch", False)
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)


@pytest.mark.asyncio
async def test_analyze_killswitch_uses_seed_for_demo_tenant(
    db: AsyncSession, killswitch_on, monkeypatch
):
    interview, tenant = await _make_demo_setup(db, is_demo=True)

    # ``generate_json`` must NOT be called when the kill-switch fires.
    def _explode(*args, **kwargs):
        raise AssertionError("generate_json should not be called under kill-switch")

    monkeypatch.setattr(
        "app.modules.ai.llm_client.generate_json", _explode
    )

    result = analyze_interview_task.run(str(interview.id), str(tenant.id))

    assert result["status"] == "completed"
    assert result.get("demo_killswitch") is True

    await db.commit()
    # The Celery task wrote through a separate sync engine; reload the
    # row in the async session so the identity-map cache does not hide
    # the kill-switch's writes.
    refreshed = (
        await db.execute(
            select(Interview)
            .where(Interview.id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.analysis_status == "completed"
    assert refreshed.analysis_data["verdict_summary"] == (
        ELENA_INTERVIEW_ANALYSIS["verdict_summary"]
    )

    # AIAssessment rows landed with non-empty citations — the acceptance
    # criterion explicitly requires the JSONB to be populated from seed.
    rows = (
        await db.execute(
            select(AIAssessment)
            .where(AIAssessment.interview_id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert rows, "AIAssessment rows must be seeded under killswitch"
    assert all(r.citations for r in rows)


@pytest.mark.asyncio
async def test_analyze_killswitch_does_not_fire_for_paid_tenant(
    db: AsyncSession, killswitch_on, monkeypatch
):
    interview, tenant = await _make_demo_setup(db, is_demo=False)

    sentinel = {"called": False}

    def _explode(*args, **kwargs):
        sentinel["called"] = True
        raise RuntimeError("real LLM call attempted — fine for this test")

    monkeypatch.setattr(
        "app.modules.ai.llm_client.generate_json", _explode
    )

    # The real path will fail (no profile, no LLM available) but the key
    # observation is that the kill-switch branch did NOT short-circuit —
    # the task tried to reach the LLM client because the tenant is not
    # ``is_demo``. The retry decorator may bubble the exception, so we
    # accept either a Celery retry or any unhandled raise here.
    with pytest.raises(Exception):  # noqa: BLE001, B017  # any error proves the real path was hit
        analyze_interview_task.run(str(interview.id), str(tenant.id))
    assert sentinel["called"] is True


@pytest.mark.asyncio
async def test_transcribe_killswitch_uses_bundled_transcript(
    db: AsyncSession, killswitch_on, monkeypatch
):
    interview, tenant = await _make_demo_setup(db, is_demo=True)
    # Reset transcription to a pre-run state so the task replays it.
    interview.transcription_status = "pending"
    interview.transcript = None
    await db.commit()

    # Whisper/Deepgram providers must not even be looked up.
    def _explode(*args, **kwargs):
        raise AssertionError(
            "transcription provider must not be resolved under kill-switch"
        )

    monkeypatch.setattr(
        "app.modules.recruitment.transcription_service.get_transcription_provider_sync",
        _explode,
    )

    result = transcribe_interview_task.run(str(interview.id), str(tenant.id))
    assert result["status"] == "completed"
    assert result.get("demo_killswitch") is True

    refreshed = (
        await db.execute(
            select(Interview)
            .where(Interview.id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.transcription_status == "completed"
    assert refreshed.transcript
    assert refreshed.transcription_provider == "demo-killswitch"


@pytest.mark.asyncio
async def test_transcribe_killswitch_wipes_stale_segments(
    db: AsyncSession, killswitch_on, monkeypatch
):
    """Killswitch transcribe must remove any existing InterviewSegment rows
    so ``analyze_interview_task`` doesn't see a transcript / segment
    mismatch from a prior real run."""
    interview, tenant = await _make_demo_setup(db, is_demo=True)
    interview.transcription_status = "pending"
    interview.transcript = None
    await db.commit()

    for idx in range(3):
        db.add(
            InterviewSegment(
                tenant_id=tenant.id,
                interview_id=interview.id,
                speaker="A",
                start_sec=float(idx),
                end_sec=float(idx + 1),
                text=f"stale {idx}",
            )
        )
    await db.commit()

    def _explode(*args, **kwargs):
        raise AssertionError(
            "transcription provider must not be resolved under kill-switch"
        )

    monkeypatch.setattr(
        "app.modules.recruitment.transcription_service.get_transcription_provider_sync",
        _explode,
    )

    result = transcribe_interview_task.run(str(interview.id), str(tenant.id))
    assert result["status"] == "completed"

    segments = (
        await db.execute(
            select(InterviewSegment).where(
                InterviewSegment.interview_id == interview.id
            ).execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert segments == []


@pytest.mark.asyncio
async def test_killswitch_analysis_status_uses_real_vocabulary(
    db: AsyncSession, killswitch_on, monkeypatch
):
    """``AIAssessment.status`` must speak the real Literal vocabulary
    (``assessed`` / ``insufficient`` / ``not_covered``), not the demo
    seed verdicts (``strong`` / ``partial`` / ``unknown``)."""
    interview, tenant = await _make_demo_setup(db, is_demo=True)

    monkeypatch.setattr(
        "app.modules.ai.llm_client.generate_json",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("LLM must not be called")
        ),
    )

    analyze_interview_task.run(str(interview.id), str(tenant.id))

    rows = (
        await db.execute(
            select(AIAssessment)
            .where(AIAssessment.interview_id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert rows
    allowed = {"assessed", "insufficient", "not_covered"}
    for r in rows:
        assert r.status in allowed, (
            f"status {r.status!r} not in {allowed}; killswitch is still "
            "emitting seed-only vocabulary"
        )


@pytest.mark.asyncio
async def test_killswitch_analysis_findings_are_dict_shaped(
    db: AsyncSession, killswitch_on, monkeypatch
):
    """`process_findings`/`blind_spots`/`red_flags` must be dicts so
    the HM-role filter and the frontend can call ``.get()`` on them."""
    interview, tenant = await _make_demo_setup(db, is_demo=True)

    monkeypatch.setattr(
        "app.modules.ai.llm_client.generate_json",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("LLM must not be called")
        ),
    )

    analyze_interview_task.run(str(interview.id), str(tenant.id))

    refreshed = (
        await db.execute(
            select(Interview)
            .where(Interview.id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    data = refreshed.analysis_data or {}
    for key in ("process_findings", "blind_spots", "red_flags"):
        items = data.get(key) or []
        for item in items:
            assert isinstance(item, dict), (
                f"{key} item must be dict, got {type(item).__name__}"
            )


@pytest.mark.asyncio
async def test_killswitch_competence_namespace_matches_real_path(
    db: AsyncSession, killswitch_on, monkeypatch
):
    """The competence_id minted by the killswitch must match the UUID
    a VacancyProfile slug would produce, so the Compact matrix
    (HRP-265) and the canvas API can join AIAssessment rows to the
    vacancy profile columns. HRP-275 wired ``competence_id`` slugs into
    the seed fixtures specifically to close this gap — the old killswitch
    minted a UUID from the human-readable label and the matrix lookup
    silently fell through to ``ai_status='missing'``."""
    from app.modules.recruitment.common import normalize_competence_id

    interview, tenant = await _make_demo_setup(db, is_demo=True)

    monkeypatch.setattr(
        "app.modules.ai.llm_client.generate_json",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("LLM must not be called")
        ),
    )
    analyze_interview_task.run(str(interview.id), str(tenant.id))

    rows = (
        await db.execute(
            select(AIAssessment)
            .where(AIAssessment.interview_id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert rows

    # Elena seed uses ``python-advanced`` as the first competence slug
    # — same value VacancyProfile records — so the UUIDs must match.
    expected = normalize_competence_id("python-advanced")
    assert expected is not None
    assert any(r.competence_id == expected for r in rows)

    # And the human-readable label must NOT collide — proves the
    # killswitch is keying off the slug, not the label.
    label_uuid = normalize_competence_id("Python (advanced)")
    assert label_uuid is not None
    assert label_uuid != expected
    assert not any(r.competence_id == label_uuid for r in rows)


@pytest.mark.asyncio
async def test_killswitch_bumps_interview_version(
    db: AsyncSession, killswitch_on, monkeypatch
):
    """HRP-275 Bug #4: every analyze path must bump ``interview.version``
    so an ETag re-poll sees fresh data. The cache-hit branch
    (``apply_cached_analysis``) was already bumping; the killswitch and
    real-LLM paths now have to match — otherwise the UI sticks on a 304
    after a kill-switch replay clobbered ``analysis_data`` underneath.

    The starting version is pinned explicitly (rather than read off the
    fresh row) so the test fails if the production idiom ever drifts
    between ``or 0`` and ``or 1`` — both produce 1 from a None baseline
    and the assertion would silently mask the divergence otherwise."""
    interview, tenant = await _make_demo_setup(db, is_demo=True)
    interview.version = 5
    await db.commit()

    monkeypatch.setattr(
        "app.modules.ai.llm_client.generate_json",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("LLM must not be called")
        ),
    )

    analyze_interview_task.run(str(interview.id), str(tenant.id))

    refreshed = (
        await db.execute(
            select(Interview)
            .where(Interview.id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.version == 6


@pytest.mark.asyncio
async def test_killswitch_analyze_sends_notification(
    db: AsyncSession, killswitch_on, monkeypatch
):
    """Killswitch must still fire N-06 analysis_ready so the demo user
    sees feedback in the activity timeline."""
    interview, tenant = await _make_demo_setup(db, is_demo=True)

    monkeypatch.setattr(
        "app.modules.ai.llm_client.generate_json",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("LLM must not be called")
        ),
    )

    calls: list[dict] = []

    def _capture_notify(*_args, **kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(
        "app.modules.recruitment.notifications.notify_sync", _capture_notify
    )

    analyze_interview_task.run(str(interview.id), str(tenant.id))

    assert any(
        c.get("event") == "recruitment.interview.analysis_ready" for c in calls
    )


@pytest.mark.asyncio
async def test_analyze_leaves_killswitch_path_when_env_flag_off(
    db: AsyncSession, killswitch_off, monkeypatch
):
    """HRP-264 review: with ``DEMO_AI_KILLSWITCH=false`` (the new
    product default), demo tenants do NOT short-circuit into the seed
    analysis. Credits + concurrent-session cap regulate spend instead.

    We don't drive the task to completion — once we've proven the
    killswitch shortcut was skipped (no ``demo_killswitch=True`` in
    the result), the rest of the LLM pipeline is covered by the
    paid-tenant tests.
    """
    interview, tenant = await _make_demo_setup(db, is_demo=True)

    reached_llm: list[bool] = []

    def _capture(*args, **kwargs):
        # Sync mock — gets called BEFORE asyncio.run wraps it, so the
        # record lands deterministically. The raise ensures the task's
        # outer try/except marks the run as failed without driving the
        # whole LLM pipeline.
        reached_llm.append(True)
        raise RuntimeError(
            "stop here — proves we left the killswitch path"
        )

    monkeypatch.setattr("app.modules.ai.llm_client.generate_json", _capture)

    with pytest.raises(Exception):  # noqa: BLE001, B017
        analyze_interview_task.run(str(interview.id), str(tenant.id))
    assert reached_llm, "expected the real LLM call when killswitch is off"


@pytest.mark.asyncio
async def test_transcribe_leaves_killswitch_path_when_env_flag_off(
    db: AsyncSession, killswitch_off, monkeypatch
):
    """HRP-264 review mirror for transcribe — confirm the killswitch
    seed shortcut is bypassed when the env flag is off. We don't drive
    the real provider (demo interviews in the fixture have no file_id,
    so the task fails earlier with "Object storage unavailable"); the
    observation that matters is ``demo_killswitch`` is NOT in the
    response."""
    interview, tenant = await _make_demo_setup(db, is_demo=True)
    interview.transcription_status = "pending"
    interview.transcript = None
    await db.commit()

    result = transcribe_interview_task.run(str(interview.id), str(tenant.id))
    assert result.get("demo_killswitch") is not True, (
        "killswitch shortcut should be skipped when DEMO_AI_KILLSWITCH=false"
    )


@pytest.mark.asyncio
async def test_killswitch_transcribe_sends_notification(
    db: AsyncSession, killswitch_on, monkeypatch
):
    """Killswitch transcribe must still fire N-05 transcript_ready."""
    interview, tenant = await _make_demo_setup(db, is_demo=True)
    interview.transcription_status = "pending"
    interview.transcript = None
    await db.commit()

    calls: list[dict] = []

    def _capture_notify(*_args, **kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(
        "app.modules.recruitment.notifications.notify_sync", _capture_notify
    )

    transcribe_interview_task.run(str(interview.id), str(tenant.id))

    assert any(
        c.get("event") == "recruitment.interview.transcript_ready" for c in calls
    )
