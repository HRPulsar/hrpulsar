"""Few-shot examples for the decomposition prompt (HRP-755).

Six processes of the internal process library, translated by hand and
committed here because the library itself is Russian and lives in
``docs/``, which is neither shipped to the public repo nor allowed to leak
Cyrillic into ``backend/**`` (the sync guard). Chosen to cover the most
situations with the fewest examples (REFACTOR_PLAN section 4.2):

- ``legal-1-contract-review`` - office, document-driven, a step of pure
  accountability (signature) with no capability at all;
- ``4.4.2-goods-receipt`` - physical work, boundary codes B1-B3, a
  scheduled slot (P11), a record with content next to a physical step;
- ``11.2.2-kyc-cdd-onboarding`` - regulated end to end, a questionnaire
  (P12), monitoring on a schedule (P11);
- ``8.5.4-feature-development`` - engineering, P9, a release step of pure
  accountability;
- ``2.3.2-ab-test`` - experimental, P10;
- ``brand-1-rebranding`` - creative work accepted by taste (P13), a
  hands-on training at the launch (B4), external interviews (P7), a
  formal approval with no capability. It replaced ``hr-1-hiring``
  (HRP-961): the hiring loop added nothing the contract review does not
  show, and the corpus had no P13 and no B4.

Since HRP-961 the codes follow ``primitives/conventions.py`` (decisions of
2026-09-28, answers of 2026-09-29): P6 only for a choice the step itself
makes - named, the point of a go or no-go check, or a negotiated
concession; P11 only where the work is to follow up; an approval on the
merits is P6 and a signature under an earlier decision is nothing; a
physical step carries P1 only for a record with content of its own.
``test_conventions`` keeps
the rare codes (P11, P12, P13, B4) in the corpus.

The ``question`` is what a COO would type: the container fields. The
``answer`` is the library's own breakdown plus ``hours_per_run`` /
``runs_per_year``: the library carries no hours, so these are the
author's estimates for a typical company of that kind, there because the
rule asks the model for an estimate and a few-shot showing null would
teach the opposite (W6, decision 2026-09-11). They vary within a process
on purpose - a discrepancy step runs less often than the receipt it
belongs to. ``reversibility`` stays unset: the prompt gives it only when
the description states it. Everything stays English whatever the
tenant's content language - the language directive appended at run time
sets the output.
"""

from __future__ import annotations

# (question_dict, answer_dict)
EXAMPLES: list[tuple[dict, dict]] = [
    (
        {
            "type": "process",
            "title": "Contract review",
            "description": (
                "Sales sends us a counterparty's contract. Legal logs the request, "
                "a lawyer checks the draft against our playbook, marks what is "
                "non-standard and decides whether the deviations are acceptable for "
                "the deal, drafts the redlines, collects opinions from security, "
                "finance and procurement, negotiates with the counterparty and "
                "decides which concessions to trade, gets "
                "formal approval, the contract is signed by an authorised signatory "
                "and filed in the contract register."
            ),
            "goal": None,
        },
        {
            "steps": [
                {
                    "title": "Intake of the request through a structured form",
                    "primitives": ["P1"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 0.25,
                    "runs_per_year": 100,
                },
                {
                    "title": "Triage and reviewer assignment by risk",
                    "primitives": ["P3"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 0.25,
                    "runs_per_year": 100,
                },
                {
                    "title": "Check against the playbook, flag the non-standard clauses",
                    "primitives": ["P2"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 2,
                    "runs_per_year": 100,
                },
                {
                    "title": "Assess whether the deviations are acceptable for the deal",
                    "primitives": ["P6"],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 1,
                    "runs_per_year": 100,
                },
                {
                    "title": "Draft the redlines",
                    "primitives": ["P5"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 2,
                    "runs_per_year": 100,
                },
                {
                    "title": "Collect opinions from security, finance and procurement",
                    "primitives": ["P8"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 1.5,
                    "runs_per_year": 100,
                },
                {
                    "title": "Negotiate with the counterparty and choose the concessions",
                    "primitives": ["P7", "P6"],
                    "responsibility": "reputational",
                    "output_type": "external_change",
                    "hours_per_run": 3,
                    "runs_per_year": 100,
                },
                {
                    "title": "Formal approval with a rationale",
                    "primitives": ["P6"],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 0.5,
                    "runs_per_year": 100,
                },
                {
                    "title": "Signature by the authorised signatory",
                    "primitives": [],
                    "responsibility": "regulatory",
                    "output_type": "external_change",
                    "hours_per_run": 0.25,
                    "runs_per_year": 100,
                },
                {
                    "title": "Register the contract with its metadata",
                    "primitives": ["P1"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 0.25,
                    "runs_per_year": 100,
                },
            ]
        },
    ),
    (
        {
            "type": "process",
            "title": "Goods receipt at the warehouse",
            "description": (
                "Inbound deliveries arrive at the warehouse dock. We confirm the "
                "receiving slot and the paperwork, unload the trailer and check the "
                "seal, count and scan the pallets against the purchase order, "
                "inspect the goods for damage and put damaged ones on hold, sort "
                "out any discrepancy with the supplier, register the receipt with "
                "batches and expiry dates, label the goods and put them away to "
                "their storage locations."
            ),
            "goal": None,
        },
        {
            "steps": [
                {
                    "title": "Confirm the receiving window and documents (PO, ASN, dock slot)",
                    "primitives": ["P2", "P11"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 0.25,
                    "runs_per_year": 1000,
                },
                {
                    "title": "Unload into the receiving area, check the seal and the trailer",
                    "primitives": ["B3", "B2"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 1,
                    "runs_per_year": 1000,
                },
                {
                    "title": "Count and scan the items against the PO",
                    "primitives": ["P2", "B1"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 1,
                    "runs_per_year": 1000,
                },
                {
                    "title": "Inspect the goods, record damage, isolate to the hold area",
                    "primitives": ["B3"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 0.5,
                    "runs_per_year": 1000,
                },
                {
                    "title": "Resolve the discrepancy: accept partially, reject, or raise an exception",
                    "primitives": ["P3", "P6"],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 0.5,
                    "runs_per_year": 200,
                },
                {
                    "title": "Register the receipt in the system (batches, expiry dates, serial numbers)",
                    "primitives": ["P1"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 0.5,
                    "runs_per_year": 1000,
                },
                {
                    "title": "Label the goods and create the put-away task",
                    "primitives": ["P3"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 0.25,
                    "runs_per_year": 1000,
                },
                {
                    "title": "Put away to the storage location and confirm the location",
                    "primitives": ["B2"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 1,
                    "runs_per_year": 1000,
                },
            ]
        },
    ),
    (
        {
            "type": "process",
            "title": "KYC/CDD at account opening",
            "description": (
                "Before a new customer can open an account we run KYC. We collect "
                "identification data, verify identity against documents and "
                "external databases, for companies obtain and verify the beneficial "
                "owners, screen everyone against sanctions, PEP and adverse media "
                "lists, build a risk profile, decide whether to open the account or "
                "run enhanced due diligence, then keep monitoring transactions and "
                "escalate anything suspicious to the regulator."
            ),
            "goal": None,
        },
        {
            "steps": [
                {
                    "title": "Collect the customer's identification data (CIP: name, date of birth, address, TIN)",
                    "primitives": ["P12", "P1"],
                    "responsibility": "regulatory",
                    "output_type": "draft",
                    "hours_per_run": 0.5,
                    "runs_per_year": 500,
                },
                {
                    "title": "Verify identity against documents and external databases",
                    "primitives": ["P2"],
                    "responsibility": "regulatory",
                    "output_type": "draft",
                    "hours_per_run": 0.5,
                    "runs_per_year": 500,
                },
                {
                    "title": "For a legal entity: obtain the beneficial ownership certification (25% share and control)",
                    "primitives": ["P1"],
                    "responsibility": "regulatory",
                    "output_type": "draft",
                    "hours_per_run": 1,
                    "runs_per_year": 150,
                },
                {
                    "title": "Identify and verify the beneficial owners",
                    "primitives": ["P2"],
                    "responsibility": "regulatory",
                    "output_type": "draft",
                    "hours_per_run": 1.5,
                    "runs_per_year": 150,
                },
                {
                    "title": "Screen against sanctions lists, PEP and adverse media",
                    "primitives": ["P2", "P3"],
                    "responsibility": "regulatory",
                    "output_type": "draft",
                    "hours_per_run": 0.5,
                    "runs_per_year": 500,
                },
                {
                    "title": "Build the customer risk profile (purpose and nature of the relationship)",
                    "primitives": ["P3"],
                    "responsibility": "regulatory",
                    "output_type": "draft",
                    "hours_per_run": 1,
                    "runs_per_year": 500,
                },
                {
                    "title": "Decide: open the account, decline, or start enhanced due diligence",
                    "primitives": ["P6"],
                    "responsibility": "regulatory",
                    "output_type": "external_change",
                    "hours_per_run": 0.5,
                    "runs_per_year": 500,
                },
                {
                    "title": "Ongoing monitoring of transactions and refresh of customer information",
                    "primitives": ["P2", "P3", "P11"],
                    "responsibility": "regulatory",
                    "output_type": "draft",
                    "hours_per_run": 2,
                    "runs_per_year": 250,
                },
                {
                    "title": "Escalate suspicious activity and file the report with the regulator",
                    "primitives": ["P3", "P5", "P6"],
                    "responsibility": "regulatory",
                    "output_type": "external_change",
                    "hours_per_run": 4,
                    "runs_per_year": 20,
                },
            ]
        },
    ),
    (
        {
            "type": "process",
            "title": "Feature development and release",
            "description": (
                "A product feature goes from requirements to production: we write "
                "requirements and acceptance criteria, design the architecture and "
                "data model, implement, review the code, test, accept against the "
                "criteria, release to production, watch metrics and errors after "
                "the release and fix the defects that surface."
            ),
            "goal": None,
        },
        {
            "steps": [
                {
                    "title": "Requirements and acceptance criteria",
                    "primitives": ["P1", "P5"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 8,
                    "runs_per_year": 40,
                },
                {
                    "title": "Design: architecture, interfaces, data schema",
                    "primitives": ["P9"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 16,
                    "runs_per_year": 40,
                },
                {
                    "title": "Implementation",
                    "primitives": ["P9"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 60,
                    "runs_per_year": 40,
                },
                {
                    "title": "Code review",
                    "primitives": ["P2"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 4,
                    "runs_per_year": 40,
                },
                {
                    "title": "Testing: unit, integration, regression",
                    "primitives": ["P2"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 16,
                    "runs_per_year": 40,
                },
                {
                    "title": "Acceptance against the criteria",
                    "primitives": ["P2"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 3,
                    "runs_per_year": 40,
                },
                {
                    "title": "Release to production",
                    "primitives": [],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 1,
                    "runs_per_year": 40,
                },
                {
                    "title": "Post-release observation: metrics, errors, rollback on regression",
                    "primitives": ["P2", "P11"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 4,
                    "runs_per_year": 40,
                },
                {
                    "title": "Defect triage and fixes",
                    "primitives": ["P3", "P4", "P9"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 8,
                    "runs_per_year": 40,
                },
            ]
        },
    ),
    (
        {
            "type": "process",
            "title": "Product hypothesis check with an A/B test",
            "description": (
                "We validate product hypotheses with A/B tests: state the "
                "hypothesis and the metric it should move, pick the success and "
                "guardrail metrics, size the test, instrument and validate logging "
                "with an A/A run, launch on a share of traffic, watch the "
                "guardrails, analyse the results and decide whether to ship or roll "
                "back, and log the outcome in our experiment database."
            ),
            "goal": None,
        },
        {
            "steps": [
                {
                    "title": "Formulate the hypothesis: which change affects which metric",
                    "primitives": ["P10"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 2,
                    "runs_per_year": 25,
                },
                {
                    "title": "Choose the OEC and the guardrail metrics",
                    "primitives": ["P10"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 2,
                    "runs_per_year": 25,
                },
                {
                    "title": "Power calculation, minimum detectable effect and duration",
                    "primitives": ["P10"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 2,
                    "runs_per_year": 25,
                },
                {
                    "title": "Instrument and validate the pipeline: logging, A/A test",
                    "primitives": ["P9", "P2"],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 8,
                    "runs_per_year": 25,
                },
                {
                    "title": "Randomise and launch on a share of traffic",
                    "primitives": ["P3"],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 1,
                    "runs_per_year": 25,
                },
                {
                    "title": "Monitor the guardrails and stop on harm",
                    "primitives": ["P2", "P11"],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 3,
                    "runs_per_year": 25,
                },
                {
                    "title": "Analysis: significance, segments, SRM and peeking checks",
                    "primitives": ["P2", "P4"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 8,
                    "runs_per_year": 25,
                },
                {
                    "title": "Decide: ship, roll back, or re-run the experiment",
                    "primitives": ["P6"],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 1,
                    "runs_per_year": 25,
                },
                {
                    "title": "Record the result in the experiment database",
                    "primitives": ["P1"],
                    "responsibility": "none",
                    "output_type": "external_change",
                    "hours_per_run": 0.5,
                    "runs_per_year": 25,
                },
            ]
        },
    ),
    (
        {
            "type": "initiative",
            "title": "Rebranding",
            "description": (
                "Our brand no longer matches where the company is going, so we are "
                "rebranding. Leadership decides to rebrand and briefs the project; "
                "we audit the brand - the market, the competitors, how customers "
                "and our own people see us; we choose the positioning and write the "
                "brand strategy, choose the approach to the name and work up "
                "options, develop directions for the visual identity, present them "
                "to the stakeholders and pick one, run rounds of revisions until "
                "the direction is accepted, check the mark against the trademark "
                "registers, get the identity approved by the board, produce the "
                "brand guideline, templates and assets, launch it inside the "
                "company with training and then outside, and measure the result "
                "against the goals after the launch."
            ),
            "goal": None,
        },
        {
            "steps": [
                {
                    "title": "Decide to rebrand and brief the project",
                    "primitives": ["P6", "P5"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 8,
                    "runs_per_year": 1,
                },
                {
                    "title": "Brand audit: market, competitors, perception outside and inside the company",
                    "primitives": ["P1", "P4", "P7"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 80,
                    "runs_per_year": 1,
                },
                {
                    "title": "Brand strategy: positioning, narrative, value proposition, architecture",
                    "primitives": ["P6", "P5"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 40,
                    "runs_per_year": 1,
                },
                {
                    "title": "Choose the approach to the name and work up name options",
                    "primitives": ["P5", "P6"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 24,
                    "runs_per_year": 1,
                },
                {
                    "title": "Develop directions for the visual identity (mark, palette, typography, imagery)",
                    "primitives": ["P13"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 120,
                    "runs_per_year": 1,
                },
                {
                    "title": "Present the directions to the stakeholders and pick one",
                    "primitives": ["P13", "P8"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 8,
                    "runs_per_year": 1,
                },
                {
                    "title": "Rounds of revisions of the chosen direction until it is accepted",
                    "primitives": ["P13"],
                    "responsibility": "none",
                    "output_type": "draft",
                    "hours_per_run": 40,
                    "runs_per_year": 1,
                },
                {
                    "title": "Check the mark for clearance against the registers and common law",
                    "primitives": ["P2", "P3"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 8,
                    "runs_per_year": 1,
                },
                {
                    "title": "Approval of the identity by the authorised body",
                    "primitives": [],
                    "responsibility": "formal",
                    "output_type": "external_change",
                    "hours_per_run": 2,
                    "runs_per_year": 1,
                },
                {
                    "title": "Brand guideline, templates and the asset set",
                    "primitives": ["P9", "P5"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 60,
                    "runs_per_year": 1,
                },
                {
                    "title": "Launch: internal stakeholders and training first, then the external relaunch",
                    "primitives": ["P8", "P5", "B4"],
                    "responsibility": "reputational",
                    "output_type": "external_change",
                    "hours_per_run": 40,
                    "runs_per_year": 1,
                },
                {
                    "title": "Post-launch evaluation against the goals of the rebranding",
                    "primitives": ["P10", "P2"],
                    "responsibility": "formal",
                    "output_type": "draft",
                    "hours_per_run": 16,
                    "runs_per_year": 1,
                },
            ]
        },
    ),
]
