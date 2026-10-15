"""HRP-820: ``/auth/me.sections`` lists every section the caller opens;
hidden and ``none`` are simply absent, ``coverage`` keeps its dynamics."""

from app.core.sections import SECTIONS
from app.modules.auth.models import user_roles

from tests.unit.test_work_containers import _role, _user_with_role

URL = "/api/settings/section-access"
ALL = [s.code for s in SECTIONS]


async def _headers(db, tenant, code):
    _, token = await _user_with_role(db, tenant, code)
    return {"Authorization": f"Bearer {token}"}


async def _me_sections(client, headers):
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["sections"]


async def _hide(auth_client, code):
    matrix = (await auth_client.get(URL)).json()
    for s in matrix["sections"]:
        if s["code"] == code:
            s["hidden"] = True
    r = await auth_client.put(
        URL,
        json={
            "sections": [
                {"code": s["code"], "hidden": s["hidden"], "levels": s["levels"]}
                for s in matrix["sections"]
            ]
        },
    )
    assert r.status_code == 200, r.text


async def test_admin_opens_everything(auth_client):
    me = await auth_client.get("/api/auth/me")
    assert me.json()["sections"] == dict.fromkeys(ALL, "manage")


async def test_employee_gets_the_defaults_without_none(client, db, tenant):
    sections = await _me_sections(client, await _headers(db, tenant, "employee"))
    assert sections == {
        "employees": "view", "company": "view", "assessments": "view", "development": "view",
        "exams": "view", "talent-market": "view",
    }


async def test_strongest_role_wins(client, db, tenant):
    user, token = await _user_with_role(db, tenant, "hr")
    employee_role = await _role(db, "employee")
    await db.execute(user_roles.insert().values(user_id=user.id, role_id=employee_role.id))
    await db.commit()
    sections = await _me_sections(client, {"Authorization": f"Bearer {token}"})
    assert sections["competences"] == "manage" and sections["employees"] == "view"
    assert "roles" not in sections


async def test_hidden_section_disappears_for_admin_too(auth_client, client, db, tenant):
    await _hide(auth_client, "exams")
    assert "exams" not in (await auth_client.get("/api/auth/me")).json()["sections"]
    assert "exams" not in await _me_sections(client, await _headers(db, tenant, "employee"))


async def test_platform_admin_ignores_the_matrix(auth_client, client, db, tenant):
    await _hide(auth_client, "exams")
    sections = await _me_sections(client, await _headers(db, tenant, "platform_admin"))
    assert sections == dict.fromkeys(ALL, "manage")
