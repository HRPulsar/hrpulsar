"""HRP-982 (review m3): the stage-change notification names the mover.

The unit database is built from model metadata, so migrations never run
here. These tests pin ``hrp982stagetpl01`` against the seeds it rewrites:
(a) the shipped body it guards on is really what the seeds wrote, so the
UPDATE hits; (b) the new body names the mover; (c) an event raised before
the change - no ``actor_name`` - renders exactly the old letter.
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

from app.modules.notification.models import NotificationTemplate
from app.modules.notification.service import render_db_template_preview

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
_CONTEXT = {
    "candidate_name": "Ann Lee",
    "vacancy_title": "Backend Engineer",
    "stage_name": "Offer",
}


def _module(filename: str) -> ModuleType:
    path = _VERSIONS / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration() -> ModuleType:
    return _module("hrp982stagetpl01_stage_change_names_mover.py")


def _preview(body: str, **extra: str) -> str:
    row = NotificationTemplate(
        code="x", locale="en", subject_template="s", body_template=body
    )
    return render_db_template_preview(row, {**_CONTEXT, **extra})[1]


def test_chains_after_the_stage_migration() -> None:
    assert _migration().down_revision == "hrp790stages01"


def test_shipped_bodies_are_the_seeds() -> None:
    mig = _migration()
    en_seed = {
        code: body
        for code, _subject, body in _module(
            "r4c1b2c3d4e5_r4c_notifications_onboarding_sharing.py"
        )._RECRUITMENT_TEMPLATES
    }
    de_seed = _module(
        "hrp481detemplates01_german_notification_templates.py"
    ).GERMAN_TEMPLATES
    assert mig.BODIES["en"][0] == en_seed[mig.CODE]
    assert mig.BODIES["de"][0] == de_seed[mig.CODE][1]


def test_new_body_names_the_mover_and_degrades_without_one() -> None:
    expected = {"en": "Moved by Mona Mover.", "de": "Verschoben von Mona Mover."}
    for locale, (shipped, new) in _migration().BODIES.items():
        assert _preview(new, actor_name="Mona Mover").endswith(expected[locale])
        assert _preview(new) == _preview(shipped)
