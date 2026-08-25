"""Guard: every role code a gate mentions is a role that actually exists.

HRP-617. Before this guard ``require_role(..., "hrd")`` looked like a gate
that let HR directors in, while the ``roles`` table had no such row — the
gate silently degraded to admin-only. The check walks the source (AST, not
grep, so a renamed helper still trips it) and compares every role code that
appears in a gate against the codes seeded by the migrations.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

# Codes seeded per-tenant or resolved at runtime rather than declared as a
# system role row — they are not expected in the migration seeds.
_NOT_A_ROLE_ROW: frozenset[str] = frozenset()


def _seeded_role_codes() -> set[str]:
    """Role codes any migration inserts into ``roles``.

    Matches the ``(gen_random_uuid(), 'Name', 'code'`` shape all four seed
    migrations use, tolerating the string concatenation in
    ``f1a2b3c4d5e6``.
    """
    pattern = re.compile(
        r"gen_random_uuid\(\),\s*(?:\"\s*\n\s*\")?'[^']+',\s*'([a-z_]+)'"
    )
    codes: set[str] = set()
    for path in MIGRATIONS_DIR.rglob("*.py"):
        source = path.read_text()
        if "INSERT INTO roles" not in source:
            continue
        codes.update(pattern.findall(source.replace("\n", " ")))
    return codes


def _string_items(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "frozenset"
    ):
        return (
            set().union(*(_string_items(a) for a in node.args)) if node.args else set()
        )
    return set()


def _gated_role_codes() -> dict[str, set[str]]:
    """Role codes per file: ``require_role`` literals + role-set constants."""
    found: dict[str, set[str]] = {}
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        codes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                )
                if name in {"require_role", "require_any_role"}:
                    codes.update(
                        a.value
                        for a in node.args
                        if isinstance(a, ast.Constant) and isinstance(a.value, str)
                    )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                if any(n.upper().endswith(("_ROLES", "_ROLE_CODES")) for n in names):
                    codes.update(_string_items(node.value) if node.value else set())
        if codes:
            found[str(path.relative_to(APP_DIR.parent))] = codes
    return found


def test_every_gated_role_code_is_seeded():
    seeded = _seeded_role_codes()
    assert {
        "admin",
        "manager",
        "employee",
        "recruiter",
        "hiring_manager",
        "platform_admin",
        "hr",
    } <= seeded

    unknown = {
        file: sorted(codes - seeded - _NOT_A_ROLE_ROW)
        for file, codes in _gated_role_codes().items()
        if codes - seeded - _NOT_A_ROLE_ROW
    }
    assert not unknown, f"gates reference role codes no migration seeds: {unknown}"


def test_hrd_is_gone():
    assert "hrd" not in {c for codes in _gated_role_codes().values() for c in codes}
