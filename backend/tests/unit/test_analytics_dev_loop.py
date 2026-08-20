"""Dev-loop analytics — stages, rule-based findings, AI-summary cache.

Covers the dashboard management engine (``analytics.service.dev_loop``):
one test per rule, plus the Redis fingerprint cache that keeps repeat
AI-summary requests over unchanged data free of LLM calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

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
    payload = await analytics_service.dev_loop(db, tenant.id)
    assert payload["stages"]["assessed"] == {
        "covered": 0,
        "total_active": 0,
        "percent": 0,
    }
    assert payload["stages"]["gaps"] == {"employees": 0, "competences": 0}
    assert payload["findings"] == []
    assert payload["data_version"]


@pytest.mark.asyncio
async def test_gap_below_bar_without_plan(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant, last_name="Gapman")
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=60)

    payload = await analytics_service.dev_loop(db, tenant.id)

    assert payload["stages"]["assessed"]["covered"] == 1
    assert payload["stages"]["gaps"] == {"employees": 1, "competences": 1}
    finding = _finding(payload, "gaps_without_plan")
    assert finding is not None
    assert finding["count"] == 1
    assert finding["severity"] == "alert"
    assert finding["employees"][0]["name"] == "Jane Gapman"


@pytest.mark.asyncio
async def test_result_at_the_bar_is_not_a_gap(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=75)

    payload = await analytics_service.dev_loop(db, tenant.id)
    assert payload["stages"]["gaps"] == {"employees": 0, "competences": 0}
    assert _finding(payload, "gaps_without_plan") is None


@pytest.mark.asyncio
async def test_gap_with_open_pdp_not_flagged(
    db: AsyncSession, tenant, status_done, type_self
):
    emp = await _make_employee(db, tenant)
    await _make_done_assessment(db, tenant, emp, status_done, type_self, percent=50)
    db.add(_pdp(tenant, emp, status="in_progress"))
    await db.commit()

    payload = await analytics_service.dev_loop(db, tenant.id)
    assert _finding(payload, "gaps_without_plan") is None
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

    payload = await analytics_service.dev_loop(db, tenant.id)
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

    payload = await analytics_service.dev_loop(db, tenant.id)
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

    payload = await analytics_service.dev_loop(db, tenant.id)
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

    payload = await analytics_service.dev_loop(db, tenant.id)
    assert payload["stages"]["closed"]["gaps_closed_90d"] == 1
    # the fresh result sits above the bar — no current gap either
    assert payload["stages"]["gaps"] == {"employees": 0, "competences": 0}


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

    payload = await analytics_service.dev_loop(db, tenant.id)
    assert payload["stages"]["closed"]["gaps_closed_90d"] == 0


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

    payload = await analytics_service.dev_loop(db, tenant.id)
    assert payload["stages"]["closed"]["plans_done_on_time_90d"] == 1


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

    first = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)
    second = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)

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

    first = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)
    await _make_employee(db, tenant)  # loop state changes → new fingerprint
    second = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)

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

    result = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)
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
        in_progress = AssessmentStatus(code="in_progress", title="In progress", sequence=3)
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
        db, tenant, emp, status_done, type_self,
        percent=60, finished_days_ago=80, competence=comp,
    )
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self,
        percent=85, finished_days_ago=3, competence=comp,
    )

    payload = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    assert payload["stages"]["closed"]["gaps_closed_90d"] == 1
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

    payload = await analytics_service.dev_loop(db, tenant.id)
    assert payload["stages"]["gaps"] == {"employees": 0, "competences": 0}
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
    spec = DictionaryItem(type="specialization", title=f"Backend {suffix}", tenant_id=tenant.id)
    junior = DictionaryItem(type="grade", title=f"Junior {suffix}", tenant_id=tenant.id)
    senior = DictionaryItem(type="grade", title=f"Senior {suffix}", tenant_id=tenant.id)
    db.add_all([spec, junior, senior])
    await db.flush()
    gs_junior = GradeSpecialization(
        tenant_id=tenant.id, grade_id=junior.id, specialization_id=spec.id,
        sort_index=0, salary_currency="EUR",
    )
    gs_senior = GradeSpecialization(
        tenant_id=tenant.id, grade_id=senior.id, specialization_id=spec.id,
        sort_index=1, salary_currency="EUR",
    )
    db.add_all([gs_junior, gs_senior])
    await db.flush()
    level = SkillLevel(title=f"Advanced {suffix}", tenant_id=tenant.id)
    missing_comp = await _make_competence(db, tenant)
    db.add(level)
    await db.flush()
    db.add_all([
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
    ])
    position = Position(
        tenant_id=tenant.id, title=f"Backend Junior {suffix}",
        specialization_id=spec.id, grade_id=junior.id,
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
        db, tenant, emp, status_done, type_self,
        percent=60, finished_days_ago=300, competence=comp,
    )
    # the closure happened here — outside the 90-day window
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self,
        percent=85, finished_days_ago=100, competence=comp,
    )
    # fresh assessment keeps the competence above the bar
    await _make_done_assessment(
        db, tenant, emp, status_done, type_self,
        percent=90, finished_days_ago=3, competence=comp,
    )

    payload = await analytics_service.dev_loop(db, tenant.id)
    assert payload["stages"]["closed"]["gaps_closed_90d"] == 0

    personal = await analytics_service.my_loop(db, tenant.id, emp.user_id)
    assert personal["stages"]["closed"]["gaps_closed_90d"] == 0


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

    first = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)
    assert first["cached"] is False

    # cached repeat is free and unlimited
    second = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)
    assert second["cached"] is True

    # a new data state past the cap is refused
    await _make_employee(db, tenant)
    with pytest.raises(AppError) as exc:
        await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)
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
    first = await analytics_service.dev_loop_ai_summary(db, tenant.id, user_a)
    assert first["cached"] is False

    await _make_employee(db, tenant)  # new data state → cache miss
    with pytest.raises(AppError) as exc:
        await analytics_service.dev_loop_ai_summary(db, tenant.id, user_a)
    assert exc.value.status_code == 429

    result = await analytics_service.dev_loop_ai_summary(db, tenant.id, user_b)
    assert result["cached"] is False


@pytest.mark.asyncio
async def test_ai_summary_client_fingerprint_skips_aggregation(
    db: AsyncSession, tenant, fake_redis, monkeypatch
):
    async def _fake_generate(db_, tenant_id, payload):
        return "text"

    monkeypatch.setattr(analytics_service, "generate_dev_loop_summary", _fake_generate)
    first = await analytics_service.dev_loop_ai_summary(db, tenant.id, _CALLER)

    async def _boom(db_, tenant_id):
        raise AssertionError("cache hit on the client fingerprint must skip dev_loop")

    monkeypatch.setattr(analytics_service, "dev_loop", _boom)
    res = await analytics_service.dev_loop_ai_summary(
        db, tenant.id, _CALLER, client_fingerprint=first["data_version"]
    )
    assert res["cached"] is True
    assert res["summary"] == "text"
    assert res["data_version"] == first["data_version"]
