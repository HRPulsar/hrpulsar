"""``POST /api/demo/guide`` — the sandbox's start routes (HRP-1159).

The pick is published for the EE watcher, and the plan and assessment
routes get their starting assessment from the real demo seed: done, with a
growth zone, no plan built from it yet. The Coverage route (HRP-1176) gets
its two processes the same way: one with no steps, one with an open gap.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.core.security import create_access_token, hash_password
from app.modules.ai_workforce import service as agents_service
from app.modules.assessment.models import (
    PDP,
    Assessment,
    AssessmentResult,
    AssessmentStatus,
)
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.demo.router import router
from app.modules.primitives import catalog_data
from app.modules.recruitment.models import Vacancy
from app.modules.work import coverage as coverage_service
from app.modules.work.models import WorkContainer, WorkHireNeed, WorkStep
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def enable_demo(
    monkeypatch,
    skill_levels,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
):
    """``test_demo_switch_view.py``'s knobs, plus the reference rows the
    seed needs to write its assessments."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_initial_credits", 0)


@pytest.fixture
def published(monkeypatch) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []

    async def _publish(event: str, data: dict) -> None:
        events.append((event, data))

    monkeypatch.setattr("app.core.events.publish", _publish)
    return events


async def _start(client: AsyncClient) -> tuple[dict[str, str], str]:
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201, start.text
    body = start.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["tenant_id"]


@pytest.mark.asyncio
async def test_plan_route_starts_from_a_done_assessment_with_growth_zones_and_no_plan(
    client: AsyncClient, admin_role, enable_demo, published, db: AsyncSession
):
    headers, tenant_id = await _start(client)

    resp = await client.post("/api/demo/guide", json={"path": "pdp"}, headers=headers)
    assert resp.status_code == 200, resp.text
    anchor = resp.json()["assessment_id"]
    assert anchor, "the demo seed must hold a done assessment to plan from"
    assert published[-1] == (
        "demo.guide_chosen",
        {"tenant_id": tenant_id, "path": "pdp"},
    )

    assessment = await db.get(Assessment, uuid.UUID(anchor))
    assert assessment is not None and str(assessment.tenant_id) == tenant_id
    status = await db.get(AssessmentStatus, assessment.status_id)
    assert status is not None and status.code == "done"
    bar = assessment.passing_score if assessment.passing_score is not None else 75
    percents = (
        (
            await db.execute(
                select(AssessmentResult.percent).where(
                    AssessmentResult.assessment_id == assessment.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(p is not None and p <= bar for p in percents), "no growth zone"
    assert not (
        await db.execute(select(PDP.id).where(PDP.assessment_id == assessment.id))
    ).first()

    # Same sandbox, same answer: the assessment route opens it too.
    again = await client.post(
        "/api/demo/guide", json={"path": "assessment"}, headers=headers
    )
    assert again.json()["assessment_id"] == anchor

    # Planned → never offered again; the next one (or none) takes its place.
    db.add(
        PDP(
            tenant_id=assessment.tenant_id,
            title="From the guide",
            employee_id=assessment.employee_id,
            assessment_id=assessment.id,
            author_id=assessment.initiator_id,
        )
    )
    await db.commit()
    after = await client.post("/api/demo/guide", json={"path": "pdp"}, headers=headers)
    assert after.status_code == 200
    assert after.json()["assessment_id"] != anchor


@pytest.fixture
async def work_catalog(db: AsyncSession):
    """``test_demo_seed_work.py``'s precondition: without the primitive
    catalog and the built-in packs the seed skips its processes whole."""
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    await agents_service.seed_packs(db)
    with patch.object(
        coverage_service, "_schedule_mapping", new=AsyncMock(return_value=False)
    ) as schedule_mapping:
        yield schedule_mapping


@pytest.mark.asyncio
async def test_coverage_route_starts_from_a_process_without_steps_and_knows_a_gap(
    client: AsyncClient,
    admin_role,
    enable_demo,
    published,
    work_catalog,
    db: AsyncSession,
):
    """HRP-1176, on the real seed: "Generate steps" needs a described
    process with no steps, and the hire step a process whose gap the seed
    guarantees - a fresh AI breakdown promises none."""
    headers, tenant_id = await _start(client)
    # Another company's process, older and just as empty: not this
    # sandbox's to start from.
    other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db.add(other)
    await db.flush()
    db.add(
        WorkContainer(
            tenant_id=other.id,
            type="process",
            title="Someone else's process",
            description="Described, and not broken down either.",
            status="draft",
            source="manual",
            catalog_version="1",
            gap_default_label="hire",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    await db.commit()
    work_catalog.reset_mock()

    resp = await client.post(
        "/api/demo/guide", json={"path": "coverage"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assessment_id"] is None
    # Reading where the route starts never starts a model run.
    work_catalog.assert_not_awaited()
    assert published[-1] == (
        "demo.guide_chosen",
        {"tenant_id": tenant_id, "path": "coverage"},
    )

    empty = await db.get(WorkContainer, uuid.UUID(body["process_id"]))
    assert empty is not None and str(empty.tenant_id) == tenant_id
    assert empty.type == "process" and empty.status == "draft"
    assert empty.description, "no description, no Generate steps button"
    assert not (
        await db.execute(select(WorkStep.id).where(WorkStep.container_id == empty.id))
    ).first()

    assert body["gap_process_id"] != body["process_id"]
    gap_process = await db.get(WorkContainer, uuid.UUID(body["gap_process_id"]))
    assert gap_process is not None and str(gap_process.tenant_id) == tenant_id
    gaps = await coverage_service.gaps(
        db, gap_process.tenant_id, gap_process.id, schedule_mapping=False
    )
    open_gaps = [g for g in gaps if g["kind"] == "no_owner" and not g["hire_need"]]
    assert open_gaps, "the hire step has nothing to open a hire need for"

    # Same sandbox, same answer.
    again = await client.post(
        "/api/demo/guide", json={"path": "coverage"}, headers=headers
    )
    assert again.json() == body

    # Broken down → no longer where the route starts; handed to
    # Recruitment → no longer where the hire step leads.
    db.add(
        WorkStep(
            tenant_id=empty.tenant_id,
            container_id=empty.id,
            position=1,
            title="First step",
        )
    )
    db.add(
        WorkHireNeed(
            tenant_id=gap_process.tenant_id,
            container_id=gap_process.id,
            vacancy_id=(
                await db.execute(
                    select(Vacancy.id).where(Vacancy.tenant_id == gap_process.tenant_id)
                )
            )
            .scalars()
            .first(),
            step_ids=[str(g["step_id"]) for g in open_gaps],
            label="hire",
        )
    )
    await db.commit()
    after = await client.post(
        "/api/demo/guide", json={"path": "coverage"}, headers=headers
    )
    assert after.json() == {
        "assessment_id": None,
        "process_id": None,
        "gap_process_id": None,
    }


@pytest.mark.asyncio
async def test_looking_around_is_recorded_without_a_start(
    client: AsyncClient, admin_role, enable_demo, published
):
    headers, tenant_id = await _start(client)

    resp = await client.post("/api/demo/guide", json={"path": "skip"}, headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "assessment_id": None,
        "process_id": None,
        "gap_process_id": None,
    }
    assert published[-1] == (
        "demo.guide_chosen",
        {"tenant_id": tenant_id, "path": "skip"},
    )


@pytest.mark.asyncio
async def test_unknown_route_is_rejected(
    client: AsyncClient, admin_role, enable_demo, published
):
    headers, _ = await _start(client)
    resp = await client.post("/api/demo/guide", json={"path": "tour"}, headers=headers)
    assert resp.status_code == 422
    assert not [e for e in published if e[0] == "demo.guide_chosen"]


@pytest.mark.asyncio
async def test_employee_persona_gets_no_routes(
    client: AsyncClient, admin_role, enable_demo, published
):
    headers, _ = await _start(client)
    switched = await client.post(
        "/api/demo/switch-view", json={"persona": "employee"}, headers=headers
    )
    assert switched.status_code == 200, switched.text
    employee = {"Authorization": f"Bearer {switched.json()['access_token']}"}

    resp = await client.post("/api/demo/guide", json={"path": "pdp"}, headers=employee)

    assert resp.status_code == 403
    assert "demo_guide_requires_demo_admin" in resp.text
    assert not [e for e in published if e[0] == "demo.guide_chosen"]


@pytest.mark.asyncio
async def test_paid_account_gets_no_routes(
    client: AsyncClient, enable_demo, published, db: AsyncSession
):
    suffix = uuid.uuid4().hex[:6]
    tenant = Tenant(name=f"Paid {suffix}", slug=f"paid-{suffix}")
    db.add(tenant)
    await db.flush()
    user = User(
        email=f"paid-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="Paid",
        last_name="User",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    headers = {
        "Authorization": f"Bearer {create_access_token(str(user.id), str(tenant.id))}"
    }

    resp = await client.post("/api/demo/guide", json={"path": "skip"}, headers=headers)

    assert resp.status_code == 403
    assert "demo_guide_requires_demo_admin" in resp.text


def test_the_frontend_calls_the_url_the_router_declares():
    route = next(r for r in router.routes if r.name == "choose_guide")
    assert route.methods == {"POST"}
    source = (BACKEND.parent / "frontend/src/lib/demo.ts").read_text(encoding="utf-8")
    assert f'"{route.path}"' in source
