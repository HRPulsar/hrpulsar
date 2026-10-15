"""HRP-827: the competence catalogue and the dictionaries on the tenant's
access matrix.

``manage`` on ``competences`` authors the catalogue - all of it, no
division owns a row. Deleting from it, the skill-level ladder and the AI
generation of the tree stay the admin role's on top (Maxim, 23.09).
``manage`` on ``dictionaries`` edits them. The reads the rest of the
product is built on answer whatever the matrix says.
"""

from tests.unit.test_section_gate import _save
from tests.unit.test_work_containers import _user_with_role

GATE = "auth_insufficient_permissions"


async def _as(db, tenant, code):
    _, token = await _user_with_role(db, tenant, code)
    return {"Authorization": f"Bearer {token}"}


async def _group(client, headers, title="Leadership"):
    return await client.post("/api/competence-groups", json={"title": title}, headers=headers)


def _refused(r):
    return r.status_code == 403 and r.json()["code"] == GATE


async def test_the_default_matrix(auth_client, client, db, tenant):
    # admin and hr author the catalogue and edit the dictionaries; a
    # manager reads the catalogue (QA 13.10), the roles below it open
    # neither section.
    for code in ("admin", "hr"):
        h = await _as(db, tenant, code)
        created = await _group(client, h, f"By {code}")
        assert created.status_code == 201, (code, created.text)
        item = await client.post("/api/dictionaries/grade", json={"title": f"G {code}"}, headers=h)
        assert item.status_code == 201, (code, item.text)
    expected = {
        "manager": ("view", None),
        "recruiter": (None, None),
        "hiring_manager": (None, None),
        "employee": (None, None),
    }
    for code, (competences, dictionaries) in expected.items():
        h = await _as(db, tenant, code)
        assert _refused(await _group(client, h)), code
        assert (await client.post("/api/dictionaries/grade", json={"title": "G"}, headers=h)).status_code == 403
        me = (await client.get("/api/auth/me", headers=h)).json()["sections"]
        assert me.get("competences") == competences, code
        assert me.get("dictionaries") == dictionaries, code

    # Deleting, the skill-level ladder and generation stay the admin role's.
    hr = await _as(db, tenant, "hr")
    gid = (await _group(client, hr, "Doomed")).json()["id"]
    assert _refused(await client.delete(f"/api/competence-groups/{gid}", headers=hr))
    assert _refused(await client.post("/api/skill-levels", json={"title": "L"}, headers=hr))
    assert _refused(await client.get("/api/competence-generation/sessions/active", headers=hr))
    assert (await auth_client.delete(f"/api/competence-groups/{gid}")).status_code == 204
    assert (await auth_client.get("/api/competence-generation/sessions/active")).status_code == 200


async def test_closed_by_default_keeps_the_shared_reads(auth_client, client, db, tenant):
    # QA 13.10: ``none`` below ``manager`` on competences and below ``hr``
    # on dictionaries must not take a picker, an assessment or a profile -
    # they read the catalogue through SHARED_READS.
    gid = (await _group(auth_client, None)).json()["id"]
    cid = (
        await auth_client.post("/api/competences", json={"title": "Listening", "group_id": gid})
    ).json()["id"]
    for code in ("recruiter", "hiring_manager", "employee", "manager"):
        h = await _as(db, tenant, code)
        for path in (
            "/api/competence-tree",
            f"/api/competences/{cid}",
            f"/api/competences/{cid}/indicators-by-level",
            "/api/skill-levels",
            "/api/dictionaries/grade",
            "/api/dictionaries/competence_type",
        ):
            r = await client.get(path, headers=h)
            assert r.status_code == 200, (code, path, r.text)
        if code != "manager":
            assert _refused(await client.get(f"/api/competences/{cid}/usage", headers=h)), code


async def test_handing_the_section_to_a_manager_opens_authoring_only(
    auth_client, client, db, tenant
):
    manager = await _as(db, tenant, "manager")
    await _save(auth_client, levels={"competences": {"manager": "manage"}})

    created = await _group(client, manager)
    assert created.status_code == 201, created.text
    gid = created.json()["id"]
    renamed = await client.put(f"/api/competence-groups/{gid}", json={"title": "Renamed"}, headers=manager)
    assert renamed.status_code == 200, renamed.text
    # The raise hands authoring, not what only the admin role did.
    assert _refused(await client.delete(f"/api/competence-groups/{gid}", headers=manager))
    assert _refused(await client.post("/api/competence-generation/sessions", json={}, headers=manager))


async def test_an_admin_lowered_to_view_stops_authoring(auth_client, client, db, tenant):
    # ``competences`` has no admin lock: the tenant may take it from admins,
    # and the admin-only extras go with it.
    admin = await _as(db, tenant, "admin")
    gid = (await _group(client, admin)).json()["id"]
    await _save(auth_client, levels={"competences": {"admin": "view"}})

    assert _refused(await _group(client, admin))
    assert _refused(await client.delete(f"/api/competence-groups/{gid}", headers=admin))
    assert _refused(await client.get("/api/competence-generation/sessions/active", headers=admin))
    assert _refused(await client.post("/api/ai/generate-competences", json={}, headers=admin))


async def test_taking_the_catalogue_away_keeps_the_shared_reads(auth_client, client, db, tenant):
    gid = (await _group(auth_client, None)).json()["id"]
    cid = (
        await auth_client.post("/api/competences", json={"title": "Listening", "group_id": gid})
    ).json()["id"]
    employee = await _as(db, tenant, "employee")

    await _save(
        auth_client,
        hidden=("competences",),
        levels={"dictionaries": {"employee": "none"}},
    )

    # The section's own reads close...
    for path in (f"/api/competences/{cid}/usage", f"/api/competence-groups/{gid}/usage"):
        assert _refused(await client.get(path, headers=employee)), path
    me = (await client.get("/api/auth/me", headers=employee)).json()["sections"]
    assert "competences" not in me and "dictionaries" not in me
    # ...the pickers every other section is built on do not.
    for path in (
        "/api/competence-tree",
        f"/api/competences/{cid}",
        f"/api/competences/{cid}/indicators-by-level",
        "/api/skill-levels",
        "/api/dictionaries/grade",
    ):
        r = await client.get(path, headers=employee)
        assert r.status_code == 200, (path, r.text)


async def test_dictionaries_at_view_read_and_do_not_write(auth_client, client, db, tenant):
    # QA 13.10: ``view`` opens the page read-only - every tab's list and
    # item answer, the writes and the usage preview stay ``manage``'s.
    iid = (await auth_client.post("/api/dictionaries/grade", json={"title": "Lead"})).json()["id"]
    manager = await _as(db, tenant, "manager")
    await _save(auth_client, levels={"dictionaries": {"manager": "view"}})

    me = (await client.get("/api/auth/me", headers=manager)).json()["sections"]
    assert me["dictionaries"] == "view"
    for item_type in ("grade", "specialization", "competence_type", "role", "goal", "project"):
        r = await client.get(f"/api/dictionaries/{item_type}", headers=manager)
        assert r.status_code == 200, (item_type, r.text)
    assert (await client.get(f"/api/dictionaries/items/{iid}", headers=manager)).status_code == 200
    assert _refused(await client.post("/api/dictionaries/grade", json={"title": "X"}, headers=manager))
    assert _refused(await client.put(f"/api/dictionaries/items/{iid}", json={"title": "X"}, headers=manager))
    assert _refused(await client.delete(f"/api/dictionaries/items/{iid}", headers=manager))
    assert _refused(await client.get(f"/api/dictionaries/items/{iid}/usage", headers=manager))


async def test_hr_edits_dictionaries_by_default(client, db, tenant):
    hr = await _as(db, tenant, "hr")
    created = await client.post("/api/dictionaries/grade", json={"title": "Staff"}, headers=hr)
    assert created.status_code == 201, created.text
    iid = created.json()["id"]
    assert (await client.get(f"/api/dictionaries/items/{iid}/usage", headers=hr)).status_code == 200
    assert (await client.delete(f"/api/dictionaries/items/{iid}", headers=hr)).status_code == 204


async def test_drafting_the_catalogue_with_ai_asks_the_level(auth_client, client, db, tenant):
    # ``/ai`` sits outside the gate, so the two catalogue drafts ask
    # ``competences`` themselves.
    manager = await _as(db, tenant, "manager")
    for path in ("/api/ai/generate-competences", "/api/ai/generate-indicators"):
        assert _refused(await client.post(path, json={}, headers=manager)), path


async def test_hr_lowered_to_view_does_not_preview_dictionary_usage(auth_client, client, db, tenant):
    # HRP-637: the usage preview maps positions to grades - it stays with
    # whoever may delete the entry.
    iid = (await auth_client.post("/api/dictionaries/grade", json={"title": "Lead"})).json()["id"]
    hr = await _as(db, tenant, "hr")
    await _save(auth_client, levels={"dictionaries": {"hr": "view"}})
    assert _refused(await client.get(f"/api/dictionaries/items/{iid}/usage", headers=hr))


async def test_platform_admin_authors_but_does_not_delete(client, db, tenant):
    # The matrix never gates the platform role, so authoring and the
    # dictionaries open to it; deleting and generation stay the admin role's.
    platform = await _as(db, tenant, "platform_admin")
    gid = (await _group(client, platform)).json()["id"]
    assert (await client.post("/api/dictionaries/grade", json={"title": "P"}, headers=platform)).status_code == 201
    assert _refused(await client.delete(f"/api/competence-groups/{gid}", headers=platform))
