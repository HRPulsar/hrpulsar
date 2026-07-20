"""HRP-253 (D5): interview upload guard for demo tenants.

Three layers:

1. :func:`_validate_upload_payload` rejects audio/video and shrinks the
   transcript size limit when ``is_demo=True``. Unit-level — no DB.
2. :func:`_enforce_demo_upload_quota` counts uploads per tenant in Redis
   with TTL pinned to the demo session lifetime. Hits the real Redis
   on ``settings.redis_url`` (docker compose stands one up; the
   existing ``test_demo_start.py`` uses the same instance).
3. :func:`enqueue_transcribe` refuses to schedule a Whisper job for a
   demo tenant — defense-in-depth that catches an attempt to
   transcribe a stale media file attached out-of-band.

Pasted text transcripts are deliberately not counted: the demo flow is
designed around the text-paste path, so charging it against the upload
quota would defeat the feature.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from app.config import settings as app_settings
from app.modules.company.models import Tenant
from app.modules.recruitment.interview_service import (
    _enforce_demo_upload_quota,
    _validate_upload_payload,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# _validate_upload_payload — pure function, no DB / Redis needed
# ---------------------------------------------------------------------------


def test_validate_demo_rejects_audio_mp3():
    with pytest.raises(HTTPException) as exc:
        _validate_upload_payload(
            "audio/mpeg", 1024, "audio", is_demo=True
        )
    assert exc.value.status_code == 415
    # HRP-276 / L5: neutral message — must NOT leak that this is a
    # demo tenant. Wording is "not allowed for this account".
    assert "demo" not in exc.value.detail.lower()
    assert "not allowed" in exc.value.detail.lower()


def test_validate_demo_rejects_video_mp4():
    with pytest.raises(HTTPException) as exc:
        _validate_upload_payload(
            "video/mp4", 1024, "video", is_demo=True
        )
    assert exc.value.status_code == 415


def test_validate_demo_accepts_text_plain():
    _validate_upload_payload(
        "text/plain", 2048, "text_transcript", is_demo=True
    )  # no raise


def test_validate_demo_accepts_pdf_within_limit():
    # Default DEMO_MAX_UPLOAD_MB = 5 MiB.
    _validate_upload_payload(
        "application/pdf",
        4 * 1024 * 1024,
        "text_transcript",
        is_demo=True,
    )  # no raise


def test_validate_demo_rejects_pdf_over_limit():
    over = (app_settings.demo_max_upload_mb + 1) * 1024 * 1024
    with pytest.raises(HTTPException) as exc:
        _validate_upload_payload(
            "application/pdf", over, "text_transcript", is_demo=True
        )
    assert exc.value.status_code == 413
    # HRP-276 / L5: neutral "upload limit" wording, no "demo" oracle.
    assert "demo" not in exc.value.detail.lower()
    assert "upload limit" in exc.value.detail.lower()


def test_validate_paid_audio_still_works():
    """Regression — the demo flag is OFF by default, paid tenants keep
    the full media path."""
    _validate_upload_payload(
        "audio/mp3", 10 * 1024 * 1024, "audio", is_demo=False
    )  # no raise


def test_validate_paid_transcript_keeps_original_10mb_cap():
    # 8 MiB pdf — within the 10 MiB paid cap, well above the 5 MiB demo cap.
    _validate_upload_payload(
        "application/pdf",
        8 * 1024 * 1024,
        "text_transcript",
        is_demo=False,
    )  # no raise


# ---------------------------------------------------------------------------
# _enforce_demo_upload_quota — Redis-backed counter
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def isolated_demo_tenant_id():
    """Random tenant uuid + Redis cleanup so concurrent test runs don't
    collide on ``demo:uploads:{id}``."""
    import contextlib

    import redis.asyncio as aioredis

    tid = uuid.uuid4()
    yield tid
    client = aioredis.from_url(app_settings.redis_url, decode_responses=True)
    try:
        await client.delete(f"demo:uploads:{tid}")
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_demo_upload_quota_allows_within_cap(
    isolated_demo_tenant_id, monkeypatch
):
    monkeypatch.setattr(app_settings, "demo_quota_uploads", 2)

    await _enforce_demo_upload_quota(isolated_demo_tenant_id)  # 1st
    await _enforce_demo_upload_quota(isolated_demo_tenant_id)  # 2nd, still ok


@pytest.mark.asyncio
async def test_demo_upload_quota_blocks_third(
    isolated_demo_tenant_id, monkeypatch
):
    monkeypatch.setattr(app_settings, "demo_quota_uploads", 2)

    await _enforce_demo_upload_quota(isolated_demo_tenant_id)
    await _enforce_demo_upload_quota(isolated_demo_tenant_id)

    with pytest.raises(HTTPException) as exc:
        await _enforce_demo_upload_quota(isolated_demo_tenant_id)
    assert exc.value.status_code == 429
    assert exc.value.detail == "Upload quota exhausted"


@pytest.mark.asyncio
async def test_demo_upload_quota_zero_disables_counter(
    isolated_demo_tenant_id, monkeypatch
):
    monkeypatch.setattr(app_settings, "demo_quota_uploads", 0)

    # Without the cap nothing accrues — call ten times, no 429.
    for _ in range(10):
        await _enforce_demo_upload_quota(isolated_demo_tenant_id)


@pytest.mark.asyncio
async def test_demo_upload_quota_sets_ttl(
    isolated_demo_tenant_id, monkeypatch
):
    """TTL pinned to the session lifetime — otherwise the counter would
    outlive the sandbox and 429 a fresh demo tenant that happened to
    inherit the same uuid (effectively never, but make it explicit)."""
    import contextlib

    import redis.asyncio as aioredis

    monkeypatch.setattr(app_settings, "demo_quota_uploads", 5)
    monkeypatch.setattr(app_settings, "demo_session_ttl_seconds", 9999)

    await _enforce_demo_upload_quota(isolated_demo_tenant_id)

    client = aioredis.from_url(app_settings.redis_url, decode_responses=True)
    try:
        ttl = await client.ttl(f"demo:uploads:{isolated_demo_tenant_id}")
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()  # type: ignore[attr-defined]
    assert 0 < ttl <= 9999


# ---------------------------------------------------------------------------
# enqueue_transcribe — defense-in-depth
# ---------------------------------------------------------------------------


async def _make_tenant(db: AsyncSession, *, is_demo: bool) -> Tenant:
    suffix = uuid.uuid4().hex[:6]
    t = Tenant(name=f"T {suffix}", slug=f"t-{suffix}", is_demo=is_demo)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@pytest.mark.asyncio
async def test_enqueue_transcribe_refuses_demo_tenant_with_real_interview(
    db: AsyncSession,
):
    """Existence check fires first (404 for unknown ids), then demo gate
    (409 once the interview is confirmed). Pins the order so we don't
    regress into a 409-vs-404 oracle on random uuids."""
    from app.modules.recruitment.interview_service import enqueue_transcribe
    from app.modules.recruitment.models import (
        Candidate,
        CandidateVacancy,
        Interview,
        Vacancy,
    )

    tenant = await _make_tenant(db, is_demo=True)

    vacancy = Vacancy(tenant_id=tenant.id, title="V", language="en")
    db.add(vacancy)
    await db.commit()
    await db.refresh(vacancy)
    candidate = Candidate(
        tenant_id=tenant.id, full_name="C", email="c@example.com"
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
        transcript="t",
        transcription_status="pending",
        analysis_status="pending",
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)

    with pytest.raises(HTTPException) as exc:
        await enqueue_transcribe(db, tenant.id, interview.id)
    assert exc.value.status_code == 409
    # HRP-276 / L5: neutral wording, no "demo" oracle.
    assert "demo" not in exc.value.detail.lower()
    assert "not allowed" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_enqueue_transcribe_unknown_id_returns_404_not_demo_409(
    db: AsyncSession,
):
    """The demo gate must run AFTER the existence check so a bogus
    interview_id returns 404 regardless of tenant class — otherwise the
    status code leaks tenant_is_demo to id-enumeration attackers."""
    from app.modules.recruitment.interview_service import enqueue_transcribe

    tenant = await _make_tenant(db, is_demo=True)

    with pytest.raises(HTTPException) as exc:
        await enqueue_transcribe(db, tenant.id, uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_complete_upload_blocks_audio_kind_in_demo(db: AsyncSession):
    """A demo tenant that passes the init gate with text/plain must NOT
    be able to flip kind to 'audio' on complete — that would leak
    arbitrary binary into S3 even though enqueue_transcribe still 409s."""
    from app.modules.recruitment.interview_service import (
        complete_interview_upload,
    )
    from app.modules.recruitment.models import (
        Candidate,
        CandidateVacancy,
        Interview,
        Vacancy,
    )
    from app.modules.recruitment.schemas import CompleteUploadRequest

    tenant = await _make_tenant(db, is_demo=True)

    vacancy = Vacancy(tenant_id=tenant.id, title="V", language="en")
    db.add(vacancy)
    candidate = Candidate(
        tenant_id=tenant.id, full_name="C", email="c@example.com"
    )
    db.add_all([vacancy, candidate])
    await db.commit()
    await db.refresh(vacancy)
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
        consent_signed_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)

    data = CompleteUploadRequest(upload_id="up", parts=[])

    with pytest.raises(HTTPException) as exc:
        await complete_interview_upload(
            db,
            tenant.id,
            uuid.uuid4(),
            interview.id,
            data,
            kind="audio",
            mime_type="audio/mpeg",
        )
    assert exc.value.status_code == 415
    # HRP-276 / L5: neutral message in HTTPException detail.
    assert "demo" not in exc.value.detail.lower()
    assert "not allowed" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_complete_upload_rejects_demo_text_over_size_cap(
    db: AsyncSession, monkeypatch
):
    """HRP-276 / M8: ``init_interview_upload`` enforces a per-tenant
    size cap up-front, but S3 does not refuse parts above it. On
    complete we re-read the final ``ContentLength`` and bail if it
    exceeded ``demo_max_upload_mb`` between init and complete — and
    we abort the multipart upload so the blob is not durably stored.
    """
    from app.modules.recruitment.interview_service import (
        complete_interview_upload,
    )
    from app.modules.recruitment.models import (
        Candidate,
        CandidateVacancy,
        Interview,
        Vacancy,
    )
    from app.modules.recruitment.schemas import CompleteUploadRequest

    monkeypatch.setattr(app_settings, "demo_max_upload_mb", 5)

    tenant = await _make_tenant(db, is_demo=True)
    vacancy = Vacancy(tenant_id=tenant.id, title="V", language="en")
    candidate = Candidate(
        tenant_id=tenant.id, full_name="C", email="c-m8@example.com"
    )
    db.add_all([vacancy, candidate])
    await db.commit()
    await db.refresh(vacancy)
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
        consent_signed_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)

    # Stub the S3 helpers — make complete succeed and report a
    # ContentLength one byte over the 5 MiB demo cap. Track that
    # delete_file was called for the finalized object (review fix:
    # abort_multipart_upload is a no-op once complete has returned).
    deleted: dict[str, bool] = {"called": False}

    def _complete_ok(*_args, **_kwargs):
        return "s3://bucket/key"

    def _head_over_limit(_key):
        return {"ContentLength": 5 * 1024 * 1024 + 1}

    def _delete_file(_path):
        deleted["called"] = True
        return True

    monkeypatch.setattr(
        "app.core.s3.complete_multipart_upload", _complete_ok
    )
    monkeypatch.setattr("app.core.s3.head_object", _head_over_limit)
    monkeypatch.setattr("app.core.s3.delete_file", _delete_file)

    data = CompleteUploadRequest(upload_id="up-1", parts=[])
    with pytest.raises(HTTPException) as exc:
        await complete_interview_upload(
            db,
            tenant.id,
            uuid.uuid4(),
            interview.id,
            data,
            kind="text_transcript",
            mime_type="text/plain",
        )
    assert exc.value.status_code == 413
    assert deleted["called"] is True


@pytest.mark.asyncio
async def test_demo_upload_quota_ttl_anchored_to_first_increment(
    isolated_demo_tenant_id, monkeypatch
):
    """pipe.expire(..., nx=True) anchors TTL to the first INCR — a
    retrying client cannot slide expiry out indefinitely by hammering
    the endpoint.

    Strategy: first call sets TTL to 60 s; second call (with a smaller
    configured TTL) must NOT shrink the existing TTL because nx=True
    skips EXPIRE when one already exists.
    """
    import contextlib

    import redis.asyncio as aioredis

    monkeypatch.setattr(app_settings, "demo_quota_uploads", 10)
    monkeypatch.setattr(app_settings, "demo_session_ttl_seconds", 60)

    await _enforce_demo_upload_quota(isolated_demo_tenant_id)

    client = aioredis.from_url(app_settings.redis_url, decode_responses=True)
    try:
        first_ttl = await client.ttl(
            f"demo:uploads:{isolated_demo_tenant_id}"
        )
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()  # type: ignore[attr-defined]
    assert 0 < first_ttl <= 60

    monkeypatch.setattr(app_settings, "demo_session_ttl_seconds", 5)
    await _enforce_demo_upload_quota(isolated_demo_tenant_id)

    client = aioredis.from_url(app_settings.redis_url, decode_responses=True)
    try:
        second_ttl = await client.ttl(
            f"demo:uploads:{isolated_demo_tenant_id}"
        )
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()  # type: ignore[attr-defined]
    # Original 60 s anchor must hold; if nx=True wasn't applied the TTL
    # would have been overwritten to the new 5 s window.
    assert second_ttl > 5, (
        f"TTL was overwritten on retry (expected anchor ~60 s, got {second_ttl})"
    )
