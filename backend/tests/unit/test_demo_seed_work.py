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
    # The boundary step of the onboarding process (B4, the buddy
    # correcting mistakes in the moment) carries no cognitive code and is
    # therefore out of the arithmetic entirely.
    assert "out_of_scope" in verdicts
    assert named_people, "the human layer named nobody — the mapping is dead"
    # ``hire`` from the regulatory judgement in the incident process,
    # ``agency`` from the one-off initiative via the §5.1 suggestion.
    assert gap_labels == {"hire", "agency"}
    assert shares_seen, "no container produced percentage shares"


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
