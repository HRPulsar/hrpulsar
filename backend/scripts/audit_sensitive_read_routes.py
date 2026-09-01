"""HRP-637: list every GET route whose payload can carry grade / salary keys.

Built after a review found the ticket's fix bypassable through a route nobody
had enumerated: the guards went on the routes the ticket named, and
``GET /dictionaries/items/{id}/usage`` — which names neither positions nor
specializations — still answered the exact "grade -> positions" map to any
member of the workspace.

Walking ``response_model`` beats grepping because it follows nested models
into payloads whose own module never mentions a position. Run it before
assuming a new route is covered, and reconcile the output against the route
table in ``docs/core/docs/rbac.md``:

    cd backend && ../.venv/bin/python scripts/audit_sensitive_read_routes.py

Every line marked BARE AUTH is a route readable by any authenticated member;
that is not automatically a leak, but it is automatically a decision.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from pydantic import BaseModel  # noqa: E402

SENSITIVE = {
    "grade_id",
    "grade_title",
    "specialization_id",
    "specialization_title",
    "grade_specialization_id",
    "salary_min",
    "salary_max",
    "salary_currency",
}


def fields(model, seen=None, depth=0) -> set[str]:
    """Field names of a pydantic model, following containers and nesting."""
    if depth > 6:
        return set()
    seen = seen or set()
    out: set[str] = set()
    if getattr(model, "__origin__", None) is not None:
        for arg in getattr(model, "__args__", ()):
            out |= fields(arg, seen, depth + 1)
        return out
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        return out
    if model in seen:
        return out
    seen.add(model)
    for name, f in model.model_fields.items():
        out.add(name)
        out |= fields(f.annotation, seen, depth + 1)
    return out


def gate(route: APIRoute) -> str:
    names: list[str] = []

    def walk(dep):
        call = getattr(dep, "call", None)
        if call is not None:
            names.append(getattr(call, "__qualname__", getattr(call, "__name__", "")))
        for sub in getattr(dep, "dependencies", []):
            walk(sub)

    walk(route.dependant)
    if any("require_role" in n for n in names):
        return "require_role"
    if any("get_current_user" in n for n in names):
        return "get_current_user"
    if any("api_key" in n.lower() for n in names):
        return "api_key"
    return "OPEN/other"


def main() -> int:
    rows = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or "GET" not in r.methods:
            continue
        hit = SENSITIVE & (fields(r.response_model) if r.response_model else set())
        if hit:
            rows.append((gate(r), r.path, sorted(hit)))
    rows.sort(key=lambda x: (x[0] != "get_current_user", x[1]))
    print(f"{len(rows)} GET routes carry sensitive keys\n")
    for g, path, hit_keys in rows:
        mark = "  <-- BARE AUTH" if g == "get_current_user" else ""
        print(f"[{g:16}] {path}{mark}")
        print(f"{'':19} {', '.join(hit_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
