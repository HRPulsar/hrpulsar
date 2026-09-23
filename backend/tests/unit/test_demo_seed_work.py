"""HRP-746 / W6 — the demo seed's work containers and competence mapping.

Coverage was the one demo surface that opened on its cold-start screen.
What matters is not that rows exist but that the screen they produce says
something true about the seeded company: agents cover the coordination,
people cover the judgement, and the two unclosed steps are real gaps with
the right label. Anything less and the demo would have been better off
empty.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.modules.ai_workforce import service as agents_service
from app.modules.competence.models import Competence
from app.modules.demo.seed import clone_seed_into_demo_tenant
from app.modules.demo.seed_data_work import COMPETENCE_PRIMITIVES, WORK_CONTAINERS
from app.modules.primitives import catalog_data
from app.modules.primitives.catalog_data import PRIMITIVES
from app.modules.primitives.models import CompetenceMappingState, CompetencePrimitive
from app.modules.work import coverage as coverage_service
from app.modules.work.models import WorkContainer, WorkStep, WorkStepPrimitive
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_CATALOG_CODES = {p["code"] for p in PRIMITIVES}


@pytest.fixture(autouse=True)
def _seed_origin_levels(skill_levels):
    """Same precondition as every other demo-seed module: without the
    origin SkillLevels ``_seed_competences`` raises before we get here."""
    return skill_levels


@pytest.fixture(autouse=True)
async def _catalog(db: AsyncSession):
    """The primitive catalog and the built-in packs are migration-seeded
    platform reference data; the test schema is built from metadata, so
    they have to be laid down by hand. Without them the seeder skips the
    work fixtures whole, which is the branch this module must not hit."""
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    await agents_service.seed_packs(db)


@pytest.fixture(autouse=True)
def _no_mapping_enqueue():
    """Coverage enqueues a mapping run for anything unmapped. These
    fixtures map everything, but the guard keeps a stray competence from
    reaching for Redis in a unit test."""
    with patch.object(
        coverage_service, "_schedule_mapping", new=AsyncMock(return_value=False)
    ):
        yield


async def _seed(db: AsyncSession, tenant, user) -> dict:
    tenant.is_demo = True
    await db.commit()
    result = await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()
    return result


def test_fixture_codes_exist_in_the_catalog():
    """A typo in a code would be silently dropped by the seeder — the
    links are written ``if code in primitives``. Catch it here instead."""
    used = {code for codes in COMPETENCE_PRIMITIVES.values() for code in codes}
    for spec in WORK_CONTAINERS:
        for step in spec["steps"]:
            used |= set(step["primitives"])
    assert used <= _CATALOG_CODES, sorted(used - _CATALOG_CODES)


def test_every_step_is_estimated():
    """A step without both numbers falls out of the shares and the ROI
    panel (``coverage.step_hours``), which is the panel these fixtures
    exist to fill."""
    for spec in WORK_CONTAINERS:
        for step in spec["steps"]:
            assert step["hours_per_run"] > 0, step["title"]
            assert step["runs_per_year"] >= 1, step["title"]


@pytest.mark.asyncio
async def test_seed_creates_the_containers_and_the_mapping(
    db: AsyncSession, tenant, user
):
    result = await _seed(db, tenant, user)

    assert result["work_containers"] == len(WORK_CONTAINERS)
    assert result["mapped_competences"] > 0

    containers = (
        (
            await db.execute(
                select(WorkContainer).where(WorkContainer.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(containers) == len(WORK_CONTAINERS)
    # One initiative among the processes: the demo shows both container
    # types, and a project is where the ``agency`` label comes from.
    assert {c.type for c in containers} == {"process", "initiative"}
    # HRP-810: the demo personas find Coverage in the menu only because the
    # seeded breakdowns are open to the whole company.
    assert {c.visibility for c in containers} == {"company"}

    by_title = {c.title: c for c in containers}
    for spec in WORK_CONTAINERS:
        container = by_title[spec["title"]]
        steps = (
            (
                await db.execute(
                    select(WorkStep)
                    .where(WorkStep.container_id == container.id)
                    .order_by(WorkStep.position)
                )
            )
            .scalars()
            .all()
        )
        assert [s.title for s in steps] == [s["title"] for s in spec["steps"]]
        assert [s.position for s in steps] == list(range(1, len(spec["steps"]) + 1))
        expected_state = (
            "accepted" if spec["status"] == "active" else "system_suggested"
        )
        assert {s.state for s in steps} == {expected_state}

    # Every declared code made it to a link row.
    declared = sum(
        len(step["primitives"]) for spec in WORK_CONTAINERS for step in spec["steps"]
    )
    linked = (
        await db.execute(
            select(func.count())
            .select_from(WorkStepPrimitive)
            .where(WorkStepPrimitive.tenant_id == tenant.id)
        )
    ).scalar_one()
    assert linked == declared

    # The mapping is ``reviewed``, not ``ai_suggested``: coverage must not
    # schedule an LLM run the moment a demo visitor opens the page.
    states = (
        (
            await db.execute(
                select(CompetenceMappingState).where(
                    CompetenceMappingState.tenant_id == tenant.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert states
    assert {s.status for s in states} == {"reviewed"}


@pytest.mark.asyncio
async def test_the_seed_stores_the_summary_the_list_reads(
    db: AsyncSession, tenant, user
):
    """HRP-862: the list column reads ``coverage_summary``; a seeded
    process nobody has opened yet would otherwise show a dash where the
    demo means to show the figures."""
    await _seed(db, tenant, user)

    containers = (
        (
            await db.execute(
                select(WorkContainer).where(WorkContainer.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    for container in containers:
        summary = container.coverage_summary
        assert summary is not None, container.title
        assert summary["hours"]["total"] > 0, container.title


async def test_mapping_matches_the_fixture_per_competence(
    db: AsyncSession, tenant, user
):
    await _seed(db, tenant, user)

    rows = (
        await db.execute(
            select(Competence.title, CompetencePrimitive.primitive_id)
            .join(
                CompetencePrimitive,
                CompetencePrimitive.competence_id == Competence.id,
            )
            .where(CompetencePrimitive.tenant_id == tenant.id)
        )
    ).all()
    assert rows
    # Count rather than codes: the fixture is keyed by competence slug and
    # the DB by title, so the check that survives a title edit is that the
    # tenant got exactly as many links as the fixture declares.
    declared_total = sum(len(codes) for codes in COMPETENCE_PRIMITIVES.values())
    assert len(rows) == declared_total


@pytest.mark.asyncio
async def test_coverage_answers_with_agents_people_and_gaps(
    db: AsyncSession, tenant, user
):
    """The whole point of the fixtures: the Coverage tab of the demo has
    an answer of every kind, not a page of "nobody here can do this"."""
    await _seed(db, tenant, user)

    containers = (
        (
            await db.execute(
                select(WorkContainer).where(WorkContainer.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    verdicts: set[str] = set()
    gap_labels: set[str] = set()
    named_people: set[str] = set()
    shares_seen = False
    for container in containers:
        report = await coverage_service.compute(
            db, tenant.id, container.id, user_id=user.id
        )
        for row in report["steps"]:
            verdicts.add(row["verdict"])
            if row["verdict"] == "gap":
                gap_labels.add(row["gap_label"])
            if row["human"]:
                named_people.add(row["human"]["name"])
        if report.get("shares"):
            shares_seen = True

    assert "agent" in verdicts, "no step falls to an agent type"
    assert "human" in verdicts, "no step falls to a named person"
    assert "gap" in verdicts, "no step is left open"
    # The boundary step of the customer-requests process (B4, showing the
    # customer the fix hands on) carries no cognitive code and is therefore
    # out of the arithmetic entirely.
    assert "out_of_scope" in verdicts
    assert named_people, "the human layer named nobody — the mapping is dead"
    # ``hire`` from the legal judgement in the customer-requests process,
    # ``agency`` from the one-off initiative via the §5.1 suggestion.
    assert gap_labels == {"hire", "agency"}
    assert shares_seen, "no container produced percentage shares"


# HRP-870: the demo has to show the benefit. Both processes must put at
# least this share of their yearly hours into "moves to an agent".
MIN_MOVES_SHARE = 30
PROCESS_KEYS = ("customer_requests", "management_reporting")


@pytest.mark.asyncio
async def test_both_processes_move_a_third_of_their_hours_to_an_agent(
    db: AsyncSession, tenant, user
):
    """Counted by ``coverage.compute`` on the seeded tenant - the number a
    demo visitor reads off the screen - not re-derived from the fixture."""
    await _seed(db, tenant, user)
    title_of = {spec["key"]: spec["title"] for spec in WORK_CONTAINERS}
    assert set(PROCESS_KEYS) < set(title_of), "the agreed pair is gone"

    for key in PROCESS_KEYS:
        container = (
            await db.execute(
                select(WorkContainer).where(
                    WorkContainer.tenant_id == tenant.id,
                    WorkContainer.title == title_of[key],
                )
            )
        ).scalar_one()
        report = await coverage_service.compute(
            db, tenant.id, container.id, user_id=user.id
        )
        assert report["shares"] is not None, key
        assert report["shares"]["moves"] >= MIN_MOVES_SHARE, (
            key,
            report["shares"],
        )
        # The same number from the hours the shares are made of: the share
        # must be of the whole estimated work, not of a flattering subset.
        hours = report["hours"]
        assert hours["unestimated"] == 0, key
        assert hours["moves"] * 100 / hours["total"] >= MIN_MOVES_SHARE, key
        # Not a process an agent does alone either: part of it is reviewed
        # and part of it stays with people.
        assert report["shares"]["to_review"] > 0, key
        assert report["shares"]["stays"] > 0, key


@pytest.mark.asyncio
async def test_the_demo_keeps_one_boundary_step_and_one_hire_gap(
    db: AsyncSession, tenant, user
):
    """What the module docstring promises: exactly one step out of scope,
    exactly one ``hire`` gap, and the ``agency`` gap still in the ISO
    project - each verdict shown once, where a visitor can find it."""
    await _seed(db, tenant, user)
    containers = (
        (
            await db.execute(
                select(WorkContainer).where(WorkContainer.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    out_of_scope: list[str] = []
    gaps: dict[str, list[str]] = {"hire": [], "agency": []}
    for container in containers:
        report = await coverage_service.compute(
            db, tenant.id, container.id, user_id=user.id
        )
        for row in report["steps"]:
            if row["verdict"] == "out_of_scope":
                out_of_scope.append(container.title)
            if row["verdict"] == "gap":
                gaps[row["gap_label"]].append(container.title)

    title_of = {spec["key"]: spec["title"] for spec in WORK_CONTAINERS}
    assert out_of_scope == [title_of["customer_requests"]]
    assert gaps["hire"] == [title_of["customer_requests"]]
    assert gaps["agency"] == [title_of["iso27001"]]


def test_the_iso_project_keeps_its_steps_under_the_new_title():
    """HRP-870 renamed the project; its steps are the same."""
    iso = next(spec for spec in WORK_CONTAINERS if spec["key"] == "iso27001")
    assert iso["title"] == "Getting ISO 27001 certified"
    assert iso["type"] == "initiative" and iso["status"] == "draft"
    assert len(iso["steps"]) == 12
    assert iso["steps"][0]["title"].startswith("Map the scope")
    assert iso["steps"][-1]["title"] == "Set up the surveillance cycle"


@pytest.mark.asyncio
async def test_reseed_is_a_no_op(db: AsyncSession, tenant, user):
    await _seed(db, tenant, user)
    again = await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    assert again["skipped"] is True
    containers = (
        await db.execute(
            select(func.count())
            .select_from(WorkContainer)
            .where(WorkContainer.tenant_id == tenant.id)
        )
    ).scalar_one()
    assert containers == len(WORK_CONTAINERS)
