"""HRP-806: employee import sends a set-password link instead of a shared password.

The Celery task body runs for real here against hrpulsar_test — the older
import tests only covered job creation, which is how a broken
``Employee(position=...)`` shipped unnoticed.
"""

import base64
import io
import uuid
import zipfile
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.auth import service as auth_service
from app.modules.auth.models import Invitation, User
from app.modules.data_import.models import ImportJob
from app.modules.data_import.service import read_rows
from app.modules.demo.seed_data_employees import (
    NAME_POOL,
    email_for,
    localized_name_pool,
)
from app.modules.demo.utils import DEMO_ADMIN_EMAIL_DOMAIN, is_demo_cast_email
from app.modules.employee.models import Employee
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

HEADER = "email,first_name,last_name,position,hire_date"


@pytest_asyncio.fixture
async def sync_test_engine(db, monkeypatch):
    """Point the import task's sync engine at hrpulsar_test.

    Yields a dict whose ``disposed`` flag turns true once the task has
    finished its database work and disposed the engine.
    """
    import app.database as database
    from app.config import settings
    from app.modules.data_import import tasks

    test_db_url = settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
    real = database.make_sync_engine
    state = {"disposed": False}

    def make_engine(url, **kw):
        engine = real(test_db_url)
        dispose = engine.dispose

        def tracked_dispose(*args, **kwargs):
            state["disposed"] = True
            return dispose(*args, **kwargs)

        engine.dispose = tracked_dispose
        return engine

    monkeypatch.setattr(database, "make_sync_engine", make_engine)
    monkeypatch.setattr(tasks, "SET_PASSWORD_EMAIL_PACE_SECONDS", 0)
    # The import queues its emails; the in-memory broker never runs them.
    emails = tasks.send_set_password_links_task
    monkeypatch.setattr(emails, "delay", lambda *args, **kw: emails(*args, **kw))
    yield state


@pytest.fixture
def sent_links():
    """Capture ``(email, token)`` of every set-password email, with a provider."""
    sent: list[tuple[str, str]] = []

    def fake_send(to, name, token, expire_days, *, locale="en"):
        sent.append((to, token))
        return True

    with (
        patch.object(auth_service, "send_account_created_email", fake_send),
        patch.object(auth_service, "email_provider_configured", lambda: True),
    ):
        yield sent


async def _run_import(
    db: AsyncSession,
    tenant,
    user,
    file_name: str,
    data: bytes,
    import_type: str = "employees",
):
    job = ImportJob(
        tenant_id=tenant.id,
        import_type=import_type,
        file_name=file_name,
        total_rows=0,
        initiated_by=user.id,
    )
    db.add(job)
    await db.commit()
    return await _run_task(db, job, data)


async def _run_task(db: AsyncSession, job: ImportJob, data: bytes) -> ImportJob:
    from app.modules.data_import.tasks import run_import_task

    run_import_task(
        str(job.id),
        str(job.tenant_id),
        str(job.initiated_by),
        job.import_type,
        base64.b64encode(data).decode(),
    )
    await db.refresh(job)
    return job


def _xlsx_with_sheet_xml(sheet_xml: bytes) -> bytes:
    """A workbook whose first sheet's XML is replaced with ``sheet_xml``."""
    src = zipfile.ZipFile(io.BytesIO(_xlsx(["a", "b"])))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = sheet_xml
            dst.writestr(item, data)
    return out.getvalue()


def _xlsx_with_chartsheet_active() -> bytes:
    wb = Workbook()
    wb.create_chartsheet()
    wb.active = 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.com"


def _xlsx(*rows) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestReadRows:
    def test_csv_comma(self):
        rows = read_rows("t.csv", f"{HEADER}\na@x.test,A,B,Dev,2024-01-15\n".encode())
        assert rows == [(2, ("a@x.test", "A", "B", "Dev", "2024-01-15"))]

    def test_csv_semicolon_with_bom_and_blank_lines(self):
        data = "\ufeffemail;first_name;last_name;position;hire_date\n\n"
        data += "a@x.test;A;;Dev;2024-01-15\n;;;;\n"
        rows = read_rows("T.CSV", data.encode())
        # Line numbers keep counting over the blank line.
        assert rows == [(3, ("a@x.test", "A", None, "Dev", "2024-01-15"))]

    def test_leading_blank_line_does_not_hide_the_header(self):
        data = "\nemail;first_name;last_name;position;hire_date\na@x.test;A;B;Dev;2024-01-15\n"
        assert read_rows("t.csv", data.encode()) == [
            (3, ("a@x.test", "A", "B", "Dev", "2024-01-15"))
        ]

    def test_german_excel_csv_in_cp1252(self):
        data = "email;first_name;last_name;position;hire_date\n"
        data += "m@x.test;Jörg;Müller;Prüfer;2024-01-15\n"
        [(_, row)] = read_rows("t.csv", data.encode("cp1252"))
        assert row[1:3] == ("Jörg", "Müller")

    def test_xlsx(self):
        data = _xlsx(
            HEADER.split(","), ["a@x.test", "A", "B", "Dev", date(2024, 1, 15)]
        )
        [(line, row)] = read_rows("t.xlsx", data)
        assert (line, row[0]) == (2, "a@x.test")

    @pytest.mark.parametrize(
        "data",
        [
            b"not a workbook",
            # openpyxl raised AttributeError and ParseError here: a 500.
            _xlsx_with_chartsheet_active(),
            _xlsx_with_sheet_xml(b"<worksheet><sheetData><row>"),
        ],
        ids=["not-a-zip", "chartsheet-active", "broken-sheet-xml"],
    )
    def test_unreadable_file_is_a_400(self, data):
        with pytest.raises(AppError) as exc:
            read_rows("t.xlsx", data)
        assert exc.value.code == "import_file_unreadable"
        assert exc.value.status_code == 400


class TestImportTask:
    async def test_creates_employees_and_emails_new_users_only(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links
    ):
        local = f"nina-{uuid.uuid4().hex[:8]}"
        cast_email = email_for(*NAME_POOL[0])
        csv = "\n".join(
            [
                HEADER,
                # Domain case is normalized the way login stores it.
                f"{local}@Test.COM,Nina,New,Data Analyst,2024-02-01",
                # Already in the tenant: gets a card, not an email.
                f"{user.email},Test,User,Lead,2023-01-01",
                f"{cast_email},Cast,Member,Dev,2024-01-01",
                f"{_unique('bad')},Bad,Date,Dev,2024-02-30",
                "not-an-email,Bad,Email,Dev,2024-01-01",
            ]
        )
        job = await _run_import(db, tenant, user, "people.csv", csv.encode())

        assert job.status == "completed"
        assert (job.processed_rows, job.error_rows) == (3, 2)
        assert [e["row"] for e in job.errors["rows"]] == [5, 6]

        new_email = f"{local}@test.com"
        new_user = (
            await db.execute(select(User).where(User.email == new_email))
        ).scalar_one()
        assert not verify_password("changeme123", new_user.password_hash)
        assert new_user.email_verified_at is None
        emp = (
            await db.execute(select(Employee).where(Employee.user_id == new_user.id))
        ).scalar_one()
        assert emp.position_title == "Data Analyst"
        assert emp.position_id is not None
        assert emp.hire_date == date(2024, 2, 1)

        assert [to for to, _ in sent_links] == [new_email]

    async def test_link_sets_the_password_and_the_person_can_sign_in(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links
    ):
        email = _unique("once")
        csv = f"{HEADER}\n{email},Olga,Once,Dev,2024-03-01\n"
        await _run_import(db, tenant, user, "people.csv", csv.encode())
        [(_, token)] = sent_links

        await auth_service.reset_password(db, token, "chosen-pass-1")
        with pytest.raises(AppError):
            await auth_service.reset_password(db, token, "hijacked-pass-2")

        signed_in = await auth_service.login(db, email, "chosen-pass-1")
        assert signed_in["access_token"]

    async def test_german_excel_csv_dates(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links
    ):
        """A German Excel saves dates into CSV as DD.MM.YYYY."""
        from app.modules.employee.models import WorkExperience

        email = _unique("datum")
        data = "email;first_name;last_name;position;hire_date;work;role;start\n"
        data += f"{email};Dora;Datum;Dev;15.01.2024;Acme;Engineer;1.3.2020\n"
        job = await _run_import(db, tenant, user, "people.csv", data.encode("cp1252"))

        assert (job.status, job.processed_rows, job.error_rows) == ("completed", 1, 0)
        emp = (
            await db.execute(
                select(Employee)
                .join(User, User.id == Employee.user_id)
                .where(User.email == email)
            )
        ).scalar_one()
        assert emp.hire_date == date(2024, 1, 15)
        experience = (
            await db.execute(
                select(WorkExperience).where(WorkExperience.employee_id == emp.id)
            )
        ).scalar_one()
        assert experience.start_date == date(2020, 3, 1)

    async def test_redelivered_job_is_not_imported_twice(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links
    ):
        """task_acks_late redelivers the message of a worker lost after the
        commit; a second pass added every row's experience again."""
        from app.modules.employee.models import WorkExperience

        email = _unique("again")
        csv = f"{HEADER},work,role,start\n{email},A,A,Dev,2024-01-01,Acme,Eng,2020-01-01\n"
        job = await _run_import(db, tenant, user, "people.csv", csv.encode())
        await _run_task(db, job, csv.encode())

        assert job.status == "completed"
        experience = (
            (
                await db.execute(
                    select(WorkExperience)
                    .join(Employee, Employee.id == WorkExperience.employee_id)
                    .join(User, User.id == Employee.user_id)
                    .where(User.email == email)
                )
            )
            .scalars()
            .all()
        )
        assert len(experience) == 1
        assert [to for to, _ in sent_links] == [email]

    async def test_email_reads_the_account_when_it_goes_out(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links, monkeypatch
    ):
        """The emails wait in the queue behind the import. An admin may re-send
        a link from the card meanwhile — the import's email must carry the
        live version — and whoever has set a password gets nothing."""
        from app.modules.data_import import tasks

        queued: list[tuple] = []
        monkeypatch.setattr(
            tasks.send_set_password_links_task, "delay", lambda *a: queued.append(a)
        )
        resent, verified = _unique("resent"), _unique("verified")
        csv = f"{HEADER}\n{resent},R,R,Dev,2024-01-01\n{verified},V,V,Dev,2024-01-01\n"
        await _run_import(db, tenant, user, "people.csv", csv.encode())

        accounts = {
            u.email: u
            for u in (
                await db.execute(select(User).where(User.email.in_([resent, verified])))
            ).scalars()
        }
        accounts[resent].token_version += 1  # what a resend from the card does
        accounts[verified].email_verified_at = datetime.now(timezone.utc)
        await db.commit()

        [(user_ids, locale, job_id)] = queued
        tasks.send_set_password_links_task(user_ids, locale, job_id)

        [(to, token)] = sent_links
        assert to == resent
        await auth_service.reset_password(db, token, "fresh-pass-1")

    async def test_emails_go_out_in_batches(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links, monkeypatch
    ):
        from app.modules.data_import import tasks

        monkeypatch.setattr(tasks, "SET_PASSWORD_EMAIL_BATCH", 2)
        emails_task = tasks.send_set_password_links_task
        queued_sizes: list[int] = []

        def delay(user_ids, locale, job_id=None):
            queued_sizes.append(len(user_ids))
            emails_task(user_ids, locale, job_id)

        monkeypatch.setattr(emails_task, "delay", delay)
        emails = [_unique(f"batch{n}") for n in range(5)]
        csv = HEADER + "".join(f"\n{e},B,B,Dev,2024-01-01" for e in emails)
        await _run_import(db, tenant, user, "people.csv", csv.encode())

        assert queued_sizes == [5, 3, 1]
        assert [to for to, _ in sent_links] == emails

    async def test_xlsx_file(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links
    ):
        email = _unique("xlsx")
        data = _xlsx(
            HEADER.split(","), [email, "Xena", "Sheet", "Dev", date(2024, 1, 15)]
        )
        job = await _run_import(db, tenant, user, "people.xlsx", data)
        assert (job.status, job.processed_rows) == ("completed", 1)
        assert [to for to, _ in sent_links] == [email]

    async def test_row_failing_in_the_database_rolls_back_alone(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links
    ):
        kept, broken = _unique("kept"), _unique("broken")
        too_long_position = "P" * 300  # positions.title is VARCHAR(255)
        csv = (
            f"{HEADER}\n{kept},K,K,Dev,2024-01-01\n"
            f"{broken},B,B,{too_long_position},2024-01-01\n"
        )
        job = await _run_import(db, tenant, user, "people.csv", csv.encode())

        assert job.status == "completed"
        assert (job.processed_rows, job.error_rows) == (1, 1)
        assert [to for to, _ in sent_links] == [kept]
        # The broken row's user went down with its savepoint.
        assert (
            await db.execute(select(User).where(User.email == broken))
        ).scalar_one_or_none() is None

    async def test_emails_go_out_only_after_the_job_is_done(
        self, db: AsyncSession, tenant, user, sync_test_engine
    ):
        """Inside the job's try, a failing send used to mark a finished import
        failed and retry it — importing the file twice."""
        attempts: list[tuple[str, bool]] = []

        def exploding_send(to, name, token, expire_days, *, locale="en"):
            attempts.append((to, sync_test_engine["disposed"]))
            raise RuntimeError("provider down")

        first, second = _unique("first"), _unique("second")
        csv = f"{HEADER}\n{first},F,F,Dev,2024-01-01\n{second},S,S,Dev,2024-01-01\n"
        with (
            patch.object(auth_service, "send_account_created_email", exploding_send),
            patch.object(auth_service, "email_provider_configured", lambda: True),
        ):
            job = await _run_import(db, tenant, user, "people.csv", csv.encode())

        assert (job.status, job.processed_rows) == ("completed", 2)
        assert attempts == [(first, True), (second, True)]

    async def test_a_send_the_provider_refuses_is_counted_on_the_job(
        self, db: AsyncSession, tenant, user, sync_test_engine
    ):
        """``send_email`` swallows the provider's error and answers False; a
        batch lost to one 429 used to leave the job plainly "completed"."""
        csv = f"{HEADER}\n{_unique('refused')},R,R,Dev,2024-01-01\n"
        with (
            patch.object(
                auth_service, "send_account_created_email", lambda *a, **k: False
            ),
            patch.object(auth_service, "email_provider_configured", lambda: True),
            patch("app.core.email.email_provider_configured", lambda: True),
        ):
            job = await _run_import(db, tenant, user, "people.csv", csv.encode())

        await db.refresh(job)
        assert job.status == "completed"
        assert job.errors["emails_failed"] == 1

    async def test_no_provider_is_not_counted_as_a_failed_email(
        self, db: AsyncSession, tenant, user, sync_test_engine
    ):
        """Without a provider the link goes to the operator's log by design."""
        csv = f"{HEADER}\n{_unique('nomail')},N,N,Dev,2024-01-01\n"
        with patch.object(auth_service, "email_provider_configured", lambda: False):
            job = await _run_import(db, tenant, user, "people.csv", csv.encode())

        await db.refresh(job)
        assert job.status == "completed"
        assert "emails_failed" not in (job.errors or {})

    async def test_a_broker_failure_does_not_fail_a_finished_import(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links, monkeypatch
    ):
        """The rows are committed: a broker that refuses the email task must
        not crash the Celery task and report the import as failed."""
        from app.modules.data_import import tasks

        def refuse(*args, **kwargs):
            raise RuntimeError("broker down")

        monkeypatch.setattr(tasks.send_set_password_links_task, "delay", refuse)
        csv = f"{HEADER}\n{_unique('broker')},B,B,Dev,2024-01-01\n"
        job = await _run_import(db, tenant, user, "people.csv", csv.encode())

        assert (job.status, job.processed_rows) == ("completed", 1)

    async def test_a_batch_that_breaks_still_queues_the_rest(
        self, db: AsyncSession, tenant, user, sync_test_engine, monkeypatch
    ):
        """A database error mid-batch used to break the chain: every account
        behind the failed batch never got a link at all."""
        from app.modules.data_import import tasks

        monkeypatch.setattr(tasks, "SET_PASSWORD_EMAIL_BATCH", 1)
        queued: list[tuple] = []
        monkeypatch.setattr(
            tasks.send_set_password_links_task, "delay", lambda *a: queued.append(a)
        )
        emails = [_unique("chain0"), _unique("chain1")]
        csv = HEADER + "".join(f"\n{e},C,C,Dev,2024-01-01" for e in emails)
        await _run_import(db, tenant, user, "people.csv", csv.encode())

        [(user_ids, locale, job_id)] = queued
        queued.clear()
        with (
            patch.object(
                auth_service,
                "can_send_set_password_link",
                side_effect=RuntimeError("connection lost"),
            ),
            pytest.raises(RuntimeError),
        ):
            tasks.send_set_password_links_task(user_ids, locale, job_id)

        assert queued == [(user_ids[1:], locale, job_id)]

    async def test_demo_emails_only_the_first_people_added_in_the_session(
        self, db: AsyncSession, tenant, user, sync_test_engine, sent_links
    ):
        from app.modules.data_import.tasks import DEMO_IMPORT_EMAIL_LIMIT

        tenant.is_demo = True
        # The seeded cast and the throw-away admin must not use up the budget.
        for cast in (
            f"c-{uuid.uuid4().hex[:6]}@demo.example.com",
            f"a-{uuid.uuid4().hex[:6]}@demo.hrpulsar.local",
        ):
            db.add(
                User(
                    email=cast,
                    password_hash="x",
                    first_name="C",
                    last_name="C",
                    tenant_id=tenant.id,
                )
            )
        await db.commit()
        # The fixture admin is not on a demo cast domain, so it already
        # counts as someone the visitor added.
        budget = DEMO_IMPORT_EMAIL_LIMIT - 1

        first_file = [_unique(f"a{n}") for n in range(budget - 1)]
        second_file = [_unique(f"b{n}") for n in range(3)]
        for emails in (first_file, second_file):
            csv = HEADER + "".join(f"\n{e},D,D,Dev,2024-01-01" for e in emails)
            job = await _run_import(db, tenant, user, "people.csv", csv.encode())
            assert job.processed_rows == len(emails)

        # A second file does not buy a second budget.
        assert [to for to, _ in sent_links] == first_file + second_file[:1]


class TestDictionaryImportTask:
    async def test_row_failing_in_the_database_rolls_back_alone(
        self, db: AsyncSession, tenant, user, sync_test_engine
    ):
        """Without a savepoint the failed flush poisoned the session: every
        later row and the final commit failed with it."""
        from app.modules.dictionary.models import DictionaryItem

        suffix = uuid.uuid4().hex[:8]
        before, after = f"Before {suffix}", f"After {suffix}"
        too_long = "T" * 300  # dictionary_items.title is VARCHAR(255)
        csv = f"type,title\nskill,{before}\nskill,{too_long}\nskill,{after}\n"
        job = await _run_import(
            db, tenant, user, "dict.csv", csv.encode(), import_type="dictionaries"
        )

        assert job.status == "completed"
        assert (job.processed_rows, job.error_rows) == (2, 1)
        assert [e["row"] for e in job.errors["rows"]] == [3]
        titles = (
            await db.scalars(
                select(DictionaryItem.title).where(
                    DictionaryItem.tenant_id == tenant.id,
                    DictionaryItem.title.in_([before, after]),
                )
            )
        ).all()
        assert sorted(titles) == [after, before]


@pytest_asyncio.fixture
async def imported_employee(db: AsyncSession, tenant):
    """What the import leaves behind: an unverified account with a card."""
    u = User(
        email=_unique("imported"),
        password_hash=hash_password("unused-pass-1"),
        first_name="Ivan",
        last_name="Imported",
        tenant_id=tenant.id,
    )
    db.add(u)
    await db.flush()
    emp = Employee(user_id=u.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    # Re-fetch with roles loaded, as the conftest ``user`` fixture does: the
    # API shares this session and would otherwise lazy-load them outside a
    # greenlet.
    db.expunge_all()
    u = (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == u.id)
        )
    ).scalar_one()
    return await db.get(Employee, emp.id), u


async def _assert_refused(auth_client, emp, sent_links):
    card = await auth_client.get(f"/api/employees/{emp.id}")
    assert card.json()["set_password_link_available"] is False
    res = await auth_client.post(f"/api/employees/{emp.id}/set-password-link")
    assert res.status_code == 409
    assert sent_links == []


class TestResendSetPasswordLink:
    async def test_sends_fresh_link_and_voids_the_old_one(
        self, db: AsyncSession, auth_client, imported_employee, sent_links
    ):
        emp, imported = imported_employee
        old_token = auth_service.create_reset_token(
            str(imported.id), imported.token_version
        )

        card = await auth_client.get(f"/api/employees/{emp.id}")
        assert card.json()["set_password_link_available"] is True

        res = await auth_client.post(f"/api/employees/{emp.id}/set-password-link")
        assert res.status_code == 204
        [(to, new_token)] = sent_links
        assert to == imported.email

        with pytest.raises(AppError):
            await auth_service.reset_password(db, old_token, "stale-pass-1")
        await auth_service.reset_password(db, new_token, "fresh-pass-1")

    async def test_the_provider_call_runs_off_the_event_loop(
        self, db: AsyncSession, auth_client, imported_employee
    ):
        """A blocking Resend/SMTP round-trip stalled every request on the worker."""
        import threading

        emp, _ = imported_employee
        threads: list[threading.Thread] = []

        def fake_send(to, name, token, expire_days, *, locale="en"):
            threads.append(threading.current_thread())
            return True

        with (
            patch.object(auth_service, "send_account_created_email", fake_send),
            patch.object(auth_service, "email_provider_configured", lambda: True),
        ):
            res = await auth_client.post(f"/api/employees/{emp.id}/set-password-link")

        assert res.status_code == 204
        assert threads and threads[0] is not threading.main_thread()

    async def test_refused_for_a_verified_user_who_never_stamped_a_login(
        self, db: AsyncSession, auth_client, imported_employee, sent_links
    ):
        """Long-standing users have ``first_login_at`` NULL (never backfilled);
        a resend would bump their token version and log them out."""
        emp, imported = imported_employee
        imported.email_verified_at = datetime.now(timezone.utc)
        await db.commit()
        assert imported.first_login_at is None

        await _assert_refused(auth_client, emp, sent_links)

    async def test_refused_for_a_terminated_employee(
        self, db: AsyncSession, auth_client, imported_employee, sent_links
    ):
        emp, _ = imported_employee
        res = await auth_client.put(
            f"/api/employees/{emp.id}", json={"status": "terminated"}
        )
        assert res.status_code == 200

        await _assert_refused(auth_client, emp, sent_links)

    async def test_refused_for_the_demo_cast(
        self, db: AsyncSession, auth_client, imported_employee, sent_links
    ):
        emp, imported = imported_employee
        imported.email = f"cast-{uuid.uuid4().hex[:6]}@demo.example.com"
        await db.commit()

        await _assert_refused(auth_client, emp, sent_links)

    async def test_not_offered_to_someone_who_accepted_an_invitation(
        self, db: AsyncSession, tenant, user, admin_role, sent_links
    ):
        from app.modules.auth.schemas import AcceptInvitationRequest, InvitationCreate

        email = _unique("accepted")
        with patch.object(auth_service, "send_invitation_email", lambda *a, **k: True):
            inv = await auth_service.create_invitation(
                db,
                tenant.id,
                user.id,
                InvitationCreate(email=email, name="Anna Accepted", role_code="admin"),
                inviter_role_codes=["admin"],
            )
        token = (await db.get(Invitation, inv["id"])).token
        await auth_service.accept_invitation(
            db,
            AcceptInvitationRequest(
                token=token,
                password="accepted-pass-1",
                first_name="Anna",
                last_name="Accepted",
            ),
        )

        invitee = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one()
        assert invitee.first_login_at is not None
        assert not auth_service.can_send_set_password_link(invitee, "active")

    async def test_failed_delivery_keeps_the_old_link(
        self, db: AsyncSession, auth_client, imported_employee
    ):
        emp, imported = imported_employee
        version = imported.token_version

        with (
            patch.object(
                auth_service, "send_account_created_email", lambda *a, **k: False
            ),
            patch.object(auth_service, "email_provider_configured", lambda: True),
        ):
            res = await auth_client.post(f"/api/employees/{emp.id}/set-password-link")

        assert res.status_code == 503
        assert res.json()["code"] == "set_password_link_not_sent"
        await db.refresh(imported)
        assert imported.token_version == version

    async def test_without_a_provider_the_operator_gets_the_link_in_the_log(
        self, db: AsyncSession, auth_client, imported_employee, caplog
    ):
        emp, imported = imported_employee
        version = imported.token_version
        rendered: list[str] = []

        with (
            patch.object(
                auth_service,
                "send_account_created_email",
                lambda to, *a, **k: rendered.append(to) or False,
            ),
            patch.object(auth_service, "email_provider_configured", lambda: False),
        ):
            res = await auth_client.post(f"/api/employees/{emp.id}/set-password-link")

        assert res.status_code == 409
        assert res.json()["code"] == "set_password_link_email_not_configured"
        assert "SET PASSWORD LINK" in caplog.text  # the suite runs onprem
        # No email is rendered for a send that cannot happen.
        assert rendered == []
        await db.refresh(imported)
        assert imported.token_version == version

    async def test_refused_in_a_demo_sandbox(
        self, db: AsyncSession, auth_client, tenant, imported_employee, sent_links
    ):
        from app.modules.company.models import Tenant

        emp, _ = imported_employee
        # The fixture expunged the session, so ``tenant`` is detached.
        (await db.get(Tenant, tenant.id)).is_demo = True
        await db.commit()

        res = await auth_client.post(f"/api/employees/{emp.id}/set-password-link")
        assert res.status_code == 409
        assert res.json()["code"] == "set_password_link_unavailable"
        assert sent_links == []

    async def test_other_tenants_employee_is_not_found(
        self, db: AsyncSession, auth_client, sent_links
    ):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.flush()
        stranger = User(
            email=_unique("stranger"),
            password_hash=hash_password("unused-pass-1"),
            first_name="S",
            last_name="S",
            tenant_id=other.id,
        )
        db.add(stranger)
        await db.flush()
        emp = Employee(
            user_id=stranger.id, tenant_id=other.id, hire_date=date(2024, 1, 1)
        )
        db.add(emp)
        await db.commit()

        res = await auth_client.post(f"/api/employees/{emp.id}/set-password-link")
        assert res.status_code == 404
        assert sent_links == []

    async def test_admin_only(
        self, db: AsyncSession, client, tenant, imported_employee, sent_links
    ):
        emp, imported = imported_employee
        token = create_access_token(str(imported.id), str(tenant.id))
        res = await client.post(
            f"/api/employees/{emp.id}/set-password-link",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        assert sent_links == []


@pytest.mark.parametrize("locale", ["en", "de", "ru"])
def test_demo_cast_emails_are_recognised(locale):
    """The seed translates cast emails per locale; the domain must survive."""
    pool = localized_name_pool(locale)
    assert all(is_demo_cast_email(email) for _, _, email in pool)
    assert is_demo_cast_email(f"demo-abc@{DEMO_ADMIN_EMAIL_DOMAIN}")
    assert not is_demo_cast_email("jane@company.com")
    assert not is_demo_cast_email(None)
