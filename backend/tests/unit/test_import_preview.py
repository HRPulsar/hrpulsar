"""HRP-806 REDO: the import preview reads a file the way the import does.

QA filled in the CSV template, the preview said "All rows valid" and the
import refused every row with "Missing required fields". The page parsed the
file itself and checked columns by header name; the import reads them by
position. A ``;``-locale Excel (German, Russian) opening the comma template
puts each line into column A - a header the page did not recognize, so it
checked nothing. Now the page asks the backend, which reads the file through
the import's own reader and row check.
"""

import io
from datetime import date
from pathlib import Path

import pytest
from app.modules.auth.models import User
from app.modules.data_import.router import router
from app.modules.data_import.service import read_table
from openpyxl import Workbook
from sqlalchemy import select

from tests.unit.test_import_set_password_link import (  # noqa: F401 - fixtures
    _run_import,
    _unique,
    sent_links,
    sync_test_engine,
)

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
PREVIEW = "/api/import/employees/preview"

# The template as a German or Russian Excel saves it after editing: each
# line sat in one cell, and the cells holding quotes were quoted again.
EXCEL_COLUMN_A = (
    '"email,""first_name"",""last_name"",""position"",""hire_date"""\r\n'
    '"{email},""Anna"",""Lee"",""Dev"",""2024-01-15"""\r\n'
)
# Ivan Petrov, analyst - as a Russian Excel saves CSV: Windows-1251.
IVAN = ("\u0418\u0432\u0430\u043d", "\u041f\u0435\u0442\u0440\u043e\u0432")
ANALYST = "\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a"


async def _preview(auth_client, name: str, data: bytes, import_type="employees"):
    return await auth_client.post(
        f"/api/import/{import_type}/preview",
        files={"file": (name, data, "application/octet-stream")},
    )


class TestPreviewAgreesWithTheImport:
    @pytest.mark.usefixtures("sync_test_engine", "sent_links")
    async def test_a_template_excel_put_into_one_column(
        self, db, tenant, user, auth_client
    ):
        data = EXCEL_COLUMN_A.format(email=_unique("anna")).encode("cp1252")
        res = await _preview(auth_client, "employees_template (2).csv", data)
        assert res.status_code == 200, res.text
        preview = res.json()
        assert preview["rows"][0]["problem"] == {"code": "required", "column": 1}

        job = await _run_import(db, tenant, user, "employees_template (2).csv", data)
        refused = [row["line"] for row in preview["rows"] if row["problem"]]
        assert refused == [e["row"] for e in job.errors["rows"]] == [2]
        assert job.errors["rows"][0]["error"] == "Missing required fields"

    @pytest.mark.usefixtures("sync_test_engine", "sent_links")
    async def test_a_file_resaved_by_a_russian_excel(
        self, db, tenant, user, auth_client
    ):
        email = _unique("ivan")
        text = "Email ;First_Name;Last_Name;Position;Hire_Date\r\n"
        text += f"{email};{IVAN[0]};{IVAN[1]};{ANALYST};15.01.2024\r\n;;;;\r\n"
        data = text.encode("cp1251")

        preview = (await _preview(auth_client, "people.csv", data)).json()
        [row] = preview["rows"]
        assert row["problem"] is None
        assert row["cells"][1:4] == [*IVAN, ANALYST]

        job = await _run_import(db, tenant, user, "people.csv", data)
        assert (job.processed_rows, job.error_rows) == (1, 0)
        person = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one()
        assert (person.first_name, person.last_name) == IVAN

    async def test_each_problem_names_its_column(self, auth_client):
        text = "email,first_name,last_name,position,hire_date\n"
        text += "a@test.com,A,B,Dev,2024-01-15\n"
        text += "a@test.com,A,,Dev,2024-01-15\n"
        text += "a@test.com,A,B,Dev,15/01/2024\n"
        text += "not-an-email,A,B,Dev,2024-01-15\n"
        preview = (await _preview(auth_client, "p.csv", text.encode())).json()
        assert preview["columns"][0] == "email"
        assert [(r["line"], r["problem"]) for r in preview["rows"]] == [
            (2, None),
            (3, {"code": "required", "column": 2}),
            (4, {"code": "date", "column": 4}),
            (5, {"code": "email", "column": 0}),
        ]

    async def test_an_xlsx_is_previewed_too(self, auth_client):
        wb = Workbook()
        wb.active.append(["email", "first_name", "last_name", "position", "hire_date"])
        wb.active.append(["a@test.com", "A", "B", "Dev", date(2024, 1, 15)])
        buf = io.BytesIO()
        wb.save(buf)
        preview = (await _preview(auth_client, "p.xlsx", buf.getvalue())).json()
        [row] = preview["rows"]
        assert row["cells"][4] == "2024-01-15"
        assert row["problem"] is None

    async def test_dictionaries(self, auth_client):
        text = "type,title,description\ngrade,Junior,\ngrade,,Mid\n"
        res = await _preview(auth_client, "d.csv", text.encode(), "dictionaries")
        assert [r["problem"] for r in res.json()["rows"]] == [
            None,
            {"code": "required", "column": 1},
        ]

    async def test_refusals(self, auth_client):
        res = await _preview(auth_client, "p.csv", b"a,b\n1,2\n", "salaries")
        assert (res.status_code, res.json()["code"]) == (400, "invalid_import_type")
        res = await _preview(auth_client, "p.xlsx", b"not a workbook")
        assert (res.status_code, res.json()["code"]) == (400, "import_file_unreadable")

    async def test_nothing_is_stored(self, db, auth_client):
        from app.modules.data_import.models import ImportJob

        before = len((await db.execute(select(ImportJob.id))).all())
        await _preview(auth_client, "p.csv", b"email\na@test.com\n")
        assert len((await db.execute(select(ImportJob.id))).all()) == before

    async def test_a_long_file_shows_its_first_rows_and_counts_all(
        self, auth_client, monkeypatch
    ):
        from app.modules.data_import import service

        monkeypatch.setattr(service, "PREVIEW_ROWS", 2)
        text = "email,first_name,last_name,position,hire_date\n"
        text += "a@test.com,A,B,Dev,2024-01-15\n" * 3
        text += "a@test.com,A,,Dev,2024-01-15\n"
        preview = (await _preview(auth_client, "p.csv", text.encode())).json()
        assert [r["line"] for r in preview["rows"]] == [2, 3]
        assert (preview["total_rows"], preview["problem_rows"]) == (4, 1)


class TestRowLimit:
    def _csv(self, data_rows: int) -> bytes:
        return ("sep=,\nemail\n" + "a@test.com\n\n" * data_rows).encode()

    def _xlsx(self, data_rows: int) -> bytes:
        wb = Workbook()
        wb.active.append(["email"])
        for _ in range(data_rows):
            wb.active.append(["a@test.com"])
            wb.active.append([None])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @pytest.mark.parametrize("ext", ["csv", "xlsx"])
    def test_at_the_limit_is_read_past_it_is_refused(self, ext, monkeypatch):
        from app.core.errors import AppError
        from app.modules.data_import import service

        monkeypatch.setattr(service, "MAX_IMPORT_ROWS", 3)
        make = self._csv if ext == "csv" else self._xlsx
        assert len(read_table(f"f.{ext}", make(3))[1]) == 3
        with pytest.raises(AppError) as exc:
            read_table(f"f.{ext}", make(4))
        assert (exc.value.status_code, exc.value.code) == (400, "import_too_many_rows")


class TestExcelSeparatorHint:
    """The template starts with ``sep=,`` so Excel splits it into columns
    whatever its locale; the reader skips that line."""

    def test_the_downloaded_template(self):
        data = 'sep=,\n"email","first_name","last_name","position","hire_date"\n'
        data += '"john@company.com","John","Doe","Software Engineer","2024-01-15"'
        header, rows = read_table("employees_template.csv", data.encode())
        assert header[0] == "email"
        assert rows == [
            (3, ("john@company.com", "John", "Doe", "Software Engineer", "2024-01-15"))
        ]

    def test_the_template_round_tripped_through_a_spreadsheet(self):
        # Google Sheets and Numbers keep the hint as a row of their own.
        data = "sep=,,,,\nemail,first_name,last_name,position,hire_date\n"
        data += "a@test.com,A,B,Dev,2024-01-15\n"
        header, [(line, _)] = read_table("t.csv", data.encode())
        assert (header[0], line) == ("email", 3)


def test_the_page_previews_through_this_route():
    route = next(r for r in router.routes if r.name == "preview_import")
    assert route.methods == {"POST"}
    called = route.path.replace("{import_type}", "${importType}")
    page = FRONTEND / "src/app/(dashboard)/settings/import/page.tsx"
    assert f"`{called}`" in page.read_text(encoding="utf-8")
