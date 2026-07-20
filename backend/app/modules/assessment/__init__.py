"""360-degree assessments, CPA (competence proficiency assessment), and PDP.

Owns assessment campaigns, per-respondent forms, score aggregation, and the
detailed-results computation consumed by the employee card and talent market.

Public surface: import from `assessment.service`, `assessment.schemas`, and
`assessment.models`. Names prefixed with `_` are module-internal — cross-module
callers should not deep-import them; promote a shared helper instead.
"""
