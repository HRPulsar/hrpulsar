"""HRP-790: Offer accepted and Probation completed in the default funnel.

The sequence is ... → Offer → Offer accepted → Hired → Probation completed
→ ...; ``hired`` keeps its terminal-positive type, and a candidate on it can
still be moved on to ``probation_completed`` (the funnel has no lock on a
terminal stage).
"""

from __future__ import annotations

import uuid

from app.core.i18n import translate
from app.modules.recruitment import service, vacancy_service
from app.modules.recruitment.models import CandidateVacancy
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    CandidateVacancyPatch,
    CandidateVacancyStatusUpdate,
    VacancyCreate,
)
from app.modules.recruitment.vacancy_service import DEFAULT_RECRUITMENT_STAGES
from migrations.versions.hrp790stages01_post_offer_stages import (
    NEW_STAGES,
    _hired_rename,
)
from sqlalchemy.ext.asyncio import AsyncSession

_BY_CODE = {code: rest for code, *rest in DEFAULT_RECRUITMENT_STAGES}
_ORDER = [code for code, *_ in DEFAULT_RECRUITMENT_STAGES]


def test_sequence_and_types() -> None:
    offer = _ORDER.index("offer")
    assert _ORDER[offer : offer + 4] == [
        "offer",
        "offer_accepted",
        "hired",
        "probation_completed",
    ]
    sort_orders = [so for _, _, so, *_ in DEFAULT_RECRUITMENT_STAGES]
    assert sort_orders == sorted(sort_orders)
    assert _BY_CODE["offer_accepted"][2] == "active"
    assert _BY_CODE["hired"][2] == "terminal_positive"
    assert _BY_CODE["probation_completed"][2] == "terminal_positive"


def test_migration_mirrors_the_seed_tuple() -> None:
    for code, anchor, stage_type, color in NEW_STAGES:
        assert _ORDER[_ORDER.index(code) - 1] == anchor
        _, _, seed_type, seed_color = _BY_CODE[code]
        assert (stage_type, color) == (seed_type, seed_color)


def test_catalog_names() -> None:
    for code, *_ in NEW_STAGES:
        en = translate(f"recruitment.stage.{code}", "en")
        assert en == _BY_CODE[code][0]
        assert translate(f"recruitment.stage.{code}", "de") != en


def test_one_word_hired_names_are_not_renamed() -> None:
    assert _hired_rename("en") is None
    assert _hired_rename("de") is None


async def _cv_on_stage(db: AsyncSession, tenant, user, code: str):
    await vacancy_service.seed_default_recruitment_stages(db, tenant.id)
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="P", last_name="C", email=f"{uuid.uuid4().hex[:8]}@example.com"
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(candidate["id"])),
            vacancy_id=uuid.UUID(str(vacancy["id"])),
        ),
    )
    stages = {
        s["code"]: uuid.UUID(str(s["id"]))
        for s in await service.get_effective_vacancy_stages(
            db, tenant.id, uuid.UUID(str(vacancy["id"]))
        )
    }
    cv_id = uuid.UUID(str(cv["id"]))
    await service.patch_candidate_vacancy(
        db, tenant.id, cv_id, CandidateVacancyPatch(stage_id=stages[code])
    )
    return cv_id, stages


async def test_hired_candidate_moves_on_to_probation_completed(
    db: AsyncSession, tenant, user
) -> None:
    cv_id, stages = await _cv_on_stage(db, tenant, user, "hired")
    await service.patch_candidate_vacancy(
        db,
        tenant.id,
        cv_id,
        CandidateVacancyPatch(stage_id=stages["probation_completed"]),
        user_id=user.id,
    )
    row = await db.get(CandidateVacancy, cv_id)
    await db.refresh(row)
    assert row.stage_id == stages["probation_completed"]
    assert row.status_history[-1]["from_stage_id"] == str(stages["hired"])


async def test_status_endpoint_accepts_the_same_move(
    db: AsyncSession, tenant, user
) -> None:
    cv_id, stages = await _cv_on_stage(db, tenant, user, "hired")
    moved = await service.change_candidate_status(
        db,
        tenant.id,
        cv_id,
        CandidateVacancyStatusUpdate(stage_id=stages["probation_completed"]),
        user_id=user.id,
    )
    assert moved["stage_id"] == stages["probation_completed"]


# ---------------------------------------------------------------------------
# The migration itself, run against the test database inside a transaction
# that is rolled back: upgrade -> downgrade -> upgrade.
# ---------------------------------------------------------------------------

_OLD_FUNNEL = [
    ("new", "New", 10, "active"),
    ("screening", "Screening", 20, "active"),
    ("tech_interview", "Tech interview", 30, "active"),
    ("manager_interview", "Interview with manager", 40, "active"),
    ("final_interview", "Final interview", 50, "active"),
    ("offer", "Offer", 60, "active"),
    ("hired", "Hired", 70, "terminal_positive"),
    ("rejected", "Rejected", 80, "terminal_negative"),
    ("withdrew", "Withdrew", 90, "terminal_neutral"),
]


def _migration():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/hrp790stages01_post_offer_stages.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn, fn) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _tenant(conn, locale: str | None, *, override: bool = False):
    from sqlalchemy import text

    tid = conn.execute(
        text(
            "INSERT INTO tenants (id, name, slug, default_locale)"
            " VALUES (gen_random_uuid(), :n, :s, :l) RETURNING id"
        ),
        {"n": f"m790 {locale}", "s": f"m790-{uuid.uuid4().hex[:10]}", "l": locale},
    ).scalar_one()
    vacancy_id = None
    if override:
        vacancy_id = conn.execute(
            text(
                "INSERT INTO vacancies (id, tenant_id, title)"
                " VALUES (gen_random_uuid(), :t, 'v') RETURNING id"
            ),
            {"t": tid},
        ).scalar_one()
    for i, (code, name, so, kind) in enumerate(_OLD_FUNNEL):
        conn.execute(
            text(
                "INSERT INTO vacancy_stages (id, tenant_id, vacancy_id, name, code,"
                " sort_order, is_terminal, stage_type)"
                " VALUES (gen_random_uuid(), :t, :v, :n, :c, :o, :term, :k)"
            ),
            {
                "t": tid,
                "v": vacancy_id,
                "n": name,
                "c": code,
                "o": i if override else so,
                "term": kind != "active",
                "k": kind,
            },
        )
    return tid, vacancy_id


def _funnel(conn, tid, vacancy_id=None) -> list[tuple[str, str]]:
    from sqlalchemy import text

    return [
        (r.code, r.name)
        for r in conn.execute(
            text(
                "SELECT code, name FROM vacancy_stages WHERE tenant_id = :t"
                " AND vacancy_id IS NOT DISTINCT FROM :v ORDER BY sort_order"
            ),
            {"t": tid, "v": vacancy_id},
        )
    ]


def _engine():
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    return create_engine(
        make_url(settings.database_url).set(
            drivername="postgresql+psycopg2", database="hrpulsar_test"
        )
    )


def test_migration_round_trip() -> None:
    from sqlalchemy import text

    mig = _migration()
    engine = _engine()
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            en, _ = _tenant(conn, "en")
            de, _ = _tenant(conn, "de")
            ov, ov_vacancy = _tenant(conn, "en", override=True)
            live = conn.execute(
                text(
                    "INSERT INTO vacancies (id, tenant_id, title, status)"
                    " VALUES (gen_random_uuid(), :t, 'live', 'published') RETURNING id"
                ),
                {"t": en},
            ).scalar_one()
            dropped = conn.execute(
                text(
                    "INSERT INTO vacancies (id, tenant_id, title, status,"
                    " close_resolution, closed_at)"
                    " VALUES (gen_random_uuid(), :t, 'old', 'closed', 'cancelled', now())"
                    " RETURNING id"
                ),
                {"t": en},
            ).scalar_one()
            expected_codes = [code for code, *_ in DEFAULT_RECRUITMENT_STAGES]

            for step in (mig.upgrade, mig.downgrade, mig.upgrade):
                _run(conn, step)
            assert [c for c, _ in _funnel(conn, en)] == expected_codes
            assert [c for c, _ in _funnel(conn, ov, ov_vacancy)] == expected_codes
            assert dict(_funnel(conn, de))["offer_accepted"] == "Angebot angenommen"

            # Review M1 / m1: one name for a live vacancy, and the old
            # "cancelled" resolution is the Cancelled status.
            row = conn.execute(
                text("SELECT status FROM vacancies WHERE id = :i"), {"i": live}
            ).one()
            assert row.status == "open"
            row = conn.execute(
                text(
                    "SELECT status, close_resolution, closed_at FROM vacancies"
                    " WHERE id = :i"
                ),
                {"i": dropped},
            ).one()
            assert (row.status, row.close_resolution) == ("cancelled", None)
            assert row.closed_at is not None
        finally:
            tx.rollback()
    engine.dispose()


def test_malformed_tenant_locale_gets_english_names_and_no_hole() -> None:
    """Review m5: room was made in every funnel while the insert skipped a
    locale like ``ru_RU`` - a gap with no stage, growing on every re-run."""
    from sqlalchemy import text

    mig = _migration()
    engine = _engine()
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            odd = [_tenant(conn, loc)[0] for loc in ("ru_RU", "english")]

            def orders(tid):
                return {
                    r.code: r.sort_order
                    for r in conn.execute(
                        text(
                            "SELECT code, sort_order FROM vacancy_stages"
                            " WHERE tenant_id = :t AND vacancy_id IS NULL"
                        ),
                        {"t": tid},
                    )
                }

            _run(conn, mig.upgrade)
            first = [orders(t) for t in odd]
            _run(conn, mig.upgrade)  # a re-run changes nothing
            assert [orders(t) for t in odd] == first

            for tid, by_code in zip(odd, first, strict=True):
                names = dict(_funnel(conn, tid))
                assert names["offer_accepted"] == "Offer accepted"
                assert names["probation_completed"] == "Probation completed"
                assert by_code["offer_accepted"] == by_code["offer"] + 1
                assert by_code["probation_completed"] == by_code["hired"] + 1
        finally:
            tx.rollback()
    engine.dispose()
