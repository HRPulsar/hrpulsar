"""HRP-632: a division head's personal competence draft.

A division head (the ``manager`` role, at ``view`` on ``competences``) adds
a competence into an existing group as their draft, renames and deletes it;
HR or an admin publishes it. Until then it is seen by its author and by
``manage`` alone, and offered by no picker - the default tree leaves every
personal draft out (Vladimir, Maxim 29.09). The catalogue's own drafts stay
as they were.
"""

import inspect

from tests.unit.test_work_containers import _user_with_role

GATE = "auth_insufficient_permissions"


async def _as(db, tenant, code):
    user, token = await _user_with_role(db, tenant, code)
    return user, {"Authorization": f"Bearer {token}"}


def _ids(tree):
    out = set()
    for node in tree:
        out |= {c["id"] for c in node["competences"]}
        out |= _ids(node.get("children", []))
    return out


async def test_a_personal_draft_is_its_authors_until_published(client, db, tenant):
    _, hr = await _as(db, tenant, "hr")
    author, mine = await _as(db, tenant, "manager")
    _, other = await _as(db, tenant, "manager")
    _, employee = await _as(db, tenant, "employee")

    gid = (
        await client.post("/api/competence-groups", json={"title": "Craft"}, headers=hr)
    ).json()["id"]
    catalogue = (
        await client.post(
            "/api/competences", json={"title": "HR's", "group_id": gid}, headers=hr
        )
    ).json()
    assert catalogue["draft_owner_id"] is None

    made = await client.post(
        "/api/competences", json={"title": "Mine", "group_id": gid}, headers=mine
    )
    assert made.status_code == 201, made.text
    draft = made.json()
    assert draft["draft_owner_id"] == str(author.id)
    assert draft["is_published"] is False
    bulk = await client.post(
        f"/api/competence-groups/{gid}/competences/bulk",
        json={"items": [{"title": "Mine too"}]},
        headers=mine,
    )
    assert bulk.status_code == 201, bulk.text
    assert bulk.json()[0]["draft_owner_id"] == str(author.id)

    # Nobody's picker offers it; the catalogue page shows it to its author
    # and to ``manage``.
    for headers in (mine, other, hr):
        picker = _ids((await client.get("/api/competence-tree", headers=headers)).json())
        assert draft["id"] not in picker and catalogue["id"] in picker
    page = "/api/competence-tree?drafts=true"
    assert draft["id"] in _ids((await client.get(page, headers=mine)).json())
    assert draft["id"] in _ids((await client.get(page, headers=hr)).json())
    assert draft["id"] not in _ids((await client.get(page, headers=other)).json())

    card = f"/api/competences/{draft['id']}"
    assert (await client.get(card, headers=mine)).status_code == 200
    assert (await client.get(card, headers=hr)).status_code == 200
    assert (await client.get(card, headers=other)).status_code == 404
    assert (await client.get(card, headers=employee)).status_code == 404
    # ...and so is every read hanging off the card.
    for read in ("usage", "materials", "material-overrides", "indicators-by-level"):
        path = f"{card}/{read}"
        assert (await client.get(path, headers=mine)).status_code == 200, path
        assert (await client.get(path, headers=hr)).status_code == 200, path
        r = await client.get(path, headers=other)
        assert r.status_code == 404 and r.json()["code"] == "competence_not_found", path

    # The author renames their own draft and nothing else.
    assert (
        await client.put(card, json={"title": "Mine, renamed"}, headers=mine)
    ).status_code == 200
    r = await client.put(card, json={"is_active": False}, headers=mine)
    assert r.status_code == 403 and r.json()["code"] == GATE
    # The edit form sends the group back unchanged - not a move.
    same_group = await client.put(
        card, json={"title": "Mine, again", "group_id": gid}, headers=mine
    )
    assert same_group.status_code == 200, same_group.text
    r = await client.put(
        f"/api/competences/{catalogue['id']}", json={"title": "X"}, headers=mine
    )
    assert r.status_code == 403 and r.json()["code"] == GATE
    assert (await client.put(card, json={"title": "X"}, headers=other)).status_code == 404
    assert (await client.delete(card, headers=other)).status_code == 404
    r = await client.post(
        "/api/competences", json={"title": "No", "group_id": gid}, headers=employee
    )
    assert r.status_code == 403 and r.json()["code"] == GATE
    # Groups stay the catalogue's.
    r = await client.post("/api/competence-groups", json={"title": "Own"}, headers=mine)
    assert r.status_code == 403

    # Publishing makes it the catalogue's: every picker, no owner.
    published = await client.post(f"{card}/publish", headers=hr)
    assert published.status_code == 200, published.text
    assert published.json()["draft_owner_id"] is None
    assert draft["id"] in _ids((await client.get("/api/competence-tree", headers=other)).json())
    r = await client.put(card, json={"title": "Y"}, headers=mine)
    assert r.status_code == 403 and r.json()["code"] == GATE

    # The author deletes a draft of their own.
    spare = bulk.json()[0]["id"]
    assert (await client.delete(f"/api/competences/{spare}", headers=mine)).status_code == 204


async def test_a_draft_stays_its_authors_narrow_piece(client, db, tenant):
    """What a personal draft may not do: land in the built-in library, move,
    publish, or reach coverage before it is published."""
    from app.modules.competence.models import CompetenceGroup
    from app.modules.primitives.mapping_service import _load_competences
    from app.modules.work.coverage import _unmapped_competences

    _, hr = await _as(db, tenant, "hr")
    _, mine = await _as(db, tenant, "manager")
    _, employee = await _as(db, tenant, "employee")
    gid = (
        await client.post("/api/competence-groups", json={"title": "Own"}, headers=hr)
    ).json()["id"]
    other_gid = (
        await client.post("/api/competence-groups", json={"title": "Else"}, headers=hr)
    ).json()["id"]
    origin = CompetenceGroup(title="Built-in", tenant_id=None)
    db.add(origin)
    await db.commit()

    for url, body in (
        ("/api/competences", {"title": "Into origin", "group_id": str(origin.id)}),
        (
            f"/api/competence-groups/{origin.id}/competences/bulk",
            {"items": [{"title": "Into origin"}]},
        ),
    ):
        r = await client.post(url, json=body, headers=mine)
        assert r.status_code == 403 and r.json()["code"] == GATE, (url, r.text)

    draft = (
        await client.post(
            "/api/competences", json={"title": "Draft", "group_id": gid}, headers=mine
        )
    ).json()
    card = f"/api/competences/{draft['id']}"
    for method, url, body in (
        ("PUT", card, {"group_id": other_gid}),
        ("POST", f"{card}/publish", None),
        ("POST", f"{card}/move", {"group_id": other_gid}),
    ):
        r = await client.request(method, url, json=body, headers=mine)
        assert r.status_code == 403, (method, url, r.text)

    tree = (await client.get("/api/competence-tree?drafts=true", headers=employee)).json()
    assert draft["id"] not in _ids(tree)

    # Coverage maps nothing that is not published yet.
    loaded = {c.id for c in await _load_competences(db, tenant.id, None)}
    assert draft["id"] not in {str(i) for i in loaded}
    unmapped = {str(i) for i in await _unmapped_competences(db, tenant.id, set())}
    assert draft["id"] not in unmapped


def test_every_catalogue_write_asks_manage_but_the_drafts():
    """The section is self-guarded since HRP-632, so its routes alone keep a
    ``view`` caller out: every write asks ``manage`` itself except the four
    a division head drafts through."""
    from app.main import app

    prefixes = (
        "/api/competences",
        "/api/competence-groups",
        "/api/competence-tree",
        "/api/indicators",
        "/api/materials",
        "/api/skill-levels",
        "/api/competence-generation",
    )
    drafts = {
        "create_competence",
        "bulk_create_competences",
        "update_competence",
        "delete_competence",
    }

    def asks_manage(dependant) -> bool:
        # ``require_section`` closes over the section and the level.
        for d in dependant.dependencies:
            if getattr(d.call, "__name__", "") == "section_checker":
                bound = inspect.getclosurevars(d.call).nonlocals
                if bound["section"].code == "competences" and bound["level"] == "manage":
                    return True
            if asks_manage(d):
                return True
        return False

    unguarded = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}
        if not path.startswith(prefixes) or not methods:
            continue
        if route.endpoint.__name__ in drafts:
            continue
        if not asks_manage(route.dependant):
            unguarded.append(f"{sorted(methods)} {path}")
    assert not unguarded, f"catalogue writes open at view: {unguarded}"


async def test_a_draft_is_attached_nowhere_and_its_children_stay_hidden(client, db, tenant):
    # Review 01.10: "attached nowhere until published" was the pickers'
    # rule only - the attach paths took any id - and the usage reads of a
    # draft's indicators and materials answered another manager by id.
    import uuid

    from app.core.errors import AppError
    from app.modules.competence.models import (
        Competence,
        CompetenceGroup,
        Indicator,
        SkillLevel,
    )
    from app.modules.competence.service import assert_catalogue_competences

    author, _ = await _as(db, tenant, "manager")
    _, other = await _as(db, tenant, "manager")
    group = CompetenceGroup(tenant_id=tenant.id, title=f"G {uuid.uuid4().hex[:4]}")
    db.add(group)
    await db.commit()
    draft = Competence(tenant_id=tenant.id, group_id=group.id, title="Draft", draft_owner_id=author.id)
    published = Competence(tenant_id=tenant.id, group_id=group.id, title="Published")
    db.add_all([draft, published])
    await db.commit()

    await assert_catalogue_competences(db, tenant.id, [published.id])
    for ids in ([draft.id], [published.id, draft.id], [uuid.uuid4()]):
        try:
            await assert_catalogue_competences(db, tenant.id, ids)
        except AppError as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError(f"{ids} attached")

    level = SkillLevel(tenant_id=tenant.id, title="L1", sort_index=1)
    db.add(level)
    await db.commit()
    indicator = Indicator(tenant_id=tenant.id, competence_id=draft.id, skill_level_id=level.id, title="I")
    db.add(indicator)
    await db.commit()
    r = await client.get(f"/api/indicators/{indicator.id}/usage", headers=other)
    assert r.status_code == 404, r.text
