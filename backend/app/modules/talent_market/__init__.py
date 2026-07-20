"""Internal talent market — surfaces employees against open needs and grades.

Aggregates competence, grade, and assessment data into ranked matches, gap
analyses, and readiness views for internal mobility.

Public surface: import from `talent_market.service`, `talent_market.schemas`,
and `talent_market.models`. Names prefixed with `_` are module-internal —
cross-module callers should not deep-import them; promote a shared helper
instead.
"""
