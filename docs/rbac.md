# Role-Based Access Control

HRPulsar ships with seven built-in role codes, all seeded by migrations. Roles are tenant-scoped (except `platform_admin`, which is platform-wide). Permissions follow the matrices below.

## Role codes

| Code             | Scope            | Notes |
|------------------|------------------|-------|
| `platform_admin` | Platform-wide    | Operates across tenants. Cannot be self-assigned. |
| `admin`          | Tenant           | Full tenant access. |
| `hr`             | Tenant           | Reads every employee record like `admin`, invites any role below admin, runs the whole hiring surface. Not a write role on `/employees`, dictionaries or assessments — see the note under the write matrix. |
| `manager`        | Tenant + division subtree | Read/write limited to employees in managed division subtree. |
| `recruiter`      | Tenant           | Hiring: vacancies, candidates, interviews, reports. |
| `hiring_manager` | Tenant, own vacancies | Hiring, restricted to vacancies they own or manage the division of. |
| `employee`       | Self             | Read own data; write only via `/auth/me` allowlist. |

`/settings/roles` (admin-only, read-only) lists these codes with the same
capability summaries, plus how many users of the workspace hold each one
(`user_count` on `GET /api/roles`), each count linking to the employee list
filtered by that role — except the baseline row, where `?role=employee` means
"holds *only* the baseline" and so answers a different question than the count
does. It deliberately does **not** render the
`permissions` rows the API also returns: they are seeded, but no gate reads a
`Permission.codename` — access resolves through `require_role` on the role
code — so printing them would claim a `recruiter` can do nothing.

Every account holds at least `employee`; the role is granted on every creation path and backfilled for accounts that predate the rule. A gate naming a code no migration seeds fails `backend/tests/unit/test_rbac_role_codes.py` (the former `hrd` code was exactly that: a gate that silently behaved as admin-only).

## `/employees/*` write matrix

`x` = allowed, `—` = `403`, `s` = allowed but limited (see notes).

| Actor             | In-scope target | Out-of-scope target | Self via `/employees` | Self via `/auth/me` |
|-------------------|-----------------|---------------------|-----------------------|---------------------|
| `platform_admin`  | x               | x                   | x                     | x                   |
| `admin`           | x               | x                   | x                     | x                   |
| `hr`              | — (`auth_insufficient_permissions`) | — | — | x (allowlist) |
| `manager`         | x               | — (`outside_division_scope`) | — (`cannot_edit_self_status`) | x (allowlist)        |
| `employee`        | —               | —                   | —                     | x (allowlist)        |

**Endpoints covered by this matrix:**

- `POST/PUT/DELETE /api/employees`, `PUT /api/employees/{id}`, `DELETE /api/employees/{id}`
- `POST /api/employees/{id}/events`
- `POST/PUT/DELETE /api/employees/{id}/work-experience`
- `POST/PUT/DELETE /api/employees/{id}/previous-employment`
- `POST/PUT/DELETE /api/employees/{id}/education`
- `POST/PUT/DELETE /api/employees/{id}/courses`
- `POST/PUT/DELETE /api/employees/{id}/compensation` — admin-only (manager `403`)

No `/employees/*` write gate names `hr`: they all spell
`require_role("admin", "manager")` or `require_role("admin")`, so an HR user is
rejected at the router before the scope check (which does treat them as an
admin) ever runs. The same holds for dictionaries and assessments. `hr` is a
read-and-hiring role today; giving it the write surface this table used to
claim is a product decision, not a documentation fix.

**In-scope** for a `manager` means the target employee belongs to a division that the manager (or their deputy) manages — directly or through any descendant in the division tree (`Division.parent_id`).

## `/employees/*` read matrix

Reads split in two: the card itself is a company directory, everything under
it is the HR record.

| Actor | `GET /employees` | `GET /employees/{id}` | `GET /employees/{id}/{sub-resource}` |
|-------|------------------|-----------------------|--------------------------------------|
| `platform_admin`, `admin`, `hr` | whole workspace, full schema | full schema | x |
| `manager` | own subtree, full schema | full schema in-scope, directory schema outside | x in-scope, `403` outside |
| anyone else | whole workspace, directory schema | full schema for own card, directory schema for a colleague | own card only, `403` otherwise |

`GET /employees/me` answers the caller's own card in the full schema, or `404
employee_profile_not_found` when the account has no employee row.

A `manager` therefore lists fewer people than their own reports do: the list
keeps the HRP-616 subtree scope for them because their rows are the full HR
record, while a rank-and-file caller gets the whole workspace in the trimmed
schema. Mixing both schemas in one response is what a company-wide directory
for managers would need; it is deliberately not built yet.

Filters over fields the directory hides (`status`, `role`, `specialization_id`,
`grade_id`, `unassigned_only`, `with_alerts`) are ignored for a directory
caller rather than applied — a predicate on a hidden field answers the same
question the field would.

**Directory schema** (`EmployeeDirectoryRead`) carries identity and placement
only: name, email, avatar, position title, division, and the grade — the grade
just when the tenant switched `directory_show_grades` on (company profile,
admin-only, off by default). No hire date, status, roles, alerts or first-login
stamp. Sub-resources (`/competences`, `/events`, `/work-experience`,
`/education`, `/previous-employment`, `/courses`, `/compensation`) are never
part of the directory and answer `403 outside_division_scope` off-scope.

## Employee rows outside `/employees/*`

Two more routes hand back employee rows: `GET /positions/{id}/employees` (also
behind the headcount drill-down) and `GET /specializations/{id}/employees`.
They share one row shape and, since HRP-633, one boundary:

| Actor | Rows | Shape |
|-------|------|-------|
| `platform_admin`, `admin`, `hr` | everyone on the position / specialization | full row: hire date, status, specialization, grade, alerts |
| `manager` | everyone | full row inside the managed subtree (and for their own card), directory row outside |
| anyone else | everyone | full row for their own card, directory row for everyone else |

The list is never narrowed — hiding the people would break the company page,
and the employee directory already shows the whole workspace. What narrows is
the row, per row, on the same predicate the employee card uses
(`get_visible_employee_ids`). A response therefore mixes both shapes, which is
why the `response_model` is `list[PositionEmployeeRead | EmployeeDirectoryRead]`.

`?with_alerts=true` is not merely dropped from the directory rows: alerts are
computed only for the employees whose full row the caller is getting.
Ordering switches too — a list ordered by `hire_date` still tells a trimmed
caller the seniority ranking, so a restricted caller gets the directory's own
`created_at, id` order.

Both routes stay on `get_current_user`; the scope rides into the service
(`visible_employee_ids=`), so a third caller cannot forget it.

**What this does not close.** `grade_title` on these rows is the grade of the
*position*, and `GET /api/positions` publishes every position's grade,
specialization and salary band to any authenticated user. Since the directory
also shows a colleague's job title, `directory_show_grades` hides the grade
from the payload but not from anyone willing to join two lists — and the same
join reconstructs `specialization_title`, which the directory schema also
withholds (on `/specializations/{id}/employees` the specialization is the
route, whatever the row shape). Closing that means gating the positions
catalogue itself — a separate decision (HRP-637).

## Catalogues, and the one exception

`Competence`, `CompetenceGroup`, `Indicator`, `Material` and `AnswerScale`
carry `tenant_id` and nothing else — no division, no owner, no author. There
is no slice of them a division head could be scoped to, so HRP-631 answered
the question with the role instead: since 22.08.2026 the catalogue is an HR
asset.

| Surface | Mutations | Reads |
|---------|-----------|-------|
| competence groups, competences, indicators, materials | `admin`, `hr` | unchanged — everyone builds assessments on them |
| answer scales | `admin`, `hr` | unchanged |
| specialization grade ladder and competence matrices | `admin`, `hr` | unchanged |
| `POST /ai/generate-competences`, `/ai/generate-indicators` | `admin`, `hr` | — |
| positions | `admin`, and `manager` **inside their managed subtree** | unchanged |

The AI generators follow the surface they write to: the two that fill the
catalogue moved with it, and `POST /ai/generate-positions` follows the
position rule instead — a division head may run it, but the drafts land in
their own subtree. The generator's context only offers them their own
divisions, an item naming any other is dropped, and the sweep of drafts the
model did not regenerate is narrowed the same way so it cannot delete a
neighbouring department's.

`Position` is the exception because it has `division_id`. Its gate was left as
`admin` / `manager` — `hr` reaches every other catalogue but not this one,
which is an inconsistency the ticket did not decide either way. A manager keeps
the role and gains a fence: `position_scope` on every mutating route, the target
division checked on create and on update so a position cannot be moved out of
the subtree that allowed the edit, and every id in a bulk approve checked
before any of them is applied. A position with no division is refused for a
scoped caller — `Position` has no author column, so nobody's subtree owns it.

Two reads moved with the catalogue rather than staying on `manager`: the
competence audit log and the AI-materials dialog's context options. Both are
editor surfaces, and leaving them behind would mean HR could edit what it
cannot open.

`can_manage` on each position payload keeps the UI honest — the positions
list is readable workspace-wide, and the edit controls render per row.
`canManageCatalogues` in `use-permissions.ts` is the frontend twin of the
catalogue gate.

## Assessments and development plans

`require_role("admin", "manager")` answers whether a caller may be on the
assessment surface at all. Since HRP-638 a second question is asked on every
mutating route: is this assessee theirs?

| Actor | May create, edit, calibrate, re-plan |
|-------|--------------------------------------|
| `platform_admin`, `admin`, `hr` | anyone in the workspace |
| `manager` | their own employee record plus the managed subtree (`get_visible_employee_ids`) |
| anyone else | nothing — `require_role` refuses first |

The assessee arrives either in the body (`POST /assessments`, `POST /pdp`) or
behind a path id, so the guards live in `assessment/scope.py` and resolve the
id back to an employee: `assessment_scope` for `{assessment_id}`, `pdp_scope`
for `{pdp_id}`. Nested resources — participants, external reviewers, plan
items, item materials, version restore — are fenced through their parent,
which is the only owner they have. `POST /ai/suggest-pdp` carries the same
fence: it drafts a plan for the assessment's assessee and spends credits.

A row that does not exist is refused rather than reported missing, so a 403
never confirms that somebody else's assessment is there.

A mass assessment names its assessees in the body and creates one assessment
per name, so it is fenced the same way: `POST /assessment-groups` refuses a
name outside the subtree, and the group's own lifecycle routes (rename,
criteria, scale, bulk status) refuse a group any of whose children sits
outside it. That is HRP-638's rule applied to the children, not an answer to
HRP-640 — who *owns* an `AssessmentGroup` is still open, and CPA and mass
exams genuinely have no assessee to fence by.

Development-plan reads follow their plan too: version list, version detail
and `GET /analytics/pdp/{id}/progress` all carry the plan's content, so they
sit behind the same guard as the restore. `GET /cpa/{id}/analytics` is a named
per-employee ranking and is scoped by assessee like `/analytics/cpa-comparison`.

What stays outside the fence:

- `POST /pdp/{id}/status` and the plan's comments also admit the named
  reviewer (`reviewer_id` may point at any user — that is what naming one is
  for), and answers and item toggles are gated on being a participant or that
  reviewer;
- the answer-scale catalogue is tenant-wide with no owning axis and is fenced
  by role instead (HRP-631).

`tests/unit/test_assessment_manager_scope.py` walks the route table and fails
on a mutating assessment/PDP route that carries no guard, so a route added
later cannot quietly reopen this.

## Analytics and the assessment export

Aggregates and exports read the same rows the lists do, so since HRP-641 they
answer for the same scope. Seven routes used to call the service with a tenant
id and nothing else: `GET /analytics/assessments`, `/analytics/pdp`,
`/analytics/dev-loop`, `POST /analytics/dev-loop/ai-summary`,
`GET /analytics/cpa-comparison`, and both assessment exports.

| Actor | Figures cover |
|-------|---------------|
| `platform_admin`, `admin`, `hr` | the workspace |
| `manager` | their own record plus the managed subtree |
| anyone else | `require_role` refuses first |

The scope rides into the service as a required argument with no default —
`None` for "no restriction", an empty set for "manages nobody". The two are
never collapsed: a manager with no subordinates gets zeroes and an empty
spreadsheet, not the company's. Leaving a default of `None` on that argument
is what reopened this once already (HRP-633).

Two places it would otherwise leak back in:

- the background export receives the resolved ids in its task arguments.
  Resolving them inside the worker would resolve them for the tenant, not for
  whoever asked, so `export_assessments_task` takes them without a default and
  a message queued by the previous release fails loudly.
- the dev-loop AI summary is cached per data fingerprint, and the client sends
  that fingerprint. The cache key carries the caller, so a guessed fingerprint
  cannot hand a manager the summary generated for an admin.

## The talent board

A published card is an internal job ad and stays readable workspace-wide.
Authoring one does not: since HRP-639 the eighteen mutating routes ask whose
card it is, on the two axes `TalentCard` carries.

| Actor | Reads | Writes |
|-------|-------|--------|
| `platform_admin`, `admin`, `hr` | every card | every card |
| `manager` | published cards, their managed subtree, their own, and cards they are a candidate on | their managed subtree and the cards they authored |
| anyone else | published cards they are a candidate on (drafts only when appointed) | nothing |

Authorship is in the write condition, as it is for vacancies, because a card
may be filed under no division at all and would otherwise belong to nobody.
That is only safe because `division_id` is fenced on the way in: `POST
/talent-market` and `PUT /talent-market/{id}` refuse a division the caller
does not manage, so "I created it" cannot become a way to author a card into
somebody else's department and keep editing it.

Hidden cards answer 404 `tm_card_not_found`, the way this module has always
hidden a card, so the answer does not confirm somebody else's draft exists;
refused writes answer 403 `outside_division_scope`. Every card payload carries
`can_manage` so the UI never renders a button that would 403 — a published
card from another department shows on the board with its action menu gone.

**What this does not close.** `GET /talent-market/{id}/candidate-pool` and
`GET /talent-market/{id}/candidates/{employee_id}/breakdown` rank
the whole workspace by competence match, which is assessment-derived data the
employee card withholds outside the subtree. Narrowing it would defeat what
internal mobility is for — the pool exists to find people elsewhere in the
company — so the boundary there is a product decision of the same class as
HRP-637, not part of this fence.

## Error codes returned on `/employees/*` write rejections

| HTTP | `error_code`                | Reason |
|------|-----------------------------|--------|
| 401  | `employee_status_blocked`   | Actor's own employee card is `terminated`/`inactive` (auth-guard layer). |
| 403  | `outside_division_scope`    | Manager attempted to write a target outside their managed subtree. |
| 403  | `cannot_edit_self_status`   | Manager attempted to mutate their own employee card; use `PUT /auth/me`. |
| 403  | `employee_write_forbidden`  | Defence-in-depth fallback when a non-admin/non-manager role bypasses router guards. |

## Self-edit policy

- `PUT /auth/me` accepts only allowlisted profile fields (first/last name, avatar, phone, language). Status, role, email, and tenant cannot be changed via this endpoint — the schema rejects unknown fields with `extra='forbid'`.
- All organisational fields (`division_id`, `position_id`, `position_title`, `status`) are mutated through `/employees/*` and require `admin` for self-edits; `hr`, managers and below cannot mutate their own card here.

## Role lifecycle

Roles attached to a user evolve as their assignments change. The platform enforces this automatically; no admin step is required to keep roles consistent with `Division.manager_id` / `deputy_manager_id`.

### Auto-upgrade on assignment

When a user is set as `Division.manager_id` or `deputy_manager_id` (via `POST` or `PUT /api/divisions[/{id}]`):

- If the user's only tier role is `employee`, the `manager` role is added.
- If the user already holds `manager`, `admin`, `hr`, or `platform_admin`, no change is made.
- The original `employee` role is preserved; `manager` is granted in addition.

### Confirmed downgrade on unassignment

When a manager assignment changes (reassign, set to `null`, division deletion), the response from `update_division` includes a `pending_role_downgrade` array: zero or more entries describing users who, after the change, no longer manage **any** division of the tenant. Each entry contains `employee_id`, `user_id`, `current_role`, `user_name`. The UI shows a confirm-dialog from this list and lets an admin call the set-role endpoint below with `role_code: "employee"`.

### Setting a role

```
PUT /api/employees/{employee_id}/role
{"role_code": "manager"}
```

Admin-only (`require_admin`, so the enterprise platform role passes too). The call replaces the user's tenant roles with the single requested one, keeping any `platform_admin` membership untouched — that role is granted platform-side and cannot be assigned or stripped here. Every change writes an `EmployeeEvent` of type `role_changed` carrying the old and new codes.

Rejections:

| HTTP | `error_code`              | Reason |
|------|---------------------------|--------|
| 400  | `role_code_not_found`     | Not a seeded system role, or `platform_admin`. |
| 422  | `cannot_change_own_role`  | Caller is the target. |
| 422  | `last_admin`              | Target is the workspace's only active admin. |
| 422  | `still_division_manager`  | Target still leads a division as manager or deputy. |

### Invitation role hierarchy

`POST /api/invitations` and `POST /api/invitations/bulk` reject any `role_code` above the inviter's tier:

| Inviter role           | May invite                                                                    |
|------------------------|-------------------------------------------------------------------------------|
| `platform_admin`       | `platform_admin`, `admin`, `hr`, `manager`, `recruiter`, `hiring_manager`, `employee` |
| `admin`                | `admin`, `hr`, `manager`, `recruiter`, `hiring_manager`, `employee`           |
| `hr`                   | `hr`, `manager`, `recruiter`, `hiring_manager`, `employee`                    |
| `manager`              | `employee` (only)                                                             |
| `employee`             | nothing — `403 role_above_inviter`                                            |

The invitations page mirrors this table; `frontend/src/__tests__/invite-tiers-parity.test.ts` fails if the two drift.

Same matrix applies to `PATCH /api/invitations/{id}` when changing `role_code`.

### Error codes

| HTTP | `error_code`                  | Reason |
|------|-------------------------------|--------|
| 403  | `role_above_inviter`          | Inviter attempted to grant a role above their own tier. |

### One-shot reconciliation

For tenants whose data predates the auto-upgrade rule, run:

```bash
python -m backend.scripts.emp3_role_consistency [--dry-run]
```

The script iterates all divisions and adds the `manager` role to any assigned user who lacks it. Idempotent. See `docs/ops/migrations/EMP3_role_consistency_2026-05-05.md` for run instructions and log format.
