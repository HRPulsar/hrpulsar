"""Conventions for assigning capability primitives (HRP-961).

The one source of the rules by which a step of work, or a competence, gets
its codes. Everything that states a rule reads from here:

- the catalog description a client sees (``scope_en`` in the seed and
  ``reference.primitive.<key>.description`` in the message catalogs) is
  ``Convention.definition`` - ``scripts/gen_primitive_seed.py`` copies it;
- the decomposition prompt (``work/prompts.py``) and the competence mapping
  prompt (``mapping_service.py``) both embed ``render_rules()`` verbatim, so
  a step and a person are judged by the same text;
- the process library and the demo seed are relabelled against it.

The rules are the product decisions of 2026-09-28 (canvas "Conventions of
capability tagging: 8 decisions", decisions 1-8, marked below) plus the
boundaries that were already in the prompts and that the decisions did
not touch. The text is written for the model and for a person alike:
"assign if" is the question to ask, "not when" names the neighbour that
takes the case instead. A change here is a change of the rules: bump the
prompt versions and relabel the examples with it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Convention:
    definition: str
    """What the capability is; shown to the client as the code's description."""

    assign_if: str
    """The check question: the code belongs on a step when this holds."""

    not_when: str
    """The cases a neighbouring code takes instead."""

    examples: tuple[str, ...]
    """Two or three canonical steps that carry the code."""


CONVENTIONS: dict[str, Convention] = {
    "P1": Convention(
        definition="Text, speech, a scan, or a form turned into fields and relations",
        assign_if=(
            "the step moves fields from a document, a form, a conversation or "
            "a reading into a system or a record, and that record is a result "
            "of the step in its own right"
        ),
        not_when=(
            "the fields are already structured and the step only picks a value "
            "or a status for them by a rule (P3); the record is a tick that the "
            "work was done, with no content of its own"
        ),
        examples=(
            "Register the receipt in the system with batches, expiry dates and "
            "serial numbers",
            "Log the complaint in the register: number, channel, subject, deadline",
            "Enter the order received by e-mail or through the portal into the system",
        ),
    ),
    "P2": Convention(
        definition=(
            "The reference is set in advance: a playbook, a regulation, "
            "a register, a previous period"
        ),
        assign_if=(
            "the step compares something against a reference that exists before "
            "the step - a checklist, a plan, a regulation, a contract, an order, "
            "a previous period - and the discrepancies are its result, including "
            "checking someone else's work: a review, a validation, a verification, "
            "a reconciliation"
        ),
        not_when=(
            "there is no reference and the cause must be found (P4); the step "
            "only signs a decision already made (no capability). A check whose "
            "verdict is a choice on the merits that someone answers for adds P6 "
            "next to P2"
        ),
        examples=(
            "Check the draft contract against the playbook and flag the "
            "non-standard clauses",
            "Validate the order: completeness of fields, items, addresses, bank details",
            "Reconcile the ledger with the bank statement",
        ),
    ),
    "P3": Convention(
        definition="The rules are known and expressible; the choice is from a finite set",
        assign_if=(
            "the step picks from a known set by rules that can be stated: a "
            "category, a level, a queue, an account, an assignee by rota or free "
            "slot, an escalation by threshold, deadline or request type"
        ),
        not_when=(
            "the person is chosen by skills, load or relationships (P8); the step "
            "tracks the deadline after the choice (P11). A risk the rule does not "
            "name - a VIP, the reputation, a regulator - adds P6 next to P3"
        ),
        examples=(
            "Assign the triage level by the scale and document it",
            "Escalate the ticket to the second line when the first line lacks "
            "the knowledge or the rights",
            "Route the request to the team that owns the product area",
        ),
    ),
    "P4": Convention(
        definition=(
            "There is no reference; the hypothesis is built from logs, "
            "statements, and documents"
        ),
        assign_if=(
            "the step builds a hypothesis about a cause from heterogeneous "
            "evidence - logs, statements, documents, history - because no "
            "reference says what is right"
        ),
        not_when=(
            "a reference exists and the step compares against it (P2); the step "
            "chooses what to do about the cause (P6); the step designs the "
            "measurement that will produce the evidence (P10)"
        ),
        examples=(
            "Root-cause analysis of the incident from the logs and the timeline",
            "Investigate the complaint: documents, staff explanations, chronology",
            "Review the failure history of the equipment",
        ),
    ),
    "P5": Convention(
        definition="A letter, a status update, a report, the wording of a correction",
        assign_if=(
            "the step produces a text that goes to an addressee - a letter, a "
            "notification, a report, a status, a brief, the wording of a "
            "correction - and the text is a result of its own"
        ),
        not_when=(
            "the reply of the addressee changes the outcome (P7) or picks a "
            "branch of a script (P12); the artifact is accepted by whether it "
            "works (P9) or by a stakeholder's taste (P13); a status change or a "
            "system tick with no text of its own (P3 or no capability)"
        ),
        examples=(
            "Acknowledge the complaint with the procedure and the deadlines",
            "Send the customer a status notification that needs no reply",
            "Write the final response with the reasons for the decision",
        ),
    ),
    "P6": Convention(
        definition="The cost of a mistake is known only inside the company's context",
        assign_if=(
            "a wrong choice costs money or risk and the step itself makes that "
            "choice, which shows in one of three ways: the description names it - "
            "decide, approve on the merits, set the priority, accept the "
            "deviation; the decision is the main point of the step - after the "
            "check the checked material (a publication, a batch, a closing) is "
            "pulled or let through and no reference settles the verdict, the "
            "person answers for the call; or the step is a negotiation that "
            "itself chooses the concession - the amount of a remedy, a partial "
            "shipment instead of a full one - where P6 goes next to P7"
        ),
        not_when=(
            "the step analyses, scopes or estimates (P4) or checks against a "
            "reference whose verdict follows from it (P2), whatever the stakes; "
            "the approver only signs a decision made "
            "earlier, or the approval is made by an outside party (no "
            "capability); the choice follows a stated rule (P3). In doubt, keep "
            "P6 with a low confidence rather than drop it"
        ),
        examples=(
            "Decide whether the deviations from the playbook are acceptable for the deal",
            "Decide: open the account, decline, or start enhanced due diligence",
            "Approve the engineering change on the merits at the change control board",
        ),
    ),
    "P7": Convention(
        definition=(
            "Negotiation, an interview, bargaining; the set of outcomes is "
            "unknown before the conversation starts and the counterpart's "
            "reaction changes the result"
        ),
        assign_if=(
            "the step is a dialogue with a party outside the company - a "
            "customer, a supplier, a candidate, a regulator - whose reply changes "
            "the result and whose outcomes are not known before it starts: "
            "negotiation, bargaining, an interview, a dispute"
        ),
        not_when=(
            "the reply only picks a branch from a known set - a questionnaire, a "
            "question tree, a procedure (P12); we inform and need no reply (P5); "
            "the counterpart is inside the company - a colleague, a manager, an "
            "employee - which is P8 or P5, never P7, unless that employee is the "
            "requester of a service process such as an HR or IT service desk"
        ),
        examples=(
            "Negotiate the contract terms with the counterparty",
            "Interview loop with the candidate",
            "Settle the disagreement with the complainant over the remedy",
        ),
    ),
    "P8": Convention(
        definition=(
            "Choose a person by skills, load and relationships, reconcile "
            "opinions, push a decision through, agree on a priority, hand over "
            "to the owner"
        ),
        assign_if=(
            "the step needs a judgment about people: choosing a person by "
            "skills, load or relationships, reconciling opinions, agreeing a "
            "priority between parties inside the company, settling a conflict"
        ),
        not_when=(
            "the assignment follows a rule - a rota, a duty schedule, a free "
            "slot, a queue (P3); the step only reminds or collects answers "
            "against a list (P11); the counterpart is outside the company (P7 "
            "or P12); the step explains or reports without needing agreement (P5)"
        ),
        examples=(
            "Assign the mentor and introduce the newcomer to the team",
            "Collect opinions from security, finance and procurement",
            "Scorecard debrief with the interviewers",
        ),
    ),
    "P9": Convention(
        definition=(
            "A drawing, code, a schema, a patent claim, a training course; "
            "verified by whether it works, not by the register of its prose"
        ),
        assign_if=(
            "the step produces an artifact accepted by whether it works: code, "
            "a drawing, a schema, a formula, a course, a configuration"
        ),
        not_when=(
            "the result is a plan, a brief or a document - P5 for writing it, P2 "
            "for checking it, P11 for scheduling it; the result is accepted by a "
            "stakeholder's taste (P13); the step posts or files by known rules (P3)"
        ),
        examples=(
            "Implement the feature",
            "Design the architecture, the interfaces and the data schema",
            "Build the missing technical controls",
        ),
    ),
    "P10": Convention(
        definition=(
            "What counts as the metric, how to define it operationally, how to "
            "set up a pilot so the effect is distinguishable from noise"
        ),
        assign_if=(
            "the step decides what to measure and how - the metric, its "
            "operational definition, the sample, the duration, the design of "
            "the pilot - before the data exists"
        ),
        not_when=(
            "the data exists and the step analyses it against a reference (P2) "
            "or hunts for a cause (P4); the step only runs a measurement "
            "designed earlier (P3, B1 or no capability)"
        ),
        examples=(
            "Choose the OEC and the guardrail metrics",
            "Power calculation, minimum detectable effect and duration",
            "Define the KPI and how it will be measured",
        ),
    ),
    "P11": Convention(
        definition=(
            "Hold the schedule, remind, react to a deadline or a trigger, track "
            "completion and answers against a list"
        ),
        assign_if=(
            "the work of the step is to follow up: hold a schedule, remind, "
            "react to a deadline or a trigger, put on the calendar, track "
            "completion or answers against a list - confirmations, a yes or a "
            "no, readiness; opinions and judgments are P8"
        ),
        not_when=(
            "the description merely mentions a deadline; the step notifies with "
            "a text of its own (P5); the step collects opinions or settles "
            "priorities (P8); the step escalates or routes by a rule (P3)"
        ),
        examples=(
            "Raise the work order when the calendar or running-hours trigger fires",
            "Reassess the waiting patients at intervals",
            "Chase the owners for the missing figures and collect the sign-offs "
            "against the list",
        ),
    ),
    "P12": Convention(
        definition=(
            "The counterpart's reaction picks a branch; the set of outcomes is "
            "known before the conversation starts: a question tree, "
            "a questionnaire, a closing procedure"
        ),
        assign_if=(
            "the step is a dialogue with a party outside the company in which "
            "the counterpart's reply picks a branch from a known set: a "
            "questionnaire, a question tree, a closing procedure, an intake script"
        ),
        not_when=(
            "the outcomes are open and the reply changes the result (P7); we "
            "only inform and need no reply (P5); the counterpart is inside the "
            "company and is not the requester of a service process (P8 or P5); "
            "the step only registers what was said (P1, "
            "which may accompany P12)"
        ),
        examples=(
            "Take the complaint in the channel and clarify the circumstances "
            "with the complainant",
            "Phone screen against the screening questions",
            "Confirm with the customer that the reply solved the problem",
        ),
    ),
    "P13": Convention(
        definition=(
            "A creative concept, a visual identity, a design direction; the "
            "acceptance criterion cannot be stated before the showing and is "
            "revealed only through the accepting party's reaction"
        ),
        assign_if=(
            "the step produces or selects a creative result - a concept, an "
            "identity, a design direction - whose acceptance criterion cannot "
            "be stated before the showing and is revealed by the accepting "
            "party's taste, including the further rounds until the direction "
            "is accepted"
        ),
        not_when=(
            "a correction of text or a layout after feedback that changes no "
            "direction (P5); adjusting after a measured test (P2); the artifact "
            "is accepted by whether it works "
            "(P9); the acceptance itself is done by the client or another "
            "outside party (no capability)"
        ),
        examples=(
            "Develop the creative concept of the campaign",
            "Design the directions of the visual identity",
            "Develop the UI concept for the client's choice",
        ),
    ),
    "B1": Convention(
        definition=(
            "Temperature at a critical control point, a scan at goods receipt, "
            "weight, vital signs"
        ),
        assign_if=(
            "the step takes a reading from an object with an instrument: "
            "temperature at a control point, a scan at receipt, weight, vital signs"
        ),
        not_when=(
            "the state is judged by the senses without an instrument (B3); the "
            "reading is only read out of a system (P1). Comparing the reading "
            "against a limit adds P2; recording it with content of its own adds P1"
        ),
        examples=(
            "Measure the temperature at the critical control point",
            "Count and scan the pallets against the purchase order",
            "Take the patient's vital signs",
        ),
    ),
    "B2": Convention(
        definition="Unloading, placement, repair, withdrawing a batch, fixing defects",
        assign_if=(
            "the step acts on a physical object with hands or tools: unloading, "
            "placement, repair, withdrawing a batch, fixing defects, changing "
            "over tooling"
        ),
        not_when=(
            "the step only plans, orders or schedules the action (P3, P5 or "
            "P11); the object is a record or a document, not a thing"
        ),
        examples=(
            "Unload the trailer into the receiving area",
            "Put the goods away to the storage location",
            "Replace the worn part and test the assembly",
        ),
    ),
    "B3": Convention(
        definition=(
            "A dented package, play and noise in an assembly, a patient's "
            "appearance, a user's behaviour in a task"
        ),
        assign_if=(
            "the step judges the condition of an object or a person on site by "
            "the senses: a dented package, play and noise in an assembly, a "
            "patient's appearance, a user's behaviour in a task"
        ),
        not_when=(
            "the state is read with an instrument (B1); the judgment is made "
            "from documents or data (P2 or P4)"
        ),
        examples=(
            "Inspect the goods for damage and isolate them to the hold area",
            "Assess the patient's appearance at triage",
            "Observe the user performing the task",
        ),
    ),
    "B4": Convention(
        definition=(
            "Demonstration, a supervised attempt, correction before the mistake sets in"
        ),
        assign_if=(
            "the step transfers a skill to a person hands-on: a demonstration, "
            "a supervised attempt, correction before the mistake sets in"
        ),
        not_when=(
            "the training material is written or built (P5 or P9); the step "
            "schedules the training (P11); the meeting is about progress and "
            "priorities, not about a skill (P8)"
        ),
        examples=(
            "First tasks under supervision with feedback",
            "Show the customer the fix hands on",
            "Demonstrate the procedure at the workstation and watch the attempt",
        ),
    ),
}

# (neighbouring codes, the deciding question between them). One entry per
# product decision of 2026-09-28, then the boundaries carried over from the
# prompts as they were.
BOUNDARIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (  # decision 1
        ("P6", "P2", "P4"),
        "P6 needs a choice that costs money or risk and that the step itself "
        "makes: the description names it, or pulling or letting the checked "
        "material through is the main point of the step and no reference "
        "settles the verdict, or a negotiation itself chooses the concession "
        "(then P6 goes next to P7). Analysis, scoping and estimating are P4, "
        "and a check whose verdict follows from a reference is P2, whatever "
        "the stakes. A doubtful P6 stays on the step with a low confidence.",
    ),
    (  # decision 2
        ("P11", "P5", "P8"),
        "P11 only when the work of the step is to follow up. A deadline "
        "mentioned in the description is not P11. A notification with a text "
        "of its own is P5. Collecting opinions is P8.",
    ),
    (  # decision 3
        ("P3", "P6"),
        "Escalation by a rule - a threshold, a deadline, a request type - is "
        "P3. Add P6 when the step must weigh a risk the rule does not name: a "
        "VIP, the reputation, a regulator.",
    ),
    (  # decision 4
        ("P3", "P1", "P11"),
        "Choosing from a known set by rules - a category, a level, a queue, an "
        "account - is P3. Moving fields from a document or a conversation into "
        "a system is P1. Putting on a schedule or tracking a deadline is P11. "
        "A step that does several of these gets several codes.",
    ),
    (  # decision 5
        ("P7", "P12", "P5"),
        "With a party outside the company: the reply changes the result and "
        "the outcomes are not known in advance - P7; the reply picks a branch "
        "from a known set - a questionnaire, a question tree, a procedure - "
        "P12; we inform and need no reply - P5. Inside the company there is no "
        "P7 and no P12: a conversation with colleagues is P8 or P5. The one "
        "exception is a service process - an HR or IT service desk: the "
        "employee who raised the request counts as the party outside the "
        "company for that process.",
    ),
    (  # decision 6
        ("P2", "P6"),
        "A check against a reference set in advance - a checklist, a plan, a "
        "regulation, a contract - is P2. An approval where the approver "
        "chooses on the merits and answers for the risk is P6. A signature "
        "under a decision made earlier gets no capability. An approval made by "
        "an outside party - a client, a regulator - is not our work and gets no "
        "capability. When the verdict does not follow from the reference and "
        "pulling or letting the checked material through is the point of the "
        "step, P6 goes next to P2.",
    ),
    (  # decision 7
        ("P8", "P3", "P11"),
        "Choosing a person by skills, load and relationships, reconciling "
        "opinions, agreeing a priority - P8. Assigning by a rule - a queue, a "
        "duty rota, a free slot - P3. Reminding or collecting answers against "
        "a list - P11.",
    ),
    (  # carried over (decision 2026-09-09)
        ("P9", "P5", "P13"),
        "P9 only for an artifact accepted by whether it works: code, a "
        "drawing, a schema, a formula, a course. A plan, a brief or a document "
        "is P5, P2 or P11. P13 only for producing or selecting creative ideas "
        "whose acceptance is a stakeholder's taste, the further rounds until "
        "the direction is accepted included; a correction of text or a layout "
        "after feedback is P5, adjusting after a measured test is P2.",
    ),
    (  # carried over, with the record rule of decision 8 applied to physical work
        ("B1", "B2", "B3", "B4", "P1", "P2"),
        "Boundary codes for work done with hands or senses: a reading from an "
        "object (B1), an action on it (B2), judging its condition on site "
        "(B3), transferring a skill hands-on (B4). A physical step gets a "
        "cognitive code next to its boundary code only for a result of its "
        "own: the record with content (P1), the discrepancies found against a "
        "limit or an order (P2).",
    ),
)

# decision 6 and the rule of 2026-09-09 on steps of pure accountability
NO_CAPABILITY = (
    "A step gets an empty list when it only executes a decision made earlier "
    "- a signature, a release to production, sending an offer already approved "
    "- or when its approval is made by an outside party: a client, a "
    "regulator, an authority. Our own work in such a step to obtain that "
    "approval is coded: presenting the result (P5), chasing it by the "
    "deadline (P11)."
)

# decision 8
SECONDARY = (
    "A second or third code only when the action has a result of its own "
    "inside the step: a record in a system (P1), a list of discrepancies (P2), "
    "a text that goes to an addressee (P5). A minor action without a result of "
    "its own gets no code."
)


def render_rules() -> str:
    """The block both prompts embed, after the catalog lines.

    'The step' is the unit of work being tagged; the mapping prompt tells
    the model to read it as the work a person exercising the competence
    does.
    """
    lines = [
        "Conventions for assigning codes (the same conventions classify the "
        "steps of a process and map competences to codes):"
    ]
    for code, c in CONVENTIONS.items():
        # The canonical examples stay out of the prompt: the few-shot corpus
        # shows every code, and each line here is paid for on every call.
        lines.append(f"- {code}: assign if {c.assign_if}. Not when {c.not_when}.")
    lines.append("Boundaries between neighbouring codes:")
    for codes, question in BOUNDARIES:
        lines.append(f"- {' / '.join(codes)}: {question}")
    lines.append(f"No capability: {NO_CAPABILITY}")
    lines.append(f"Secondary codes: {SECONDARY}")
    return "\n".join(lines)


__all__ = [
    "BOUNDARIES",
    "CONVENTIONS",
    "NO_CAPABILITY",
    "SECONDARY",
    "Convention",
    "render_rules",
]
