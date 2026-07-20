"""Recruitment sub-routers, split by resource (project-review #19).

Each module owns one cohesive slice of the recruitment REST surface and
exposes a ``router`` object; ``app.modules.recruitment.router`` aggregates
them into the single router mounted in ``app/main.py``. Import endpoints
through the aggregator, not from individual sub-modules.
"""
