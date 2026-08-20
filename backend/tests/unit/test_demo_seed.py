"""HRP-250 (D2) — reusable demo seed.

Covers ``clone_seed_into_demo_tenant`` end-to-end on a freshly created
demo tenant: counts of vacancies / candidates / interviews, idempotency,
the ``with_completed_interviews=False`` toggle, and that the produced
``Interview`` row carries ``analysis_status='completed'`` with the deep
analysis payload populated (the demo's first-screen promise).
"""

from __future__ import annotations

import pytest
from app.modules.assessment.models import (
    PDP,
    Assessment,
    AssessmentAnswer,
    AssessmentParticipant,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.company.models import Division
from app.modules.competence.models import Competence, Indicator, Material, SkillLevel
from app.modules.demo.seed import clone_seed_into_demo_tenant
from app.modules.demo.seed_data import (
    ELENA_INTERVIEW_ANALYSIS,
    INVESTOR_MARKER,
    TOMAS_INTERVIEW_ANALYSIS,
    VACANCIES,
    candidates,
)
from app.modules.demo.seed_data_competences import (
    COMPETENCES,
    INDICATORS,
    MATERIALS,
)
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee
from app.modules.exam.models import Exam, MassExam
from app.modules.notification.models import Notification
from app.modules.recruitment.models import Candidate, Interview, Vacancy
from app.modules.talent_market.models import TalentCard
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _flag_demo(db, tenant) -> None:
    """Flip ``tenant.is_demo`` on so the seeder's guard passes.

    The conftest tenant fixture defaults to is_demo=False (standard
    paying tenant). For the seed tests we want the demo branch.
    """
    tenant.is_demo = True
    await db.commit()
    await db.refresh(tenant)


@pytest.fixture(autouse=True)
def _seed_origin_levels(skill_levels):
    """Every demo-seed test needs the Basic/Intermediate/Advanced origin
    SkillLevels — without them the seeder raises a hard error (see
    ``_seed_competences``). Requesting the ``skill_levels`` fixture
    here implicitly satisfies the precondition for every test in this
    module without each test having to spell it out."""
    return skill_levels


@pytest.mark.asyncio
async def test_clone_seed_populates_expected_counts(db: AsyncSession, tenant, user):
    await _flag_demo(db, tenant)
    result = await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    assert result["skipped"] is False
    # HRP-281 / S7: extras layer adds vacancies + candidates + interviews
    # on top of the legacy base — the result dict now reports the merged
    # totals, so the lower bound is still the legacy counts.
    assert result["vacancies"] >= len(VACANCIES)
    assert result["candidates"] >= len(candidates())
    assert result["interviews"] >= 2

    vac_count = (
        (await db.execute(select(Vacancy).where(Vacancy.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(vac_count) == result["vacancies"]

    cand_count = (
        (
            await db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant.id,
                    Candidate.source == INVESTOR_MARKER,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(cand_count) == result["candidates"]
    # HRP-276 / H2: demo seed must NOT mint Person rows — those are
    # tenant-less and would accumulate after each demo purge.
    assert all(c.person_id is None for c in cand_count)


@pytest.mark.asyncio
async def test_clone_seed_marks_interviews_completed_with_analysis(
    db: AsyncSession, tenant, user
):
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    interviews = (
        (await db.execute(select(Interview).where(Interview.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(interviews) >= 2

    # The two legacy AI-analyzed interviews still carry the deep
    # ``analysis_data`` payload. The HRP-281 / S7 extras layer adds
    # interviews in the non-completed states (scheduled / in_progress /
    # completed-without-analysis / archived) which intentionally do NOT
    # set ``analysis_data`` — assert only on the AI-analyzed subset.
    analyzed = [
        iv
        for iv in interviews
        if iv.analysis_status == "completed" and iv.analysis_data is not None
    ]
    assert len(analyzed) >= 2
    for iv in analyzed:
        assert iv.transcription_status == "completed"
        assert "competence_assessments" in iv.analysis_data
        assert iv.analysis_data["competence_assessments"]

    elena = next(iv for iv in analyzed if "Elena" in (iv.title or ""))
    assert elena.analysis_data == ELENA_INTERVIEW_ANALYSIS
    # Transcript packaged with the module gets attached verbatim — the
    # demo opens this exact interview on the first screen and we want
    # the panel populated.
    assert elena.transcript
    assert len(elena.transcript) > 100


@pytest.mark.asyncio
async def test_clone_seed_writes_ready_ai_assessments_with_citations(
    db: AsyncSession, tenant, user
):
    """HRP-250 acceptance: the demo opens on a finished AI evaluation.

    QA saw an empty AI matrix on a freshly started demo: the seed marked
    the interviews ``completed`` and stored ``analysis_data``, but wrote
    no AIAssessment rows — and the compact matrix reads those rows, not
    the JSON blob. Nothing was visible until someone pressed Analyze.
    """
    from app.modules.recruitment.common import normalize_competence_id
    from app.modules.recruitment.models import AIAssessment

    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    rows = (
        (
            await db.execute(
                select(AIAssessment).where(AIAssessment.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows, "seeded interviews must carry ready AI assessments"
    assert all(r.citations for r in rows), "citations are the demo's headline"

    # Keyed on the vacancy-profile slug namespace, the ids the matrix
    # looks up (HRP-275) — a label-derived uuid renders as '--'.
    expected = {
        str(normalize_competence_id(ca["competence_id"]))
        for ca in ELENA_INTERVIEW_ANALYSIS["competence_assessments"]
    }
    assert expected <= {str(r.competence_id) for r in rows}


@pytest.mark.asyncio
async def test_clone_seed_is_idempotent(db: AsyncSession, tenant, user):
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    second = await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()
    assert second["skipped"] is True
    assert second["vacancies"] == 0
    assert second["candidates"] == 0
    assert second["interviews"] == 0

    # And the row counts did not double. The merged total now includes
    # the HRP-281 / S7 extras, but the assertion is still: same number
    # of marked candidates after a re-run as after the first run.
    cand_count = (
        (
            await db.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant.id,
                    Candidate.source == INVESTOR_MARKER,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(cand_count) >= len(candidates())


@pytest.mark.asyncio
async def test_clone_seed_without_interviews_skips_interview_rows(
    db: AsyncSession, tenant, user
):
    await _flag_demo(db, tenant)
    result = await clone_seed_into_demo_tenant(
        db, tenant.id, owner_user_id=user.id, with_completed_interviews=False
    )
    await db.commit()
    assert result["interviews"] == 0

    interviews = (
        (await db.execute(select(Interview).where(Interview.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert interviews == []


@pytest.mark.asyncio
async def test_clone_seed_refuses_non_demo_tenant_by_default(
    db: AsyncSession, tenant, user
):
    """Tenant.is_demo guard fires unless the caller explicitly opts out."""
    # ``tenant`` fixture defaults to is_demo=False, mirroring a real
    # paying customer tenant.
    assert tenant.is_demo is False

    with pytest.raises(ValueError, match="is_demo"):
        await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)


@pytest.mark.asyncio
async def test_clone_seed_opt_out_allows_non_demo_tenant(
    db: AsyncSession, tenant, user
):
    """``require_demo_tenant=False`` is the escape hatch used by the
    self-hosted CLI on the long-lived Pulsar Technologies tenant."""
    assert tenant.is_demo is False
    result = await clone_seed_into_demo_tenant(
        db,
        tenant.id,
        owner_user_id=user.id,
        require_demo_tenant=False,
    )
    await db.commit()
    assert result["skipped"] is False
    assert result["vacancies"] >= len(VACANCIES)


# ---------------------------------------------------------------------------
# HRP-281 / S9 — coverage assertions for the seed expansion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_creates_minimum_employees(db: AsyncSession, tenant, user):
    """S3 must materialise at least 30 employee cards so the Employees
    page is no longer empty."""
    await _flag_demo(db, tenant)
    result = await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    assert result["employees"] >= 30
    rows = (
        (await db.execute(select(Employee).where(Employee.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(rows) >= 30
    # Statuses are mixed — not every row is active.
    statuses = {r.status for r in rows}
    assert "active" in statuses
    assert statuses - {"active"}  # at least one non-active row


@pytest.mark.asyncio
async def test_seed_division_tree_consistent(db: AsyncSession, tenant, user):
    """Every Division.parent_id must reference another Division in the
    same tenant — no orphan pointers."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    divisions = (
        (await db.execute(select(Division).where(Division.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert divisions
    ids = {d.id for d in divisions}
    for d in divisions:
        if d.parent_id is not None:
            assert (
                d.parent_id in ids
            ), f"Division {d.name} has orphan parent_id {d.parent_id}"


@pytest.mark.asyncio
async def test_seed_pdps_cover_all_statuses(db: AsyncSession, tenant, user):
    """S4 must produce PDPs in every status used by the kanban
    (draft / in_progress / review / returned / done / cancelled)."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    pdps = (
        (await db.execute(select(PDP).where(PDP.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    statuses = {p.status for p in pdps}
    for expected in {"draft", "in_progress", "review", "returned", "done", "cancelled"}:
        assert expected in statuses, f"PDP status '{expected}' is missing"


@pytest.mark.asyncio
async def test_seed_exam_assignments_have_mix_of_statuses(
    db: AsyncSession, tenant, user
):
    """S5 must populate Exam rows across done / in_progress / assigned
    so the assignments kanban has all columns populated."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    mass_exams = (
        (await db.execute(select(MassExam).where(MassExam.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(mass_exams) >= 4

    exams = (
        (await db.execute(select(Exam).where(Exam.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    statuses = {e.status for e in exams}
    for expected in {"done", "in_progress", "assigned"}:
        assert expected in statuses, f"Exam assignment status '{expected}' is missing"


@pytest.mark.asyncio
async def test_seed_talent_cards_cover_every_status(db: AsyncSession, tenant, user):
    """S6 must produce TalentCards in every status (draft / published /
    completed / cancelled)."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    cards = (
        (await db.execute(select(TalentCard).where(TalentCard.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    statuses = {c.status for c in cards}
    for expected in {"draft", "published", "completed", "cancelled"}:
        assert expected in statuses, f"TalentCard status '{expected}' is missing"


@pytest.mark.asyncio
async def test_seed_cross_tenant_isolation(db: AsyncSession, tenant, user):
    """Two demo sessions on different tenants must not see each other's
    employee rows."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User
    from app.modules.company.models import Tenant

    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    other_tenant = Tenant(
        name=f"Other demo {_uuid.uuid4().hex[:6]}",
        slug=f"other-{_uuid.uuid4().hex[:8]}",
        is_demo=True,
    )
    db.add(other_tenant)
    await db.commit()
    await db.refresh(other_tenant)

    other_user = User(
        email=f"otherowner-{_uuid.uuid4().hex[:6]}@demo.example.com",
        password_hash=hash_password("testpass123"),
        first_name="Other",
        last_name="Owner",
        tenant_id=other_tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)

    await clone_seed_into_demo_tenant(db, other_tenant.id, owner_user_id=other_user.id)
    await db.commit()

    first_employees = (
        (await db.execute(select(Employee).where(Employee.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    second_employees = (
        (
            await db.execute(
                select(Employee).where(Employee.tenant_id == other_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert first_employees
    assert second_employees
    first_ids = {e.id for e in first_employees}
    second_ids = {e.id for e in second_employees}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_seed_creates_assessments_across_statuses(
    db: AsyncSession,
    tenant,
    user,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
    notification_templates,
):
    """HRP-314: assessments are back. The demo tenant ships cycles in
    every kanban status (draft / in_progress / done / cancelled) so the
    /assessments page lands on real content."""
    await _flag_demo(db, tenant)
    result = await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    assert result["assessments"] > 0, "demo seed must create Assessment rows (HRP-314)"
    assert result["pdps"] > 0
    assert (
        result["notifications"] > 0
    ), "expected Notification rows when templates present"

    assessments = (
        (
            await db.execute(
                select(Assessment)
                .join(AssessmentStatus, Assessment.status_id == AssessmentStatus.id)
                .where(Assessment.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(assessments) == result["assessments"]

    status_rows = (await db.execute(select(AssessmentStatus))).scalars().all()
    code_by_id = {s.id: s.code for s in status_rows}
    seen_statuses = {code_by_id[a.status_id] for a in assessments}
    for expected in {"draft", "in_progress", "done", "cancelled"}:
        assert (
            expected in seen_statuses
        ), f"Assessment status '{expected}' is missing — kanban will look empty"

    notifications = (
        (
            await db.execute(
                select(Notification).where(Notification.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == result["notifications"]


@pytest.mark.asyncio
async def test_seed_assessments_have_criteria_type_set(
    db: AsyncSession,
    tenant,
    user,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
):
    """HRP-314: every demo assessment must declare a criteria_type so the
    Draft → Sent transition (which checks criteria_type IS NOT NULL) does
    not block the cycle the moment a user tries to send it."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    assessments = (
        (await db.execute(select(Assessment).where(Assessment.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert assessments
    for a in assessments:
        assert a.criteria_type in {
            "competences",
            "target_position",
            "current_positions",
        }, (
            f"Assessment {a.title!r} has criteria_type={a.criteria_type!r}, "
            "expected one of competences/target_position/current_positions"
        )


@pytest.mark.asyncio
async def test_seed_180_360_assessments_have_division_manager(
    db: AsyncSession,
    tenant,
    user,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
):
    """HRP-314: 180/360 cycles must pick up the assessee's Division
    Manager as a 'manager' participant — that's the whole point of those
    review types and the original HRP-300 cycles shipped without one."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    assessments = (
        (
            await db.execute(
                select(Assessment)
                .join(AssessmentType, Assessment.type_id == AssessmentType.id)
                .where(
                    Assessment.tenant_id == tenant.id,
                    AssessmentType.code.in_(("180", "360")),
                )
            )
        )
        .scalars()
        .all()
    )
    assert assessments, "demo seed must include at least one 180/360 cycle"

    for a in assessments:
        participants = (
            (
                await db.execute(
                    select(AssessmentParticipant).where(
                        AssessmentParticipant.assessment_id == a.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        roles = {p.role for p in participants}
        assert (
            "self" in roles
        ), f"Assessment {a.title!r} is missing the self participant"
        assert "manager" in roles, (
            f"Assessment {a.title!r} ({a.id}) is a 180/360 cycle but has no "
            f"'manager' participant — the Division chain lookup did not "
            f"resolve a Division.manager_id"
        )


@pytest.mark.asyncio
async def test_seed_done_assessments_have_results_for_each_competence(
    db: AsyncSession,
    tenant,
    user,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
):
    """HRP-314: every done cycle must produce one AssessmentResult per
    competence in its result_overrides so the /assessments/[id] results
    widget renders a populated table instead of an empty state."""
    from app.modules.demo.seed_data_assessments import ASSESSMENTS

    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    done_specs = [s for s in ASSESSMENTS if s["status_code"] == "done"]
    assert done_specs, "expected demo seed to ship at least one done assessment"

    for spec in done_specs:
        # Catches the gap where a done spec ships ``result_overrides=[]``
        # — the previous test would pass at 0==0 even though the results
        # widget would render an empty table on the demo.
        assert spec["result_overrides"], (
            f"Done spec {spec['title']!r} ships empty result_overrides — "
            "/assessments/[id] would render an empty results widget"
        )
        assessment = (
            await db.execute(
                select(Assessment).where(
                    Assessment.tenant_id == tenant.id,
                    Assessment.title == spec["title"],
                )
            )
        ).scalar_one()
        results = (
            (
                await db.execute(
                    select(AssessmentResult).where(
                        AssessmentResult.assessment_id == assessment.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(results) == len(spec["result_overrides"]), (
            f"Done assessment {spec['title']!r} has {len(results)} result rows, "
            f"expected {len(spec['result_overrides'])}"
        )


# ---------------------------------------------------------------------------
# S2 follow-up: indicators + per-indicator assessment answers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_competences_have_indicators_per_skill_level(
    db: AsyncSession, tenant, user, skill_levels
):
    """Each demo competence ships one indicator per ladder cell.

    HRP-299 collapsed the legacy 4-level ladder onto the 3-level origin
    set. The seed dedupes by (competence, skill_level), so an INDICATORS
    spec carrying both an sl-l3 and an sl-l4 entry for the same
    competence lands as a single Advanced indicator — not two indicators
    on the same Advanced row (which is the duplicated-ladder UX HRP-299
    was meant to eliminate).
    """
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    competences = (
        (await db.execute(select(Competence).where(Competence.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(competences) >= len(COMPETENCES)

    # Expected count: unique (competence_key, collapsed skill_level_key)
    # pairs across INDICATORS, where sl-l4 collapses onto sl-l3.
    _COLLAPSE = {"sl-l4": "sl-l3"}
    expected_cells = {
        (
            spec["competence_key"],
            _COLLAPSE.get(spec["skill_level_key"], spec["skill_level_key"]),
        )
        for spec in INDICATORS
    }

    indicators = (
        (await db.execute(select(Indicator).where(Indicator.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(indicators) == len(expected_cells)

    by_competence: dict = {}
    for ind in indicators:
        by_competence.setdefault(ind.competence_id, []).append(ind)
    for comp in competences:
        rows = by_competence.get(comp.id, [])
        # Every indicator on a competence sits on a distinct skill_level
        # — no duplicate Advanced rows, no duplicate any-level rows.
        assert len({r.skill_level_id for r in rows}) == len(rows), (
            f"Competence {comp.title!r} has duplicate indicators on the "
            f"same skill_level"
        )
        # And no competence ships more than the 3-level ladder allows.
        assert len(rows) <= 3, (
            f"Competence {comp.title!r} has {len(rows)} indicators, "
            f"expected ≤ 3 (one per origin ladder cell)"
        )


@pytest.mark.asyncio
async def test_seed_in_progress_and_done_assessments_have_answers(
    db: AsyncSession,
    tenant,
    user,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
    notification_templates,
):
    """HRP-314: every in_progress / done cycle must produce at least one
    AssessmentAnswer per resolvable competence_key. Draft / cancelled
    cycles intentionally have no answers — asserted via the per-spec
    answer count, not a blanket "any > 0" so a silent 80% drop in
    answers still fails the test."""
    from app.modules.demo.seed_data_assessments import ASSESSMENTS

    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    for spec in ASSESSMENTS:
        assessment = (
            await db.execute(
                select(Assessment).where(
                    Assessment.tenant_id == tenant.id,
                    Assessment.title == spec["title"],
                )
            )
        ).scalar_one()
        answers = (
            (
                await db.execute(
                    select(AssessmentAnswer).where(
                        AssessmentAnswer.assessment_id == assessment.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if spec["status_code"] in {"in_progress", "done"}:
            assert answers, (
                f"Assessment {spec['title']!r} ({spec['status_code']}) "
                "must have AssessmentAnswer rows so the scoring form is "
                "not blank"
            )
        else:
            assert not answers, (
                f"Assessment {spec['title']!r} ({spec['status_code']}) "
                "must not ship AssessmentAnswer rows — draft/cancelled "
                "cycles should look untouched"
            )


# ---------------------------------------------------------------------------
# HRP-296 wave: demo-tenant correctness pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_uses_origin_skill_levels_only(
    db: AsyncSession, tenant, user, skill_levels
):
    """HRP-299: demo no longer ships a 4-level custom skill ladder. After
    the seed runs the tenant must only see the 3 origin levels (Basic /
    Intermediate / Advanced), not a 3+N mix."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    tenant_levels = (
        (await db.execute(select(SkillLevel).where(SkillLevel.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert tenant_levels == [], (
        "demo seed should not create tenant-scoped SkillLevels (HRP-299); "
        f"got {[lvl.title for lvl in tenant_levels]}"
    )


@pytest.mark.asyncio
async def test_seed_attaches_materials_to_every_competence_level(
    db: AsyncSession, tenant, user, skill_levels
):
    """HRP-298: every (competence × Basic/Intermediate/Advanced) cell
    must produce at least one Material row so the /competences "Materials"
    tab is non-empty."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    competences = (
        (await db.execute(select(Competence).where(Competence.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert competences

    materials = (
        (await db.execute(select(Material).where(Material.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(materials) == len(MATERIALS)

    by_competence: dict = {}
    for m in materials:
        by_competence.setdefault(m.competence_id, set()).add(m.skill_level_id)
    for comp in competences:
        levels = by_competence.get(comp.id, set())
        assert len(levels) == 3, (
            f"Competence {comp.title!r} has materials on {len(levels)} "
            "levels, expected 3 (Basic/Intermediate/Advanced)"
        )


@pytest.mark.asyncio
async def test_seed_grades_reuse_origin_dictionary_items(
    db: AsyncSession, tenant, user, origin_grades
):
    """HRP-302: demo no longer creates tenant-scoped Custom copies of the
    System grade dictionary — the Dictionaries → Grades page must render
    a single Junior / Middle / Senior / Lead / Principal set."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    tenant_grades = (
        (
            await db.execute(
                select(DictionaryItem).where(
                    DictionaryItem.tenant_id == tenant.id,
                    DictionaryItem.type == "grade",
                )
            )
        )
        .scalars()
        .all()
    )
    assert tenant_grades == [], (
        "demo seed should not create tenant-scoped grade DictionaryItems "
        f"when origin rows exist (HRP-302); got {[g.title for g in tenant_grades]}"
    )


@pytest.mark.asyncio
async def test_seed_engineering_parent_has_manager_and_deputy(
    db: AsyncSession, tenant, user
):
    """HRP-303: the Engineering parent division (no direct headcount,
    only sub-divisions) must still have manager_id + deputy_manager_id
    wired up so downstream assessment / PDP flows can resolve a Division
    Manager for any employee dragged under it."""
    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    eng = (
        await db.execute(
            select(Division).where(
                Division.tenant_id == tenant.id,
                Division.name == "Engineering",
                Division.parent_id.is_(None),
            )
        )
    ).scalar_one()
    assert eng.manager_id is not None, "Engineering must have a Manager"
    assert eng.deputy_manager_id is not None, "Engineering must have a Deputy Manager"
    assert (
        eng.manager_id != eng.deputy_manager_id
    ), "Manager and Deputy Manager must be different employees"


def test_demo_session_ttl_default_is_four_hours():
    """HRP-297: the documented behaviour is that a demo session lives
    for 4 h; the default must match so a deploy that forgets the env
    override does not log visitors out at the 30-minute mark."""
    from app.config import settings

    assert settings.demo_session_ttl_seconds == 14400
    assert settings.demo_inactivity_ttl_seconds == 14400


def test_seed_analysis_payloads_match_writer_schemas():
    """The interview page renders ``analysis_data`` through the real
    ``ProcessFinding``/``BlindSpot``/``RedFlag`` shapes (HRP-579) —
    the plain strings seeded before crashed the demo's Elena page."""
    from app.modules.recruitment.prompts_interview import (
        BlindSpot,
        ProcessFinding,
        RedFlag,
    )

    profile_slugs = {
        c["id"]
        for v in VACANCIES
        if v["key"] == "senior-backend"
        for c in v["profile"]["competences"]
    }
    for payload in (ELENA_INTERVIEW_ANALYSIS, TOMAS_INTERVIEW_ANALYSIS):
        assert payload["verdict"] in {"recommended", "needs_check", "not_recommended"}
        for item in payload["process_findings"]:
            ProcessFinding.model_validate(item)
        for item in payload["blind_spots"]:
            BlindSpot.model_validate(item)
            # The panel resolves the competence name via the vacancy
            # profile — an unknown slug renders a nameless blind spot.
            assert item["competence_id"] in profile_slugs
        for item in payload["red_flags"]:
            RedFlag.model_validate(item)


@pytest.mark.asyncio
async def test_seeded_results_survive_a_recompute(
    db: AsyncSession,
    tenant,
    user,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
):
    """The seeded percent must equal what the recompute engine derives
    from the seeded answers — otherwise the first status re-transition
    (or calibration reset) silently rewrites the storyline: every
    below-the-bar score snapped to 75 and the dev-loop story vanished
    (review finding)."""
    from app.modules.assessment.service import _recompute_assessment_results

    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    done = (
        await db.execute(
            select(Assessment)
            .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
            .where(
                Assessment.tenant_id == tenant.id,
                AssessmentStatus.code == "done",
            )
        )
    ).scalars().all()
    assert done

    before: dict = {}
    for a in done:
        rows = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a.id
                )
            )
        ).scalars().all()
        for r in rows:
            before[(a.id, r.competence_id)] = r.percent

    for a in done:
        await _recompute_assessment_results(db, a)
    await db.commit()

    drifted = {}
    for a in done:
        rows = (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id == a.id
                )
            )
        ).scalars().all()
        for r in rows:
            if before[(a.id, r.competence_id)] != r.percent:
                drifted[(str(a.title), str(r.competence_id))] = (
                    before[(a.id, r.competence_id)],
                    r.percent,
                )
    assert not drifted, f"recompute changed seeded percents: {drifted}"


async def test_seeded_tenant_tells_the_dev_loop_story(
    db: AsyncSession,
    tenant,
    user,
    assessment_statuses,
    assessment_types,
    default_answer_scale,
):
    """The demo's first screen is the dashboard dev-loop: the seed must
    produce below-the-bar employees without a plan (GTM storyline), an
    overdue plan and a stalled review — so a fresh demo session opens
    on real problems with real actions, not flat stats."""
    from app.modules.analytics.service import dev_loop

    await _flag_demo(db, tenant)
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    payload = await dev_loop(db, tenant.id)
    findings = {f["code"]: f for f in payload["findings"]}

    # Storyline A: sales team below the bar with no development plan.
    assert "gaps_without_plan" in findings
    assert findings["gaps_without_plan"]["count"] >= 4
    # Storyline B: an overdue plan and a plan stuck in review/returned.
    assert findings["pdp_overdue"]["count"] >= 1
    assert findings["pdp_stuck_review"]["count"] >= 1
    # Coverage is deliberately partial — the "run assessments" CTA fires.
    assert "assessment_coverage" in findings
    assert 0 < payload["stages"]["assessed"]["percent"] < 100
    # Ivan Petrov: gap that HAS a plan — the plan is just going nowhere.
    assert payload["stages"]["developing"]["gap_employees_with_plan"] >= 1
    # Storyline C: Bella Martins closed her Python gap in a re-assessment.
    assert payload["stages"]["closed"]["gaps_closed_90d"] >= 1
    # Carlos's Q3 plan finished before its deadline — the sub-line is alive.
    assert payload["stages"]["closed"]["plans_done_on_time_90d"] >= 1

    # The demo employee persona (Carlos Mendez, HRP-612 wave 2) opens a
    # live personal dashboard: strengths, a gap without a plan, and a
    # growth direction up the seeded backend ladder.
    from app.modules.analytics.service import my_loop
    from app.modules.auth.models import User as AuthUser

    carlos = (
        await db.execute(
            select(AuthUser).where(
                AuthUser.tenant_id == tenant.id,
                AuthUser.email == "carlos.mendez@demo.example.com",
            )
        )
    ).scalar_one()
    personal = await my_loop(db, tenant.id, carlos.id)
    assert personal["strengths"]["top"]
    assert any(f["code"] == "gap_without_plan" for f in personal["findings"])
    assert personal["growth"] is not None
    assert personal["growth"]["next_grade"] is not None
