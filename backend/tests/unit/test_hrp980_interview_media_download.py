"""HRP-980 (QA 21.10): the interview recording has a Download.

Whoever runs hiring on the vacancy (admin, HR, recruiter by default)
downloads it; a hiring manager named on the vacancy plays it back but
gets a 403 from the download link. Every click signs a fresh link that
saves the file under its own name - never the expired playback link
that S3 answers with an XML error.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import pytest
import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import Role, User, user_roles
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
    Vacancy,
)
from app.modules.storage.models import File
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _user(db: AsyncSession, tenant, code: str) -> User:
    role = (await db.execute(select(Role).where(Role.code == code))).scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    u = User(
        email=f"{code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name=code,
        last_name="X",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    return (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == u.id)
        )
    ).scalar_one()


def _headers(u: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(u.id), str(u.tenant_id))}"
    }


@pytest_asyncio.fixture
async def recorded(db: AsyncSession, tenant, monkeypatch):
    signed: list[dict] = []

    def _presign(path, expires_in=3600, *, content_disposition=None, **_):
        signed.append({"path": path, "disposition": content_disposition})
        return f"https://s3/{path}?n={len(signed)}"

    monkeypatch.setattr("app.core.s3.get_presigned_url", _presign)

    users = {
        code: await _user(db, tenant, code)
        for code in ("admin", "hr", "recruiter", "hiring_manager")
    }
    vacancy = Vacancy(
        tenant_id=tenant.id,
        title="Backend",
        owner_id=users["recruiter"].id,
        hiring_manager_id=users["hiring_manager"].id,
    )
    candidate = Candidate(
        tenant_id=tenant.id, full_name="Elena Volkova", email="elena@example.com"
    )
    db.add_all([vacancy, candidate])
    await db.commit()
    cv = CandidateVacancy(
        tenant_id=tenant.id, candidate_id=candidate.id, vacancy_id=vacancy.id
    )
    db.add(cv)
    await db.commit()
    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        type="audio",
        status="completed",
    )
    db.add(interview)
    await db.commit()
    file_row = File(
        tenant_id=tenant.id,
        name="recording.mp3",
        original_name="Vorstellungsgespräch — Elena Vogel.mp3",
        path=f"tenants/{tenant.id}/interviews/{interview.id}/recording.mp3",
        size=1024,
        mime_type="audio/mpeg",
        uploaded_by=users["recruiter"].id,
        entity_type="interview",
        entity_id=interview.id,
    )
    db.add(file_row)
    await db.commit()
    interview.audio_file_id = file_row.id
    await db.commit()
    return {"users": users, "interview": interview, "signed": signed}


@pytest.mark.parametrize("code", ["admin", "hr", "recruiter"])
async def test_whoever_runs_hiring_downloads_under_the_file_name(
    client: AsyncClient, recorded, code: str
):
    path = f"/api/recruitment/interviews/{recorded['interview'].id}/media-download-url"
    first = await client.get(path, headers=_headers(recorded["users"][code]))
    again = await client.get(path, headers=_headers(recorded["users"][code]))
    assert first.status_code == again.status_code == 200, first.text
    # A fresh link on every click, never a cached one.
    assert first.json()["url"] != again.json()["url"]
    assert first.json()["kind"] == "audio"
    assert first.json()["expires_in"] == 300
    disposition = recorded["signed"][-1]["disposition"]
    assert disposition.startswith("attachment;")
    assert (
        unquote(disposition.split("filename*=UTF-8''")[1])
        == "Vorstellungsgespräch — Elena Vogel.mp3"
    )


async def test_the_hiring_manager_plays_it_but_cannot_download(
    client: AsyncClient, recorded
):
    headers = _headers(recorded["users"]["hiring_manager"])
    interview_id = recorded["interview"].id
    play = await client.get(
        f"/api/recruitment/interviews/{interview_id}/media-url", headers=headers
    )
    assert play.status_code == 200, play.text
    # Playback stays inline - the player streams it.
    assert recorded["signed"][-1]["disposition"] is None

    download = await client.get(
        f"/api/recruitment/interviews/{interview_id}/media-download-url",
        headers=headers,
    )
    assert download.status_code == 403
    assert len(recorded["signed"]) == 1


_PAGE = (
    Path(__file__).resolve().parents[3]
    / "frontend/src/app/(dashboard)/recruitment/interviews/[id]/page.tsx"
)


@pytest.mark.skipif(not _PAGE.exists(), reason="frontend tree not present")
def test_the_page_calls_the_download_url_the_app_serves():
    urls = re.findall(
        r"/recruitment/interviews/\$\{[^}]*\}/media[^`\"'?]*", _PAGE.read_text("utf-8")
    )
    referenced = {"/api" + re.sub(r"\$\{[^}]*\}", "{}", u) for u in urls}
    mounted = {
        re.sub(r"\{[^}]*\}", "{}", getattr(route, "path", "")) for route in app.routes
    }
    assert "/api/recruitment/interviews/{}/media-download-url" in referenced
    assert referenced <= mounted, sorted(referenced - mounted)
