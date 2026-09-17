"""HRP-813: a demo sandbox emails at most DEMO_INVITATION_LIMIT invitations.

The visitor is anonymous and picks the addresses, and ``POST
/invitations/bulk`` took a hundred of them per request, again and again.
"""

import asyncio
import uuid

import pytest
from app.core.errors import AppError
from app.modules.auth import service
from app.modules.auth.schemas import InvitationCreate, InvitationEmailUpdate
from sqlalchemy.ext.asyncio import AsyncSession

LIMIT = service.DEMO_INVITATION_LIMIT


def _invite(n: int) -> InvitationCreate:
    return InvitationCreate(
        email=f"guest-{n}-{uuid.uuid4().hex[:6]}@example.com",
        name=f"Guest {n}",
        role_code="admin",
    )


@pytest.fixture
def mails(monkeypatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(
        service, "send_invitation_email", lambda to, *a, **k: sent.append(to)
    )
    monkeypatch.setattr(
        service, "send_invitation_reminder_email", lambda to, *a, **k: sent.append(to)
    )
    return sent


@pytest.fixture
async def demo_tenant(db: AsyncSession, tenant):
    tenant.is_demo = True
    await db.commit()
    return tenant


async def test_demo_invites_up_to_the_limit(db, demo_tenant, user, mails):
    for n in range(LIMIT):
        await service.create_invitation(db, demo_tenant.id, user.id, _invite(n))

    with pytest.raises(AppError) as exc:
        await service.create_invitation(db, demo_tenant.id, user.id, _invite(LIMIT))

    assert exc.value.status_code == 429
    assert exc.value.code == "demo_invitation_limit_reached"
    assert len(mails) == LIMIT


async def test_regular_tenant_has_no_limit(db, tenant, user, mails):
    for n in range(LIMIT + 1):
        await service.create_invitation(db, tenant.id, user.id, _invite(n))

    assert len(mails) == LIMIT + 1


async def test_bulk_goes_through_the_same_limit(demo_tenant, auth_client, mails):
    invitations = [_invite(n).model_dump(mode="json") for n in range(LIMIT + 2)]

    resp = await auth_client.post(
        "/api/invitations/bulk", json={"invitations": invitations}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert len(body["created"]) == LIMIT
    assert [f["error_code"] for f in body["failed"]] == [
        "demo_invitation_limit_reached"
    ] * 2
    assert len(mails) == LIMIT


async def test_parallel_requests_share_the_limit(
    demo_tenant, user, session_factory, mails
):
    async def attempt(n: int) -> bool:
        async with session_factory() as session:
            try:
                await service.create_invitation(
                    session,
                    demo_tenant.id,
                    user.id,
                    _invite(n),
                    inviter_role_codes=["admin"],
                )
            except AppError as exc:
                assert exc.code == "demo_invitation_limit_reached"
                return False
            return True

    results = await asyncio.gather(*(attempt(n) for n in range(LIMIT * 2)))

    assert results.count(True) == LIMIT
    assert len(mails) == LIMIT


async def test_demo_neither_resends_nor_readdresses(db, demo_tenant, user, mails):
    inv = await service.create_invitation(db, demo_tenant.id, user.id, _invite(0))

    with pytest.raises(AppError) as resend:
        await service.resend_invitation(db, demo_tenant.id, inv["id"])
    with pytest.raises(AppError) as readdress:
        await service.update_invitation_email(
            db,
            demo_tenant.id,
            inv["id"],
            InvitationEmailUpdate(email="someone-else@example.com"),
        )

    assert resend.value.code == "demo_invitation_resend_unavailable"
    assert readdress.value.code == "demo_invitation_resend_unavailable"
    assert len(mails) == 1
