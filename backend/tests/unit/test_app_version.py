"""HRP-396 — app version resolution.

Docker images no longer bake a bogus ``APP_VERSION=0.0.0`` default: when
the env var is absent or empty, Settings reads ``__version__`` from
version.py (repo root in dev, /app inside the image). An explicit
APP_VERSION still overrides.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings, _version_from_file

# Independent oracle: execute version.py the way the deploy workflows do,
# instead of duplicating the regex under test.
_ns: dict = {}
exec((Path(__file__).resolve().parents[3] / "version.py").read_text(), _ns)
REPO_VERSION: str = _ns["__version__"]


def test_version_from_file_reads_repo_version():
    assert _version_from_file() == REPO_VERSION


def test_empty_version_falls_back_to_version_py():
    settings = Settings(version="")
    assert settings.version == REPO_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", settings.version)


def test_explicit_version_overrides_file():
    assert Settings(version="9.9.9").version == "9.9.9"
    assert Settings(app_version="8.8.8").version == "8.8.8"


def test_non_numeric_version_falls_back_to_version_py():
    # SaaS compose leaks APP_VERSION=latest (image-tag selector) into the
    # container env; stale self-hosted .env files carry APP_VERSION=dev.
    assert Settings(version="latest").version == REPO_VERSION
    assert Settings(version="dev").version == REPO_VERSION
