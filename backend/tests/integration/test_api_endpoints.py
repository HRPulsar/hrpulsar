import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import seed_send_prereqs


class TestCompanyEndpoints:
    async def test_get_company(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/company")
        assert resp.status_code == 200
        assert "name" in resp.json()

    async def test_create_division(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/divisions",
            json={
                "name": "Engineering",
                "description": "Eng dept",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Engineering"

    async def test_get_divisions(self, auth_client: AsyncClient):
        await auth_client.post("/api/divisions", json={"name": "HR"})
        resp = await auth_client.get("/api/divisions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestEmployeeEndpoints:
    async def test_list_employees(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/employees")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_create_employee(self, auth_client: AsyncClient, user):
        resp = await auth_client.post(
            "/api/employees",
            json={
                "user_id": str(user.id),
                "position_title": "Developer",
                "hire_date": "2024-01-15",
            },
        )
        # May return 201 or 409 if employee already exists from fixture
        assert resp.status_code in (201, 409, 400)


class TestAssessmentEndpoints:
    async def test_list_assessments(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/assessments")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_create_assessment(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        resp = await auth_client.post(
            "/api/assessments",
            json={
                "title": "API Test Assessment",
                "employee_id": str(employee.id),
                "type_code": "self",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "API Test Assessment"


class TestDictionaryEndpoints:
    async def test_list_dictionaries(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/dictionaries/grade")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestExamEndpoints:
    async def test_create_mass_exam(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/mass-exams",
            json={
                "title": "Q1 Exam",
                "description": "Quarterly exam",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Q1 Exam"

    async def test_list_mass_exams(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/mass-exams")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestNotificationEndpoints:
    async def test_list_notifications(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/notifications")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_unread_count(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/notifications/unread-count")
        assert resp.status_code == 200
        assert "count" in resp.json()

    async def test_mark_read(self, auth_client: AsyncClient):
        resp = await auth_client.post("/api/notifications/mark-read", json={})
        assert resp.status_code == 200
        assert "updated" in resp.json()


class TestHealthEndpoint:
    async def test_health(self, client: AsyncClient):
        # Seed the celery heartbeat so /health returns ok in CI where the
        # beat scheduler isn't running.
        import asyncio

        import redis.asyncio as aioredis
        from app.config import settings

        r = aioredis.from_url(settings.redis_url)
        try:
            await r.set("status:celery:heartbeat", "ci", ex=90)
        finally:
            await r.aclose()

        # Retry against transient DB-pool blips: after ~2800 tests the
        # asyncpg pool occasionally has a stale connection that fails
        # the first SELECT 1, then recovers. On 503 we surface the
        # full per-check body so future regressions are diagnosable.
        last_resp = None
        for _ in range(3):
            last_resp = await client.get("/health")
            if last_resp.status_code == 200:
                break
            await asyncio.sleep(0.5)
        assert last_resp is not None
        assert last_resp.status_code == 200, last_resp.text
        assert last_resp.json()["status"] == "ok"


# ===================================================================
# Additional coverage tests
# ===================================================================


class TestAssessmentParticipantsAndWorkflow:
    """Cover add/remove participants, competences, answers, results, calibrate, scales."""

    async def _create_assessment(
        self, auth_client, employee, assessment_statuses, assessment_types
    ):
        resp = await auth_client.post(
            "/api/assessments",
            json={
                "title": f"Workflow Test {uuid.uuid4().hex[:6]}",
                "employee_id": str(employee.id),
                "type_code": "360",
            },
        )
        assert resp.status_code == 201
        return resp.json()

    async def test_get_assessment_detail(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_assessment(
            auth_client, employee, assessment_statuses, assessment_types
        )
        resp = await auth_client.get(f"/api/assessments/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert "participants" in data
        assert "competence_ids" in data
        assert "results" in data

    async def test_add_participant(
        self,
        auth_client: AsyncClient,
        db: AsyncSession,
        employee,
        tenant,
        admin_role,
        position,
        assessment_statuses,
        assessment_types,
    ):
        # HRP-18 auto-adds the assessee as a "self" participant on create, so
        # we need a *second* user/employee to validate manual add-participant.
        from datetime import date, datetime, timezone

        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles
        from app.modules.employee.models import Employee

        peer_user = User(
            email=f"peer-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="Peer",
            last_name="Reviewer",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(peer_user)
        await db.commit()
        await db.refresh(peer_user)
        await db.execute(
            user_roles.insert().values(user_id=peer_user.id, role_id=admin_role.id)
        )
        peer_emp = Employee(
            user_id=peer_user.id,
            tenant_id=tenant.id,
            position_id=position.id,
            position_title=position.title,
            hire_date=date(2024, 1, 15),
        )
        db.add(peer_emp)
        await db.commit()
        await db.refresh(peer_emp)

        created = await self._create_assessment(
            auth_client, employee, assessment_statuses, assessment_types
        )
        resp = await auth_client.post(
            f"/api/assessments/{created['id']}/participants",
            json={
                "employee_id": str(peer_emp.id),
                "role": "manager",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["user_id"] == str(peer_user.id)
        assert data["role"] == "manager"
        assert data["is_completed"] is False

    async def test_add_competences(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_assessment(
            auth_client, employee, assessment_statuses, assessment_types
        )
        # Use empty list to avoid FK constraint issues
        resp = await auth_client.post(
            f"/api/assessments/{created['id']}/competences",
            json={"competence_ids": []},
        )
        assert resp.status_code == 201

    async def test_get_results(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_assessment(
            auth_client, employee, assessment_statuses, assessment_types
        )
        resp = await auth_client.get(f"/api/assessments/{created['id']}/results")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_calibrate(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_assessment(
            auth_client, employee, assessment_statuses, assessment_types
        )
        resp = await auth_client.post(
            f"/api/assessments/{created['id']}/calibrate",
            json={
                "results": [],
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_change_status(
        self,
        auth_client: AsyncClient,
        db: AsyncSession,
        employee,
        tenant,
        assessment_statuses,
        assessment_types,
    ):
        created = await self._create_assessment(
            auth_client, employee, assessment_statuses, assessment_types
        )
        await seed_send_prereqs(db, tenant.id, uuid.UUID(created["id"]))
        resp = await auth_client.post(
            f"/api/assessments/{created['id']}/status",
            json={
                "status_code": "sent",
            },
        )
        assert resp.status_code == 200

    async def test_list_answer_scales(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/answer-scales")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAssessmentCPA:
    """Cover CPA create and list."""

    async def test_create_cpa(
        self, auth_client: AsyncClient, assessment_statuses, assessment_types
    ):
        resp = await auth_client.post(
            "/api/cpa",
            json={
                "title": f"CPA Test {uuid.uuid4().hex[:6]}",
                "type_code": "360",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"].startswith("CPA Test")
        assert "id" in data

    async def test_list_cpas(
        self, auth_client: AsyncClient, assessment_statuses, assessment_types
    ):
        # Create one first
        await auth_client.post(
            "/api/cpa",
            json={
                "title": f"CPA List {uuid.uuid4().hex[:6]}",
                "type_code": "self",
            },
        )
        resp = await auth_client.get("/api/cpa")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAssessmentPDP:
    """Cover PDP CRUD, items, materials, comments."""

    async def _create_pdp(self, auth_client, employee):
        resp = await auth_client.post(
            "/api/pdp",
            json={
                "title": "Plan",
                "employee_id": str(employee.id),
            },
        )
        assert resp.status_code == 201
        return resp.json()

    async def test_create_pdp(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        data = await self._create_pdp(auth_client, employee)
        assert data["employee_id"] == str(employee.id)
        assert data["status"] == "draft"

    async def test_list_pdps(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        await self._create_pdp(auth_client, employee)
        resp = await auth_client.get("/api/pdp")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    async def test_list_pdps_by_employee(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        await self._create_pdp(auth_client, employee)
        resp = await auth_client.get(f"/api/pdp?employee_id={employee.id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_pdp_detail(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_pdp(auth_client, employee)
        resp = await auth_client.get(f"/api/pdp/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "comments" in data

    async def test_change_pdp_status(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        # HRP-12: the plan needs at least one item with a material before
        # draft → sent is allowed.
        created = await self._create_pdp(auth_client, employee)
        item_resp = await auth_client.post(
            f"/api/pdp/{created['id']}/items", json={"title": "x"}
        )
        assert item_resp.status_code == 201
        item_id = item_resp.json()["id"]
        mat_resp = await auth_client.post(
            f"/api/pdp/{created['id']}/items/{item_id}/materials",
            json={"title": "m", "link": "https://example.com"},
        )
        assert mat_resp.status_code == 201
        resp = await auth_client.post(
            f"/api/pdp/{created['id']}/status",
            json={
                "status_code": "sent",
            },
        )
        assert resp.status_code == 200

    async def test_patch_pdp_title(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_pdp(auth_client, employee)
        resp = await auth_client.patch(
            f"/api/pdp/{created['id']}",
            json={"title": "New title"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New title"

    async def test_patch_pdp_empty_body(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_pdp(auth_client, employee)
        resp = await auth_client.patch(f"/api/pdp/{created['id']}", json={})
        assert resp.status_code == 422

    async def test_patch_pdp_unknown_field(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_pdp(auth_client, employee)
        resp = await auth_client.patch(
            f"/api/pdp/{created['id']}", json={"status": "done"}
        )
        assert resp.status_code == 422

    async def test_add_pdp_item(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_pdp(auth_client, employee)
        resp = await auth_client.post(
            f"/api/pdp/{created['id']}/items",
            json={
                "title": "Learn Python testing",
                "description": "Complete pytest course",
                "sort_index": 1,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Learn Python testing"
        assert data["is_passed"] is False

    async def test_mark_item_passed(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        # HRP-12 + HRP-13 + HRP-20: marking now requires the plan to be in
        # sent / in_progress / returned, every item to carry a material, and
        # the caller to be the plan owner. The auth_client fixture is signed
        # in as the user that owns ``employee``, so owner-check passes once
        # we (a) seed a material, (b) send the plan, then (c) tick the item
        # (auto-promotes to in_progress).
        created = await self._create_pdp(auth_client, employee)
        item_resp = await auth_client.post(
            f"/api/pdp/{created['id']}/items",
            json={
                "title": "Passable item",
            },
        )
        assert item_resp.status_code == 201
        item_id = item_resp.json()["id"]
        mat_resp = await auth_client.post(
            f"/api/pdp/{created['id']}/items/{item_id}/materials",
            json={"title": "Mat", "link": "https://example.com"},
        )
        assert mat_resp.status_code == 201
        send_resp = await auth_client.post(
            f"/api/pdp/{created['id']}/status", json={"status_code": "sent"}
        )
        assert send_resp.status_code == 200
        resp = await auth_client.post(f"/api/pdp/{created['id']}/items/{item_id}/pass")
        assert resp.status_code == 200

    async def test_add_pdp_material(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_pdp(auth_client, employee)
        item_resp = await auth_client.post(
            f"/api/pdp/{created['id']}/items",
            json={
                "title": "Material target item",
            },
        )
        assert item_resp.status_code == 201
        item_id = item_resp.json()["id"]
        resp = await auth_client.post(
            f"/api/pdp/{created['id']}/items/{item_id}/materials",
            json={
                "title": "Pytest docs",
                "format": "article",
                "link": "https://docs.pytest.org",
                "study_time": 120,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Pytest docs"
        assert data["format"] == "article"

    async def test_add_pdp_comment(
        self, auth_client: AsyncClient, employee, assessment_statuses, assessment_types
    ):
        created = await self._create_pdp(auth_client, employee)
        resp = await auth_client.post(
            f"/api/pdp/{created['id']}/comments",
            json={
                "text": "Great progress so far!",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["text"] == "Great progress so far!"
        assert data["pdp_id"] == created["id"]


class TestCompetenceGroupsAndCompetences:
    """Cover competence groups, competences, indicators, skill levels."""

    async def _create_group(self, auth_client):
        resp = await auth_client.post(
            "/api/competence-groups",
            json={
                "title": f"Group {uuid.uuid4().hex[:6]}",
                "description": "Test group",
            },
        )
        assert resp.status_code == 201
        return resp.json()

    async def _create_competence(self, auth_client, group_id):
        resp = await auth_client.post(
            "/api/competences",
            json={
                "title": f"Competence {uuid.uuid4().hex[:6]}",
                "description": "Test competence",
                "group_id": group_id,
            },
        )
        assert resp.status_code == 201
        return resp.json()

    async def test_create_competence_group(self, auth_client: AsyncClient):
        data = await self._create_group(auth_client)
        assert "id" in data
        assert data["title"].startswith("Group")
        assert data["is_active"] is True

    async def test_update_competence_group(self, auth_client: AsyncClient):
        group = await self._create_group(auth_client)
        resp = await auth_client.put(
            f"/api/competence-groups/{group['id']}",
            json={
                "title": "Updated Group Title",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Group Title"

    async def test_delete_competence_group(self, auth_client: AsyncClient):
        group = await self._create_group(auth_client)
        resp = await auth_client.delete(f"/api/competence-groups/{group['id']}")
        assert resp.status_code == 204

    async def test_get_competence_tree(self, auth_client: AsyncClient):
        await self._create_group(auth_client)
        resp = await auth_client.get("/api/competence-tree")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_competence(self, auth_client: AsyncClient):
        group = await self._create_group(auth_client)
        data = await self._create_competence(auth_client, group["id"])
        assert data["title"].startswith("Competence")
        assert data["group_id"] == group["id"]
        assert data["is_active"] is True

    async def test_get_competence_detail(self, auth_client: AsyncClient):
        group = await self._create_group(auth_client)
        comp = await self._create_competence(auth_client, group["id"])
        resp = await auth_client.get(f"/api/competences/{comp['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == comp["id"]
        assert "indicators" in data
        assert "materials" in data

    async def test_update_competence(self, auth_client: AsyncClient):
        group = await self._create_group(auth_client)
        comp = await self._create_competence(auth_client, group["id"])
        resp = await auth_client.put(
            f"/api/competences/{comp['id']}",
            json={
                "title": "Updated Competence",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Competence"

    async def test_delete_competence(self, auth_client: AsyncClient):
        group = await self._create_group(auth_client)
        comp = await self._create_competence(auth_client, group["id"])
        resp = await auth_client.delete(f"/api/competences/{comp['id']}")
        assert resp.status_code == 204

    async def test_list_skill_levels(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/skill-levels")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_indicator(self, auth_client: AsyncClient):
        group = await self._create_group(auth_client)
        comp = await self._create_competence(auth_client, group["id"])
        # Need a skill level; fetch existing or use a fake one
        sl_resp = await auth_client.get("/api/skill-levels")
        levels = sl_resp.json()
        if not levels:
            pytest.skip("No skill levels seeded")
        skill_level_id = levels[0]["id"]
        resp = await auth_client.post(
            f"/api/competences/{comp['id']}/indicators",
            json={
                "title": f"Indicator {uuid.uuid4().hex[:6]}",
                "weight": 10,
                "sort_index": 1,
                "skill_level_id": skill_level_id,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"].startswith("Indicator")
        assert data["competence_id"] == comp["id"]


class TestAuthForgotResetPassword:
    """Cover forgot-password, reset-password, role CRUD."""

    async def test_forgot_password_existing_email(self, auth_client: AsyncClient, user):
        resp = await auth_client.post(
            "/api/auth/forgot-password",
            json={
                "email": user.email,
            },
        )
        assert resp.status_code == 200
        assert "message" in resp.json()

    async def test_forgot_password_nonexistent_email(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/forgot-password",
            json={
                "email": "nobody@example.com",
            },
        )
        # Always returns success to prevent email enumeration
        assert resp.status_code == 200
        assert "message" in resp.json()

    async def test_reset_password_invalid_token(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/reset-password",
            json={
                "token": "invalid-token-value",
                "new_password": "newpassword123",
            },
        )
        # Should fail with 400 or 404 for bad token
        assert resp.status_code in (400, 404, 422)

    async def test_list_roles(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/roles")
        assert resp.status_code == 200
        roles = resp.json()
        assert isinstance(roles, list)
        assert len(roles) >= 1
        # Should have at least the admin role
        codes = [r["code"] for r in roles]
        assert "admin" in codes

    async def test_create_role(self, auth_client: AsyncClient):
        code = f"role_{uuid.uuid4().hex[:6]}"
        resp = await auth_client.post(
            "/api/roles",
            json={
                "name": f"Test Role {code}",
                "code": code,
                "description": "A test role",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == code
        assert data["is_system"] is False

    async def test_update_role(self, auth_client: AsyncClient):
        code = f"upd_{uuid.uuid4().hex[:6]}"
        create_resp = await auth_client.post(
            "/api/roles",
            json={
                "name": "Updatable Role",
                "code": code,
            },
        )
        assert create_resp.status_code == 201
        role_id = create_resp.json()["id"]
        resp = await auth_client.put(
            f"/api/roles/{role_id}",
            json={
                "name": "Updated Role Name",
                "description": "Updated description",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Role Name"

    async def test_delete_role(self, auth_client: AsyncClient):
        code = f"del_{uuid.uuid4().hex[:6]}"
        create_resp = await auth_client.post(
            "/api/roles",
            json={
                "name": "Deletable Role",
                "code": code,
            },
        )
        assert create_resp.status_code == 201
        role_id = create_resp.json()["id"]
        resp = await auth_client.delete(f"/api/roles/{role_id}")
        assert resp.status_code == 204


class TestEmployeeDetailAndEvents:
    """Cover get employee, update employee, events CRUD."""

    async def test_get_employee(self, auth_client: AsyncClient, employee):
        resp = await auth_client.get(f"/api/employees/{employee.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(employee.id)
        assert data["position_title"] == "Software Engineer"

    async def test_get_employee_not_found(self, auth_client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.get(f"/api/employees/{fake_id}")
        assert resp.status_code == 404

    async def test_update_employee(self, auth_client: AsyncClient, employee):
        resp = await auth_client.put(
            f"/api/employees/{employee.id}",
            json={
                "status": "on_leave",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "on_leave"

    async def test_list_events_empty(self, auth_client: AsyncClient, employee):
        resp = await auth_client.get(f"/api/employees/{employee.id}/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_event(self, auth_client: AsyncClient, employee):
        resp = await auth_client.post(
            f"/api/employees/{employee.id}/events",
            json={
                "event_type": "promotion",
                "description": "Promoted to senior",
                "event_date": "2025-06-01",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["event_type"] == "promotion"
        assert data["employee_id"] == str(employee.id)

    async def test_create_and_list_events(self, auth_client: AsyncClient, employee):
        await auth_client.post(
            f"/api/employees/{employee.id}/events",
            json={
                "event_type": "training",
                "description": "Completed AWS course",
                "event_date": "2025-07-15",
            },
        )
        resp = await auth_client.get(f"/api/employees/{employee.id}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        types = [e["event_type"] for e in events]
        assert "training" in types


class TestTalentMarketEndpoints:
    """Cover talent market card CRUD, search, publish, requirements, candidates."""

    async def _create_card(self, auth_client):
        resp = await auth_client.post(
            "/api/talent-market",
            json={
                "title": f"Vacancy {uuid.uuid4().hex[:6]}",
                "description": "Looking for a Python developer",
                "card_type": "vacancy",
            },
        )
        assert resp.status_code == 201
        return resp.json()

    async def test_create_card(self, auth_client: AsyncClient):
        data = await self._create_card(auth_client)
        assert data["card_type"] == "vacancy"
        assert data["status"] == "draft"
        assert data["is_published"] is False

    async def test_search_cards(self, auth_client: AsyncClient):
        await self._create_card(auth_client)
        resp = await auth_client.post(
            "/api/talent-market/search",
            json={
                "card_type": "vacancy",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_search_cards_empty_filter(self, auth_client: AsyncClient):
        resp = await auth_client.post("/api/talent-market/search", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    async def test_get_card_detail(self, auth_client: AsyncClient):
        card = await self._create_card(auth_client)
        resp = await auth_client.get(f"/api/talent-market/{card['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == card["id"]
        assert "requirements" in data
        assert "candidates" in data

    async def test_update_card(self, auth_client: AsyncClient):
        card = await self._create_card(auth_client)
        resp = await auth_client.put(
            f"/api/talent-market/{card['id']}",
            json={
                "title": "Updated Vacancy Title",
                "description": "Updated description",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Vacancy Title"

    async def _attach_required_competence(self, auth_client, card_id: str) -> None:
        """HRP-87: publish requires ≥1 Required Competence — wire one up."""
        group = await auth_client.post(
            "/api/competence-groups",
            json={"title": f"G-{uuid.uuid4().hex[:6]}"},
        )
        assert group.status_code == 201
        comp = await auth_client.post(
            "/api/competences",
            json={
                "title": f"C-{uuid.uuid4().hex[:6]}",
                "group_id": group.json()["id"],
            },
        )
        assert comp.status_code == 201
        level = await auth_client.post(
            "/api/skill-levels",
            json={"title": f"L-{uuid.uuid4().hex[:6]}", "sort_index": 0},
        )
        assert level.status_code in (200, 201)
        link = await auth_client.post(
            f"/api/talent-market/{card_id}/required-competences",
            json={
                "items": [
                    {
                        "competence_id": comp.json()["id"],
                        "skill_level_id": level.json()["id"],
                    }
                ],
            },
        )
        assert link.status_code == 201

    async def test_publish_card(self, auth_client: AsyncClient, employee):
        card = await self._create_card(auth_client)
        await self._attach_required_competence(auth_client, card["id"])
        # HRP-150: publish also requires at least one Candidate attached.
        cand = await auth_client.post(
            f"/api/talent-market/{card['id']}/candidates",
            json={"employee_id": str(employee.id)},
        )
        assert cand.status_code == 201
        resp = await auth_client.post(f"/api/talent-market/{card['id']}/publish")
        assert resp.status_code == 200
        assert resp.json()["is_published"] is True

    async def test_publish_without_required_competence_rejected(
        self, auth_client: AsyncClient
    ):
        """HRP-87: empty Required Competence block → 422."""
        card = await self._create_card(auth_client)
        resp = await auth_client.post(f"/api/talent-market/{card['id']}/publish")
        assert resp.status_code == 422

    async def test_delete_card(self, auth_client: AsyncClient):
        card = await self._create_card(auth_client)
        resp = await auth_client.delete(f"/api/talent-market/{card['id']}")
        assert resp.status_code == 204

    async def test_add_requirement(self, auth_client: AsyncClient):
        card = await self._create_card(auth_client)
        resp = await auth_client.post(
            f"/api/talent-market/{card['id']}/requirements",
            json={
                "description": "3+ years Python experience",
                "min_experience_years": 3,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["description"] == "3+ years Python experience"
        assert data["min_experience_years"] == 3

    async def test_add_candidate(self, auth_client: AsyncClient, employee):
        card = await self._create_card(auth_client)
        resp = await auth_client.post(
            f"/api/talent-market/{card['id']}/candidates",
            json={
                "employee_id": str(employee.id),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["employee_id"] == str(employee.id)
        # HRP-214: matched / not_matched / appointed replaced nominated
        assert data["status"] in ("matched", "not_matched", "appointed")

    async def test_get_card_not_found(self, auth_client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.get(f"/api/talent-market/{fake_id}")
        assert resp.status_code == 404
