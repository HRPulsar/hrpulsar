"""AI-powered competence generation sessions.

Backend for the "Generate with AI" flow on the competence library page.
A session represents one user-initiated generation request: scope, base
snapshot, LLM payload, per-node selection state, and lifecycle.

The Celery worker (`tasks.run_generation_session`) consumes a pending
session, builds the prompt, calls the LLM with a JSON-Schema constraint,
and stores the normalized payload back on the row. Endpoints under
`/api/competence-generation/*` then let the user inspect, refine, and
apply the result.
"""
