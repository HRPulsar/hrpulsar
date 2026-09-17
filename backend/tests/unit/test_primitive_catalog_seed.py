"""HRP-748: the primitive catalog seed (v1.1) and its i18n surface.

``catalog_data.PRIMITIVES`` is generated from
``docs/plans/process-library/_catalog.yaml`` by ``scripts/gen_primitive_seed.py``
and committed: ``docs/`` never reaches the public tree, so the runtime and
the seed migration read the Python list, not the YAML. These tests pin the
shape the rest of the epic relies on — 17 codes, ``kind`` stored as data
rather than derived from the code prefix, the verdict snapshot fields, and a
``reference.primitive.*`` entry in both message catalogs for every row.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from app.modules.primitives import catalog_data, service
from app.modules.primitives.models import Primitive
from sqlalchemy import select

REPO = Path(__file__).resolve().parents[3]
MESSAGES = REPO / "frontend" / "messages"
CATALOG_YAML = REPO / "docs" / "plans" / "process-library" / "_catalog.yaml"

ROWS = catalog_data.PRIMITIVES
VERDICTS = {"strong", "better_than_human", "draft", "no"}
# Golden hash of catalog v1.1 as seeded by v2prim01 — see
# test_seed_content_is_pinned for what bumping it commits you to.
SEED_SHA256 = "36ec3b54ea2e6ea28e4ded08d2cbc5b915c6b14573c6566ba8aa82bdaf62e82a"


def test_seed_has_17_unique_codes():
    codes = [r["code"] for r in ROWS]
    assert len(codes) == 17
    assert len(set(codes)) == 17
    assert len({r["i18n_key"] for r in ROWS}) == 17
    # seed_insert() binds by SEED_COLUMNS: every row must carry exactly them.
    for r in ROWS:
        assert tuple(r) == catalog_data.SEED_COLUMNS, r["code"]


def test_kind_is_data_not_a_code_prefix():
    by_kind: dict[str, list[str]] = {}
    for r in ROWS:
        by_kind.setdefault(r["kind"], []).append(r["code"])
    assert set(by_kind) == {"cognitive", "boundary"}
    assert len(by_kind["cognitive"]) == 13
    assert len(by_kind["boundary"]) == 4


def test_every_row_carries_the_verdict_snapshot():
    # Decision 2026-08-28: the AI verdict is a snapshot, not a property of
    # the code — a quarterly revision rewrites ai_as_of/ai_basis without
    # touching the catalog version.
    for r in ROWS:
        assert isinstance(r["ai_as_of"], date), r["code"]
        assert r["ai_basis"], r["code"]
        assert r["ai_verdict"] in VERDICTS, r["code"]
        assert r["introduced_in"] in {"v1", "v1.1"}, r["code"]
        assert r["title_en"].strip(), r["code"]


def test_seed_is_english_only():
    # scripts/sync_repos.sh refuses to publish any Cyrillic under backend/**.
    for r in ROWS:
        for key in ("title_en", "scope_en"):
            text = r[key] or ""
            assert not any("\u0400" <= ch <= "\u04ff" for ch in text), (r["code"], key)


@pytest.mark.parametrize("locale", ["en", "de"])
def test_reference_keys_exist_in_message_catalog(locale):
    tree = json.loads((MESSAGES / f"{locale}.json").read_text())
    block = tree["reference"]["primitive"]
    for r in ROWS:
        entry = block[r["i18n_key"]]
        assert entry["label"].strip(), (locale, r["code"])
        assert entry["description"].strip(), (locale, r["code"])
        if locale == "en":
            # The DB fallback text and the rendered English must agree.
            assert entry["label"] == r["title_en"], r["code"]
            assert entry["description"] == r["scope_en"], r["code"]
    assert set(block) == {r["i18n_key"] for r in ROWS}


def test_seed_content_is_pinned():
    """Migration v2prim01 seeds whatever ``catalog_data`` holds at run time,
    so a later edit would change what a fresh install gets while upgraded
    installs keep the old rows (ON CONFLICT DO NOTHING). Editing the seed
    therefore requires a data migration for existing installs — bump this
    hash in the same change."""
    digest = hashlib.sha256(
        json.dumps(ROWS, default=str, sort_keys=True).encode()
    ).hexdigest()
    assert digest == SEED_SHA256, digest


async def test_list_primitives_hides_retired_by_default(db):
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    p13 = (
        await db.execute(select(Primitive).where(Primitive.code == "P13"))
    ).scalar_one()
    p13.retired_in = "v9-test"
    await db.commit()
    try:
        active = await service.list_primitives(db)
        assert "P13" not in {p.code for p in active}
        assert [p.sort_index for p in active] == sorted(p.sort_index for p in active)
        everything = await service.list_primitives(db, include_retired=True)
        assert "P13" in {p.code for p in everything}
    finally:
        p13.retired_in = None
        await db.commit()


def test_seed_matches_the_yaml_source():
    """Drift guard between the human-edited YAML and the generated seed."""
    if not CATALOG_YAML.exists():
        pytest.skip("docs/ is not part of the public tree")
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(CATALOG_YAML.read_text())
    assert doc["version"] == catalog_data.CATALOG_VERSION
    expected = {}
    for kind, section in (("cognitive", "primitives"), ("boundary", "boundary")):
        for p in doc[section]:
            verdict = "no" if p["ai"] is False else p["ai"]
            expected[p["code"]] = (
                kind,
                verdict,
                p["ai_as_of"],
                p["ai_basis"],
                p.get("added_in", "v1"),
            )
    got = {
        r["code"]: (
            r["kind"],
            r["ai_verdict"],
            r["ai_as_of"],
            r["ai_basis"],
            r["introduced_in"],
        )
        for r in ROWS
    }
    assert got == expected


async def test_seed_insert_is_idempotent(db):
    # The migration and this test share one statement, so what the test
    # proves about ON CONFLICT is what production runs.
    await db.execute(catalog_data.seed_insert())
    await db.execute(catalog_data.seed_insert())
    await db.commit()

    rows = (await db.execute(select(Primitive))).scalars().all()
    assert len(rows) == 17
    assert {r.code for r in rows if r.kind == "boundary"} == {"B1", "B2", "B3", "B4"}
    assert all(r.retired_in is None and r.merged_into_id is None for r in rows)
    p11 = next(r for r in rows if r.code == "P11")
    assert p11.introduced_in == "v1.1"
    assert p11.ai_as_of == date(2026, 8, 31)


async def test_seed_insert_survives_a_renamed_code(db):
    # ``primitives`` is unique on code *and* on i18n_key. A catalog version
    # that renames a code keeps the i18n key, so a seed targeting ``code``
    # alone would abort the whole insert on the second constraint.
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    row = (
        await db.execute(select(Primitive).where(Primitive.code == "P1"))
    ).scalar_one()
    row.code = "P1X"
    await db.commit()
    try:
        await db.execute(catalog_data.seed_insert())
        await db.commit()

        codes = set((await db.execute(select(Primitive.code))).scalars().all())
        # The renamed row kept the i18n key, so the catalog's P1 was skipped.
        assert "P1X" in codes and "P1" not in codes
    finally:
        # The catalog is seeded once into the shared test database; every
        # later test reads it back by code.
        row.code = "P1"
        await db.commit()
