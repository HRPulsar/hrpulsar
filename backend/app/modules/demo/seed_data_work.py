"""Work-design fixtures for the demo seed (HRP-746 / W6).

Coverage is the only surface of the demo that opened empty: the seed laid
down people, competences and assessments but no work to cover, so a demo
visitor met the cold-start screen on the one page the primitives story is
about. Three broken-down containers fix that - two processes and one
initiative - picked so the Coverage tab shows every verdict the arithmetic
can produce (``coverage.py`` §5.2) against the company the rest of the
seed builds; a fourth is left for the visitor to break down. HRP-1193 gave
all four the descriptions and goals the Russian demo is shown with, and
the steps follow those descriptions:

* ``customer_requests`` - a request comes in through any channel, is
  registered, qualified and routed to a specialist, who clarifies, solves,
  keeps the customer informed and closes it; a rating request follows.
  Registering, qualifying, routing, the knowledge-base lookup and the
  closing are strong codes on work nobody signs for, so they move to an
  agent whole; the replies are drafted and sent under review. It carries
  the seed's only boundary step (B4, showing the customer the fix hands
  on): out of scope by design. And one judgement nobody in the company is
  currently assessed for - the disputed invoice that accounting decides -
  the seed's ``hire`` gap. Per-step ``runs_per_year`` differs on purpose:
  every request is registered, one in five reaches an engineer, a handful
  a year are about money.
* ``management_reporting`` - a monthly cycle (``runs_per_year=12``).
  Exporting, checking, handing over, reconciling and tabling the numbers is
  half of the hours, and all of it moves to an agent; the reports and the
  explanations are drafted under review; the approval, the meeting and the
  call on the strategy stay with the leadership. No step of it may be left
  open: at twelve runs a year every gap would read as ``agency``.
* ``iso27001`` - an initiative, not a process: it runs once
  (``runs_per_year=1``) and its unclosed step (the internal audit) falls to
  ``agency`` through the §5.1 suggestion rather than a hand-set label. A
  certification project is what a company of this size actually outsources.
* ``customer_onboarding`` - a process with a description and no steps
  (HRP-1176): what ``/coverage/new`` leaves behind before the first
  breakdown. The Coverage start route opens it, so the visitor runs
  "Generate steps" on a page that really offers it. Its ``preset_steps``
  are what that run returns while the text is the seeded one (HRP-1208,
  :func:`preset_breakdown`): the demo shows the result at once instead of
  two minutes of a model call. One of them is a ``hire`` gap - the call on
  whether the launch is complete - so the route's next step, opening a
  hire need, can be done on the steps just generated.

Both processes are picked so that "moves to an agent" is at least 30 % of
their yearly hours (HRP-870): the demo has to show the benefit. The pair
they replaced - onboarding a hire, responding to a production incident -
was mostly review and judgement, under 15 % of its hours moving to an
agent, so a visitor opened Coverage on a number that argued against it.
``test_demo_seed_work`` pins the share with the arithmetic of
``coverage.compute``, not by eye.

``DEMO_AGENTS`` (HRP-1194) are the tools the company already runs, the
rows "I already use this" writes - a name and an agent type. Without them
"Already automated" read 0 % on every process. Two types of the ones the
steps call for, so some of the work is automated today and the rest is
still to do.

``COMPETENCE_PRIMITIVES`` is the other half. The human layer of coverage
reads ``competence_primitives``, which is written by an LLM mapping run;
without it every step would report "nobody here can do this" while the
demo tenant is full of engineers. The demo has avoided live LLM calls
since HRP-276, so the mapping is authored here and seeded as
``reviewed`` - the same shape a company gets after confirming the AI's
suggestion, and a status the next mapping run will not overwrite.

Hours are the author's estimate for a company of this size, as in
``work/_examples.py``; the point is a believable ROI panel, not a
benchmark. English is the single source - ``seed_i18n`` translates
``title`` / ``description`` / ``goal`` / ``name`` at clone time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
# Agents the company already uses (HRP-1194)
# ---------------------------------------------------------------------------
#
# Matched to steps by codes like any registered agent (``coverage._match_agent``);
# ``pack`` is the built-in agent type's code. The names sort the same way in
# every seed locale, so the step both agents could take goes to the same one.

DEMO_AGENTS: list[dict] = [
    {
        "name": "Customer chatbot",
        "pack": "scripted_dialogue",
        "category": "chat",
        "data_classification": "customer_data",
    },
    {
        "name": "Scheduler",
        "pack": "coordinator",
        "category": "agent",
        "data_classification": "internal",
    },
]


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
            "The process starts when a customer's request arrives through any "
            "channel (phone, email, the website chat, messengers), where the "
            "system registers it automatically and gives it a unique number. "
            "Then comes the first qualification: an operator determines the "
            "topic of the question and its urgency and sends the request to "
            "the right specialist (for example, technical support, sales or "
            "accounting). The specialist contacts the customer, clarifies the "
            "details of the problem and does what is needed to solve it. If "
            "the question needs a long investigation, the customer is told "
            "the timeline and the current status. Once the problem is solved, "
            "the specialist records the result in the system and closes the "
            "request. At the end, the customer may be sent a request to rate "
            "the quality of the service, and all the data is kept in the "
            "database for later analysis."
        ),
        "goal": (
            "Resolve customers' questions quickly, well and on time, to keep "
            "their satisfaction and loyalty high."
        ),
        "steps": [
            {
                "title": "Register the request from any channel and give it a number",
                "description": (
                    "Who is asking, about what and through which channel, "
                    "taken from the call, the email or the chat into one record."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.1,
                "runs_per_year": 2400,
            },
            {
                "title": "Determine the topic and urgency of the request",
                "description": (
                    "Topic and priority by the published rules: what is "
                    "broken, for how many people, and how fast it is needed."
                ),
                "primitives": ["P3"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.05,
                "runs_per_year": 2400,
            },
            {
                "title": "Send the request to the right specialist",
                "description": (
                    "Technical support, sales or accounting — by the routing "
                    "table, not by who happens to be online."
                ),
                "primitives": ["P3"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.05,
                "runs_per_year": 2400,
            },
            {
                "title": "Contact the customer and clarify the details of the problem",
                "description": (
                    "The standard questions for this type of request: what "
                    "exactly happens, since when, on which account."
                ),
                "primitives": ["P12"],
                "responsibility": "reputational",
                "output_type": "draft",
                "hours_per_run": 0.15,
                "runs_per_year": 1200,
            },
            {
                "title": "Look for an answer in the knowledge base and past requests",
                "description": (
                    "The article or the closed request that matches, checked "
                    "against this customer's setup before it is trusted."
                ),
                "primitives": ["P1", "P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.15,
                "runs_per_year": 2400,
            },
            {
                "title": "Find the cause together with the engineer on duty",
                "description": (
                    "For what the knowledge base cannot answer: the "
                    "customer's report, the logs and the recent releases, "
                    "until the cause is clear."
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
                    "A screen share where the customer's admin makes the "
                    "change themselves, corrected as they go."
                ),
                "primitives": ["B4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 240,
            },
            {
                "title": "Tell the customer the timeline and the current status",
                "description": (
                    "When the investigation takes longer: what is being done, "
                    "when to expect an answer, and an update when the status "
                    "changes."
                ),
                "primitives": ["P5"],
                "responsibility": "reputational",
                "output_type": "external_change",
                "hours_per_run": 0.1,
                "runs_per_year": 480,
            },
            {
                "title": "Write the customer the solution",
                "description": (
                    "The answer for this customer: what happened, what to do, "
                    "and what we are doing about it."
                ),
                "primitives": ["P5"],
                "responsibility": "reputational",
                "output_type": "draft",
                "hours_per_run": 0.2,
                "runs_per_year": 2400,
            },
            {
                "title": "Decide on a disputed invoice: refund, discount or refusal",
                "description": (
                    "What the contract says, what the customer is worth to us "
                    "and what the precedent costs — and the call on the money."
                ),
                "primitives": ["P2", "P6"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 120,
            },
            {
                "title": "Record the result and close the request",
                "description": (
                    "What was done, the cause and the product area, by the "
                    "closing checklist, so the data is ready for analysis."
                ),
                "primitives": ["P1", "P3"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.1,
                "runs_per_year": 2400,
            },
            {
                "title": "Ask the customer to rate the service",
                "description": (
                    "The survey goes out after closing, a reminder follows if "
                    "there is no answer, and the score lands on the request."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.02,
                "runs_per_year": 2400,
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
            "The process starts at the end of the calendar month, when the "
            "departments (sales, marketing, production, finance) export the "
            "primary data from their own systems (CRM, ERP, accounting). The "
            "data is checked for completeness and correctness and then handed "
            "over to the analytics team or the finance department. The "
            "specialists consolidate the information, resolve the "
            "discrepancies between the systems and bring all the figures into "
            "single tables. From the collected data they build reports with "
            "the key metrics (KPIs), an analysis of the deviations from the "
            "plan and the trends. The prepared report pack is then reviewed "
            "by the middle managers and approved by the top management. The "
            "final documents are presented at a meeting and sent to the "
            "stakeholders, who use them for further management decisions and "
            "to adjust the strategy for the next period."
        ),
        "goal": (
            "Give the company's leadership a complete and reliable picture of "
            "the month's results, so that management decisions are well "
            "founded and the business strategy is adjusted in time."
        ),
        "steps": [
            {
                "title": "Export the month's primary data from CRM, ERP and accounting",
                "description": (
                    "Sales, marketing, production and finance figures, each "
                    "out of the system it lives in."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 6,
                "runs_per_year": 12,
            },
            {
                "title": "Check the data for completeness and correctness",
                "description": (
                    "Every department and every period in place, totals that "
                    "add up, no empty or duplicated rows."
                ),
                "primitives": ["P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 4,
                "runs_per_year": 12,
            },
            {
                "title": "Hand the data over to the analytics team or finance",
                "description": (
                    "Who has handed over their data and who has not, with a "
                    "reminder to the late ones."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 12,
            },
            {
                "title": "Reconcile the figures between the systems",
                "description": (
                    "Every number that appears in two systems compared, and "
                    "each discrepancy resolved with its owner."
                ),
                "primitives": ["P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 6,
                "runs_per_year": 12,
            },
            {
                "title": "Bring all the figures into single tables",
                "description": (
                    "One set of tables in the agreed structure, each metric "
                    "computed the way its definition says."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 4,
                "runs_per_year": 12,
            },
            {
                "title": "Build the KPI reports",
                "description": (
                    "The key metrics against the plan, in the layout the "
                    "leadership already knows how to read."
                ),
                "primitives": ["P5"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 4,
                "runs_per_year": 12,
            },
            {
                "title": "Explain the deviations from the plan and the trends",
                "description": (
                    "The deals, releases, hires and outages behind every "
                    "figure that moved, until the explanation holds."
                ),
                "primitives": ["P4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 4,
                "runs_per_year": 12,
            },
            {
                "title": "Have the middle managers review the report pack",
                "description": (
                    "Each manager checks the figures of their area against "
                    "what they know happened in the month."
                ),
                "primitives": ["P2"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 3,
                "runs_per_year": 12,
            },
            {
                "title": "Approve the report pack",
                "description": (
                    "The top management reads the pack and signs it off as "
                    "the company's official numbers for the month."
                ),
                "primitives": ["P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 12,
            },
            {
                "title": "Present the results at the meeting",
                "description": (
                    "The leadership walks through the same numbers together "
                    "and agrees what to do about them."
                ),
                "primitives": ["P8"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 1.5,
                "runs_per_year": 12,
            },
            {
                "title": "Send the final documents to the stakeholders",
                "description": (
                    "The agreed list, the agreed day, and a confirmation that "
                    "it arrived."
                ),
                "primitives": ["P11"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 12,
            },
            {
                "title": "Decide how to adjust the strategy for the next period",
                "description": (
                    "What the month means for the plan: what to keep, what to "
                    "change, and who does it."
                ),
                "primitives": ["P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 2,
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
            "Getting ISO 27001 certified starts with defining the boundaries "
            "of the security management system and analysing the company's "
            "current state to find the weak spots. Then the internal "
            "documentation is written: the security rules, the risk "
            "assessment method and the information protection plan. Next, "
            "the company puts the necessary technical and organisational "
            "controls in place (for example, access settings, encryption, "
            "rules for employees), trains the staff and collects the evidence "
            "that all the processes work. Before the external auditors are "
            "invited, an internal audit and a readiness review by the "
            "management are mandatory. After that, the company applies to an "
            "accredited certification body, which first examines the "
            "submitted documents (stage 1 of the audit) and then comes for an "
            "on-site audit (stage 2). Once every check is passed, the company "
            "receives a certificate valid for three years; to keep it, the "
            "company passes a surveillance audit every year and renews the "
            "certificate every three years."
        ),
        "goal": (
            "Officially confirm that the company meets the international "
            "information security standard (ISO 27001), to guarantee reliable "
            "data protection, raise the trust of customers and partners, and "
            "gain a competitive advantage in the market."
        ),
        "steps": [
            {
                "title": "Define the boundaries of the security system",
                "description": (
                    "Which systems, data, offices and suppliers are in scope, "
                    "out of the architecture docs, the contracts and the "
                    "vendor list."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 40,
                "runs_per_year": 1,
            },
            {
                "title": "Analyse the current state and find the weak spots",
                "description": (
                    "Every requirement of the standard against what the "
                    "company actually does today, with the gaps written down."
                ),
                "primitives": ["P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 60,
                "runs_per_year": 1,
            },
            {
                "title": "Write the security rules and the risk assessment method",
                "description": (
                    "The policy set and the method of scoring risks, in the "
                    "wording an auditor expects."
                ),
                "primitives": ["P5"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 80,
                "runs_per_year": 1,
            },
            {
                "title": "Assess the risks and approve the protection plan",
                "description": (
                    "Which risks we accept, which we reduce and which we "
                    "transfer: a business call, signed by the owner."
                ),
                "primitives": ["P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 32,
                "runs_per_year": 1,
            },
            {
                "title": "Set up the technical controls",
                "description": (
                    "Access settings, encryption, logging, backup and restore "
                    "— the ones the analysis found missing."
                ),
                "primitives": ["P9"],
                "responsibility": "none",
                "output_type": "external_change",
                "hours_per_run": 120,
                "runs_per_year": 1,
            },
            {
                "title": "Introduce the rules for employees and train the staff",
                "description": (
                    "Everyone gets the rules and the course, reminders go "
                    "out, and the completion record is chased until it is "
                    "whole."
                ),
                "primitives": ["P11"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 16,
                "runs_per_year": 1,
            },
            {
                "title": "Collect the evidence that the processes work",
                "description": (
                    "Screenshots, exports, tickets and logs, filed against "
                    "the requirement they prove."
                ),
                "primitives": ["P1", "P2"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 48,
                "runs_per_year": 1,
            },
            {
                "title": "Run the internal audit",
                "description": (
                    "An independent pass over the evidence, and a verdict on "
                    "whether each control really works."
                ),
                "primitives": ["P2", "P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 40,
                "runs_per_year": 1,
            },
            {
                "title": "Hold the management readiness review",
                "description": (
                    "The audit findings, the open issues and the resources, "
                    "settled into decisions the leadership stands behind."
                ),
                "primitives": ["P8"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 8,
                "runs_per_year": 1,
            },
            {
                "title": "Apply to an accredited certification body",
                "description": (
                    "The application form filled in from our scope, policies "
                    "and evidence, and sent with the documents."
                ),
                "primitives": ["P1"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 6,
                "runs_per_year": 1,
            },
            {
                "title": "Pass stage 1: the auditor's review of the documents",
                "description": (
                    "The auditor's questions about the documents, about work "
                    "we have to explain rather than recite."
                ),
                "primitives": ["P7"],
                "responsibility": "regulatory",
                "output_type": "external_change",
                "hours_per_run": 16,
                "runs_per_year": 1,
            },
            {
                "title": "Pass stage 2: the on-site audit",
                "description": (
                    "The auditors on site, talking to the people who run the "
                    "controls and looking at how the work is done."
                ),
                "primitives": ["P7"],
                "responsibility": "regulatory",
                "output_type": "external_change",
                "hours_per_run": 24,
                "runs_per_year": 1,
            },
            {
                "title": "Plan the annual surveillance audits and the renewal",
                "description": (
                    "A surveillance audit every year and the recertification "
                    "in three years — on the calendar, not in someone's memory."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 8,
                "runs_per_year": 1,
            },
        ],
    },
    {
        "key": "customer_onboarding",
        "type": "process",
        # Not broken down yet, on purpose (HRP-1176): status and source are
        # what ``work.service.create_container`` writes for a process typed
        # in by hand, and the seeder stores no summary for it.
        "status": "draft",
        "source": "manual",
        "gap_default_label": "hire",
        "title": "Onboarding a new customer",
        "description": (
            "Onboarding a new customer starts when the data about the closed "
            "deal is handed over and a card is created in the CRM; within 24 "
            "hours comes the first contact, with a welcome letter and the "
            "implementation plan. Then a kick-off meeting is held to get to "
            "know each other, clarify the goals and draw up an individual "
            "launch checklist, from which the working account is created, "
            "access is issued and the basic settings of the system are "
            "configured. Next, the first training demo is run for the "
            "customer's staff, after which the customer takes the first "
            "practical steps in the system on their own under a curator's "
            "supervision. Alongside this, the customer is introduced to the "
            "rules for contacting support and given access to the knowledge "
            "base, and two weeks after the launch a check-in call is held to "
            "collect feedback and resolve the difficulties that came up. The "
            "process ends with the first invoice issued under the contract, "
            "the customer moved to the “Active” status and handed "
            "over to regular service."
        ),
        "goal": (
            "Move a new customer from “buyer” to “active "
            "user” quickly and painlessly, helping them learn the "
            "product, get the first value out of it and build loyalty to the "
            "company."
        ),
        "steps": [],
        # HRP-1208: what "Generate steps" returns at once while the
        # description and the goal are the seeded ones - see
        # ``preset_breakdown``. Written by the rules of the steps above.
        "preset_steps": [
            {
                "title": "Create the customer card in the CRM from the closed deal",
                "description": (
                    "Company, contacts, plan and contract terms, taken from "
                    "the deal sales handed over."
                ),
                "primitives": ["P1"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 60,
            },
            {
                "title": "Send the welcome letter and the implementation plan within 24 hours",
                "description": (
                    "The first contact: who the customer's curator is, what "
                    "happens next and by when."
                ),
                "primitives": ["P5"],
                "responsibility": "reputational",
                "output_type": "external_change",
                "hours_per_run": 1,
                "runs_per_year": 60,
            },
            {
                "title": "Hold the kick-off meeting and clarify the goals",
                "description": (
                    "Getting to know the customer's team: what they want from "
                    "the product and what success looks like for them."
                ),
                "primitives": ["P7"],
                "responsibility": "reputational",
                "output_type": "draft",
                "hours_per_run": 1.5,
                "runs_per_year": 60,
            },
            {
                "title": "Draw up the individual launch checklist",
                "description": (
                    "What needs to be configured, imported and trained for "
                    "this customer, out of the kick-off notes."
                ),
                "primitives": ["P5"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 1,
                "runs_per_year": 60,
            },
            {
                "title": "Create the account, issue access and configure the basic settings",
                "description": (
                    "The workspace, the users and their roles, and the "
                    "settings from the checklist."
                ),
                "primitives": ["P9"],
                "responsibility": "none",
                "output_type": "external_change",
                "hours_per_run": 3,
                "runs_per_year": 60,
            },
            {
                "title": "Run the first training demo for the customer's staff",
                "description": (
                    "A live demo on the customer's own data, prepared for "
                    "their tasks, with questions answered on the spot."
                ),
                "primitives": ["P5", "B4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 60,
            },
            {
                "title": "Supervise the customer's first practical steps in the system",
                "description": (
                    "The customer does the first real tasks themselves, and "
                    "the curator corrects them as they go."
                ),
                "primitives": ["B4"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 2,
                "runs_per_year": 60,
            },
            {
                "title": "Introduce the support rules and give access to the knowledge base",
                "description": (
                    "How and where to ask for help, what answer times to "
                    "expect, and a login to the knowledge base."
                ),
                "primitives": ["P5"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 60,
            },
            {
                "title": "Schedule the check-in call two weeks after the launch",
                "description": (
                    "The date on both calendars and a reminder the day before."
                ),
                "primitives": ["P11"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.1,
                "runs_per_year": 60,
            },
            {
                "title": "Hold the check-in call: collect feedback and resolve the difficulties",
                "description": (
                    "What works, what gets in the way, and what we fix for "
                    "the customer and by when."
                ),
                "primitives": ["P7"],
                "responsibility": "reputational",
                "output_type": "draft",
                "hours_per_run": 1,
                "runs_per_year": 60,
            },
            {
                "title": "Issue the first invoice under the contract",
                "description": (
                    "The amount, the period and the details from the "
                    "contract, checked before it goes out."
                ),
                "primitives": ["P1", "P2"],
                "responsibility": "formal",
                "output_type": "external_change",
                "hours_per_run": 0.5,
                "runs_per_year": 60,
            },
            {
                # The preset's ``hire`` gap, as the disputed invoice is in
                # ``customer_requests``: the Coverage route's hire step can
                # be done on the steps just generated.
                "title": "Decide whether the launch is complete or needs more time",
                "description": (
                    "What on the checklist is done, what is not and what it "
                    "risks — and the call: the customer goes to “Active” "
                    "or the launch is extended."
                ),
                "primitives": ["P2", "P6"],
                "responsibility": "formal",
                "output_type": "draft",
                "hours_per_run": 0.5,
                "runs_per_year": 60,
            },
            {
                "title": "Move the customer to “Active” and hand them over to regular service",
                "description": (
                    "The status changed in the CRM and the account assigned "
                    "to the support team by the rota."
                ),
                "primitives": ["P3"],
                "responsibility": "none",
                "output_type": "draft",
                "hours_per_run": 0.3,
                "runs_per_year": 60,
            },
        ],
    },
]


def _same_text(a: object, b: object) -> bool:
    """Equal after whitespace normalisation: a trailing space or a line
    break pasted back in is not an edit of the process."""
    return " ".join(str(a or "").split()) == " ".join(str(b or "").split())


def preset_breakdown(container: Mapping[str, Any], language: str) -> dict | None:
    """HRP-1208: the prepared breakdown of a seeded process whose
    description and goal are still the ones the seed wrote in ``language``
    (the tenant's content language), in the payload shape the decomposition
    worker writes; None for any other text. The caller decides who gets it
    - the demo sandbox only, never a cache of other companies' breakdowns."""
    from app.modules.demo.seed_i18n import localize

    for spec in WORK_CONTAINERS:
        if not spec.get("preset_steps"):
            continue
        local = localize(spec, language)
        if _same_text(container.get("description"), local["description"]) and (
            _same_text(container.get("goal"), local["goal"])
        ):
            return {
                "steps": [
                    {**step, "evidence": [], "first_pass_codes": step["primitives"]}
                    for step in local["preset_steps"]
                ]
            }
    return None
