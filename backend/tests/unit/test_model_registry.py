"""Model registry completeness (prod incident 2026-07-15).

``candidate_vacancies.manager_score_source_round_id`` carries a string
ForeignKey to ``recruitment_assessment_rounds``, which is defined in
``manager_assessment_models.py``. The Celery worker only imported
``*/models.py``, so the first ORM flush in the worker raised
``NoReferencedTableError`` and every analysis task died on retry.

Two guards:

* every module file that defines a ``__tablename__`` must match the
  ``import_all_models()`` glob (``models.py`` / ``*_models.py``), so a
  future ``foo_tables.py`` can't silently escape registration;
* in a fresh interpreter that imports models the same way the worker
  does (no FastAPI router graph), every ForeignKey in ``Base.metadata``
  must resolve.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
MODULES_DIR = BACKEND_DIR / "app" / "modules"


def test_every_tablename_file_matches_models_glob():
    covered = {
        *MODULES_DIR.glob("*/models.py"),
        *MODULES_DIR.glob("*/*_models.py"),
    }
    offenders = [
        path.relative_to(BACKEND_DIR)
        for path in MODULES_DIR.glob("*/*.py")
        if "__tablename__" in path.read_text(encoding="utf-8") and path not in covered
    ]
    assert not offenders, (
        f"Model definitions outside the import_all_models() glob: {offenders}. "
        "Rename to models.py / *_models.py or extend "
        "app.database.import_all_models()."
    )


def test_worker_style_import_resolves_all_foreign_keys():
    """Simulate the Celery worker: import_all_models() in a clean process
    (no app.main / router imports), then force-resolve every FK."""
    script = (
        "from app.database import Base, import_all_models\n"
        "import_all_models()\n"
        "for table in Base.metadata.tables.values():\n"
        "    for fk in table.foreign_keys:\n"
        "        fk.column  # raises NoReferencedTableError if unresolvable\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"FK resolution failed in a worker-style process:\n{result.stderr}"
    )
