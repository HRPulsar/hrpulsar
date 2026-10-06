"""HRP-927: saved public checks become Coverage processes of the visitor's
new workspace - on the approval of a SaaS signup request (a), on the
confirmed email of an open registration (b), and by the button of "my
checks" (c).

The unit database keeps rows between tests: every test uses addresses of
its own and looks only at its own tenant.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings
from app.core.security import create_email_verification_token
from app.modules.auth import service as auth_service
from app.modules.auth.models import Role
from app.modules.auth.schemas import RegisterRequest
from app.modules.primitives import catalog_data
from app.modules.primitives.models import Primitive
from app.modules.public_check import move, service
from app.modules.public_check.models import PublicCheck, PublicCheckEmail
from app.modules.public_check.schemas import CheckResult
from app.modules.signup.models import SignupRequest
from app.modules.signup.service import approve_signup
from app.modules.work import coverage
from app.modules.work.models import WorkContainer, WorkStep, WorkStepPrimitive
from sqlalchemy import select, update

from tests.unit.test_ai_workforce_router import _user_with_role

pytestmark = pytest.mark.asyncio

API = "/api/public-check"
DESCRIPTION = "Pay supplier invoices\nfrom the shared inbox to the bank run"


def _step(position, title, codes, *, mode="draft_then_review", hours=2.0, runs=12,
          responsibility="none", output_type="draft"):  # fmt: skip
    return {
        "position": position,
        "title": title,
        "description": f"{title}, step by step",
        "codes": codes,
        "hours_per_run": hours,
        "runs_per_year": runs,
        "hours_per_year": hours * runs if hours and runs else None,
        "reason": {
            "mode": mode,
            "codes": codes,
            "responsibility": responsibility,
            "output_type": output_type,
        },
    }


# The buckets interleave the process order: the move restores it.
RESULT = CheckResult.model_validate(
    {
        "preliminary": True,
        "catalog_version": catalog_data.CATALOG_VERSION,
        "shares": None,
        "hours": {
            "total": 72,
            "moves": 24,
            "to_review": 24,
            "stays": 24,
            "to_review_after": 12,
            "freed": 36,
            "unestimated": 0,
        },
        "money": None,
        "buckets": {
            "moves": [_step(2, "Match invoices", ["P1"], mode="automatable")],
            "to_review": [_step(1, "Collect invoices", ["P4", "P13", "P4"])],
            "stays": [
                _step(
                    4,
                    "Approve the payment run",
                    ["P6"],
                    mode="blocked_judgment",
                    hours=0.5,
                    runs=52,
                    responsibility="formal",
                    output_type="external_change",
                )
            ],
        },
        "out_of_scope": [
            _step(
                3,
                "File paper copies",
                ["B1"],
                mode="blocked_physical",
                hours=None,
                runs=None,
            ),  # fmt: skip
        ],
    }
).model_dump(mode="json")
ORDER = [
    "Collect invoices",
    "Match invoices",
    "File paper copies",
    "Approve the payment run",
]


@pytest.fixture(autouse=True)
async def _catalog(db, monkeypatch):
    monkeypatch.setattr(settings, "public_check_enabled", True)
    await db.execute(catalog_data.seed_insert())
    await db.commit()


async def _address(db, email=None, *, verified=True) -> tuple[PublicCheckEmail, str]:
    """An address of saved checks and its live "my checks" link."""
    now = datetime.now(UTC)
    magic = f"magic-{uuid.uuid4().hex}"
    row = PublicCheckEmail(
        email=(email or f"mover.{uuid.uuid4().hex[:12]}@example.com").lower(),
        locale="en",
        consent_at=now,
        verified_at=now if verified else None,
        unsubscribe_token_hash=service.hash_token(uuid.uuid4().hex),
        magic_token_hash=service.hash_token(magic),
        magic_expires_at=now + timedelta(hours=1),
    )
    db.add(row)
    await db.commit()
    return row, magic


async def _check(
    db, address, *, status="ready", expires_at=None, result=None, dictated=False
) -> PublicCheck:
    check = PublicCheck(
        token_hash=service.hash_token(uuid.uuid4().hex),
        status=status,
        description=DESCRIPTION,
        answers={"industry": "Logistics", "frequency": "weekly"},
        locale="en",
        result=result or (RESULT if status == "ready" else None),
        email_id=address.id,
        expires_at=expires_at,
        dictated=dictated,
    )
    db.add(check)
    await db.commit()
    return check


async def _containers(db, tenant_id) -> list[WorkContainer]:
    return list(
        (
            await db.scalars(
                select(WorkContainer)
                .where(WorkContainer.tenant_id == tenant_id)
                .order_by(WorkContainer.created_at)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def _fresh(db, check) -> PublicCheck:
    return await db.get(PublicCheck, check.id, populate_existing=True)


async def _steps(db, container_id) -> list[tuple[WorkStep, list[WorkStepPrimitive]]]:
    steps = (
        await db.scalars(
            select(WorkStep)
            .where(WorkStep.container_id == container_id)
            .order_by(WorkStep.position)
        )
    ).all()
    out = []
    for step in steps:
        links = (
            await db.scalars(
                select(WorkStepPrimitive).where(WorkStepPrimitive.step_id == step.id)
            )
        ).all()
        out.append((step, list(links)))
    return out


async def _codes(db, links) -> set[str]:
    ids = [link.primitive_id for link in links]
    by_id = dict(
        (
            await db.execute(
                select(Primitive.id, Primitive.code).where(Primitive.id.in_(ids))
            )
        )
        .tuples()
        .all()
    )
    return {by_id[i] for i in ids}


async def _pending_signup(db, email) -> SignupRequest:
    for code, name in (("admin", "Admin"), ("employee", "Employee")):
        if await db.scalar(select(Role).where(Role.code == code)) is None:
            db.add(Role(name=name, code=code, is_system=True))
    row = SignupRequest(
        email=email,
        first_name="Lead",
        last_name="Mover",
        company_name=f"Movers {uuid.uuid4().hex[:8]}",
        role="founder",
        status="pending_moderation",
        email_verified_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    return row


class TestOnApproval:
    async def test_checks_of_the_confirmed_address_become_draft_processes(self, db):
        address, _ = await _address(db)
        first = await _check(db, address)
        second = await _check(db, address)
        pending = await _check(db, address, status="pending")
        expired = await _check(
            db, address, expires_at=datetime.now(UTC) - timedelta(hours=1)
        )
        # Saved to the address - by anyone - but its own letter not clicked.
        unconfirmed = await _check(
            db, address, expires_at=datetime.now(UTC) + timedelta(days=1)
        )
        # The applicant typed the address in another case.
        row = await _pending_signup(db, address.email.upper())

        row_after, _token, payload = await approve_signup(
            db, row.id, moderator_user_id=None
        )

        assert row_after.status == "approved"
        tenant_id = uuid.UUID(payload["tenant_id"])
        user_id = uuid.UUID(payload["user_id"])
        containers = await _containers(db, tenant_id)
        assert len(containers) == 2
        for container in containers:
            assert container.type == "process"
            assert container.status == "draft"
            assert container.source == "ai"
            assert container.owner_id == user_id
            assert container.title == "Pay supplier invoices"
            # The text the breakdown was made from, answers included.
            assert container.description.startswith(DESCRIPTION)
            assert "Industry: Logistics" in container.description
            assert "every week" in container.description
            assert container.coverage_summary is not None
            steps = await _steps(db, container.id)
            assert [s.title for s, _ in steps] == ORDER
            assert [s.position for s, _ in steps] == [1, 2, 3, 4]
            assert {s.state for s, _ in steps} == {"system_suggested"}
            collect, match, paper, approve = steps
            assert await _codes(db, collect[1]) == {"P4", "P13"}
            assert await _codes(db, match[1]) == {"P1"}
            assert all(
                link.source == "system_suggested" and link.confirmed_at is None
                for _, links in steps
                for link in links
            )
            assert float(approve[0].hours_per_run) == 0.5
            assert approve[0].runs_per_year == 52
            assert approve[0].responsibility == "formal"
            assert approve[0].output_type == "external_change"
            assert paper[0].hours_per_run is None and paper[0].runs_per_year is None
            # Coverage reads it as the model's word, not the company's.
            computed = await coverage.compute(
                db, tenant_id, container.id, schedule_mapping=False, people=False
            )
            assert computed["steps"] and all(r["tentative"] for r in computed["steps"])
        for check in (first, second):
            fresh = await _fresh(db, check)
            assert fresh.moved_at is not None
            assert fresh.moved_tenant_id == tenant_id
        for check in (pending, expired, unconfirmed):
            assert (await _fresh(db, check)).moved_at is None

    async def test_a_dictated_check_moves_with_the_dictation_note(self, db):
        address, _ = await _address(db)
        await _check(db, address, dictated=True)
        row = await _pending_signup(db, address.email)

        _row, _token, payload = await approve_signup(db, row.id, moderator_user_id=None)

        [container] = await _containers(db, uuid.UUID(payload["tenant_id"]))
        assert container.description.startswith(service.DICTATED_NOTE)

    async def test_an_unconfirmed_address_is_not_moved(self, db):
        address, _ = await _address(db, verified=False)
        check = await _check(db, address)
        row = await _pending_signup(db, address.email)

        _, _, payload = await approve_signup(db, row.id, moderator_user_id=None)

        assert await _containers(db, uuid.UUID(payload["tenant_id"])) == []
        assert (await _fresh(db, check)).moved_at is None

    async def test_checks_of_another_address_stay(self, db):
        address, _ = await _address(db)
        check = await _check(db, address)
        row = await _pending_signup(db, f"other.{uuid.uuid4().hex[:8]}@example.com")

        _, _, payload = await approve_signup(db, row.id, moderator_user_id=None)

        assert await _containers(db, uuid.UUID(payload["tenant_id"])) == []
        assert (await _fresh(db, check)).moved_at is None

    async def test_a_failed_move_does_not_fail_the_approval(self, db, monkeypatch):
        address, _ = await _address(db)
        check = await _check(db, address)
        row = await _pending_signup(db, address.email)

        async def _broken(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(move, "move_checks", _broken)
        row_after, token, payload = await approve_signup(
            db, row.id, moderator_user_id=None
        )

        assert row_after.status == "approved" and token
        assert payload["user_email"] == address.email
        assert (await _fresh(db, check)).moved_at is None
        assert await _containers(db, uuid.UUID(payload["tenant_id"])) == []

    async def test_a_code_retired_since_the_check_is_dropped(self, db):
        address, _ = await _address(db)
        await _check(db, address)
        row = await _pending_signup(db, address.email)
        retire = Primitive.__table__.update().where(Primitive.code == "P13")
        await db.execute(retire.values(retired_in="v9.9"))
        await db.commit()
        try:
            _, _, payload = await approve_signup(db, row.id, moderator_user_id=None)
        finally:
            await db.execute(retire.values(retired_in=None))
            await db.commit()

        (container,) = await _containers(db, uuid.UUID(payload["tenant_id"]))
        collect = (await _steps(db, container.id))[0]
        assert collect[0].title == "Collect invoices"
        assert await _codes(db, collect[1]) == {"P4"}


class TestRepeat:
    async def test_a_second_move_creates_nothing(self, db, user, tenant):
        address, _ = await _address(db, user.email)
        await _check(db, address)
        await _check(db, address)

        await move.move_after_signup(db, user)
        await move.move_after_signup(db, user)
        again = await move.move_checks(
            db, tenant_id=tenant.id, user_id=user.id, email=user.email
        )

        assert again == (0, 0)
        assert len(await _containers(db, tenant.id)) == 2

    async def test_two_moves_at_once_move_each_check_once(
        self, db, user, tenant, session_factory, monkeypatch
    ):
        address, _ = await _address(db, user.email)
        await _check(db, address)
        await _check(db, address)
        compute = coverage.compute

        async def _slow(*args, **kwargs):
            # The first move holds its row locks while the second one asks.
            await asyncio.sleep(0.2)
            return await compute(*args, **kwargs)

        monkeypatch.setattr(coverage, "compute", _slow)

        async def _one() -> int:
            async with session_factory() as own:
                moved, _ = await move.move_checks(
                    own, tenant_id=tenant.id, user_id=user.id, email=user.email
                )
                await own.commit()
                return moved

        assert sorted(await asyncio.gather(_one(), _one())) == [0, 2]
        assert len(await _containers(db, tenant.id)) == 2


class TestOpenRegistration:
    def _request(self, email) -> RegisterRequest:
        return RegisterRequest(
            email=email,
            password="long-enough-1",
            first_name="Open",
            last_name="Signup",
            company_name=f"Open {uuid.uuid4().hex[:8]}",
        )

    async def _user(self, db, email):
        from app.modules.auth.models import User

        return await db.scalar(
            select(User)
            .where(User.email == email)
            .execution_options(populate_existing=True)
        )

    async def test_checks_move_once_the_email_is_confirmed(self, db, monkeypatch):
        monkeypatch.setattr(settings, "deployment_mode", "saas")
        monkeypatch.setattr(
            auth_service, "_send_verification_or_log", lambda *a, **k: None
        )
        address, _ = await _address(db)
        check = await _check(db, address)

        await auth_service.register(db, self._request(address.email))
        user = await self._user(db, address.email)
        assert user.email_verified_at is None
        assert await _containers(db, user.tenant_id) == []

        await auth_service.verify_email(
            db, create_email_verification_token(str(user.id))
        )

        assert len(await _containers(db, user.tenant_id)) == 1
        assert (await _fresh(db, check)).moved_tenant_id == user.tenant_id

    async def test_an_auto_verified_registration_moves_at_once(self, db, monkeypatch):
        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        monkeypatch.setattr("app.core.email.email_provider_configured", lambda: False)
        address, _ = await _address(db)
        check = await _check(db, address)

        result = await auth_service.register(db, self._request(address.email))

        assert result["auto_verified"] is True
        user = await self._user(db, address.email)
        assert len(await _containers(db, user.tenant_id)) == 1
        assert (await _fresh(db, check)).moved_at is not None


class TestByLink:
    async def test_the_owner_of_the_address_moves_into_their_workspace(
        self, auth_client, db, user, tenant
    ):
        address, magic = await _address(db, user.email.upper())
        check = await _check(db, address)

        resp = await auth_client.post(f"{API}/mine/{magic}/move")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"moved": 1, "skipped": 0}
        (container,) = await _containers(db, tenant.id)
        assert container.owner_id == user.id
        assert (await _fresh(db, check)).moved_tenant_id == tenant.id
        again = await auth_client.post(f"{API}/mine/{magic}/move")
        assert again.json() == {"moved": 0, "skipped": 0}
        assert len(await _containers(db, tenant.id)) == 1

    async def test_another_signed_in_user_is_403(self, auth_client, db, tenant):
        address, magic = await _address(db)
        check = await _check(db, address)

        resp = await auth_client.post(f"{API}/mine/{magic}/move")

        assert resp.status_code == 403
        assert resp.json()["code"] == "public_check_move_wrong_account"
        assert (await _fresh(db, check)).moved_at is None
        assert await _containers(db, tenant.id) == []

    async def test_a_user_who_may_not_create_processes_is_403(self, client, db, tenant):
        reader, token, _ = await _user_with_role(db, tenant, "employee")
        address, magic = await _address(db, reader.email)
        check = await _check(db, address)

        resp = await client.post(
            f"{API}/mine/{magic}/move", headers={"Authorization": f"Bearer {token}"}
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "auth_insufficient_permissions"
        assert (await _fresh(db, check)).moved_at is None

    async def test_signed_out_dead_link_and_switched_off(
        self, client, auth_client, db, user, monkeypatch
    ):
        address, magic = await _address(db, user.email)
        await _check(db, address)
        anonymous = await client.post(
            f"{API}/mine/{magic}/move", headers={"Authorization": ""}
        )
        assert anonymous.status_code == 401
        await db.execute(
            update(PublicCheckEmail)
            .where(PublicCheckEmail.id == address.id)
            .values(magic_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
        dead = await auth_client.post(f"{API}/mine/{magic}/move")
        assert dead.status_code == 404
        assert dead.json()["code"] == "public_check_link_invalid"
        monkeypatch.setattr(settings, "public_check_enabled", False)
        off = await auth_client.post(f"{API}/mine/{magic}/move")
        assert off.status_code == 404


class TestMyChecks:
    async def test_the_list_says_whether_to_sign_in_and_what_moved(
        self, client, db, user, tenant
    ):
        address, magic = await _address(db, user.email)
        await _check(db, address)
        stranger, stranger_magic = await _address(db)
        await _check(db, stranger)

        before = (await client.get(f"{API}/mine/{magic}")).json()
        assert before["account"] is True
        assert [c["moved"] for c in before["checks"]] == [False]
        await move.move_checks(
            db, tenant_id=tenant.id, user_id=user.id, email=user.email
        )
        await db.commit()
        after = (await client.get(f"{API}/mine/{magic}")).json()
        assert [c["moved"] for c in after["checks"]] == [True]
        assert (await client.get(f"{API}/mine/{stranger_magic}")).json()[
            "account"
        ] is False


def _broken(kind: str) -> dict:
    """A snapshot that cannot become a process: ``schema`` - it no longer
    validates; ``table`` - it validates, but a step breaks a CHECK of
    ``work_steps`` (more hours per run than the table allows)."""
    if kind == "schema":
        return {**RESULT, "buckets": {"moves": "not a list"}}
    step = {**RESULT["buckets"]["moves"][0], "hours_per_run": 5000.0}
    return {**RESULT, "buckets": {**RESULT["buckets"], "moves": [step]}}


@pytest.mark.parametrize("kind", ["schema", "table"])
class TestBrokenSnapshot:
    async def test_the_button_moves_the_rest_and_skips_it_every_time(
        self, auth_client, db, user, tenant, kind
    ):
        address, magic = await _address(db, user.email)
        broken = await _check(db, address, result=_broken(kind))
        valid = await _check(db, address)

        resp = await auth_client.post(f"{API}/mine/{magic}/move")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"moved": 1, "skipped": 1}
        assert (await _fresh(db, valid)).moved_tenant_id == tenant.id
        assert (await _fresh(db, broken)).moved_at is None
        (container,) = await _containers(db, tenant.id)
        assert [s.title for s, _ in await _steps(db, container.id)] == ORDER
        # The broken one is selected again and skipped again: no 500.
        again = await auth_client.post(f"{API}/mine/{magic}/move")
        assert again.json() == {"moved": 0, "skipped": 1}
        assert len(await _containers(db, tenant.id)) == 1

    async def test_the_approval_moves_the_rest(self, db, kind):
        address, _ = await _address(db)
        broken = await _check(db, address, result=_broken(kind))
        valid = await _check(db, address)
        row = await _pending_signup(db, address.email)

        row_after, _, payload = await approve_signup(db, row.id, moderator_user_id=None)

        assert row_after.status == "approved"
        tenant_id = uuid.UUID(payload["tenant_id"])
        assert len(await _containers(db, tenant_id)) == 1
        assert (await _fresh(db, valid)).moved_tenant_id == tenant_id
        assert (await _fresh(db, broken)).moved_at is None
