"""Work-design fixtures for the demo seed (HRP-746 / W6).

Coverage is the only surface of the demo that opened empty: the seed laid
down people, competences and assessments but no work to cover, so a demo
visitor met the cold-start screen on the one page the primitives story is
about. Three containers fix that — two processes and one initiative —
picked so the Coverage tab shows every verdict the arithmetic can produce
(``coverage.py`` §5.2) against the company the rest of the seed builds:

* ``customer_requests`` — Go-to-Market. Intake, classification, routing
  and the knowledge-base lookup are strong codes on work nobody signs for,
  so they move to an agent whole; the reply is drafted and sent under
  review; the angry call and the refund stay with people. It carries the
  seed's only boundary step (B4, showing the customer the fix hands on):
  out of scope by design. And one legal judgement nobody in the company is
  currently assessed for — the seed's ``hire`` gap. Per-step
  ``runs_per_year`` differs on purpose: every request is classified, one
  in five reaches an engineer, a handful a year are about personal data.
* ``management_reporting`` — a monthly cycle (``runs_per_year=12``).
  Collecting, reconciling and checking the numbers is half of the hours,
  and all of it moves to an agent; the commentary is drafted under review; the
  call on what the month means stays with the head of the function.
* ``iso27001`` — an initiative, not a process: it runs once
  (``runs_per_year=1``) and its unclosed step falls to ``agency`` through
  the §5.1 suggestion rather than a hand-set label. A certification
  project is what a company of this size actually outsources.

Both processes are picked so that "moves to an agent" is at least 30 % of
their yearly hours (HRP-870): the demo has to show the benefit. The pair
they replaced - onboarding a hire, responding to a production incident -
was mostly review and judgement, under 15 % of its hours moving to an
agent, so a visitor opened Coverage on a number that argued against it.
``test_demo_seed_work`` pins the share with the arithmetic of
``coverage.compute``, not by eye.

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
    # Qualifying an opportunity by published criteria is rule-based
    # classification; it is also what sorting an inbound queue is, and the
    # sales floor is who does that here today (HRP-870).
    "c-sales-discovery": ["P1", "P3", "P7"],
    # Knowing the product is checking a customer's case against how the
    # product really behaves, not only reciting it.
    "c-product-knowledge": ["P2", "P12"],
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
        "key": "customer_requests",
        "type": "process",
        "status": "active",
        "source": "ai",
        "gap_default_label": "hire",
        "title": "Handling inbound customer requests",
        "description": (
            "Requests reach us by email, by chat and through the form in the "
            "product. Each one is taken into a single record, classified and "
            "given a priority by the published rules, routed to the team that "
            "owns the product area, and answered from the knowledge base and "
            "the past requests where an answer exists. A reply is drafted in "
            "our tone, sent, and confirmed with the customer. What the "
            "knowledge base cannot answer goes to the engineer on duty; a "
            "customer who is stuck is shown the fix hands on, an angry one "
            "gets a call, a refund or a contract exception gets a decision, "
            "and a request about personal data gets a legal one. Closed "
            "requests are tagged with their cause, and the questions that "
            "keep coming back become knowledge-base articles."
        ),
        "goal": (
            "Every request answered within the agreed time, and the team's "
            "hours spent on the customers who need a person rather than on "
            "sorting the queue."
        ),
        "steps": [
            {
                "title": "Take the request into one record, whatever channel it came by",
                "description": (
                    "Who is asking, which account, which product area and "
                    "what they actually want, out of the free text of an "
                    "email, a chat or the form."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.1,
                "runs_per_year": 2400,
            },
            {
                "title": "Classify the request and set its priority",
                "description": (
                    "Type and priority by the published rules: what is "
                    "broken, for how many people, and on which plan."
                ),
                "primitives": ["P3"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.05,
                "runs_per_year": 2400,
            },
            {
                "title": "Route the request to the team that owns the product area",
                "description": (
                    "The queue the type and the product area point at, by "
                    "the routing table rather than by who happens to be online."
                ),
                "primitives": ["P3"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.05,
                "runs_per_year": 2400,
            },
            {
                "title": "Search the knowledge base and the past requests for an answer",
                "description": (
                    "The article or the closed request that matches, checked "
                    "against this customer's version and setup before it is "
                    "trusted."
                ),
                "primitives": ["P1", "P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.15,
                "runs_per_year": 2400,
            },
            {
                "title": "Draft the reply in our tone",
                "description": (
                    "The answer written for this customer: what happened, "
                    "what to do, and what we are doing about it."
                ),
                "primitives": ["P5"],
                "responsibility": "reputational",
                "output_type": "draft",
                "hours_per_run": 0.2,
                "runs_per_year": 2400,
            },
            {
                "title": "Send the reply and confirm that it solved the problem",
                "description": (
                    "The reply out, the follow-up at the agreed interval, and "
                    "the customer's yes or no recorded on the request."
                ),
                "primitives": ["P12"],
                "responsibility": "reputational",
                "output_type": "external_change",
                "hours_per_run": 0.1,
                "runs_per_year": 2400,
            },
            {
                "title": "Work out with the engineer on duty what is actually broken",
                "description": (
                    "For what the knowledge base cannot answer: the "
                    "customer's report, the logs and the recent releases, "
                    "until there is a cause rather than a symptom."
                ),
                "primitives": ["P4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.75,
                "runs_per_year": 480,
            },
            {
                "title": "Show the customer the fix hands on",
                "description": (
                    "A screen-share with the customer's admin doing the "
                    "setup themselves, corrected as they go, so the same "
                    "request does not come back next week."
                ),
                "primitives": ["B4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 240,
            },
            {
                "title": "Call the customer who is angry",
                "description": (
                    "A conversation with no script: what went wrong for "
                    "them, what they need to hear, and what we can promise."
                ),
                "primitives": ["P7"],
                "responsibility": "reputational",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 240,
            },
            {
                "title": "Decide on a refund, a credit or a contract exception",
                "description": (
                    "What the customer is worth, what the precedent costs, "
                    "and what the contract actually says."
                ),
                "primitives": ["P6"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 120,
            },
            {
                "title": "Decide whether a request is about personal data and what the law requires",
                "description": (
                    "Access, deletion and correction requests against the "
                    "regulation and its deadlines, and the call on what we "
                    "must hand over or erase."
                ),
                "primitives": ["P2", "P6"],
                "responsibility": "regulatory",
                "output_type": "external_change",
                "hours_per_run": 1,
                "runs_per_year": 24,
            },
            {
                "title": "Close the request and tag what caused it",
                "description": (
                    "Cause, product area and whether the knowledge base had "
                    "the answer, by the closing checklist."
                ),
                "primitives": ["P3"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.05,
                "runs_per_year": 2400,
            },
            {
                "title": "Turn the questions that keep coming back into knowledge-base articles",
                "description": (
                    "Once a month: the most repeated causes written up as "
                    "articles a customer can follow without us."
                ),
                "primitives": ["P5"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 3,
                "runs_per_year": 12,
            },
        ],
    },
    {
        "key": "management_reporting",
        "type": "process",
        "status": "active",
        "source": "ai",
        "gap_default_label": "hire",
        "title": "Monthly management reporting",
        "description": (
            "In the first week of every month the leadership gets one pack "
            "about the month before. The numbers are pulled out of billing, "
            "the CRM, the product analytics and the HR system, reconciled "
            "between the systems, and the owners are chased for what is "
            "missing or does not add up. The pack is assembled to the "
            "standing template and checked against last month's and against "
            "the metric definitions; the deviations from the plan are "
            "explained, the commentary is drafted, the head of the function "
            "reviews it and decides what it means for the quarter, the pack "
            "goes out to the agreed list, the leadership team walks through "
            "it, and the actions are filed."
        ),
        "goal": (
            "The pack on the table by the fifth working day, with the people "
            "who own the numbers spending their time on what the numbers "
            "mean rather than on collecting them."
        ),
        "steps": [
            {
                "title": "Pull the month's numbers out of the systems",
                "description": (
                    "Revenue and churn from billing, the pipeline from the "
                    "CRM, usage from the product analytics, headcount and "
                    "hiring from the HR system."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 6,
                "runs_per_year": 12,
            },
            {
                "title": "Reconcile the numbers between the systems",
                "description": (
                    "Billing against the CRM against the bank: every figure "
                    "that appears in two places, and the list of the ones "
                    "that disagree."
                ),
                "primitives": ["P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 5,
                "runs_per_year": 12,
            },
            {
                "title": "Chase the owners for what is missing or does not add up",
                "description": (
                    "Down the list of open figures, owner by owner, until "
                    "each one is confirmed or corrected."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 12,
            },
            {
                "title": "Assemble the pack to the standing template",
                "description": (
                    "Tables, charts and the one-page summary, in the layout "
                    "the leadership already knows how to read."
                ),
                "primitives": ["P9"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 4,
                "runs_per_year": 12,
            },
            {
                "title": "Check the pack against last month's and the metric definitions",
                "description": (
                    "Every metric computed the way its definition says, and "
                    "every jump from last month either real or a mistake."
                ),
                "primitives": ["P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 12,
            },
            {
                "title": "Find what explains the deviations from the plan",
                "description": (
                    "The deals, the releases, the hires and the outages "
                    "behind each number that moved, until the story holds."
                ),
                "primitives": ["P4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 4,
                "runs_per_year": 12,
            },
            {
                "title": "Draft the commentary for the leadership",
                "description": (
                    "A page of plain language: what moved, why, and what to "
                    "watch next month."
                ),
                "primitives": ["P5"],
                "responsibility": "reputational",
                "output_type": "draft",
                "hours_per_run": 3,
                "runs_per_year": 12,
            },
            {
                "title": "Review the pack and decide what it means for the quarter",
                "description": (
                    "The head of the function reads the pack before anyone "
                    "else does and makes the call on the forecast."
                ),
                "primitives": ["P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 12,
            },
            {
                "title": "Send the pack to the leadership and the board list",
                "description": (
                    "The agreed recipients, the agreed day, and the "
                    "acknowledgement that it arrived."
                ),
                "primitives": ["P11"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 12,
            },
            {
                "title": "Walk the leadership team through the pack and agree the actions",
                "description": (
                    "Everyone's reading of the same numbers, argued down to "
                    "the few actions worth taking."
                ),
                "primitives": ["P8"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 1.5,
                "runs_per_year": 12,
            },
            {
                "title": "File the agreed actions with owners and due dates",
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
        "title": "Getting ISO 27001 certified",
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
