"""HRP-638: a division head writes assessments and plans for their own subtree.

Reading was fenced years ago; the mutating routes were not. ``require_role
("admin", "manager")`` answered "may you be here" and nothing answered "is
this person yours", so a head of a three-person department could create,
edit, calibrate and re-plan anyone in the workspace — including their own
boss — by putting the id in the body or the URL.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.assessment.models import PDP, Assessment, ExternalReviewer, PDPItem
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _user(db: AsyncSession, tenant, code: str) -> User:
    result = await db.execute(select(Role).where(Role.code == code))
    role = result.scalars().first()
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
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


def _headers(u: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(u.id), str(u.tenant_id))}"
    }


@pytest_asyncio.fixture
async def scoped(
    db: AsyncSession, tenant, assessment_statuses, assessment_types
) -> dict:
    """Two divisions, one assessee and one plan each.

    ``mine`` is managed by ``mgr``; ``theirs`` is a neighbouring
    department. ``lonely`` is a manager of nothing — the row where a
    ``if not visible_ids`` shortcut turns into "no filter".
    """
    mgr_user = await _user(db, tenant, "manager")
    lonely_user = await _user(db, tenant, "manager")
    admin_user = await _user(db, tenant, "admin")
    plain_user = await _user(db, tenant, "employee")

    mgr_emp = Employee(
        user_id=mgr_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
    )
    lonely_emp = Employee(
        user_id=lonely_user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1)
    )
    db.add_all([mgr_emp, lonely_emp])
    await db.commit()
    await db.refresh(mgr_emp)
    await db.refresh(lonely_emp)

    mine = Division(
        tenant_id=tenant.id, name=f"Mine {uuid.uuid4().hex[:4]}", manager_id=mgr_emp.id
    )
    theirs = Division(tenant_id=tenant.id, name=f"Theirs {uuid.uuid4().hex[:4]}")
    db.add_all([mine, theirs])
    await db.commit()
    await db.refresh(mine)
    await db.refresh(theirs)

    out: dict = {
        "mgr_user": mgr_user,
        "lonely_user": lonely_user,
        "admin_user": admin_user,
        "plain_user": plain_user,
    }
    for key, division in (("mine", mine), ("theirs", theirs)):
        emp_user = await _user(db, tenant, "employee")
        emp = Employee(
            user_id=emp_user.id,
            tenant_id=tenant.id,
            division_id=division.id,
            hire_date=date(2024, 1, 1),
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)

        assessment = Assessment(
            tenant_id=tenant.id,
            title=f"{key} assessment",
            employee_id=emp.id,
            initiator_id=admin_user.id,
            type_id=assessment_types["360"].id,
            status_id=assessment_statuses["draft"].id,
        )
        pdp = PDP(
            tenant_id=tenant.id,
            title=f"{key} plan",
            employee_id=emp.id,
            author_id=admin_user.id,
            status="draft",
        )
        db.add_all([assessment, pdp])
        await db.commit()
        await db.refresh(assessment)
        await db.refresh(pdp)

        item = PDPItem(pdp_id=pdp.id, title=f"{key} item")
        reviewer = ExternalReviewer(
            tenant_id=tenant.id,
            assessment_id=assessment.id,
            token=uuid.uuid4().hex,
            expires_at=datetime.now(timezone.utc).replace(year=2030),
        )
        db.add_all([item, reviewer])
        await db.commit()
        await db.refresh(item)
        await db.refresh(reviewer)

        out[f"{key}_employee"] = emp
        out[f"{key}_assessment"] = assessment
        out[f"{key}_pdp"] = pdp
        out[f"{key}_item"] = item
        out[f"{key}_reviewer"] = reviewer
    return out


def _mutations(s: dict, side: str) -> list[tuple[str, str, dict | None]]:
    """Every route this ticket fences, keyed by ``mine`` / ``theirs``."""
    a = s[f"{side}_assessment"].id
    p = s[f"{side}_pdp"].id
    item = s[f"{side}_item"].id
    reviewer = s[f"{side}_reviewer"].id
    return [
        ("patch", f"/api/assessments/{a}", {"title": "renamed"}),
        ("post", f"/api/assessments/{a}/status", {"status_code": "cancelled"}),
        ("post", f"/api/assessments/{a}/participants", {"user_id": None}),
        ("post", f"/api/assessments/{a}/competences", {"competence_ids": []}),
        ("put", f"/api/assessments/{a}/criteria", {"items": []}),
        ("post", f"/api/assessments/{a}/calibrate", {"results": []}),
        ("post", f"/api/assessments/{a}/calibration/start", None),
        ("post", f"/api/assessments/{a}/calibration/save", {"totals": []}),
        ("post", f"/api/assessments/{a}/calibration/cancel", None),
        ("put", f"/api/assessments/{a}/scale", {"scale_id": str(uuid.uuid4())}),
        ("get", f"/api/assessments/{a}/external-reviewers", None),
        ("post", f"/api/assessments/{a}/external-reviewers", {"name": "Ext"}),
        ("delete", f"/api/assessments/{a}/external-reviewers/{reviewer}", None),
        ("patch", f"/api/pdp/{p}", {"title": "renamed"}),
        ("post", f"/api/pdp/{p}/status", {"status_code": "cancelled"}),
        ("post", f"/api/pdp/{p}/items", {"title": "new item"}),
        ("patch", f"/api/pdp/{p}/items/{item}", {"title": "renamed"}),
        ("delete", f"/api/pdp/{p}/items/{item}", None),
        ("post", f"/api/pdp/{p}/items/reorder", {"ordered_ids": [str(item)]}),
        ("post", f"/api/pdp/{p}/items/{item}/materials", {"title": "m"}),
        (
            "patch",
            f"/api/pdp/{p}/items/{item}/materials/{uuid.uuid4()}",
            {"title": "m"},
        ),
        ("delete", f"/api/pdp/{p}/items/{item}/materials/{uuid.uuid4()}", None),
        ("post", f"/api/pdp/{p}/versions/{uuid.uuid4()}/restore", None),
    ]


async def _call(client: AsyncClient, method: str, path: str, body, headers) -> int:
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    return (await getattr(client, method)(path, **kwargs)).status_code


class TestManagerAssessmentScope:
    async def test_manager_refused_on_a_neighbouring_division(
        self, client: AsyncClient, scoped
    ):
        h = _headers(scoped["mgr_user"])
        for method, path, body in _mutations(scoped, "theirs"):
            code = await _call(client, method, path, body, h)
            assert code == 403, f"{method.upper()} {path} -> {code}"

    async def test_manager_passes_the_fence_on_their_own_subtree(
        self, client: AsyncClient, scoped
    ):
        """Not 403. Some of these still 400/404/409 on the payload — the
        point is that the scope guard is not what stopped them."""
        h = _headers(scoped["mgr_user"])
        for method, path, body in _mutations(scoped, "mine"):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_manager_without_subordinates_is_refused_everywhere(
        self, client: AsyncClient, scoped
    ):
        """Empty scope means nothing, not everything."""
        h = _headers(scoped["lonely_user"])
        for side in ("mine", "theirs"):
            for method, path, body in _mutations(scoped, side):
                code = await _call(client, method, path, body, h)
                assert code == 403, f"{method.upper()} {path} -> {code}"

    async def test_admin_keeps_the_whole_tenant(self, client: AsyncClient, scoped):
        h = _headers(scoped["admin_user"])
        for method, path, body in _mutations(scoped, "theirs"):
            code = await _call(client, method, path, body, h)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_plain_employee_is_still_refused_by_the_role_gate(
        self, client: AsyncClient, scoped
    ):
        h = _headers(scoped["plain_user"])
        for method, path, body in _mutations(scoped, "mine"):
            code = await _call(client, method, path, body, h)
            assert code == 403, f"{method.upper()} {path} -> {code}"

    async def test_create_refuses_an_assessee_from_another_division(
        self, client: AsyncClient, scoped, assessment_types
    ):
        h = _headers(scoped["mgr_user"])
        resp = await client.post(
            "/api/assessments",
            headers=h,
            json={
                "employee_id": str(scoped["theirs_employee"].id),
                "type_code": "360",
            },
        )
        assert resp.status_code == 403
        resp = await client.post(
            "/api/pdp",
            headers=h,
            json={
                "title": "Foreign plan",
                "employee_id": str(scoped["theirs_employee"].id),
            },
        )
        assert resp.status_code == 403

    async def test_create_allows_an_assessee_from_the_managed_subtree(
        self, client: AsyncClient, scoped
    ):
        h = _headers(scoped["mgr_user"])
        resp = await client.post(
            "/api/pdp",
            headers=h,
            json={
                "title": "Own plan",
                "employee_id": str(scoped["mine_employee"].id),
            },
        )
        assert resp.status_code == 201, resp.text

    async def test_named_reviewer_still_drives_the_status(
        self, db: AsyncSession, client: AsyncClient, scoped
    ):
        """``PDP.reviewer_id`` may point outside the assessee's division —
        that is what naming a reviewer is for."""
        theirs = scoped["theirs_pdp"]
        assert (
            await _call(
                client,
                "post",
                f"/api/pdp/{theirs.id}/status",
                {"status_code": "cancelled"},
                _headers(scoped["mgr_user"]),
            )
            == 403
        )
        theirs.reviewer_id = scoped["mgr_user"].id
        await db.commit()
        assert (
            await _call(
                client,
                "post",
                f"/api/pdp/{theirs.id}/status",
                {"status_code": "cancelled"},
                _headers(scoped["mgr_user"]),
            )
            != 403
        )

    async def test_a_mass_assessment_cannot_name_foreign_assessees(
        self, client: AsyncClient, scoped
    ):
        """The one-call bypass: ``POST /assessment-groups`` creates one
        assessment per employee id in the body."""
        h = _headers(scoped["mgr_user"])
        refused = await client.post(
            "/api/assessment-groups",
            headers=h,
            json={
                "title": "Everyone",
                "type_code": "360",
                "employee_ids": [
                    str(scoped["mine_employee"].id),
                    str(scoped["theirs_employee"].id),
                ],
            },
        )
        assert refused.status_code == 403, refused.text

        created = await client.post(
            "/api/assessment-groups",
            headers=h,
            json={
                "title": "My team",
                "type_code": "360",
                "employee_ids": [str(scoped["mine_employee"].id)],
            },
        )
        assert created.status_code == 201, created.text

    async def test_a_group_covering_foreign_people_cannot_be_driven(
        self, client: AsyncClient, scoped
    ):
        """Its lifecycle routes are the same write as the per-assessment
        ones, so they follow the same rule — every child must be theirs."""
        admin = _headers(scoped["admin_user"])
        group = await client.post(
            "/api/assessment-groups",
            headers=admin,
            json={
                "title": "Company-wide",
                "type_code": "360",
                "employee_ids": [
                    str(scoped["mine_employee"].id),
                    str(scoped["theirs_employee"].id),
                ],
            },
        )
        assert group.status_code == 201, group.text
        gid = group.json()["id"]
        h = _headers(scoped["mgr_user"])
        for method, path, body in (
            ("patch", f"/api/assessment-groups/{gid}", {"title": "hijacked"}),
            (
                "post",
                f"/api/assessment-groups/{gid}/status",
                {"status_code": "cancelled"},
            ),
            ("put", f"/api/assessment-groups/{gid}/criteria", {"items": []}),
            (
                "put",
                f"/api/assessment-groups/{gid}/scale",
                {"scale_id": str(uuid.uuid4())},
            ),
        ):
            code = await _call(client, method, path, body, h)
            assert code == 403, f"{method.upper()} {path} -> {code}"
        for method, path, body in (
            ("patch", f"/api/assessment-groups/{gid}", {"title": "renamed"}),
            (
                "post",
                f"/api/assessment-groups/{gid}/status",
                {"status_code": "cancelled"},
            ),
        ):
            code = await _call(client, method, path, body, admin)
            assert code != 403, f"{method.upper()} {path} -> {code}"

    async def test_plan_history_reads_follow_the_plan(
        self, client: AsyncClient, scoped
    ):
        """The restore was fenced; the version reads next to it carry the
        same plan content."""
        h = _headers(scoped["mgr_user"])
        for side, expected in (("mine", 200), ("theirs", 403)):
            pdp = scoped[f"{side}_pdp"].id
            assert (
                await _call(client, "get", f"/api/pdp/{pdp}/versions", None, h)
                == expected
            ), side
            assert (
                await _call(
                    client,
                    "get",
                    f"/api/analytics/pdp/{pdp}/progress",
                    None,
                    h,
                )
                == expected
            ), side

    async def test_comments_do_not_reach_another_division_plan(
        self, client: AsyncClient, scoped
    ):
        h = _headers(scoped["plain_user"])
        assert (
            await _call(
                client,
                "post",
                f"/api/pdp/{scoped['theirs_pdp'].id}/comments",
                {"text": "hello"},
                h,
            )
            == 403
        )

    async def test_ai_pdp_draft_follows_the_assessment(
        self, client: AsyncClient, scoped
    ):
        h = _headers(scoped["mgr_user"])
        refused = await client.post(
            "/api/ai/suggest-pdp",
            headers=h,
            json={"assessment_id": str(scoped["theirs_assessment"].id)},
        )
        assert refused.status_code == 403


class TestEveryMutatingRouteCarriesAGuard:
    """The enforcement the "required argument, no default" rule was after.

    A route added later without a scope guard fails here rather than
    silently handing the tenant to a division head.
    """

    GUARDS = {
        "assessment_scope",
        "assessment_group_scope",
        "pdp_scope",
        "pdp_status_scope",
    }

    # Mutations that are deliberately not fenced by the assessee's
    # division, each for its own reason:
    #  * CPA and mass-exam rows carry no assessee at all, only an author,
    #    so there is nothing to fence them by yet (HRP-640). A mass
    #    assessment does carry assessees and is fenced — see
    #    ``assessment_group_scope``;
    #  * answers and item toggles are gated on being a participant or the
    #    plan's named reviewer — people who are on the plan precisely
    #    because they sit outside the subtree;
    #  * the answer-scale catalogue is tenant-wide with no owning axis, so
    #    it is fenced by role instead (HRP-631);
    #  * the external-review submit route is authenticated by its token.
    EXEMPT = {
        "create_cpa",
        "add_cpa_criteria",
        "add_cpa_participant",
        "copy_cpa",
        "record_answer",
        "mark_item_passed",
        "create_answer_scale",
        "update_answer_scale",
        "delete_answer_scale",
        "submit_external_answers",
    }

    def test_no_unguarded_mutation(self):
        unguarded = []
        for route in app.routes:
            endpoint = getattr(route, "endpoint", None)
            if getattr(endpoint, "__module__", "") != "app.modules.assessment.router":
                continue
            if not getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}:
                continue
            if endpoint.__name__ in self.EXEMPT:
                continue
            names = {d.call.__name__ for d in route.dependant.dependencies if d.call}
            if names & self.GUARDS:
                continue
            source = inspect.getsource(endpoint)
            if (
                "assert_assessee_in_scope" in source
                or "assert_assessees_in_scope" in source
            ):
                continue
            unguarded.append(f"{sorted(route.methods)} {route.path}")
        assert not unguarded, f"mutating routes without a scope guard: {unguarded}"
