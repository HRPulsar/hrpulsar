"""HRP-398 — requirements lock must not drift from the .in sources.

Docker and CI install from the pip-compile locks (requirements*.txt);
requirements*.in stay the human-edited sources. Adding a dependency to an
.in file without running ``make lock`` breaks reproducible builds — these
tests catch that before it ships.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version

BACKEND = Path(__file__).resolve().parents[2]


def _requirements(in_file: Path) -> list[Requirement]:
    reqs = []
    for raw in in_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-r ", "-c ")):
            continue
        try:
            reqs.append(Requirement(line))
        except InvalidRequirement:
            continue
    return reqs


def _direct_deps(in_file: Path) -> set[str]:
    deps = set()
    for raw in in_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-r ", "-c ")):
            continue
        name = re.split(r"[\[<>=!~; ]", line, maxsplit=1)[0]
        if name:
            deps.add(name.lower().replace("_", "-"))
    return deps


def _pinned(lock_file: Path) -> dict[str, str]:
    pins = {}
    for line in lock_file.read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==(\S+)", line)
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def test_runtime_lock_covers_requirements_in():
    missing = _direct_deps(BACKEND / "requirements.in") - set(
        _pinned(BACKEND / "requirements.txt")
    )
    assert not missing, f"run `make lock`: unpinned runtime deps {sorted(missing)}"


def test_dev_lock_covers_requirements_test_in():
    missing = _direct_deps(BACKEND / "requirements.test.in") - set(
        _pinned(BACKEND / "requirements.test.txt")
    )
    assert not missing, f"run `make lock`: unpinned dev deps {sorted(missing)}"


def test_runtime_pins_satisfy_declared_constraints():
    """A version bump in requirements.in without `make lock` must fail."""
    pins = _pinned(BACKEND / "requirements.txt")
    violations = {}
    for req in _requirements(BACKEND / "requirements.in"):
        name = req.name.lower().replace("_", "-")
        pinned = pins.get(name)
        if pinned is None:
            violations[name] = "not pinned"
        elif req.specifier and not req.specifier.contains(
            Version(pinned), prereleases=True
        ):
            violations[name] = f"pin {pinned} violates '{req.specifier}'"
    assert not violations, f"run `make lock`: {violations}"


def test_dev_lock_agrees_with_runtime_lock():
    runtime = _pinned(BACKEND / "requirements.txt")
    dev = _pinned(BACKEND / "requirements.test.txt")
    conflicts = {
        name: (version, dev[name])
        for name, version in runtime.items()
        if name in dev and dev[name] != version
    }
    assert not conflicts, f"run `make lock`: dev/runtime pin conflicts {conflicts}"
