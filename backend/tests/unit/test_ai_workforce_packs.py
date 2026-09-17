"""HRP-752: the built-in agent packs (decision O5, 2026-08-31) and their
``SKILL.md`` skeletons.

Coverage counts agent capability by pack, not by registered agent
(REFACTOR_PLAN §1.2), and the matching rule ``step.primitives ⊆
pack.primitives`` stays a single line only because no pack ever declares a
code the catalog says an agent should not do: P6 / P7 / P8 (verdict "no")
and the boundary codes B1–B4. These tests pin that contract, the seed
shape shared by migration ``v2agnt01`` and the runtime, and the
``reference.agentPack.*`` labels in every shipped message catalog.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from app.modules.ai_workforce import pack_data, service, skill_templates
from app.modules.ai_workforce.models import AIAgentPack, AIAgentPackPrimitive
from app.modules.company.models import Tenant
from app.modules.primitives import catalog_data
from app.modules.primitives.models import Primitive
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

REPO = Path(__file__).resolve().parents[3]
MESSAGES = REPO / "frontend" / "messages"

PACKS = pack_data.PACKS
EXPECTED_CODES = {
    "extraction",
    "compliance_check",
    "triage_router",
    "drafting",
    "investigation",
    "artifact_builder",
    "experiment_design",
    "coordinator",
    "scripted_dialogue",
}
NEVER_IN_A_PACK = {"P6", "P7", "P8", "B1", "B2", "B3", "B4"}
CATALOG = {row["code"]: row for row in catalog_data.PRIMITIVES}


def test_seed_has_the_nine_packs():
    codes = [p["code"] for p in PACKS]
    assert set(codes) == EXPECTED_CODES
    assert len(codes) == 9
    assert len({p["i18n_key"] for p in PACKS}) == 9
    assert [p["sort_index"] for p in PACKS] == list(range(9))


def test_pack_construction_matches_the_catalog():
    # §2.4: every pack is P1 plus its verdict code; coordinator and
    # scripted_dialogue carry the v1.1 "yes" codes P11 / P12.
    by_code = {p["code"]: set(p["primitives"]) for p in PACKS}
    assert by_code["extraction"] == {"P1"}
    assert by_code["compliance_check"] == {"P1", "P2"}
    assert by_code["triage_router"] == {"P1", "P2", "P3"}
    assert by_code["drafting"] == {"P1", "P5"}
    assert by_code["investigation"] == {"P1", "P4"}
    assert by_code["artifact_builder"] == {"P1", "P9"}
    assert by_code["experiment_design"] == {"P1", "P10"}
    assert by_code["coordinator"] == {"P1", "P11"}
    assert by_code["scripted_dialogue"] == {"P1", "P12"}


def test_no_pack_declares_a_no_verdict_or_boundary_code():
    declared = {code for p in PACKS for code in p["primitives"]}
    assert declared & NEVER_IN_A_PACK == set()
    for code in declared:
        row = CATALOG[code]
        assert row["kind"] == "cognitive", code
        assert row["ai_verdict"] != "no", code


def test_every_pack_has_a_skeleton_of_the_right_construction():
    for p in PACKS:
        text = skill_templates.skeleton_for(p["code"])
        assert text.startswith("---\n"), p["code"]
        assert "{{step_title}}" in text, p["code"]
        if p["code"] in skill_templates.PIPELINE_PACKS:
            # Deterministic pipeline: a verification-against-reference section.
            assert "## Verification against the reference" in text, p["code"]
        else:
            assert p["code"] in skill_templates.ACCEPTANCE_PACKS
            assert "## Acceptance by a human" in text, p["code"]
    assert (
        set(skill_templates.PIPELINE_PACKS) | set(skill_templates.ACCEPTANCE_PACKS)
        == EXPECTED_CODES
    )
    with pytest.raises(KeyError):
        skill_templates.skeleton_for("no_such_pack")


def test_seed_is_english_only():
    # scripts/sync_repos.sh refuses any Cyrillic under backend/**.
    texts = [p["title_en"] + (p["description_en"] or "") for p in PACKS]
    texts += [skill_templates.skeleton_for(p["code"]) for p in PACKS]
    for text in texts:
        assert not any("\u0400" <= ch <= "\u04ff" for ch in text)


@pytest.mark.parametrize("locale", ["en", "de", "ru"])
def test_reference_keys_exist_in_message_catalog(locale):
    path = MESSAGES / f"{locale}.json"
    if not path.exists():
        pytest.skip(f"{locale}.json is not part of this checkout")
    block = json.loads(path.read_text())["reference"]["agentPack"]
    for p in PACKS:
        entry = block[p["i18n_key"]]
        assert entry["label"].strip(), (locale, p["code"])
        assert entry["description"].strip(), (locale, p["code"])
        if locale == "en":
            assert entry["label"] == p["title_en"], p["code"]
            assert entry["description"] == p["description_en"], p["code"]
    assert set(block) == {p["i18n_key"] for p in PACKS}


async def _seeded(db: AsyncSession) -> dict[str, set[str]]:
    rows = await db.execute(
        select(AIAgentPack.code, Primitive.code)
        .join(AIAgentPackPrimitive, AIAgentPackPrimitive.pack_id == AIAgentPack.id)
        .join(Primitive, Primitive.id == AIAgentPackPrimitive.primitive_id)
        .where(AIAgentPack.tenant_id.is_(None))
    )
    out: dict[str, set[str]] = {}
    for pack_code, code in rows.all():
        out.setdefault(pack_code, set()).add(code)
    return out


async def test_seed_packs_is_idempotent(db):
    # The migration and the service run the same statements, so what this
    # proves about a re-run is what production runs.
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    await service.seed_packs(db)
    await service.seed_packs(db)

    packs = (
        (await db.execute(select(AIAgentPack).where(AIAgentPack.tenant_id.is_(None))))
        .scalars()
        .all()
    )
    assert {p.code for p in packs} == EXPECTED_CODES
    assert len(packs) == 9
    assert all(p.is_active for p in packs)
    seeded = await _seeded(db)
    assert seeded == {p["code"]: set(p["primitives"]) for p in PACKS}


async def test_seed_refuses_a_pack_code_the_catalog_does_not_have(db, monkeypatch):
    """The insert resolves codes with ``IN``, so a missing one used to seed
    one row fewer and leave the pack quietly covering less than it declares
    - coverage then answers ``gap`` where the pack says ``agent``."""
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    monkeypatch.setattr(
        pack_data,
        "PACKS",
        [*PACKS, {**PACKS[0], "code": "bogus", "primitives": ["P1", "P404"]}],
    )
    with pytest.raises(RuntimeError, match="P404"):
        await service.seed_packs(db)
    await db.rollback()
    assert (
        await db.execute(select(AIAgentPack).where(AIAgentPack.code == "bogus"))
    ).first() is None


async def test_list_packs_hides_inactive_and_other_tenants(db, tenant):
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    await service.seed_packs(db)
    other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
    db.add(other)
    await db.flush()
    db.add_all(
        [
            AIAgentPack(
                code="custom", title_en="Custom", i18n_key="custom", tenant_id=tenant.id
            ),
            AIAgentPack(
                code="old",
                title_en="Old",
                i18n_key="old",
                is_active=False,
                tenant_id=tenant.id,
            ),
            AIAgentPack(
                code="theirs", title_en="Theirs", i18n_key="theirs", tenant_id=other.id
            ),
        ]
    )
    await db.commit()

    mine = await service.list_packs(db, tenant.id)
    assert [p["code"] for p in mine][:9] == [p["code"] for p in PACKS]
    assert {p["code"] for p in mine} == EXPECTED_CODES | {"custom"}
    codes = {p["code"]: p["primitive_codes"] for p in mine}
    assert codes["coordinator"] == ["P1", "P11"]
    assert codes["custom"] == []
    assert {p["code"] for p in await service.list_packs(db, other.id)} == (
        EXPECTED_CODES | {"theirs"}
    )
