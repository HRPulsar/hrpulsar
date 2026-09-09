"""Dev-loop analytics — stages, rule-based findings, AI-summary cache.

Covers the dashboard management engine (``analytics.service.dev_loop``):
one test per rule, plus the Redis fingerprint cache that keeps repeat
AI-summary requests over unchanged data free of LLM calls.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.analytics import service as analytics_service
from app.modules.assessment.models import (
    PDP,
    Assessment,
    AssessmentParticipant,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee import issues
from app.modules.employee.models import Employee
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Any UUID works as the AI-summary caller identity — it only scopes the
# per-user budget counter in Redis.
_CALLER = uuid.UUID("00000000-0000-0000-0000-000000000ca1")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def status_done(db: AsyncSession):
    result = await db.execute(
        select(AssessmentStatus).where(AssessmentStatus.code == "done")
    )
    s = result.scalar_one_or_none()
    if not s:
        s = AssessmentStatus(code="done", title="Done", sequence=6)
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return s


@pytest_asyncio.fixture
async def type_self(db: AsyncSession):
    result = await db.execute(
        select(AssessmentType).where(AssessmentType.code == "self")
    )
    t = result.scalar_one_or_none()
    if not t:
        t = AssessmentType(code="self", title="Self assessment")
        db.add(t)
        await db.commit()
        await db.refresh(t)
    return t


@pytest_asyncio.fixture
async def tenant(db: AsyncSession):
    suffix = uuid.uuid4().hex[:6]
    t = Tenant(name=f"Loop-{suffix}", slug=f"loop-{suffix}")
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _make_employee(
    db: AsyncSession, tenant: Tenant, *, last_name: str = "Doe", status: str = "active"
) -> Employee:
    suffix = uuid.uuid4().hex[:6]
    user = User(
        email=f"loop-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="Jane",
        last_name=last_name,
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        position_title="Engineer",
        hire_date=date(2024, 1, 15),
        status=status,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _make_competence(db: AsyncSession, tenant: Tenant) -> Competence:
    group = CompetenceGroup(tenant_id=tenant.id, title=f"Group {uuid.uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    comp = Competence(
        tenant_id=tenant.id,
        group_id=group.id,
        title=f"Comp {uuid.uuid4().hex[:6]}",
    )
    db.add(comp)
    await db.flush()
    return comp


async def _make_done_assessment(
    db: AsyncSession,
    tenant: Tenant,
    emp: Employee,
    status_done: AssessmentStatus,
    type_self: AssessmentType,
    *,
    percent: int | None = None,
    finished_days_ago: int = 3,
    competence: Competence | None = None,
    passing_score: int | None = None,
) -> Assessment:
    a = Assessment(
        tenant_id=tenant.id,
        title=f"Review {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        type_id=type_self.id,
        status_id=status_done.id,
        initiator_id=emp.user_id,
        finished_at=datetime.now(UTC) - timedelta(days=finished_days_ago),
        passing_score=passing_score,
    )
    db.add(a)
    await db.flush()
    if percent is not None:
        comp = competence or await _make_competence(db, tenant)
        db.add(
            AssessmentResult(
                assessment_id=a.id,
                competence_id=comp.id,
                avg_score=percent / 25,
                percent=percent,
            )
        )
    await db.commit()
    await db.refresh(a)
    return a


def _pdp(tenant: Tenant, emp: Employee, **kwargs) -> PDP:
    return PDP(
        tenant_id=tenant.id,
        title=f"Plan {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        author_id=emp.user_id,
        **kwargs,
    )


def _finding(payload: dict, code: str) -> dict | None:
    return next((f for f in payload["findings"] if f["code"] == code), None)


# ---------------------------------------------------------------------------
# Stage / finding rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_tenant_returns_zeroes(db: AsyncSession, tenant):
    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["assessed"] == {
        "covered": 0,
        "total_active": 0,
        "percent": 0,
    }
    assert payload["stages"]["gaps"] == {
        "employees": 0,
        "competences": 0,
        "without_plan": 0,
    }
    assert payload["findings"] == []
    assert payload["data_version"]


@pytest.mark.asyncio
async def test_gap_below_bar_without_plan(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant, last_name="Gapman")
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=60)

    payload = await analytics_service.dev_loop(db, tenant.id, None)

    assert payload["stages"]["assessed"]["covered"] == 1
    assert payload["stages"]["gaps"] == {
        "employees": 1,
        "competences": 1,
        "without_plan": 1,
    }
    finding = _finding(payload, "gaps_without_plan")
    assert finding is not None
    assert finding["count"] == 1
    assert finding["severity"] == "alert"
    assert finding["employees"][0]["name"] == "Jane Gapman"


@pytest.mark.asyncio
async def test_result_at_the_bar_is_a_gap(
    db: AsyncSession, tenant, status_done, type_self
):
    # HRP-731: the bar itself counts as a growth zone. One rule across the
    # product, and it is the inclusive one the group analytics always used.
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=75)

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["gaps"] == {
        "employees": 1,
        "competences": 1,
        "without_plan": 1,
    }
    assert _finding(payload, "gaps_without_plan") is not None


@pytest.mark.asyncio
async def test_result_just_above_the_bar_is_not_a_gap(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=76)

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["gaps"] == {
        "employees": 0,
        "competences": 0,
        "without_plan": 0,
    }
    assert _finding(payload, "gaps_without_plan") is None


@pytest.mark.asyncio
async def test_gap_with_open_pdp_not_flagged(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=50)
    db.add(_pdp(tenant, emp, status="in_progress"))
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert _finding(payload, "gaps_without_plan") is None
    # HRP-656: the gap is real but planned — the tile must not go red.
    assert payload["stages"]["gaps"]["employees"] == 1
    assert payload["stages"]["gaps"]["without_plan"] == 0
    assert payload["stages"]["developing"]["gap_employees_with_plan"] == 1
    assert payload["stages"]["developing"]["open_pdps"] == 1


@pytest.mark.asyncio
async def test_pdp_overdue_flagged(db: AsyncSession, tenant):
    emp = await _make_employee(db, tenant, last_name="Late")
    db.add(
        _pdp(
            tenant,
            emp,
            status="in_progress",
            deadline=datetime.now(UTC) - timedelta(days=14),
        )
    )
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    finding = _finding(payload, "pdp_overdue")
    assert finding is not None
    assert finding["count"] == 1
    assert finding["severity"] == "alert"


@pytest.mark.asyncio
async def test_pdp_stuck_in_review_flagged(db: AsyncSession, tenant):
    emp = await _make_employee(db, tenant)
    stale = datetime.now(UTC) - timedelta(days=30)
    db.add(_pdp(tenant, emp, status="review", updated_at=stale))
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    finding = _finding(payload, "pdp_stuck_review")
    assert finding is not None
    assert finding["count"] == 1
    assert finding["severity"] == "warn"


@pytest.mark.asyncio
async def test_stale_assessment_counts_as_uncovered(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self, finished_days_ago=200
    )
    await _make_employee(db, tenant)  # never assessed

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["assessed"]["covered"] == 0
    finding = _finding(payload, "assessment_coverage")
    assert finding is not None
    assert finding["count"] == 2
    assert finding["severity"] == "info"


@pytest.mark.asyncio
async def test_gap_closed_by_reassessment(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    comp = await _make_competence(db, tenant)
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=60,
        finished_days_ago=80,
        competence=comp,
    )
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=85,
        finished_days_ago=3,
        competence=comp,
    )

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["closed"]["gaps_closed"] == 1
    # the fresh result sits above the bar — no current gap either
    assert payload["stages"]["gaps"] == {
        "employees": 0,
        "competences": 0,
        "without_plan": 0,
    }


@pytest.mark.asyncio
async def test_closure_outside_window_not_counted(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    comp = await _make_competence(db, tenant)
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=60,
        finished_days_ago=200,
        competence=comp,
    )
    # the closing assessment itself finished before the 90-day window
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=85,
        finished_days_ago=100,
        competence=comp,
    )

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["closed"]["gaps_closed"] == 0


@pytest.mark.asyncio
async def test_plans_done_on_time_in_closed_window(db: AsyncSession, tenant):
    emp = await _make_employee(db, tenant)
    now = datetime.now(UTC)
    # done inside the window, before its deadline → counts
    db.add(
        _pdp(
            tenant,
            emp,
            status="done",
            finished_at=now - timedelta(days=10),
            deadline=now - timedelta(days=5),
        )
    )
    # done inside the window but after the deadline → late, not counted
    db.add(
        _pdp(
            tenant,
            emp,
            status="done",
            finished_at=now - timedelta(days=10),
            deadline=now - timedelta(days=20),
        )
    )
    # done on time but outside the 90-day window → not counted
    db.add(
        _pdp(
            tenant,
            emp,
            status="done",
            finished_at=now - timedelta(days=120),
            deadline=now - timedelta(days=100),
        )
    )
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["closed"]["plans_done_on_time"] == 1


# ---------------------------------------------------------------------------
# AI-summary fingerprint cache
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Dict-backed stand-in for the async Redis client."""

    def __init__(self, store: dict):
        self._store = store

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def aclose(self):
        pass


@pytest.fixture
def fake_redis(monkeypatch):
    import app.core.redis as redis_helper

    store: dict = {}
    monkeypatch.setattr(
        redis_helper.aioredis, "from_url", lambda *a, **kw: _FakeRedis(store)
    )
    return store


@pytest.mark.asyncio
async def test_ai_summary_generated_once_per_data_state(
    db: AsyncSession, tenant, fake_redis, monkeypatch
):
    calls = []

    async def _fake_generate(db_, tenant_id, payload):
        calls.append(payload["data_version"])
        return "summary text"

    monkeypatch.setattr(analytics_service, "generate_dev_loop_summary", _fake_generate)

    first = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )
    second = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )

    assert first == {
        "summary": "summary text",
        "cached": False,
        "data_version": first["data_version"],
    }
    assert second["cached"] is True
    assert second["summary"] == "summary text"
    assert len(calls) == 1  # repeat click over unchanged data is free


@pytest.mark.asyncio
async def test_ai_summary_regenerates_when_data_changes(
    db: AsyncSession, tenant, fake_redis, monkeypatch
):
    calls = []

    async def _fake_generate(db_, tenant_id, payload):
        calls.append(payload["data_version"])
        return f"summary {len(calls)}"

    monkeypatch.setattr(analytics_service, "generate_dev_loop_summary", _fake_generate)

    first = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )
    await _make_employee(db, tenant)  # loop state changes → new fingerprint
    second = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )

    assert first["data_version"] != second["data_version"]
    assert second["cached"] is False
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_ai_summary_fails_open_without_redis(
    db: AsyncSession, tenant, monkeypatch
):
    import app.core.redis as redis_helper

    def _explode(*a, **kw):
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_helper.aioredis, "from_url", _explode)

    async def _fake_generate(db_, tenant_id, payload):
        return "no-cache summary"

    monkeypatch.setattr(analytics_service, "generate_dev_loop_summary", _fake_generate)

    result = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )
    assert result["summary"] == "no-cache summary"
    assert result["cached"] is False


# ---------------------------------------------------------------------------
# Personal loop (my_loop)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_loop_without_employee_profile_404(db: AsyncSession, tenant):
    user = User(
        email=f"noemp-{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="No",
        last_name="Employee",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()

    with pytest.raises(AppError) as exc:
        await analytics_service.my_loop(db, tenant.id, user.id)
    assert exc.value.status_code == 404
    assert exc.value.code == "employee_profile_not_found"


@pytest.mark.asyncio
async def test_my_loop_stages_and_gap_finding(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=60)

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)

    assert payload["stages"]["assessed"]["avg_percent"] == 60
    assert payload["stages"]["gaps"]["competences"] == 1
    assert payload["stages"]["developing"]["pdp"] is None
    codes = {f["code"] for f in payload["findings"]}
    assert "gap_without_plan" in codes
    assert "assessment_stale" not in codes
    assert payload["history"][0]["avg_percent"] == 60
    assert payload["data_version"]


@pytest.mark.asyncio
async def test_my_loop_stale_and_survey_pending(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    # in_progress assessment with an incomplete participation for me
    result = await db.execute(
        select(AssessmentStatus).where(AssessmentStatus.code == "in_progress")
    )
    in_progress = result.scalar_one_or_none()
    if not in_progress:
        in_progress = AssessmentStatus(
            code="in_progress", title="In progress", sequence=3
        )
        db.add(in_progress)
        await db.flush()
    a = Assessment(
        tenant_id=tenant.id,
        title=f"Survey {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        type_id=type_self.id,
        status_id=in_progress.id,
        initiator_id=emp.user_id,
    )
    db.add(a)
    await db.flush()
    db.add(
        AssessmentParticipant(
            assessment_id=a.id, user_id=emp.user_id, role="self", is_completed=False
        )
    )
    await db.commit()

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    findings = {f["code"]: f for f in payload["findings"]}
    assert findings["survey_pending"]["count"] == 1
    assert findings["survey_pending"]["href"] == f"/assessments/{a.id}"
    # no done assessment at all → stale
    assert "assessment_stale" in findings


@pytest.mark.asyncio
async def test_my_loop_personal_closure_and_strengths(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    comp = await _make_competence(db, tenant)
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=60,
        finished_days_ago=80,
        competence=comp,
    )
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=85,
        finished_days_ago=3,
        competence=comp,
    )

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    assert payload["stages"]["closed"]["gaps_closed"] == 1
    assert payload["strengths"]["top"][0]["percent"] == 85
    # I'm the only holder of this competence in the tenant → rare skill
    assert [s["percent"] for s in payload["strengths"]["rare_skills"]] == [85]
    assert len(payload["history"]) == 2


@pytest.mark.asyncio
async def test_zero_passing_bar_is_respected(
    db: AsyncSession, tenant, status_done, type_self
):
    """A stored bar of 0 means "no bar" — it must not fall back to 75."""
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self, percent=40, passing_score=0
    )

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["gaps"] == {
        "employees": 0,
        "competences": 0,
        "without_plan": 0,
    }
    assert _finding(payload, "gaps_without_plan") is None

    personal = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    assert personal["stages"]["gaps"]["competences"] == 0
    assert [s["percent"] for s in personal["strengths"]["top"]] == [40]


@pytest.mark.asyncio
async def test_my_loop_below_bar_scores_are_not_strengths(
    db: AsyncSession, tenant, status_done, type_self
):
    """All-gaps employee: the weakest scores must not be praised as
    strengths (nor fed to the coach LLM as such)."""
    emp = await _make_employee(db, tenant)
    for percent in (30, 25, 20):
        await _make_done_assessment(
            db, tenant, emp, status_done, type_self, percent=percent
        )

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    assert payload["strengths"]["top"] == []
    assert payload["strengths"]["rare_skills"] == []


@pytest.mark.asyncio
async def test_my_loop_growth_next_grade(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    comp = await _make_competence(db, tenant)
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self, percent=80, competence=comp
    )

    suffix = uuid.uuid4().hex[:6]
    spec = DictionaryItem(
        type="specialization", title=f"Backend {suffix}", tenant_id=tenant.id
    )
    junior = DictionaryItem(type="grade", title=f"Junior {suffix}", tenant_id=tenant.id)
    senior = DictionaryItem(type="grade", title=f"Senior {suffix}", tenant_id=tenant.id)
    db.add_all([spec, junior, senior])
    await db.flush()
    gs_junior = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=junior.id,
        specialization_id=spec.id,
        sort_index=0,
        salary_currency="EUR",
    )
    gs_senior = GradeSpecialization(
        tenant_id=tenant.id,
        grade_id=senior.id,
        specialization_id=spec.id,
        sort_index=1,
        salary_currency="EUR",
    )
    db.add_all([gs_junior, gs_senior])
    await db.flush()
    level = SkillLevel(title=f"Advanced {suffix}", tenant_id=tenant.id)
    missing_comp = await _make_competence(db, tenant)
    db.add(level)
    await db.flush()
    db.add_all(
        [
            GradeCompetenceLink(
                grade_specialization_id=gs_senior.id,
                competence_id=comp.id,
                skill_level_id=level.id,
            ),
            GradeCompetenceLink(
                grade_specialization_id=gs_senior.id,
                competence_id=missing_comp.id,
                skill_level_id=level.id,
            ),
        ]
    )
    position = Position(
        tenant_id=tenant.id,
        title=f"Backend Junior {suffix}",
        specialization_id=spec.id,
        grade_id=junior.id,
    )
    db.add(position)
    await db.flush()
    emp.position_id = position.id
    await db.commit()
    # the session identity map still holds emp with .position loaded as None
    await db.refresh(emp, ["position"])

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    growth = payload["growth"]
    assert growth is not None
    assert growth["next_grade"]["title"] == f"Senior {suffix}"
    # comp is at 80 ≥ 75 → covered; the second link has no result → missing
    missing_ids = {m["competence_id"] for m in growth["missing"]}
    assert missing_ids == {str(missing_comp.id)}


@pytest.mark.asyncio
async def test_my_loop_no_position_hides_growth(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=80)

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    assert payload["growth"] is None


@pytest.mark.asyncio
async def test_my_loop_ai_summary_cached_per_employee_state(
    db: AsyncSession, tenant, fake_redis, monkeypatch, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=80)
    calls = []

    async def _fake_generate(db_, tenant_id, payload):
        calls.append(payload["data_version"])
        return "coach text"

    monkeypatch.setattr(analytics_service, "generate_my_loop_summary", _fake_generate)

    first = await analytics_service.my_loop_ai_summary(db, tenant.id, emp.user_id)
    second = await analytics_service.my_loop_ai_summary(db, tenant.id, emp.user_id)

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["summary"] == "coach text"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reclosure_not_recounted_on_next_assessment(
    db: AsyncSession, tenant, status_done, type_self
):
    """A gap closed by an older re-assessment must not be re-counted by
    every subsequent assessment (review finding: monotonic Closed tile)."""
    emp = await _make_employee(db, tenant)
    comp = await _make_competence(db, tenant)
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=60,
        finished_days_ago=300,
        competence=comp,
    )
    # the closure happened here — outside the 90-day window
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=85,
        finished_days_ago=100,
        competence=comp,
    )
    # fresh assessment keeps the competence above the bar
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=90,
        finished_days_ago=3,
        competence=comp,
    )

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["stages"]["closed"]["gaps_closed"] == 0

    personal = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    assert personal["stages"]["closed"]["gaps_closed"] == 0


@pytest.mark.asyncio
async def test_my_loop_survey_pending_sees_sent_assessment(
    db: AsyncSession, tenant, type_self
):
    emp = await _make_employee(db, tenant)
    result = await db.execute(
        select(AssessmentStatus).where(AssessmentStatus.code == "sent")
    )
    sent = result.scalar_one_or_none()
    if not sent:
        sent = AssessmentStatus(code="sent", title="Sent", sequence=2)
        db.add(sent)
        await db.flush()
    a = Assessment(
        tenant_id=tenant.id,
        title=f"Survey {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        type_id=type_self.id,
        status_id=sent.id,
        initiator_id=emp.user_id,
    )
    db.add(a)
    await db.flush()
    db.add(
        AssessmentParticipant(
            assessment_id=a.id, user_id=emp.user_id, role="self", is_completed=False
        )
    )
    await db.commit()

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    findings = {f["code"]: f for f in payload["findings"]}
    assert findings["survey_pending"]["count"] == 1


class _CountingRedis(_FakeRedis):
    """Pipeline fake: returns one result per queued command, like redis."""

    def __init__(self, store):
        super().__init__(store)
        self._queued: list = []

    def pipeline(self, transaction=True):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def incr(self, key):
        self._store[key] = self._store.get(key, 0) + 1
        self._queued.append(self._store[key])

    def expire(self, key, ttl):
        self._queued.append(True)

    async def execute(self):
        out, self._queued = self._queued, []
        return out


@pytest.mark.asyncio
async def test_ai_summary_daily_budget_blocks_generation(
    db: AsyncSession, tenant, monkeypatch
):
    import app.core.redis as redis_helper

    store: dict = {}
    monkeypatch.setattr(
        redis_helper.aioredis, "from_url", lambda *a, **kw: _CountingRedis(store)
    )
    # cap = BASE + PER_EMPLOYEE × active; pin it to exactly 1 so the
    # employee created below (to change the fingerprint) can't raise it
    monkeypatch.setattr(analytics_service, "_AI_SUMMARY_DAILY_BASE", 1)
    monkeypatch.setattr(analytics_service, "_AI_SUMMARY_DAILY_PER_EMPLOYEE", 0)

    async def _fake_generate(db_, tenant_id, payload):
        return "text"

    monkeypatch.setattr(analytics_service, "generate_dev_loop_summary", _fake_generate)

    first = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )
    assert first["cached"] is False

    # cached repeat is free and unlimited
    second = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )
    assert second["cached"] is True

    # a new data state past the cap is refused
    await _make_employee(db, tenant)
    with pytest.raises(AppError) as exc:
        await analytics_service.dev_loop_ai_summary(
            db, tenant.id, _CALLER, visible_employee_ids=None
        )
    assert exc.value.status_code == 429
    assert exc.value.code == "ai_summary_rate_limited"


@pytest.mark.asyncio
async def test_ai_summary_per_user_budget_partition(
    db: AsyncSession, tenant, monkeypatch
):
    """One caller exhausting their slice must not block another caller."""
    import app.core.redis as redis_helper

    store: dict = {}
    monkeypatch.setattr(
        redis_helper.aioredis, "from_url", lambda *a, **kw: _CountingRedis(store)
    )
    monkeypatch.setattr(analytics_service, "_AI_SUMMARY_DAILY_PER_USER", 1)

    async def _fake_generate(db_, tenant_id, payload):
        return "text"

    monkeypatch.setattr(analytics_service, "generate_dev_loop_summary", _fake_generate)

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    first = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, user_a, visible_employee_ids=None
    )
    assert first["cached"] is False

    await _make_employee(db, tenant)  # new data state → cache miss
    with pytest.raises(AppError) as exc:
        await analytics_service.dev_loop_ai_summary(
            db, tenant.id, user_a, visible_employee_ids=None
        )
    assert exc.value.status_code == 429

    result = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, user_b, visible_employee_ids=None
    )
    assert result["cached"] is False


@pytest.mark.asyncio
async def test_ai_summary_client_fingerprint_skips_aggregation(
    db: AsyncSession, tenant, fake_redis, monkeypatch
):
    async def _fake_generate(db_, tenant_id, payload):
        return "text"

    monkeypatch.setattr(analytics_service, "generate_dev_loop_summary", _fake_generate)
    first = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, visible_employee_ids=None
    )

    async def _boom(db_, tenant_id, visible_employee_ids):
        raise AssertionError("cache hit on the client fingerprint must skip dev_loop")

    monkeypatch.setattr(analytics_service, "dev_loop", _boom)
    res = await analytics_service.dev_loop_ai_summary(
        db,
        tenant.id,
        _CALLER,
        visible_employee_ids=None,
        client_fingerprint=first["data_version"],
    )
    assert res["cached"] is True
    assert res["summary"] == "text"
    assert res["data_version"] == first["data_version"]


# ---------------------------------------------------------------------------
# Read scope (HRP-638)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_counts_only_the_visible_employees(
    db: AsyncSession, tenant, status_done, type_self
):
    """A manager's tiles must count their own people, not the whole tenant.

    Before HRP-638 the loop filtered by tenant alone, so a division manager
    saw company-wide numbers — and finding names from divisions they cannot
    open — while /employees honoured their scope.
    """
    mine = await _make_employee(db, tenant, last_name="Mine")
    theirs = await _make_employee(db, tenant, last_name="Theirs")
    for emp in (mine, theirs):
        await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=50)

    payload = await analytics_service.dev_loop(db, tenant.id, {mine.id})

    assert payload["stages"]["assessed"]["total_active"] == 1
    assert payload["stages"]["gaps"]["employees"] == 1
    finding = _finding(payload, "gaps_without_plan")
    assert [e["name"] for e in finding["employees"]] == ["Jane Mine"]


@pytest.mark.asyncio
async def test_empty_scope_reports_an_empty_loop(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=50)

    payload = await analytics_service.dev_loop(db, tenant.id, set())

    assert payload["stages"]["assessed"]["total_active"] == 0
    assert payload["findings"] == []


@pytest.mark.asyncio
async def test_coverage_finding_names_the_unassessed(db: AsyncSession, tenant):
    """The finding links to a filtered list, so it carries the names too."""
    await _make_employee(db, tenant, last_name="Unseen")

    payload = await analytics_service.dev_loop(db, tenant.id, None)

    finding = _finding(payload, "assessment_coverage")
    assert finding["count"] == 1
    assert [e["name"] for e in finding["employees"]] == ["Jane Unseen"]
    assert finding["href"] == "/employees?issue=assessment_stale"


# ---------------------------------------------------------------------------
# HRP-724: development dynamics over a period
# ---------------------------------------------------------------------------


async def _role_user(db: AsyncSession, tenant: Tenant, code: str) -> User:
    """A user holding ``code``, with the roles relationship loaded."""
    from app.modules.auth.models import Role, user_roles
    from sqlalchemy.orm import selectinload

    role = (await db.execute(select(Role).where(Role.code == code))).scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    u = User(
        email=f"dyn-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="Dyn",
        last_name=code.title(),
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(u)
    await db.commit()
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    return (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == u.id)
        )
    ).scalar_one()


def _headers(u: User) -> dict[str, str]:
    from app.core.security import create_access_token

    return {
        "Authorization": f"Bearer {create_access_token(str(u.id), str(u.tenant_id))}"
    }


@pytest.mark.asyncio
async def test_dynamics_counts_plans_finished_inside_the_window(
    db: AsyncSession, tenant
):
    emp = await _make_employee(db, tenant, last_name="Finisher")
    now = datetime.now(UTC)
    db.add(_pdp(tenant, emp, status="done", finished_at=now - timedelta(days=10)))
    db.add(_pdp(tenant, emp, status="done", finished_at=now - timedelta(days=200)))
    # Still running: finishing is what the number counts.
    db.add(_pdp(tenant, emp, status="in_progress"))
    await db.commit()

    month = await analytics_service.dev_loop(db, tenant.id, None, days=30)
    year = await analytics_service.dev_loop(db, tenant.id, None, days=365)

    assert month["dynamics"] == {
        "days": 30,
        "plans_completed": 1,
        "competences_improved": 0,
    }
    assert year["dynamics"]["plans_completed"] == 2


@pytest.mark.asyncio
async def test_dynamics_defaults_to_a_quarter(db: AsyncSession, tenant):
    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert payload["dynamics"]["days"] == 90


@pytest.mark.asyncio
async def test_dynamics_counts_a_strict_rise_against_the_earlier_result(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant, last_name="Riser")
    comp = await _make_competence(db, tenant)
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=40,
        finished_days_ago=200,
        competence=comp,
    )
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=55,
        finished_days_ago=5,
        competence=comp,
    )

    payload = await analytics_service.dev_loop(db, tenant.id, None, days=90)

    # Still under the bar, so no gap was closed -- but it moved, and moving
    # is what this block reports.
    assert payload["dynamics"]["competences_improved"] == 1
    assert payload["stages"]["closed"]["gaps_closed"] == 0


@pytest.mark.asyncio
async def test_dynamics_ignores_a_score_that_held_or_fell(
    db: AsyncSession, tenant, status_done, type_self
):
    for last_name, later in (("Flat", 40), ("Fallen", 30)):
        emp = await _make_employee(db, tenant, last_name=last_name)
        comp = await _make_competence(db, tenant)
        await _make_done_assessment(
            db,
            tenant,
            emp,
            status_done,
            type_self,
            percent=40,
            finished_days_ago=200,
            competence=comp,
        )
        await _make_done_assessment(
            db,
            tenant,
            emp,
            status_done,
            type_self,
            percent=later,
            finished_days_ago=5,
            competence=comp,
        )

    payload = await analytics_service.dev_loop(db, tenant.id, None, days=90)

    assert payload["dynamics"]["competences_improved"] == 0


@pytest.mark.asyncio
async def test_dynamics_ignores_a_competence_measured_for_the_first_time(
    db: AsyncSession, tenant, status_done, type_self
):
    """No baseline, no gain -- a first reading is not an improvement."""
    emp = await _make_employee(db, tenant, last_name="Newcomer")
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self, percent=90, finished_days_ago=5
    )

    payload = await analytics_service.dev_loop(db, tenant.id, None, days=90)

    assert payload["dynamics"]["competences_improved"] == 0


@pytest.mark.asyncio
async def test_dynamics_is_outside_the_ai_summary_fingerprint(
    db: AsyncSession, tenant, status_done, type_self
):
    """Flipping the period must not mint a new cache key for the same state."""
    emp = await _make_employee(db, tenant, last_name="Steady")
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=60)

    month = await analytics_service.dev_loop(db, tenant.id, None, days=30)
    quarter = await analytics_service.dev_loop(db, tenant.id, None, days=90)

    assert month["data_version"] == quarter["data_version"]


@pytest.mark.asyncio
async def test_my_loop_dynamics_counts_my_own_plans_and_rises(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant, last_name="Mine")
    other = await _make_employee(db, tenant, last_name="Theirs")
    comp = await _make_competence(db, tenant)
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=50,
        finished_days_ago=200,
        competence=comp,
    )
    await _make_done_assessment(
        db,
        tenant,
        emp,
        status_done,
        type_self,
        percent=80,
        finished_days_ago=5,
        competence=comp,
    )
    now = datetime.now(UTC)
    db.add(_pdp(tenant, emp, status="done", finished_at=now - timedelta(days=10)))
    db.add(_pdp(tenant, other, status="done", finished_at=now - timedelta(days=10)))
    await db.commit()

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id, days=90)

    assert payload["dynamics"] == {
        "days": 90,
        "plans_completed": 1,
        "competences_improved": 1,
    }


@pytest.mark.asyncio
async def test_my_loop_reads_another_employee_when_asked(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant, last_name="Subject")
    viewer = await _make_employee(db, tenant, last_name="Viewer")
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=60)

    payload = await analytics_service.my_loop(
        db, tenant.id, viewer.user_id, employee_id=emp.id
    )

    assert payload["employee_id"] == str(emp.id)


@pytest.mark.asyncio
async def test_my_loop_route_rejects_an_employee_outside_the_read_scope(
    db: AsyncSession, tenant, client
):
    """Own loop always; somebody else's only inside the caller's scope."""
    admin = await _role_user(db, tenant, "admin")
    plain = await _role_user(db, tenant, "employee")
    subject = await _make_employee(db, tenant, last_name="Subject")
    mine = Employee(
        user_id=plain.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 15),
        status="active",
    )
    db.add(mine)
    await db.commit()
    await db.refresh(mine)

    denied = await client.get(
        f"/api/analytics/my-loop?employee_id={subject.id}", headers=_headers(plain)
    )
    assert denied.status_code == 403

    own = await client.get(
        f"/api/analytics/my-loop?employee_id={mine.id}", headers=_headers(plain)
    )
    assert own.status_code == 200
    assert own.json()["employee_id"] == str(mine.id)

    allowed = await client.get(
        f"/api/analytics/my-loop?employee_id={subject.id}", headers=_headers(admin)
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_my_loop_manager_reads_only_their_own_subtree(
    db: AsyncSession, tenant, client
):
    """A manager is neither admin nor a stranger: the subtree is the line."""
    from app.modules.company.models import Division

    manager = await _role_user(db, tenant, "manager")
    managed = Division(tenant_id=tenant.id, name=f"Managed {uuid.uuid4().hex[:6]}")
    elsewhere = Division(tenant_id=tenant.id, name=f"Other {uuid.uuid4().hex[:6]}")
    db.add_all([managed, elsewhere])
    await db.commit()

    boss = Employee(
        user_id=manager.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 15),
        status="active",
        division_id=managed.id,
    )
    db.add(boss)
    await db.commit()
    await db.refresh(boss)
    managed.manager_id = boss.id
    await db.commit()

    mine = await _make_employee(db, tenant, last_name="Mine")
    theirs = await _make_employee(db, tenant, last_name="Theirs")
    mine.division_id = managed.id
    theirs.division_id = elsewhere.id
    await db.commit()

    inside = await client.get(
        f"/api/analytics/my-loop?employee_id={mine.id}", headers=_headers(manager)
    )
    assert inside.status_code == 200, inside.text[:200]
    assert inside.json()["employee_id"] == str(mine.id)

    outside = await client.get(
        f"/api/analytics/my-loop?employee_id={theirs.id}", headers=_headers(manager)
    )
    assert outside.status_code == 403, outside.text[:200]


@pytest.mark.asyncio
async def test_loop_routes_accept_every_listed_period(
    db: AsyncSession, tenant, client
):
    """Asked-for periods must actually arrive.

    A query parameter reaches the route as a string, so the first version of
    this typed the periods as a literal of ints and answered 422 to every
    ``?days=`` a caller wrote -- while the default, never parsed, worked. The
    422 half of the contract passed on its own; only asserting the 200 half
    catches it.
    """
    admin = await _role_user(db, tenant, "admin")
    # my-loop is somebody's own loop: without an employee row it is a 404,
    # which would hide the very status code this test is about.
    db.add(
        Employee(
            user_id=admin.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 15),
            status="active",
        )
    )
    await db.commit()
    for days in (30, 90, 365):
        for route in ("dev-loop", "my-loop"):
            r = await client.get(
                f"/api/analytics/{route}?days={days}", headers=_headers(admin)
            )
            assert r.status_code == 200, (route, days, r.text[:200])
            assert r.json()["dynamics"]["days"] == days


@pytest.mark.asyncio
async def test_loop_routes_reject_an_unlisted_period(db: AsyncSession, tenant, client):
    admin = await _role_user(db, tenant, "admin")
    for url in ("/api/analytics/dev-loop?days=45", "/api/analytics/my-loop?days=45"):
        assert (await client.get(url, headers=_headers(admin))).status_code == 422


# ---------------------------------------------------------------------------
# HRP-764 — what the AI summary is allowed to be handed
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_prompt(monkeypatch):
    """Record the prompt the dev-loop summary sends to the model."""
    import app.modules.ai.llm_client as llm_client

    seen: dict[str, str] = {}

    async def _fake_generate(prompt, *args, **kwargs):
        seen["prompt"] = prompt
        seen["system"] = kwargs.get("system", "")
        return "summary"

    monkeypatch.setattr(llm_client, "generate", _fake_generate)
    return seen


@pytest.mark.asyncio
async def test_prompt_payload_carries_no_issue_codes(
    db: AsyncSession, tenant, status_done, type_self, captured_prompt
):
    """No key from the issue registry may reach the model.

    The reported symptom was the summary printing ``gaps_without_plan``
    and ``assessment_coverage`` mid-sentence -- it could hardly do
    otherwise, having been handed those strings and nothing else to call
    the findings. Every seeded finding fires here so the assertion covers
    the registry, not one row of it.
    """
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self, percent=40
    )
    stale = await _make_employee(db, tenant, last_name="Stale")
    await _make_done_assessment(
        db, tenant, stale, status_done, type_self, finished_days_ago=300
    )
    overdue = await _make_employee(db, tenant, last_name="Overdue")
    db.add(
        _pdp(
            tenant,
            overdue,
            status="in_progress",
            deadline=datetime.now(UTC) - timedelta(days=5),
        )
    )
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    assert {f["code"] for f in payload["findings"]} >= {
        "gaps_without_plan",
        "pdp_overdue",
        "assessment_coverage",
    }

    await analytics_service.generate_dev_loop_summary(db, tenant.id, payload)
    prompt = captured_prompt["prompt"]
    leaked = [code for code in issues.ISSUE_CODES if code in prompt]
    # ``assessment_coverage`` is the dev-loop's own name for the stale
    # cohort and is not in ISSUE_CODES; the payload must not carry it either.
    leaked += [code for code in ("assessment_coverage",) if code in prompt]
    assert not leaked, f"issue codes reached the prompt: {leaked}"
    assert "employees below the grade bar with no development plan" in prompt


@pytest.mark.asyncio
async def test_prompt_payload_names_the_tenant_grades(
    db: AsyncSession, tenant, captured_prompt
):
    """(a) of HRP-764: the ladder in the prompt is the tenant's, not the
    model's favourite one. A workspace that renamed its rungs must not read
    "Junior" back out of the summary."""
    db.add_all(
        [
            DictionaryItem(
                type="grade", title="Apprentice", tenant_id=tenant.id, sort_index=0
            ),
            DictionaryItem(
                type="grade", title="Craftsman", tenant_id=tenant.id, sort_index=1
            ),
            DictionaryItem(
                type="grade",
                title="Retired rung",
                tenant_id=tenant.id,
                sort_index=2,
                is_active=False,
            ),
        ]
    )
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    await analytics_service.generate_dev_loop_summary(db, tenant.id, payload)
    prompt = captured_prompt["prompt"]
    assert '"Apprentice"' in prompt and '"Craftsman"' in prompt
    assert "Retired rung" not in prompt


@pytest.mark.asyncio
async def test_origin_grade_reaches_the_prompt_in_the_content_language(
    db: AsyncSession, tenant, captured_prompt
):
    """An origin grade stores its English title plus a stable ``i18n_key``;
    the interface renders the catalog label. Handing the model the stored
    title is how "Junior" survived into a German summary (HRP-770)."""
    from app.modules.ai_settings import service as ai_settings_service

    stored_title = f"Junior {uuid.uuid4().hex[:6]}"
    db.add(
        DictionaryItem(
            type="grade",
            title=stored_title,
            i18n_key="junior",
            tenant_id=tenant.id,
        )
    )
    await db.commit()
    settings_row = await ai_settings_service.get_or_default(db, tenant.id)
    settings_row.content_language = "de"
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    await analytics_service.generate_dev_loop_summary(db, tenant.id, payload)
    prompt = captured_prompt["prompt"]
    assert '"Junior"' in prompt
    assert stored_title not in prompt


# The codes ``my_loop`` can emit, harvested from the source rather than
# retyped: a code added to the personal loop tomorrow joins this guard on
# its own, which is the whole point — the leak was never about one code.
_MY_LOOP_CODE_RE = re.compile(r'"code": "([a-z_]+)"')


def _my_loop_finding_codes() -> list[str]:
    source = Path(analytics_service.__file__).read_text(encoding="utf-8")
    start = source.index("async def my_loop(")
    codes = sorted(set(_MY_LOOP_CODE_RE.findall(source[start:])))
    assert codes, "code literal scan found nothing — my_loop or the regex moved"
    return codes


@pytest.fixture
def captured_my_prompt(monkeypatch):
    """Record the prompt the personal summary sends to the model."""
    import app.modules.ai.llm_client as llm_client

    seen: dict[str, str] = {}

    async def _fake_generate(prompt, *args, **kwargs):
        seen["prompt"] = prompt
        return "summary"

    monkeypatch.setattr(llm_client, "generate", _fake_generate)
    return seen


@pytest.mark.asyncio
async def test_my_loop_prompt_carries_no_issue_codes(
    db: AsyncSession, tenant, status_done, type_self, captured_my_prompt
):
    """HRP-764, the personal half.

    The company summary was the reported one, but ``my_loop`` hands the
    model the same machine codes off the same registry — and this one
    speaks to the employee about themselves, so ``gap_without_plan``
    mid-sentence reads even worse. Every code the personal loop can emit
    is forced into the payload at once, so the assertion covers the
    registry rather than whichever finding this fixture happened to fire.
    """
    emp = await _make_employee(db, tenant, last_name="Personal")
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self, percent=40
    )

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    codes = _my_loop_finding_codes()
    payload["findings"] = [
        {"code": code, "severity": "alert", "count": 1, "href": f"/x?issue={code}"}
        for code in codes
    ]

    await analytics_service.generate_my_loop_summary(db, tenant.id, payload)
    prompt = captured_my_prompt["prompt"]
    leaked = [code for code in codes if code in prompt]
    assert not leaked, f"issue codes reached the personal prompt: {leaked}"
    # And the model was given something to call them instead.
    assert "no development plan" in prompt
