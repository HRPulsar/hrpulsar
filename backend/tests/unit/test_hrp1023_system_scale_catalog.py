"""HRP-1023: the frontend translates the seeded recruitment scale by its
English text, so ``reference.recruitmentScale`` in the en catalog and
``lib/reference-labels.ts`` must carry the seed byte for byte."""

import json
from pathlib import Path

from app.modules.recruitment.manager_assessment_service import (
    DEFAULT_SCALE_DESCRIPTION,
    DEFAULT_SCALE_LEVELS,
    DEFAULT_SCALE_NAME,
)

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
KEYS = {1: "notSuitable", 2: "below", 3: "meets", 4: "exceeds"}


def test_the_en_catalog_mirrors_the_seed():
    en = json.loads((FRONTEND / "messages" / "en.json").read_text())["reference"]["recruitmentScale"]
    assert en["standard"] == {"name": DEFAULT_SCALE_NAME, "description": DEFAULT_SCALE_DESCRIPTION}
    assert {lvl["value"] for lvl in DEFAULT_SCALE_LEVELS} == set(KEYS)
    for lvl in DEFAULT_SCALE_LEVELS:
        assert en["level"][KEYS[lvl["value"]]] == {"label": lvl["label"], "description": lvl["description"]}


def test_the_display_join_keys_are_the_seed():
    source = (FRONTEND / "src" / "lib" / "reference-labels.ts").read_text()
    for text in (DEFAULT_SCALE_NAME, DEFAULT_SCALE_DESCRIPTION):
        assert f'"{text}"' in source
    for lvl in DEFAULT_SCALE_LEVELS:
        assert f'label: "{lvl["label"]}", description: "{lvl["description"]}"' in source
