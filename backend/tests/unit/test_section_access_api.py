"""HRP-820: the matrix endpoint - deviations only, one log row per save,
three error codes, and the admin cannot lock themselves out."""

from app.core.sections import ROLE_CODES, SECTIONS
from app.modules.company.models import (
    TenantSectionAccess,
    TenantSectionAccessLog,
    TenantSectionSetting,
)
from sqlalchemy import func, select

from tests.unit.test_work_containers import _user_with_role

URL = "/api/settings/section-access"


def _body(matrix: dict, **changes: dict) -> dict:
    """The full matrix as the screen sends it, with per-section changes:
    ``exams={"hidden": True}``, ``employees={"hr": "none"}``."""
    rows = []
    for section in matrix["sections"]:
        key = section["code"].replace("-", "_")
        change = changes.get(key) or changes.get(key + "_", {})
        levels = {**section["levels"], **{k: v for k, v in change.items() if k != "hidden"}}
        rows.append({"code": section["code"], "hidden": change.get("hidden", section["hidden"]), "levels": levels})
    return {"sections": rows}


async def _counts(db, tenant_id) -> tuple[int, int, int]:
    out = []
    for model in (TenantSectionAccess, TenantSectionSetting, TenantSectionAccessLog):
        out.append(await db.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant_id)))
    return tuple(out)


async def test_get_lists_every_section_with_defaults(auth_client):
    r = await auth_client.get(URL)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["roles"] == list(ROLE_CODES)
    assert [s["code"] for s in data["sections"]] == [s.code for s in SECTIONS]
    by_code = {s["code"]: s for s in data["sections"]}
    assert by_code["company"]["admin_locked"] and by_code["company"]["never_hidden"]
    assert by_code["employees"]["never_hidden"] and not by_code["employees"]["admin_locked"]
    # ``self_guarded`` only ever weakens the gate, so it is pinned here
    # rather than left to be set by accident on a section whose routes do
    # not rule their own writes. The eight below write at ``view`` on their
    # own terms (the owner, the respondent, the reviewer, the hr catalogue
    # role, a division head's personal competence draft - see each
    # section's chapter in rbac.md); ``analytics``, ``exams``,
    # ``dictionaries`` and the admin block write only at ``manage``, so the
    # generic rule covers them.
    assert {s.code for s in SECTIONS if s.self_guarded} == {
        "coverage", "talent-market", "development", "assessments", "company", "employees",
        "recruitment", "competences",
    }
    for s in data["sections"]:
        assert s["levels"] == s["defaults"] and s["hidden"] is False


async def test_get_and_put_are_admin_only(client, db, tenant):
    _, token = await _user_with_role(db, tenant, "hr")
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get(URL, headers=headers)).status_code == 403
    assert (await client.put(URL, json={"sections": []}, headers=headers)).status_code == 403


async def test_unchanged_matrix_writes_nothing(auth_client, db, tenant):
    matrix = (await auth_client.get(URL)).json()
    r = await auth_client.put(URL, json=_body(matrix))
    assert r.status_code == 200, r.text
    assert await _counts(db, tenant.id) == (0, 0, 0)


async def test_deviations_only_and_one_log_row(auth_client, db, tenant):
    matrix = (await auth_client.get(URL)).json()
    r = await auth_client.put(URL, json=_body(matrix, exams={"hidden": True}, employees={"hr": "none"}))
    assert r.status_code == 200, r.text
    by_code = {s["code"]: s for s in r.json()["sections"]}
    assert by_code["exams"]["hidden"] is True
    assert by_code["employees"]["levels"]["hr"] == "none"
    assert await _counts(db, tenant.id) == (1, 1, 1)
    log = (await db.execute(select(TenantSectionAccessLog).where(TenantSectionAccessLog.tenant_id == tenant.id))).scalar_one()
    assert log.diff == {"exams": {"hidden": [False, True]}, "employees": {"roles": {"hr": ["view", "none"]}}}
    assert log.changed_by_id is not None

    # Saving the same screen again is not a change.
    again = await auth_client.put(URL, json=_body(matrix, exams={"hidden": True}, employees={"hr": "none"}))
    assert again.status_code == 200
    assert await _counts(db, tenant.id) == (1, 1, 1)

    # A section left out of the body goes back to its defaults.
    reset = await auth_client.put(URL, json={"sections": [{"code": "exams", "hidden": True, "levels": by_code["exams"]["levels"]}]})
    assert reset.status_code == 200
    assert await _counts(db, tenant.id) == (0, 1, 2)


async def test_widening_is_kept(auth_client, db, tenant):
    # A cell above the default is stored as written: HRP-831 translated the
    # last section and HRP-832 dropped the clamp that narrowed the rest.
    matrix = (await auth_client.get(URL)).json()
    r = await auth_client.put(URL, json=_body(matrix, invitations={"recruiter": "manage"}))
    assert r.status_code == 200, r.text
    assert {s["code"]: s for s in r.json()["sections"]}["invitations"]["levels"]["recruiter"] == "manage"
    assert await _counts(db, tenant.id) == (1, 0, 1)


async def test_unknown_section_or_role(auth_client):
    matrix = (await auth_client.get(URL)).json()
    r = await auth_client.put(URL, json={"sections": [{"code": "payroll", "levels": {}}]})
    assert r.status_code == 400 and r.json()["code"] == "section_access_unknown_section"
    r = await auth_client.put(URL, json=_body(matrix, exams={"ceo": "manage"}))
    assert r.status_code == 400 and r.json()["code"] == "section_access_unknown_section"
    r = await auth_client.put(URL, json=_body(matrix, exams={"hr": "owner"}))
    assert r.status_code == 422


async def test_admin_cannot_lock_themselves_out(auth_client):
    matrix = (await auth_client.get(URL)).json()
    r = await auth_client.put(URL, json=_body(matrix, company={"admin": "view"}))
    assert r.status_code == 400 and r.json()["code"] == "section_access_admin_locked"
    r = await auth_client.put(URL, json=_body(matrix, roles={"admin": "none"}))
    assert r.status_code == 400 and r.json()["code"] == "section_access_admin_locked"
    r = await auth_client.put(URL, json=_body(matrix, employees={"hidden": True}))
    assert r.status_code == 400 and r.json()["code"] == "section_access_cannot_hide"
    r = await auth_client.put(URL, json=_body(matrix, import_={"hidden": True}))
    assert r.status_code == 400 and r.json()["code"] == "section_access_cannot_hide"


async def test_rows_the_registry_now_forbids_are_dropped_on_read(auth_client, db, tenant):
    # Review 01.10: a hidden row stored before its section became
    # never_hidden (or an admin override before admin_locked) was honoured
    # by the gate and sent back by the screen into a save that refuses it.
    db.add_all([
        TenantSectionSetting(tenant_id=tenant.id, section="import", hidden=True),
        TenantSectionAccess(tenant_id=tenant.id, section="roles", role_code="admin", level="view"),
    ])
    await db.commit()
    matrix = (await auth_client.get(URL)).json()
    by_code = {s["code"]: s for s in matrix["sections"]}
    assert by_code["import"]["hidden"] is False
    assert by_code["roles"]["levels"]["admin"] == "manage"
    r = await auth_client.put(URL, json={"sections": [
        {"code": s["code"], "hidden": s["hidden"], "levels": s["levels"]} for s in matrix["sections"]
    ]})
    assert r.status_code == 200, r.text
