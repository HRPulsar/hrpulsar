"""HRP-926: a visitor keeps their public checks by email - save, confirm,
"my checks" by a 24-hour link, unsubscribe, delete my data, the purge of
unconfirmed addresses.

Letters are caught at ``enqueue_email``; the templates are the migration's
own seed (the unit database is built from metadata, migrations never run).
The unit database keeps rows between tests, so every test uses addresses
of its own.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from app.config import settings
from app.core.redis import redis_client
from app.modules.public_check import router, service
from app.modules.public_check.models import PublicCheck, PublicCheckEmail
from app.modules.work.models import WorkContainer
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

pytestmark = pytest.mark.asyncio

HOST = "check.example.test"
API = "/api/public-check"
_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "hrp926pcsave_public_check_emails.py"
)


def _seed() -> tuple:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._TEMPLATES


@pytest.fixture(autouse=True)
def _service(monkeypatch):
    monkeypatch.setattr(service, "SANDBOX_SLUG", f"pc_save_{uuid.uuid4().hex[:10]}")
    monkeypatch.setattr(settings, "public_check_enabled", True)
    monkeypatch.setattr(settings, "public_check_host", HOST)
    monkeypatch.setattr(settings, "public_check_turnstile_secret", "")
    monkeypatch.setattr(router.limiter, "enabled", False)


@pytest.fixture(autouse=True)
async def _templates(db):
    from app.modules.notification.models import NotificationTemplate

    for code, locale, subject, body in _seed():
        stmt = insert(NotificationTemplate).values(
            code=code, locale=locale, subject_template=subject, body_template=body
        )
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_notification_templates_code_locale",
                set_={"subject_template": subject, "body_template": body},
            )
        )
    await db.commit()


@pytest.fixture(autouse=True)
async def _mail_counters():
    async def _drop():
        async with redis_client() as client:
            keys = await client.keys("public_check:mail:*")
            if keys:
                await client.delete(*keys)

    await _drop()
    yield
    await _drop()


@pytest.fixture
def letters():
    sent: list[dict] = []

    def _catch(to, subject, html_body, **kwargs):
        sent.append({"to": to, "subject": subject, "body": html_body, **kwargs})

    with patch("app.core.email.enqueue_email", side_effect=_catch):
        yield sent


def _address() -> str:
    return f"Visitor.{uuid.uuid4().hex[:12]}@Example.com"


def _owner(token: str) -> str:
    """The owner key the browser that ran the check holds."""
    return f"owner-{token}"


async def _check(db, *, expires_in=timedelta(days=10), result=None) -> tuple:
    token = f"tok-{uuid.uuid4().hex}"
    check = PublicCheck(
        token_hash=service.hash_token(token),
        owner_key_hash=service.hash_token(_owner(token)),
        status="ready" if result else "pending",
        description=f"Close the month\nand more {uuid.uuid4()}",
        answers={},
        locale="en",
        result=result,
        expires_at=datetime.now(UTC) + expires_in if expires_in else None,
    )
    db.add(check)
    await db.commit()
    return token, check


async def _fresh(db, model, row_id):
    return await db.get(model, row_id, populate_existing=True)


async def _row(db, email: str) -> PublicCheckEmail | None:
    return await db.scalar(
        select(PublicCheckEmail)
        .where(PublicCheckEmail.email == email.strip().lower())
        .execution_options(populate_existing=True)
    )


def _link(letter: dict, path: str) -> str:
    found = re.search(rf'https://{re.escape(HOST)}/{path}/([^"]+)"', letter["body"])
    assert found, f"no /{path}/ link in {letter['body']}"
    return found.group(1)


async def _save(client, token, email, **extra):
    """A save by the owner; ``owner_key=None`` sends none (a shared link)."""
    body = {"email": email, "consent": True, "owner_key": _owner(token), **extra}
    body = {k: v for k, v in body.items() if v is not None}
    return await client.post(f"{API}/checks/{token}/save", json=body)


async def _keep(client, letters, token, email, **extra) -> None:
    """A save by the owner and the click of its letter."""
    resp = await _save(client, token, email, **extra)
    assert resp.json() == {"status": "confirm"}
    assert letters[-1]["to"] == email.strip().lower()
    confirm = _link(letters[-1], "confirm")
    assert (await client.post(f"{API}/confirm/{confirm}")).status_code == 200


async def _confirmed(client, db, letters, email, locale="en") -> PublicCheckEmail:
    token, _check_row = await _check(db)
    await _keep(client, letters, token, email, locale=locale)
    return await _row(db, email)


async def _magic(client, letters, email) -> str:
    resp = await client.post(f"{API}/links", json={"email": email})
    assert resp.status_code == 202
    assert letters[-1]["template_code"] == "public_check_magic_link"
    return _link(letters[-1], "my")


class TestSave:
    @pytest.mark.parametrize("consent", [False, None])
    async def test_without_consent_it_is_422_and_nothing_is_saved(
        self, client, db, letters, consent
    ):
        token, check = await _check(db)
        email = _address()
        body = (
            {"email": email}
            if consent is None
            else {"email": email, "consent": consent}
        )
        resp = await client.post(f"{API}/checks/{token}/save", json=body)
        assert resp.status_code == 422
        assert await _row(db, email) is None
        assert (await _fresh(db, PublicCheck, check.id)).email_id is None
        assert letters == []

    async def test_an_unconfirmed_address_gets_a_letter_and_the_term_stays(
        self, client, db, letters
    ):
        token, check = await _check(db)
        term = check.expires_at
        email = _address()
        resp = await _save(client, token, f"  {email} ", marketing=True)
        assert resp.status_code == 200
        assert resp.json() == {"status": "confirm"}

        address = await _row(db, email)
        assert address.email == email.lower()
        assert address.consent_at is not None
        # The opt-in waits on the check until the click.
        assert address.marketing_opt_in is False
        assert address.verified_at is None
        saved = await _fresh(db, PublicCheck, check.id)
        assert saved.email_id == address.id
        assert saved.expires_at == term
        assert saved.confirm_marketing is True

        (letter,) = letters
        assert letter["to"] == email.lower()
        assert letter["template_code"] == "public_check_confirm"
        assert letter.get("tenant_id") is None  # no tenant, no demo gate
        assert "Confirm" in letter["subject"]
        confirm = _link(letter, "confirm")
        # Hashes only, never the clear token - on the check, not the address.
        assert saved.confirm_token_hash == service.hash_token(confirm)
        # Every letter: the unsubscribe link and why it came.
        unsubscribe = _link(letter, "unsubscribe")
        assert address.unsubscribe_token_hash == service.hash_token(unsubscribe)
        assert f"used to save a process check on {HOST}" in letter["body"]

    async def test_a_confirmed_address_still_needs_the_letter_of_the_check(
        self, client, db, letters
    ):
        """A save proves nothing about owning the address: the answer is
        the same as for a new one, and the check is kept - and shown in
        "my checks" - only once the owner clicks its own letter."""
        email = _address()
        await _confirmed(client, db, letters, email)
        magic = await _magic(client, letters, email)
        sent = len(letters)
        token, check = await _check(db)
        resp = await _save(client, token, email.upper())
        assert resp.json() == {"status": "confirm"}
        saved = await _fresh(db, PublicCheck, check.id)
        assert saved.expires_at is not None
        assert saved.email_id == (await _row(db, email)).id
        listed = (await client.get(f"{API}/mine/{magic}")).json()["checks"]
        assert str(check.id) not in [c["id"] for c in listed]
        assert (
            await client.get(f"{API}/mine/{magic}/checks/{check.id}")
        ).status_code == 404

        assert len(letters) == sent + 1
        assert letters[-1]["template_code"] == "public_check_confirm"
        confirm = _link(letters[-1], "confirm")
        assert (await client.post(f"{API}/confirm/{confirm}")).status_code == 200
        assert (await _fresh(db, PublicCheck, check.id)).expires_at is None
        listed = (await client.get(f"{API}/mine/{magic}")).json()["checks"]
        assert str(check.id) in [c["id"] for c in listed]

    @pytest.mark.parametrize("key", [None, "", "owner-of-something-else"])
    async def test_only_the_owner_key_saves_a_shared_link_does_not(
        self, client, db, letters, key
    ):
        token, check = await _check(db)
        email = _address()
        resp = await _save(client, token, email, owner_key=key)
        assert resp.status_code == 403
        assert resp.json()["code"] == "public_check_not_owner"
        assert await _row(db, email) is None
        assert (await _fresh(db, PublicCheck, check.id)).email_id is None
        assert letters == []

    async def test_a_check_without_an_owner_key_cannot_be_saved(
        self, client, db, letters
    ):
        token, check = await _check(db)
        check.owner_key_hash = None
        await db.commit()
        resp = await _save(client, token, _address())
        assert resp.status_code == 403
        assert letters == []

    async def test_the_owner_key_comes_once_with_the_check_and_only_as_a_hash(
        self, client, db, monkeypatch
    ):
        from app.core import task_enqueue

        monkeypatch.setattr(task_enqueue, "enqueue_task", lambda *a, **k: None)
        created = await client.post(
            f"{API}/checks", json={"description": f"We answer requests. {uuid.uuid4()}"}
        )
        assert created.status_code == 202, created.text
        body = created.json()
        row = await db.scalar(
            select(PublicCheck).where(
                PublicCheck.token_hash == service.hash_token(body["token"])
            )
        )
        assert row.owner_key_hash == service.hash_token(body["owner_key"])
        assert body["owner_key"] != body["token"]
        read = (await client.get(f"{API}/checks/{body['token']}")).json()
        assert "owner_key" not in read and body["owner_key"] not in str(read)

    async def test_the_click_opts_in_and_never_takes_an_unsubscribe_back(
        self, client, db, letters
    ):
        email = _address()
        first, _ = await _check(db)
        await _keep(client, letters, first, email, marketing=True)
        address = await _row(db, email)
        assert address.marketing_opt_in is True
        assert address.marketing_opt_in_at is not None
        link = _link(letters[-1], "unsubscribe")
        await client.post(f"{API}/unsubscribe/{link}")
        unsubscribed = (await _row(db, email)).unsubscribed_at
        second, _ = await _check(db)
        await _keep(client, letters, second, email, marketing=True)
        address = await _row(db, email)
        assert address.unsubscribed_at == unsubscribed
        assert address.marketing_opt_in is False

    async def test_a_strangers_save_changes_nothing_on_the_address(
        self, client, db, letters
    ):
        """An existing address keeps its language, consent and opt-in, and
        the owner's letter of another check keeps working."""
        email = _address()
        own, own_check = await _check(db)
        await _save(client, own, email, locale="de")
        own_link = _link(letters[-1], "confirm")
        before = await _row(db, email)
        planted, planted_check = await _check(db)
        await _save(client, planted, email, locale="en", marketing=True)
        after = await _row(db, email)
        assert (after.locale, after.consent_at, after.marketing_opt_in) == (
            "de",
            before.consent_at,
            False,
        )
        assert (await client.post(f"{API}/confirm/{own_link}")).status_code == 200
        assert (await _fresh(db, PublicCheck, own_check.id)).expires_at is None
        # The owner's click confirms their own check only, nor opts them in.
        assert (await _fresh(db, PublicCheck, planted_check.id)).expires_at is not None
        assert (await _row(db, email)).marketing_opt_in is False

    async def test_a_kept_check_cannot_be_moved_to_another_address(
        self, client, db, letters
    ):
        owner = _address()
        token, check = await _check(db)
        await _keep(client, letters, token, owner)
        sent = len(letters)
        stranger = _address()
        resp = await _save(client, token, stranger)
        assert resp.status_code == 409
        assert resp.json()["code"] == "public_check_already_saved"
        assert (await _fresh(db, PublicCheck, check.id)).email_id == (
            await _row(db, owner)
        ).id
        assert await _row(db, stranger) is None
        assert len(letters) == sent

    async def test_a_save_does_not_change_a_confirmed_address(
        self, client, db, letters
    ):
        email = _address()
        before = await _confirmed(client, db, letters, email, locale="de")
        assert before.marketing_opt_in is False
        token, _ = await _check(db)
        await _save(client, token, email, locale="en", marketing=True)
        after = await _row(db, email)
        assert (after.locale, after.marketing_opt_in) == ("de", False)

    async def test_letters_per_address_are_capped_and_each_confirms_its_check(
        self, client, db, letters
    ):
        email = _address()
        checks = []
        for _ in range(service.MAIL_CAP + 1):
            token, check = await _check(db)
            assert (await _save(client, token, email)).json() == {"status": "confirm"}
            checks.append(check)
        assert len(letters) == service.MAIL_CAP
        for letter in letters:
            confirm = _link(letter, "confirm")
            assert (await client.post(f"{API}/confirm/{confirm}")).status_code == 200
        for check in checks[:-1]:
            assert (await _fresh(db, PublicCheck, check.id)).expires_at is None
        # The capped save got no letter: it waits for one.
        assert (await _fresh(db, PublicCheck, checks[-1].id)).expires_at is not None

    async def test_an_expired_or_unknown_check_is_404(self, client, db, letters):
        token, _ = await _check(db, expires_in=timedelta(seconds=-1))
        for key in (token, "no-such-token"):
            resp = await _save(client, key, _address())
            assert resp.status_code == 404
            assert resp.json()["code"] == "public_check_not_found"
        assert letters == []

    async def test_a_failed_captcha_saves_nothing(
        self, client, db, letters, monkeypatch
    ):
        asked = []

        async def _refuse(secret, token, remote_ip=None, action=None, hostname=None):
            asked.append((token, action, hostname))
            return False

        monkeypatch.setattr(router, "verify_turnstile", _refuse)
        token, check = await _check(db)
        email = _address()
        resp = await _save(client, token, email, turnstile_token="tt")
        assert resp.status_code == 400
        assert resp.json()["code"] == "public_check_captcha_failed"
        assert asked == [("tt", router.ACTION_SAVE, HOST)]
        assert await _row(db, email) is None
        assert (await _fresh(db, PublicCheck, check.id)).email_id is None
        assert letters == []

    async def test_saves_have_an_ip_bucket_of_their_own(
        self, client, db, letters, monkeypatch
    ):
        monkeypatch.setattr(router.limiter, "enabled", True)
        monkeypatch.setattr(settings, "public_check_rate_limit", "2/hour")
        router.limiter.reset()
        visitor = {"X-Forwarded-For": "203.0.113.77"}
        try:
            token, _ = await _check(db)
            for _ in range(2):
                resp = await client.post(
                    f"{API}/checks/{token}/save",
                    json={
                        "email": _address(),
                        "consent": True,
                        "owner_key": _owner(token),
                    },
                    headers=visitor,
                )
                assert resp.status_code == 200
            refused = await client.post(
                f"{API}/links", json={"email": _address()}, headers=visitor
            )
            assert refused.status_code == 429
            assert refused.json()["code"] == "public_check_rate_limited"
            assert int(refused.headers["Retry-After"]) >= 1
            # The bucket of new checks is untouched by the saves.
            created = await client.post(
                f"{API}/checks",
                json={"description": f"We answer requests. {uuid.uuid4()}"},
                headers=visitor,
            )
            assert created.status_code == 202, created.text
        finally:
            router.limiter.reset()

    async def test_the_service_off_is_404_everywhere(self, client, monkeypatch):
        monkeypatch.setattr(settings, "public_check_enabled", False)
        calls = [
            client.post(f"{API}/checks/t/save", json={}),
            client.post(f"{API}/links", json={}),
            client.post(f"{API}/confirm/t"),
            client.post(f"{API}/unsubscribe/t"),
            client.get(f"{API}/mine/t"),
            client.get(f"{API}/mine/t/checks/{uuid.uuid4()}"),
            client.delete(f"{API}/mine/t"),
        ]
        for call in calls:
            resp = await call
            assert resp.status_code == 404
            assert resp.json()["code"] == "public_check_not_found"


class TestConfirm:
    async def test_it_lifts_the_term_of_its_own_check_only_and_is_idempotent(
        self, client, db, letters
    ):
        email = _address()
        first, check_a = await _check(db)
        second, check_b = await _check(db)
        await _save(client, first, email)
        link_a = _link(letters[-1], "confirm")
        await _save(client, second, email)
        confirm = _link(letters[-1], "confirm")
        for _ in range(2):
            resp = await client.post(f"{API}/confirm/{confirm}")
            assert resp.status_code == 200
            assert resp.json() == {"status": "confirmed"}
        assert (await _row(db, email)).verified_at is not None
        assert (await _fresh(db, PublicCheck, check_b.id)).expires_at is None
        assert (await _fresh(db, PublicCheck, check_a.id)).expires_at is not None
        # Expired before the click: it stays expired for the purge.
        await db.execute(
            update(PublicCheck)
            .where(PublicCheck.id == check_a.id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
        resp = await client.post(f"{API}/confirm/{link_a}")
        assert resp.json()["code"] == "public_check_link_invalid"
        assert (await _fresh(db, PublicCheck, check_a.id)).expires_at is not None

    async def test_an_expired_replaced_or_unknown_link_is_refused(
        self, client, db, letters
    ):
        email = _address()
        token, check = await _check(db)
        await _save(client, token, email)
        old = _link(letters[-1], "confirm")
        await _save(client, token, email)
        new = _link(letters[-1], "confirm")
        await db.execute(
            update(PublicCheck)
            .where(PublicCheck.id == check.id)
            .values(confirm_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
        for link in (old, new, "nothing-like-it"):
            resp = await client.post(f"{API}/confirm/{link}")
            assert resp.status_code == 404
            assert resp.json()["code"] == "public_check_link_invalid"
        assert (await _row(db, email)).verified_at is None
        assert (await _fresh(db, PublicCheck, check.id)).expires_at is not None

    async def test_a_kept_check_reads_its_old_link_as_fine(self, client, db, letters):
        email = _address()
        token, check = await _check(db)
        await _keep(client, letters, token, email)
        confirm = _link(letters[-1], "confirm")
        await db.execute(
            update(PublicCheck)
            .where(PublicCheck.id == check.id)
            .values(confirm_expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await db.commit()
        assert (await client.post(f"{API}/confirm/{confirm}")).status_code == 200


class TestLinks:
    async def test_the_answer_is_the_same_for_every_address(self, client, db, letters):
        unknown, unconfirmed, confirmed = _address(), _address(), _address()
        token, _ = await _check(db)
        await _save(client, token, unconfirmed)
        await _confirmed(client, db, letters, confirmed)
        letters.clear()

        answers = []
        for email in (unknown, unconfirmed, confirmed):
            resp = await client.post(f"{API}/links", json={"email": email})
            answers.append((resp.status_code, resp.json()))
        assert answers == [(202, {"status": "sent"})] * 3
        # No magic link but to a confirmed address; the unconfirmed one gets
        # the confirmation it misses; the unknown one nothing.
        assert [(m["to"], m["template_code"]) for m in letters] == [
            (unconfirmed.lower(), "public_check_confirm"),
            (confirmed.lower(), "public_check_magic_link"),
        ]

    async def test_a_new_confirmation_confirms_the_newest_waiting_check(
        self, client, db, letters
    ):
        email = _address()
        token, check = await _check(db)
        await _save(client, token, email)
        first = _link(letters[-1], "confirm")
        await client.post(f"{API}/links", json={"email": email})
        again = _link(letters[-1], "confirm")
        assert again != first
        assert (await client.post(f"{API}/confirm/{first}")).status_code == 404
        assert (await client.post(f"{API}/confirm/{again}")).status_code == 200
        assert (await _fresh(db, PublicCheck, check.id)).expires_at is None

    async def test_nothing_to_confirm_sends_nothing(self, client, db, letters):
        email = _address()
        token, check = await _check(db)
        await _save(client, token, email)
        check.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        letters.clear()
        resp = await client.post(f"{API}/links", json={"email": email})
        assert resp.status_code == 202
        assert letters == []

    async def test_the_lookup_runs_after_the_answer(
        self, client, db, letters, monkeypatch
    ):
        """No oracle in the clock: the answer does not wait for the lookup
        and the letter, and a failure there never reaches the visitor."""

        async def _broken(db, email):
            raise RuntimeError("mail down")

        monkeypatch.setattr(service, "request_link", _broken)
        resp = await client.post(f"{API}/links", json={"email": _address()})
        assert (resp.status_code, resp.json()) == (202, {"status": "sent"})

    async def test_the_letter_goes_in_the_address_language_not_the_request(
        self, client, db, letters
    ):
        email = _address()
        await _confirmed(client, db, letters, email, locale="de")
        assert "Bestätigen" in letters[-1]["subject"]
        resp = await client.post(
            f"{API}/links", json={"email": email}, headers={"Accept-Language": "en"}
        )
        assert resp.status_code == 202
        assert letters[-1]["subject"] == "Ihre gespeicherten Prozessprüfungen"
        assert 'lang="de"' in letters[-1]["body"]
        assert "Produktneuigkeiten abbestellen" in letters[-1]["body"]

    async def test_link_requests_share_the_letter_cap(self, client, db, letters):
        email = _address()
        await _confirmed(client, db, letters, email)
        letters.clear()
        for _ in range(service.MAIL_CAP + 1):
            await client.post(f"{API}/links", json={"email": email})
        # One of the hour's letters went to the confirmation.
        assert len(letters) == service.MAIL_CAP - 1


class TestMyChecks:
    async def test_the_list_by_link_and_a_result_from_it(self, client, db, letters):
        email = _address()
        hours = dict.fromkeys(
            ("total", "moves", "to_review", "stays", "to_review_after", "freed"), 1.0
        )
        result = {
            "preliminary": True,
            "catalog_version": "test",
            "shares": {"moves": 42.5, "to_review": 30, "stays": 27.5},
            "hours": {**hours, "unestimated": 0},
            "money": None,
            "buckets": {"moves": [], "to_review": [], "stays": []},
            "out_of_scope": [],
        }
        older, check_old = await _check(db)
        newer, check_new = await _check(db, result=result)
        await _keep(client, letters, newer, email)
        await _keep(client, letters, older, email)
        stranger_token, stranger = await _check(db)
        await _keep(client, letters, stranger_token, _address())

        magic = await _magic(client, letters, email)
        resp = await client.get(f"{API}/mine/{magic}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == email.lower()
        ids = [c["id"] for c in body["checks"]]
        assert str(stranger.id) not in ids
        newest = next(c for c in body["checks"] if c["id"] == str(check_new.id))
        assert newest["title"] == "Close the month"
        assert newest["status"] == "ready"
        assert newest["share_moves"] == 42.5
        assert newest["expires_at"] is None
        assert ids.index(str(check_new.id)) < ids.index(str(check_old.id))

        opened = await client.get(f"{API}/mine/{magic}/checks/{check_new.id}")
        assert opened.status_code == 200
        assert opened.json()["description"] == check_new.description
        foreign = await client.get(f"{API}/mine/{magic}/checks/{stranger.id}")
        assert foreign.status_code == 404

    async def test_the_link_has_a_term_and_the_latest_one_wins(
        self, client, db, letters
    ):
        email = _address()
        await _confirmed(client, db, letters, email)
        first = await _magic(client, letters, email)
        second = await _magic(client, letters, email)
        assert (await client.get(f"{API}/mine/{first}")).status_code == 404
        assert (await client.get(f"{API}/mine/{second}")).status_code == 200
        address = await _row(db, email)
        assert address.magic_expires_at - datetime.now(UTC) <= service.MAGIC_TTL
        address.magic_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        resp = await client.get(f"{API}/mine/{second}")
        assert resp.status_code == 404
        assert resp.json()["code"] == "public_check_link_invalid"

    async def test_delete_my_data_takes_the_address_checks_and_containers(
        self, client, db, letters
    ):
        email = _address()
        sandbox_id, user_id = await service.ensure_sandbox(db)
        container = WorkContainer(
            tenant_id=sandbox_id,
            owner_id=user_id,
            created_by_id=user_id,
            type="process",
            title="saved",
            catalog_version="test",
        )
        db.add(container)
        await db.commit()
        token, check = await _check(db)
        check.container_id = container.id
        await db.commit()
        await _confirmed(client, db, letters, email)
        await _save(client, token, email)
        magic = await _magic(client, letters, email)

        resp = await client.delete(f"{API}/mine/{magic}")
        assert resp.status_code == 204
        assert await _row(db, email) is None
        assert await _fresh(db, PublicCheck, check.id) is None
        assert await _fresh(db, WorkContainer, container.id) is None
        assert (await client.get(f"{API}/mine/{magic}")).status_code == 404
        assert (await client.delete(f"{API}/mine/{magic}")).status_code == 404


class TestUnsubscribe:
    async def test_the_link_of_any_letter_unsubscribes_and_again_is_fine(
        self, client, db, letters
    ):
        email = _address()
        token, _ = await _check(db)
        await _save(client, token, email, marketing=True)
        await _save(client, token, email, marketing=True)
        # The same permanent link in every letter.
        assert _link(letters[0], "unsubscribe") == _link(letters[1], "unsubscribe")
        link = _link(letters[0], "unsubscribe")
        resp = await client.post(f"{API}/unsubscribe/{link}")
        assert resp.json() == {"status": "unsubscribed"}
        first = (await _row(db, email)).unsubscribed_at
        assert first is not None
        assert (await _row(db, email)).marketing_opt_in is False
        assert (await client.post(f"{API}/unsubscribe/{link}")).status_code == 200
        assert (await _row(db, email)).unsubscribed_at == first
        unknown = await client.post(f"{API}/unsubscribe/nothing-like-it")
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "public_check_link_invalid"


class TestPurge:
    async def test_unconfirmed_addresses_without_checks_go_when_old(
        self, client, db, letters
    ):
        old = datetime.now(UTC) - service.UNCONFIRMED_ADDRESS_TTL - timedelta(hours=1)
        lonely, kept_by_check, confirmed, young = (_address() for _ in range(4))
        for email in (lonely, kept_by_check, young):
            token, _ = await _check(db)
            await _save(client, token, email)
        await _confirmed(client, db, letters, confirmed)
        await db.execute(
            update(PublicCheck)
            .where(
                PublicCheck.email_id.in_(
                    select(PublicCheckEmail.id).where(
                        PublicCheckEmail.email.in_([lonely.lower(), confirmed.lower()])
                    )
                )
            )
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.execute(
            update(PublicCheckEmail)
            .where(
                PublicCheckEmail.email.in_(
                    [e.lower() for e in (lonely, kept_by_check, confirmed)]
                )
            )
            .values(created_at=old, updated_at=old)
        )
        await db.commit()

        result = await service.purge_expired(db)
        assert result["addresses"] >= 1
        assert await _row(db, lonely) is None
        for email in (kept_by_check, confirmed, young):
            assert await _row(db, email) is not None


class TestPurgeRace:
    """An unconfirmed address a save re-uses must survive a purge running at
    the same moment: the purge's NOT EXISTS reads its old snapshot, so the
    address's own ``updated_at`` - which a save moves - is the guard."""

    async def test_a_save_moves_the_address_clock(self, client, db, letters):
        email = _address()
        token, _ = await _check(db)
        await _save(client, token, email)
        old = datetime.now(UTC) - timedelta(days=30)
        await db.execute(
            update(PublicCheckEmail)
            .where(PublicCheckEmail.email == email.lower())
            .values(created_at=old, updated_at=old)
        )
        await db.commit()
        other, _ = await _check(db)
        await _save(client, other, email)
        assert (await _row(db, email)).updated_at > old + timedelta(days=29)

    async def test_the_purge_spares_an_old_address_touched_lately(self, db):
        old = datetime.now(UTC) - service.UNCONFIRMED_ADDRESS_TTL - timedelta(hours=1)
        touched, idle = _address().lower(), _address().lower()
        for email, updated in ((touched, datetime.now(UTC)), (idle, old)):
            db.add(
                PublicCheckEmail(
                    email=email,
                    locale="en",
                    consent_at=old,
                    unsubscribe_token_hash=service.hash_token(email),
                    created_at=old,
                    updated_at=updated,
                )
            )
        await db.commit()
        await service.purge_expired(db)
        assert await _row(db, touched) is not None
        assert await _row(db, idle) is None


async def test_the_columns_of_hrp927_exist(db):
    columns = {
        row[0]
        for row in (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'public_checks'"
                )
            )
        ).all()
    }
    # HRP-927 writes ``moved_*`` (test_public_check_move.py).
    assert {"email_id", "moved_at", "moved_tenant_id"} <= columns
