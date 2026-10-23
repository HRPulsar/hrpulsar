"""HRP-1066: the company region on the company profile.

ISO 3166-1 alpha-2, one of ``REGIONS``; the employee card reads it from
/auth/me to pick the education levels.
"""

from __future__ import annotations

from app.modules.company.schemas import REGIONS
from httpx import AsyncClient

PROFILE = "/api/settings/company-profile"


def test_regions_are_iso_alpha2() -> None:
    assert len(REGIONS) == 249
    assert all(len(c) == 2 and c.isascii() and c.isupper() for c in REGIONS)
    assert {"RU", "DE", "US", "GB"} <= REGIONS


async def test_region_round_trips_and_reaches_me(auth_client: AsyncClient) -> None:
    assert (await auth_client.get(PROFILE)).json()["region"] is None
    res = await auth_client.put(PROFILE, json={"region": "RU"})
    assert res.status_code == 200, res.text
    assert res.json()["region"] == "RU"
    assert (await auth_client.get(PROFILE)).json()["region"] == "RU"
    assert (await auth_client.get("/api/auth/me")).json()["tenant_region"] == "RU"

    # Saving another field keeps it; an explicit null clears it.
    res = await auth_client.put(PROFILE, json={"industry": "Software"})
    assert res.json()["region"] == "RU"
    res = await auth_client.put(PROFILE, json={"region": None})
    assert res.status_code == 200
    assert res.json()["region"] is None
    assert (await auth_client.get("/api/auth/me")).json()["tenant_region"] is None


async def test_unknown_region_is_rejected(auth_client: AsyncClient) -> None:
    res = await auth_client.put(PROFILE, json={"region": "XX"})
    assert res.status_code == 400
    assert res.json()["code"] == "unsupported_region"
    for bad in ("ru", "RUS", "R1", ""):
        res = await auth_client.put(PROFILE, json={"region": bad})
        assert res.status_code == 422, bad
    assert (await auth_client.get(PROFILE)).json()["region"] is None


def _migration():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/hrp1066region_tenant_region.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_down_and_up() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.config import settings
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    def column(conn):
        return conn.execute(
            text(
                "SELECT character_maximum_length, is_nullable"
                " FROM information_schema.columns"
                " WHERE table_name = 'tenants' AND column_name = 'region'"
            )
        ).one_or_none()

    mig = _migration()
    engine = create_engine(
        make_url(settings.database_url).set(
            drivername="postgresql+psycopg2", database="hrpulsar_test"
        )
    )
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            # The unit schema comes from create_all, so the column is there.
            assert column(conn) is not None
            with Operations.context(MigrationContext.configure(conn)):
                mig.downgrade()
                assert column(conn) is None
                mig.upgrade()
            assert tuple(column(conn)) == (2, "YES")
        finally:
            tx.rollback()
    engine.dispose()
