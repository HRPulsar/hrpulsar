"""HRP-759: a gap of one or more steps becomes one draft vacancy in
Recruitment - cognitive codes only, the tenant's competences that overlap
the gap pre-filled, the link kept on the work side."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from app.core.errors import AppError
from app.modules.ai_settings.models import TenantAISettings
from app.modules.company.models import Tenant
from app.modules.recruitment.models import Vacancy, VacancyCompetence
from app.modules.talent_market.models import TalentCard
from app.modules.work import coverage, service
from app.modules.work.models import WorkHireNeed
from app.modules.work.schemas import ContainerUpdate, HireNeedCreate, StepUpdate
from sqlalchemy import select

from tests.unit.test_coverage_matching import (
    _competence,
    _container,
    _employee,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded
from tests.unit.test_section_gate import _save
from tests.unit.test_work_containers import _user_with_role

no_mapping_enqueue = _quiet
seeded = _seeded


async def _vacancy(db, vacancy_id) -> Vacancy:
    return (
        await db.execute(select(Vacancy).where(Vacancy.id == vacancy_id))
    ).scalar_one()


async def test_gap_of_several_steps_becomes_one_draft_vacancy(db, tenant, user, seeded):
    c = await _container(db, tenant, user, owner_id=user.id)
    judge = await _step(
        db,
        tenant,
        c,
        ["P6", "B1"],
        title="Approve the write-off",
        description="On site",
    )
    covered = await _step(db, tenant, c, ["P1"])
    talk = await _step(db, tenant, c, ["P8"], title="Settle the priorities")
    both = await _competence(db, tenant.id, ["P6", "P8"])
    one = await _competence(db, tenant.id, ["P6"])
    await _competence(db, tenant.id, ["P1"])  # no overlap with the gap
    await _competence(db, tenant.id, ["B1"])  # a boundary code is not hired for
    await _competence(db, tenant.id, ["P6", "P8"], applicable_to="agent")

    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(
            step_ids=[judge["id"], covered["id"], talk["id"]], label="agency"
        ),
        user_id=user.id,
    )
    # The covered step is skipped, the two gaps are kept in breakdown order.
    assert [uuid.UUID(s) for s in need.step_ids] == [judge["id"], talk["id"]]
    assert need.label == "agency"
    assert need.created_by_id == user.id

    vacancy = await _vacancy(db, need.vacancy_id)
    assert vacancy.status == "draft"
    # HRP-801 (QA 23.10, d): an agency need says so in the title.
    assert vacancy.title == "[Filled by an agency] Month-end close"
    assert vacancy.owner_id == user.id
    assert vacancy.hiring_manager_id == user.id
    assert (
        vacancy.description == "Approve the write-off\nOn site\n\nSettle the priorities"
    )

    rows = (
        (
            await db.execute(
                select(VacancyCompetence)
                .where(VacancyCompetence.vacancy_id == vacancy.id)
                .order_by(VacancyCompetence.created_at, VacancyCompetence.id)
            )
        )
        .scalars()
        .all()
    )
    # The agent-only, the unrelated and the physical ones stay out.
    assert {r.competence_id for r in rows} == {both.id, one.id}
    assert {r.source for r in rows} == {"ai"}


async def test_top_five_by_overlap(db, tenant, user, seeded):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6", "P8"])
    for _ in range(7):
        await _competence(db, tenant.id, ["P6"])
    # Created last, ranked first: it overlaps the gap on two codes.
    best = await _competence(db, tenant.id, ["P6", "P8"])
    need = await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
    )
    rows = (
        (
            await db.execute(
                select(VacancyCompetence).where(
                    VacancyCompetence.vacancy_id == need.vacancy_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == service.HIRE_NEED_COMPETENCES
    assert best.id in {r.competence_id for r in rows}


async def test_cold_tenant_still_gets_the_vacancy(db, tenant, user, seeded):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[step["id"]], title="Risk owner"),
        user_id=user.id,
    )
    vacancy = await _vacancy(db, need.vacancy_id)
    assert vacancy.title == "Risk owner"
    assert vacancy.description == "P6"
    assert (
        await db.execute(
            select(VacancyCompetence).where(VacancyCompetence.vacancy_id == vacancy.id)
        )
    ).first() is None


async def test_a_step_is_handed_over_once(db, tenant, user, seeded):
    """A double click (or a retry on a slow create) would otherwise open a
    second draft vacancy nobody sees: the screen shows the newest need."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    other = await _step(db, tenant, c, ["P8"])
    await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
    )
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db,
            tenant.id,
            c.id,
            HireNeedCreate(step_ids=[step["id"], other["id"]]),
            user_id=user.id,
        )
    assert exc.value.code == "work_hire_need_exists"
    assert exc.value.status_code == 409
    needs = (
        (
            await db.execute(
                select(WorkHireNeed).where(WorkHireNeed.container_id == c.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(needs) == 1
    # The step nobody handed over yet still opens a vacancy of its own.
    second = await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[other["id"]]), user_id=user.id
    )
    assert second.step_ids == [str(other["id"])]


async def test_selection_without_a_gap_is_refused(db, tenant, user, seeded):
    # ``covered`` is a step an agent type takes: it is on the To do list as
    # ``not_automated_yet``, and one does not hire for it (W6, §5.10).
    c = await _container(db, tenant, user)
    covered = await _step(db, tenant, c, ["P1"])
    signature = await _step(db, tenant, c, [], responsibility="regulatory")
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db,
            tenant.id,
            c.id,
            HireNeedCreate(step_ids=[covered["id"], signature["id"], uuid.uuid4()]),
            user_id=user.id,
        )
    assert exc.value.code == "work_hire_need_no_gaps"
    assert (
        await db.execute(
            select(WorkHireNeed).where(WorkHireNeed.tenant_id == tenant.id)
        )
    ).first() is None


async def test_assigned_step_is_not_hired_for(db, tenant, user, seeded):
    """HRP-809: an assignment closes the gap, skills or not - the hire guard
    reads the verdict, so the step is refused like any covered one."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    emp = await _employee(db, tenant)
    await service.update_step(
        db, tenant.id, step["id"], StepUpdate(executor_employee_id=emp.id)
    )
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
        )
    assert exc.value.status_code == 422
    assert exc.value.code == "work_hire_need_no_gaps"


async def test_internal_search_switch_reaches_the_vacancy(db, tenant, user, seeded):
    """W6 (§5.9): hiring from a Coverage row offers "inside first" or
    "straight outside"; the switch belongs to the vacancy, not to us."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[step["id"]], internal_search_allowed=False),
        user_id=user.id,
    )
    vacancy = await _vacancy(db, need.vacancy_id)
    assert vacancy.internal_search_allowed is False
    # The default keeps the internal search on.
    other = await _step(db, tenant, c, ["P7"])
    need = await service.create_hire_need(
        db, tenant.id, c.id, HireNeedCreate(step_ids=[other["id"]]), user_id=user.id
    )
    assert (await _vacancy(db, need.vacancy_id)).internal_search_allowed is True


async def test_hire_need_skips_the_not_automated_kind(db, tenant, user, seeded):
    """W6: the guard is on the server, not in the checkboxes - a stale
    screen must not open a vacancy for work an agent is about to do."""
    c = await _container(db, tenant, user)
    automatable = await _step(db, tenant, c, ["P1"])
    real_gap = await _step(db, tenant, c, ["P6"])
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[automatable["id"], real_gap["id"]]),
        user_id=user.id,
    )
    assert need.step_ids == [str(real_gap["id"])]


async def test_gaps_carry_the_link_and_routes(db, tenant, user, seeded, auth_client):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    res = await auth_client.post(
        f"/api/work/containers/{c.id}/gaps/hire-need",
        json={"step_ids": [str(step["id"])], "label": "hire"},
    )
    assert res.status_code == 201, res.text
    need = res.json()
    res = await auth_client.get(f"/api/work/containers/{c.id}/gaps")
    assert res.json()[0]["hire_need"] == {
        "id": need["id"],
        "vacancy_id": need["vacancy_id"],
        "label": "hire",
        # A cold tenant: no library competence, so no talent card.
        "talent_card_id": None,
    }
    # Deleting the vacancy drops the link (ON DELETE SET NULL), not the need.
    await db.delete(await _vacancy(db, uuid.UUID(need["vacancy_id"])))
    await db.commit()
    gaps = await coverage.gaps(db, tenant.id, c.id)
    assert gaps[0]["hire_need"] is None
    res = await auth_client.post(
        f"/api/work/containers/{uuid.uuid4()}/gaps/hire-need",
        json={"step_ids": [str(step["id"])]},
    )
    assert res.status_code == 404


async def test_archived_container_refuses_and_label_does_not_reopen(
    db, tenant, user, seeded
):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    await service.accept_container(
        db, tenant.id, c.id, user_id=user.id, can_manage=True
    )
    # The gap label and the hours are not content: the breakdown stays
    # accepted through the Gaps tab and the hours editor alike.
    updated = await service.update_step(
        db,
        tenant.id,
        step["id"],
        StepUpdate(gap_label="agency", hours_per_run=0.5, runs_per_year=250),
    )
    assert updated["gap_label"] == "agency"
    assert updated["runs_per_year"] == 250
    assert updated["state"] == "accepted"
    assert (await service.get_container(db, tenant.id, c.id)).status == "active"
    await service.update_container(
        db, tenant.id, c.id, ContainerUpdate(status="archived")
    )
    with pytest.raises(AppError) as exc:
        await service.create_hire_need(
            db, tenant.id, c.id, HireNeedCreate(step_ids=[step["id"]]), user_id=user.id
        )
    assert exc.value.code == "work_container_archived"


async def test_deleting_a_step_prunes_its_hire_need(db, tenant, user, seeded):
    """A need naming a deleted step would offer the same handoff on every
    coverage read; the need goes with its last step, the vacancy stays."""
    c = await _container(db, tenant, user, owner_id=user.id)
    first = await _step(db, tenant, c, ["P6"], title="Approve the write-off")
    second = await _step(db, tenant, c, ["P8"], title="Settle the priorities")
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[first["id"], second["id"]], label="hire"),
        user_id=user.id,
    )
    need_id, vacancy_id = need.id, need.vacancy_id

    await service.delete_step(db, tenant.id, first["id"])
    kept = await db.get(WorkHireNeed, need_id, populate_existing=True)
    assert kept is not None and kept.step_ids == [str(second["id"])]

    await service.delete_step(db, tenant.id, second["id"])
    assert await db.get(WorkHireNeed, need_id) is None
    assert await _vacancy(db, vacancy_id) is not None


async def test_draft_vacancy_description_is_bounded(db, tenant, user, seeded):
    """A 500-step container must not hand Recruitment a multi-megabyte
    description: it is prose for a person and later a prompt for a model."""
    c = await _container(db, tenant, user, owner_id=user.id)
    steps = [
        await _step(db, tenant, c, ["P6"], title=f"Judge {i}", description="x" * 800)
        for i in range(60)
    ]
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(step_ids=[s["id"] for s in steps], label="hire"),
        user_id=user.id,
    )
    # Every gap is still recorded; only the text is capped.
    assert len(need.step_ids) == 60
    description = (await _vacancy(db, need.vacancy_id)).description
    assert description.endswith(service.HIRE_NEED_TRUNCATED)
    assert len(description) <= service.HIRE_NEED_MAX_DESCRIPTION + 16
    assert description.count("Judge ") <= service.HIRE_NEED_MAX_STEPS


async def test_other_tenants_container_is_404(db, tenant, user, seeded, auth_client):
    other = Tenant(
        name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
    )
    db.add(other)
    await db.commit()
    # HRP-810: the creator becomes the owner, so it is the other tenant's.
    other_admin, _ = await _user_with_role(db, other, "admin")
    c = await _container(db, other, other_admin)
    step = await _step(db, other, c, ["P6"])
    res = await auth_client.post(
        f"/api/work/containers/{c.id}/gaps/hire-need",
        json={"step_ids": [str(step["id"])]},
    )
    assert res.status_code == 404


# --- HRP-801 REDO (QA 23.10) -------------------------------------------------


async def _hand_over(auth_client, c, step, **body):
    res = await auth_client.post(
        f"/api/work/containers/{c.id}/gaps/hire-need",
        json={"step_ids": [str(step["id"])], **body},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_look_inside_first_lands_on_the_talent_market(
    db, tenant, user, seeded, auth_client
):
    """(b): the draft gets its internal-mobility twin, and the step links to
    the card - the vacancy's own ``talent_card_id``, no column of ours."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    await _competence(db, tenant.id, ["P6"])
    need = await _hand_over(
        auth_client, c, step, label="hire", internal_search_allowed=True
    )
    vacancy = await _vacancy(db, uuid.UUID(need["vacancy_id"]))
    assert vacancy.internal_search_allowed is True
    assert vacancy.talent_card_id is not None
    assert need["talent_card_id"] == str(vacancy.talent_card_id)
    card = await db.get(TalentCard, vacancy.talent_card_id)
    assert card is not None and card.card_type == "vacancy"
    gaps = (await auth_client.get(f"/api/work/containers/{c.id}/gaps")).json()
    assert gaps[0]["hire_need"]["talent_card_id"] == need["talent_card_id"]
    # A card deleted in the talent market drops the link back to the vacancy.
    await db.delete(card)
    await db.commit()
    gaps = (await auth_client.get(f"/api/work/containers/{c.id}/gaps")).json()
    assert gaps[0]["hire_need"]["talent_card_id"] is None
    assert gaps[0]["hire_need"]["vacancy_id"] == need["vacancy_id"]


async def test_without_a_library_competence_the_draft_stays_in_recruitment(
    db, tenant, user, seeded, auth_client
):
    """The twin's precondition (a library competence on the vacancy) fails
    on a cold tenant. Decision: the need still opens on the draft, internal
    search on, and says so with ``talent_card_id`` None - the recruiter
    posts it from the vacancy once it has competences."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    need = await _hand_over(
        auth_client, c, step, label="hire", internal_search_allowed=True
    )
    assert need["talent_card_id"] is None
    vacancy = await _vacancy(db, uuid.UUID(need["vacancy_id"]))
    assert vacancy.internal_search_allowed is True
    assert vacancy.talent_card_id is None
    assert (await db.execute(select(WorkHireNeed.id))).first() is not None


async def test_a_failed_talent_market_post_keeps_the_need_open(
    db, tenant, user, seeded, auth_client, monkeypatch
):
    """The bridge commits the card, then the matcher fails: it deletes the
    card itself and re-raises. The need and its draft are committed by then
    - a 500 would strand them behind a retry that answers 409 - so the need
    opens on the draft like any refusal, and the session still answers."""
    from app.modules.talent_market import matching

    async def broken_matcher(*args, **kwargs):
        raise RuntimeError("matcher down")

    monkeypatch.setattr(matching, "_auto_populate_candidates", broken_matcher)
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    await _competence(db, tenant.id, ["P6"])
    container_id, tenant_id = c.id, tenant.id

    need = await _hand_over(
        auth_client, c, step, label="hire", internal_search_allowed=True
    )
    assert need["talent_card_id"] is None
    assert await db.get(WorkHireNeed, uuid.UUID(need["id"])) is not None
    vacancy = await _vacancy(db, uuid.UUID(need["vacancy_id"]))
    assert vacancy.talent_card_id is None and vacancy.internal_search_allowed
    cards = await db.execute(
        select(TalentCard.id).where(TalentCard.tenant_id == tenant_id)
    )
    assert cards.first() is None
    gaps = (await auth_client.get(f"/api/work/containers/{container_id}/gaps")).json()
    assert gaps[0]["hire_need"]["vacancy_id"] == need["vacancy_id"]


@pytest.mark.parametrize("label", ["hire", "agency"])
async def test_outside_routes_never_reach_the_talent_market(
    db, tenant, user, seeded, auth_client, label
):
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    await _competence(db, tenant.id, ["P6"])
    need = await _hand_over(
        auth_client, c, step, label=label, internal_search_allowed=False
    )
    assert need["talent_card_id"] is None
    assert (await _vacancy(db, uuid.UUID(need["vacancy_id"]))).talent_card_id is None


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("en", "[Filled by an agency] Month-end close"),
        ("de", "[Besetzung durch Agentur] Month-end close"),
        # Enterprise-only catalog: read from it, no Cyrillic in core.
        ("ru", None),
    ],
)
async def test_agency_title_is_in_the_tenant_language(
    db, tenant, user, seeded, language, title
):
    """(d): the prefix is the tenant's content language - the language the
    draft and its steps are written in - not the reader's interface."""
    if title is None:
        catalogs = pytest.importorskip("ee.i18n_catalogs")
        prefix = catalogs.load_catalog(language)["work_hire_need"]["agency_title"]
        title = prefix.format(title="Month-end close")
        assert not title.startswith("[Filled")
    db.add(TenantAISettings(tenant_id=tenant.id, content_language=language))
    await db.commit()
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    need = await service.create_hire_need(
        db,
        tenant.id,
        c.id,
        HireNeedCreate(
            step_ids=[step["id"]], label="agency", internal_search_allowed=False
        ),
        user_id=user.id,
    )
    assert (await _vacancy(db, need.vacancy_id)).title == title


async def test_vacancy_and_card_name_the_process_they_came_from(
    db, tenant, user, seeded, auth_client
):
    """(b)-(d): "Based on {process}" - the work side answers by vacancy and by
    talent card; recruitment and talent_market learn nothing about work."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    await _competence(db, tenant.id, ["P6"])
    need = await _hand_over(auth_client, c, step, internal_search_allowed=True)
    expected = {
        "container_id": str(c.id),
        "type": "process",
        "title": "Month-end close",
        "can_open": True,
    }
    by_vacancy = await auth_client.get(
        f"/api/work/origin/vacancies/{need['vacancy_id']}"
    )
    assert by_vacancy.status_code == 200, by_vacancy.text
    assert by_vacancy.json() == expected
    by_card = await auth_client.get(
        f"/api/work/origin/talent-cards/{need['talent_card_id']}"
    )
    assert by_card.json() == expected

    # A vacancy and a card nobody opened from a process: no line.
    other = await _container(db, tenant, user)
    plain = await _hand_over(
        auth_client,
        other,
        await _step(db, tenant, other, ["P6"]),
        internal_search_allowed=False,
    )
    await db.execute(
        WorkHireNeed.__table__.delete().where(WorkHireNeed.container_id == other.id)
    )
    await db.commit()
    assert (
        await auth_client.get(f"/api/work/origin/vacancies/{plain['vacancy_id']}")
    ).json() is None
    assert (
        await auth_client.get(f"/api/work/origin/talent-cards/{uuid.uuid4()}")
    ).json() is None


async def test_the_origin_follows_who_sees_the_vacancy(
    db, tenant, user, seeded, auth_client, client
):
    """Whoever sees the vacancy sees the line; the title links only for a
    reader who may open the coverage. A recruiter outside a restricted
    process reads it as text, also with Coverage closed to the role - the
    path is a shared read, the Coverage gate does not drop the line."""
    c = await _container(db, tenant, user)
    step = await _step(db, tenant, c, ["P6"])
    need = await _hand_over(auth_client, c, step, internal_search_allowed=False)
    url = f"/api/work/origin/vacancies/{need['vacancy_id']}"
    _, recruiter = await _user_with_role(db, tenant, "recruiter")
    recruiter_h = {"Authorization": f"Bearer {recruiter}"}

    seen = await client.get(url, headers=recruiter_h)
    assert seen.status_code == 200, seen.text
    assert seen.json()["title"] == "Month-end close"
    assert seen.json()["can_open"] is False

    await _save(auth_client, levels={"coverage": {"recruiter": "none"}})
    closed = await client.get(url, headers=recruiter_h)
    assert closed.status_code == 200, closed.text
    assert closed.json()["can_open"] is False

    # The Employee role never reaches hiring: no vacancy, no line.
    _, employee = await _user_with_role(db, tenant, "employee")
    refused = await client.get(url, headers={"Authorization": f"Bearer {employee}"})
    assert refused.status_code == 403


def test_the_frontend_asks_the_origin_routes():
    """The URL the vacancy page and the talent card call is the router's."""
    from app.main import app

    work_ts = Path(__file__).resolve().parents[3] / "frontend/src/lib/api/work.ts"
    if not work_ts.exists():
        pytest.skip("frontend tree not present")
    source = work_ts.read_text()
    paths = {getattr(r, "path", "") for r in app.routes}
    for route, called in [
        ("/api/work/origin/vacancies/{vacancy_id}", "/work/origin/vacancies/${"),
        ("/api/work/origin/talent-cards/{card_id}", "/work/origin/talent-cards/${"),
    ]:
        assert route in paths
        assert called in source
