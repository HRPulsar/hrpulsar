"""Work-design fixtures for the demo seed (HRP-746 / W6).

Coverage is the only surface of the demo that opened empty: the seed laid
down people, competences and assessments but no work to cover, so a demo
visitor met the cold-start screen on the one page the primitives story is
about. Three containers fix that — two processes and one initiative —
picked so the Coverage tab shows every verdict the arithmetic can produce
(``coverage.py`` §5.2) against the company the rest of the seed builds:

* ``onboarding`` — People & Talent. Coordination-heavy, so the "this
  moves to an agent" bucket is not a theoretical one, and it carries the
  seed's only boundary step (B4, the buddy correcting mistakes as they
  happen): out of scope by design, and the largest single block of hours
  in the process. That contrast is the point of the boundary codes.
* ``incident`` — Platform. Investigation, a rollback call, a customer
  notification to an agreed script, and one regulatory judgement nobody
  in the company is currently assessed for — the seed's ``hire`` gap.
  Per-step ``runs_per_year`` differs on purpose: every incident is
  triaged, only the serious ones get a postmortem.
* ``iso27001`` — an initiative, not a process: it runs once
  (``runs_per_year=1``) and its unclosed step falls to ``agency`` through
  the §5.1 suggestion rather than a hand-set label. A certification
  project is what a company of this size actually outsources.

``COMPETENCE_PRIMITIVES`` is the other half. The human layer of coverage
reads ``competence_primitives``, which is written by an LLM mapping run;
without it every step would report "nobody here can do this" while the
demo tenant is full of engineers. The demo has avoided live LLM calls
since HRP-276, so the mapping is authored here and seeded as
``reviewed`` — the same shape a company gets after confirming the AI's
suggestion, and a status the next mapping run will not overwrite.

Hours are the author's estimate for a company of this size, as in
``work/_examples.py``; the point is a believable ROI panel, not a
benchmark. English is the single source — ``seed_i18n`` translates
``title`` / ``description`` / ``goal`` at clone time.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Competence → primitive mapping
# ---------------------------------------------------------------------------
#
# Keyed by the ``key`` slugs of ``seed_data_competences.COMPETENCES``.
# A competence absent from this map stays unmapped, exactly as it would
# after a real run that found no code for it — the coverage screen has a
# counter for those and the demo should not pretend the number is zero.

COMPETENCE_PRIMITIVES: dict[str, list[str]] = {
    # Engineering — building a thing from a specification, and finding out
    # why a running thing stopped behaving.
    "c-python": ["P9"],
    "c-fastapi": ["P9"],
    # Schemas and queries are an artifact built to a spec; EXPLAIN work is
    # an investigation. Deliberately not P2 — checking against a reference
    # is what the performance budget below is, not what SQL is.
    "c-postgres": ["P4", "P9"],
    "c-distributed": ["P4", "P9"],
    "c-typescript": ["P9"],
    "c-react": ["P9"],
    "c-web-perf": ["P2", "P4"],
    # Product & UX — talking to people outside the company and turning what
    # they said into something structured.
    "c-user-research": ["P1", "P7"],
    "c-roadmap": ["P6"],
    "c-design-systems": ["P9", "P13"],
    # Communication.
    "c-written": ["P5"],
    "c-async": ["P5", "P11"],
    "c-cross-fn": ["P8"],
    # Leadership. Mentoring is the one competence that maps to a boundary
    # code: in-the-moment correction of a person is B4 by definition.
    "c-mentoring": ["B4"],
    "c-hiring": ["P6", "P7"],
    "c-conflict": ["P8"],
    # AI literacy.
    "c-prompt": ["P5", "P9"],
    "c-ai-tools": ["P3", "P11"],
    "c-agentic": ["P9", "P11"],
    # Business.
    "c-customer-discovery": ["P1", "P7"],
    "c-okrs": ["P6", "P10"],
    "c-sales-discovery": ["P1", "P7"],
    "c-product-knowledge": ["P12"],
    "c-objection-handling": ["P7"],
}


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
#
# ``key`` is the idempotency handle (the seeder matches on title, the key
# is for tests and cross-references). Steps are seeded in list order;
# ``position`` is the index. ``state`` and ``status`` follow the container:
# an accepted breakdown is ``active`` with every step ``accepted``, a draft
# one keeps its steps ``system_suggested`` so the demo also shows the
# "accept this breakdown" affordance on a real list.

WORK_CONTAINERS: list[dict] = [
    {
        "key": "onboarding",
        "type": "process",
        "status": "active",
        "source": "ai",
        "gap_default_label": "hire",
        "title": "Onboarding a new hire",
        "description": (
            "Every new hire starts on a Monday. People Ops takes the signed "
            "offer and the personal data into the HR record, opens the "
            "accounts and the access the role needs, books the first week "
            "with the team, picks a buddy, briefs the hire on the security "
            "and data-handling rules, the manager agrees the 30/60/90 "
            "expectations, the buddy shows the day-to-day tools hands on, "
            "People Ops chases whatever is still missing, and after three "
            "months the manager runs the probation review and the outcome "
            "becomes a development plan."
        ),
        "goal": (
            "A new hire productive by the end of the first month, with no "
            "step of the process resting on somebody remembering it."
        ),
        "steps": [
            {
                "title": "Take the signed offer and the hire's data into the HR record",
                "description": (
                    "Contract, personal data, tax and bank details out of the "
                    "signed documents and into the employee record."
                ),
                "primitives": ["P1"],
                "responsibility": "regulatory",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 24,
            },
            {
                "title": "Open the accounts and the access the role needs",
                "description": (
                    "The access list of the role, ticket by ticket, with the "
                    "manager's approval where the system asks for one."
                ),
                "primitives": ["P11"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 1,
                "runs_per_year": 24,
            },
            {
                "title": "Book the first week with the team",
                "description": (
                    "Intro calls with the team, the manager, the People "
                    "Partner and the neighbouring divisions, around the "
                    "calendars that already exist."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 24,
            },
            {
                "title": "Pick the buddy for the first month",
                "description": (
                    "Who has the time, the patience and the overlap with what "
                    "the hire will be doing — a judgement about people, made "
                    "with the division head."
                ),
                "primitives": ["P6"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.25,
                "runs_per_year": 24,
            },
            {
                "title": "Brief the hire on the security and data-handling rules",
                "description": (
                    "The standard briefing, question by question, with the "
                    "acknowledgement recorded."
                ),
                "primitives": ["P12"],
                "responsibility": "regulatory",
                "output_type": "draft",
                "hours_per_run": 1,
                "runs_per_year": 24,
            },
            {
                "title": "Agree the 30/60/90 expectations with the manager",
                "description": (
                    "What the team, the manager and the People Partner each "
                    "expect by each checkpoint, argued down to one list."
                ),
                "primitives": ["P8"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 1,
                "runs_per_year": 24,
            },
            {
                "title": "Show the day-to-day tools hands on",
                "description": (
                    "The buddy sits with the hire through the first real "
                    "tasks and corrects the mistakes as they happen, before "
                    "the wrong habit sets in."
                ),
                "primitives": ["B4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 4,
                "runs_per_year": 24,
            },
            {
                "title": "Chase what is still missing at the end of week one",
                "description": (
                    "Equipment, access, signatures, the training that was not "
                    "completed — down the checklist until it is empty."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 24,
            },
            {
                "title": "Run the probation review against the 30/60/90",
                "description": (
                    "Read the evidence of three months and decide whether the "
                    "hire has passed probation."
                ),
                "primitives": ["P1", "P6"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 1.5,
                "runs_per_year": 24,
            },
            {
                "title": "Turn the outcome into a development plan",
                "description": (
                    "The review written up as goals, materials and dates the "
                    "hire and the manager both sign off."
                ),
                "primitives": ["P5"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 1,
                "runs_per_year": 24,
            },
        ],
    },
    {
        "key": "incident",
        "type": "process",
        "status": "active",
        "source": "ai",
        "gap_default_label": "hire",
        "title": "Production incident response",
        "description": (
            "An alert fires, or a customer reports that something is broken. "
            "The on-call engineer confirms the alert against the runbook, "
            "sets a severity and pages the right rota, opens the incident "
            "channel and keeps the timeline, works out what changed and why, "
            "decides between a rollback and a fix forward, applies it, keeps "
            "the status page and the affected customers informed to the "
            "agreed wording, confirms the system is healthy again, decides "
            "whether the incident is reportable, and for the serious ones "
            "writes the postmortem, walks the team through it and files the "
            "action items."
        ),
        "goal": (
            "Customer-visible downtime down, and the on-call engineer "
            "spending the night on the cause rather than on the paperwork "
            "around it."
        ),
        "steps": [
            {
                "title": "Confirm the alert against the runbook and the dashboards",
                "description": (
                    "Is this real, and is it the failure the runbook "
                    "describes or a different one."
                ),
                "primitives": ["P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.25,
                "runs_per_year": 60,
            },
            {
                "title": "Set the severity and page the right rota",
                "description": (
                    "Severity by the published criteria, then the rota the "
                    "severity and the affected service point at."
                ),
                "primitives": ["P3"],
                "responsibility": "none",
                "output_type": "external_change",
                "hours_per_run": 0.1,
                "runs_per_year": 60,
            },
            {
                "title": "Open the incident channel and keep the timeline",
                "description": (
                    "Channel, roles, the running log of what was done and "
                    "when, so the postmortem has something to read."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 60,
            },
            {
                "title": "Work out what changed and why",
                "description": (
                    "Logs, deploys, metrics and the customer's report, until "
                    "there is a hypothesis that explains all four."
                ),
                "primitives": ["P4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 60,
            },
            {
                "title": "Decide between a rollback and a fix forward",
                "description": (
                    "What each option costs, what it risks, and how long the "
                    "customer stays broken either way."
                ),
                "primitives": ["P6"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 60,
            },
            {
                "title": "Apply the fix or the rollback",
                "description": "The change itself, through the usual review and deploy.",
                "primitives": ["P9"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 1.5,
                "runs_per_year": 60,
            },
            {
                "title": "Keep the status page and the affected customers informed",
                "description": (
                    "The agreed wording, at the agreed intervals, to the "
                    "customers the incident actually touched."
                ),
                "primitives": ["P12"],
                "responsibility": "reputational",
                "output_type": "external_change",
                "hours_per_run": 0.75,
                "runs_per_year": 60,
            },
            {
                "title": "Confirm the system is healthy against the exit criteria",
                "description": (
                    "Every metric the severity's exit criteria name, back "
                    "inside its band and staying there."
                ),
                "primitives": ["P2"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 60,
            },
            {
                "title": "Decide whether the incident is reportable",
                "description": (
                    "Personal data, the contractual thresholds and the "
                    "notification deadlines, against what actually happened."
                ),
                "primitives": ["P2", "P6"],
                "responsibility": "regulatory",
                "output_type": "external_change",
                "hours_per_run": 1,
                "runs_per_year": 12,
            },
            {
                "title": "Write the postmortem",
                "description": (
                    "Timeline, cause, contributing factors and what made the "
                    "incident last as long as it did."
                ),
                "primitives": ["P4", "P5"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 3,
                "runs_per_year": 12,
            },
            {
                "title": "Walk the team through the postmortem and agree the actions",
                "description": (
                    "Everyone's reading of the same incident, argued down to "
                    "the few actions worth doing."
                ),
                "primitives": ["P8"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 1,
                "runs_per_year": 12,
            },
            {
                "title": "File the action items with owners and due dates",
                "description": (
                    "Into the tracker, with an owner and a date, and chased "
                    "until they close."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 12,
            },
        ],
    },
    {
        "key": "iso27001",
        "type": "initiative",
        # Left as a draft on purpose: the list then shows both states, and
        # the detail page shows the "accept this breakdown" path a demo
        # visitor would otherwise have to generate a container to reach.
        "status": "draft",
        "source": "ai",
        # A one-off project is outsourced, not hired for; the §5.1
        # suggestion says the same thing for every step here, but the
        # default has to be right for the ones that carry accountability.
        "gap_default_label": "agency",
        "title": "ISO 27001 certification",
        "description": (
            "Enterprise deals keep stalling on the security questionnaire, "
            "so we are getting certified. We map the scope and the data "
            "flows, run a gap analysis against the controls, assess the "
            "risks and agree the treatment, write the policies and the "
            "Statement of Applicability, build the technical controls we do "
            "not have, roll out awareness training, collect the evidence per "
            "control, run an internal audit, hold the management review, go "
            "through the external stage 1 and stage 2 audits, close the "
            "non-conformities and set up the surveillance cycle."
        ),
        "goal": (
            "Certificate in hand before the next enterprise renewal round, "
            "and the security questionnaire off the critical path of a deal."
        ),
        "steps": [
            {
                "title": "Map the scope: systems, data flows and third parties",
                "description": (
                    "What is in scope, what data moves where, and who else "
                    "touches it — out of the architecture docs, the contracts "
                    "and the vendor list."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 40,
                "runs_per_year": 1,
            },
            {
                "title": "Gap analysis against the controls",
                "description": (
                    "Every control against what the company actually does "
                    "today, and the difference written down."
                ),
                "primitives": ["P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 60,
                "runs_per_year": 1,
            },
            {
                "title": "Assess the risks and agree the treatment",
                "description": (
                    "Which risks we accept, which we mitigate and which we "
                    "transfer — a business call, signed by the owner."
                ),
                "primitives": ["P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 32,
                "runs_per_year": 1,
            },
            {
                "title": "Write the policies and the Statement of Applicability",
                "description": (
                    "The policy set and the statement, in the register the "
                    "standard expects and the wording an auditor reads."
                ),
                "primitives": ["P5"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 80,
                "runs_per_year": 1,
            },
            {
                "title": "Build the missing technical controls",
                "description": (
                    "Logging, access review, backup and restore, key "
                    "handling — the ones the gap analysis found missing."
                ),
                "primitives": ["P9"],
                "responsibility": "none",
                "output_type": "external_change",
                "hours_per_run": 120,
                "runs_per_year": 1,
            },
            {
                "title": "Roll out awareness training and confirm completion",
                "description": (
                    "Everyone assigned, reminded and chased until the "
                    "completion record is whole."
                ),
                "primitives": ["P11"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 16,
                "runs_per_year": 1,
            },
            {
                "title": "Collect the evidence for each control",
                "description": (
                    "Screenshots, exports, tickets and logs, pulled from the "
                    "systems and filed against the control they prove."
                ),
                "primitives": ["P1", "P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 48,
                "runs_per_year": 1,
            },
            {
                "title": "Internal audit against the controls",
                "description": (
                    "An independent pass over the evidence, and a judgement "
                    "on whether each control is genuinely operating."
                ),
                "primitives": ["P2", "P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 40,
                "runs_per_year": 1,
            },
            {
                "title": "Hold the management review",
                "description": (
                    "The findings, the objections and the resourcing, "
                    "resolved into decisions the leadership stands behind."
                ),
                "primitives": ["P8"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 8,
                "runs_per_year": 1,
            },
            {
                "title": "Go through the external stage 1 and stage 2 audits",
                "description": (
                    "The auditor's questions, on their terms, about work we "
                    "have to explain rather than recite."
                ),
                "primitives": ["P7"],
                "responsibility": "regulatory",
                "output_type": "external_change",
                "hours_per_run": 24,
                "runs_per_year": 1,
            },
            {
                "title": "Close the non-conformities from the audit report",
                "description": (
                    "Each finding fixed, the fix evidenced, and the evidence "
                    "back with the auditor."
                ),
                "primitives": ["P9"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 24,
                "runs_per_year": 1,
            },
            {
                "title": "Set up the surveillance cycle",
                "description": (
                    "Annual internal audit, quarterly access review, the "
                    "management review on the calendar — scheduled, not "
                    "remembered."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 8,
                "runs_per_year": 1,
            },
        ],
    },
]
