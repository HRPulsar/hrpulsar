"""Audit coverage scanner — every mutating recruitment service function
must be either in AUDITED or AUDIT_EXEMPT. Mirrors the billing coverage
scanner in ``tests/unit/ee/test_billing_coverage.py``.
"""

import ast
import importlib
from pathlib import Path

from app.modules.recruitment.audit_registry import AUDIT_EXEMPT, AUDITED

MUTATION_PATTERNS = {"db.add", "db.delete", "await db.commit", "setattr"}

# Modules that the audit decorator targets (or explicitly exempts). The
# scanner walks each one and ensures every mutating public function is
# declared. Mirrors the recruitment subset of ``SERVICE_MODULES`` in the
# billing coverage scanner.
SERVICE_MODULES = [
    "app.modules.recruitment.service",
    # project-review #7 split of the former god-service:
    "app.modules.recruitment.common",
    "app.modules.recruitment.vacancy_service",
    "app.modules.recruitment.vacancy_profile_service",
    "app.modules.recruitment.candidate_service",
    "app.modules.recruitment.assessment_service",
    "app.modules.recruitment.interview_service",
    "app.modules.recruitment.consent_service",
    "app.modules.recruitment.report_service",
    "app.modules.recruitment.settings_service",
    "app.modules.recruitment.gdpr_service",
    "app.modules.recruitment.audit_service",
    "app.modules.recruitment.onboarding_service",
    "app.modules.recruitment.share_service",
    # HRP-204: resume-only / top-up / bulk AI analysis.
    "app.modules.recruitment.resume_analysis_service",
]


def _audited_keys() -> set[str]:
    result: set[str] = set()
    for module_path, entries in AUDITED.items():
        for func_name, _ in entries:
            result.add(f"{module_path}:{func_name}")
    return result


def _get_async_functions(module_path: str) -> list[str]:
    module = importlib.import_module(module_path)
    source_file = Path(module.__file__)
    tree = ast.parse(source_file.read_text())
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_")
    ]


def _is_read_only(module_path: str, func_name: str) -> bool:
    module = importlib.import_module(module_path)
    source_file = Path(module.__file__)
    source = source_file.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            func_source = ast.get_source_segment(source, node) or ""
            if func_name.startswith(("list_", "get_", "search_")):
                return True
            return all(pattern not in func_source for pattern in MUTATION_PATTERNS)
    return True


class TestAuditCoverage:
    def test_all_mutating_functions_declared(self):
        audited = _audited_keys()
        missing: list[str] = []

        for module_path in SERVICE_MODULES:
            funcs = _get_async_functions(module_path)
            for func_name in funcs:
                key = f"{module_path}:{func_name}"
                if key in audited or key in AUDIT_EXEMPT:
                    continue
                if _is_read_only(module_path, func_name):
                    continue
                missing.append(key)

        assert missing == [], (
            "Mutating recruitment functions without audit declaration:\n"
            + "\n".join(f"  - {m}" for m in sorted(missing))
            + "\n\nAdd to AUDITED or AUDIT_EXEMPT in audit_registry.py."
        )

    def test_audited_functions_exist(self):
        for module_path, entries in AUDITED.items():
            module = importlib.import_module(module_path)
            for func_name, _ in entries:
                assert hasattr(module, func_name), (
                    f"AUDITED references {module_path}.{func_name} but it does not exist"
                )

    def test_exempt_functions_exist(self):
        for key in AUDIT_EXEMPT:
            module_path, func_name = key.rsplit(":", 1)
            module = importlib.import_module(module_path)
            assert getattr(module, func_name, None) is not None, (
                f"AUDIT_EXEMPT references {key} but it does not exist"
            )

    def test_no_overlap(self):
        audited = _audited_keys()
        overlap = audited & AUDIT_EXEMPT
        assert overlap == set(), (
            f"Functions in both AUDITED and AUDIT_EXEMPT: {overlap}"
        )
