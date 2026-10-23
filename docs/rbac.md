# Role-Based Access Control

HRPulsar ships with seven built-in role codes, all seeded by migrations. Roles are tenant-scoped (except `platform_admin`, which is platform-wide). Permissions follow the matrices below.

## Role codes

| Code             | Scope            | Notes |
|------------------|------------------|-------|
| `platform_admin` | Platform-wide    | Operates across tenants. Cannot be self-assigned. |
| `admin`          | Tenant           | Full tenant access. |
| `hr`             | Tenant           | Reads every employee record like `admin`, invites any role below admin, runs the whole hiring surface. Not a write role on `/employees` or assessments — see the note under the write matrix; edits the dictionaries by default (HRP-827). |
| `manager`        | Tenant + division subtree | Read/write limited to employees in managed division subtree. |
| `recruiter`      | Tenant           | Hiring: vacancies, candidates, interviews, reports - `manage` on the recruitment section by default. |
| `hiring_manager` | Tenant, own vacancies | Evaluates candidates on the vacancies they are named on, own or manage the division of - `view` on the recruitment section plus the evaluation, by role. |
| `employee`       | Self             | Read own data; write only via `/auth/me` allowlist. |

`/settings/roles` (read-only; `view` on the roles section, the admin role's by
default - HRP-831) lists these codes with the same
capability summaries, plus how many users of the workspace hold each one
(`user_count` on `GET /api/roles`), each count linking to the employee list
filtered by that role — except the baseline row, where `?role=employee` means
"holds *only* the baseline" and so answers a different question than the count
does. Access resolves through the role code and the section matrix; the
permission codenames of the first release (`employees.read` and the like) were
never read by a gate; HRP-832 dropped them from the code, and HRP-973 dropped
their tables one release later.

Every account holds at least `employee`; the role is granted on every creation path and backfilled for accounts that predate the rule (HRP-619 covered accounts with no role at all; HRP-832 closed signup, invitation acceptance, signup approval, enterprise tenant creation, the demo visitor and the set-role call, which used to grant the tier role alone, and backfilled the accounts created in between). Because literally every account holds it, anything that names the `employee` role - a Coverage access rule, a raised `employee` row of the section matrix - reaches every member of the workspace, invited managers and recruiters included. A gate naming a code no migration seeds fails `backend/tests/unit/test_rbac_role_codes.py` (the former `hrd` code was exactly that: a gate that silently behaved as admin-only).

## `/employees/*` write matrix

The table is the default section access matrix. Since HRP-829 every write
below asks for `manage` on the `employees` section instead of the
`admin`/`manager` role list, so a tenant that raises or lowers a role
moves that role's row: `manage` writes inside the caller's subtree, an
admin-level role (`admin`, `hr`, `platform_admin`) at `manage` writes the
whole workspace. `recruiter`, `hiring_manager` and `employee` go no further
than `view` here (a role ceiling, REDO QA 14.10): `manage` would run a
subtree those roles do not head, so only `admin`, `hr` and `manager` may be
raised to it.

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
- `POST/PUT/DELETE /api/employees/{id}/education` — plus the self-service
  carve-out below
- `POST/PUT/DELETE /api/employees/{id}/courses` — plus the self-service
  carve-out below
- `GET/POST/PUT/DELETE /api/employees/{id}/compensation` — same matrix, and
  one's own pay is admin-level only: a `manage` holder below the admin level
  neither reads nor sets it on their own card (`cannot_edit_self_status`,
  HRP-829)

**Self-service carve-out (HRP-66).** Education and Courses are the two sections
anyone may write on their *own* card: those routes gate on authentication only
(`get_current_user`, no `require_role`), and the service layer allows the write
when the target employee's `user_id` is the caller's. Everyone else — including
`hr` and a `manager` writing on someone else's card — falls back to the matrix
above. Reads are unchanged.

No `/employees/*` write gate names `hr`: outside that carve-out they spell
`require_section("employees", "manage")` (`hr` defaults to `view`) or the
admin role, so an HR user is rejected at the router before the scope check
ever runs. Inside the carve-out the service lets the owner in and asks
everyone else for `manage` - an HR user at `view` writing on somebody else's
education gets `employee_write_forbidden`. Until HRP-829 the scope check
waved the admin tier through there, so `hr` could do that through the API
(never from the UI, which this table already described); Maxim closed it on
24.09. The same holds for assessments on the default matrix - since
HRP-826…829 the tenant may raise `hr` to `manage` there. Dictionaries
differ: `hr` edits them by default since QA 13.10 on HRP-827.

**A new record and a transfer land in the caller's subtree (HRP-829).**
`POST /api/employees` and a `PUT /api/employees/{id}` that changes
`division_id` also check the destination with the division write scope: a
division in the caller's managed subtree, or anywhere - no division
included - for an admin-level role (`outside_division_scope` otherwise).
Before HRP-829 a manager could file a new person in any division or none
and move a report anywhere; only whose card they wrote was checked.
Deleting someone stays `require_role("admin")`; granting a role and the
set-password link stay `require_admin`.

**Below the admin level (HRP-829, Maxim 24.09).** A `manage` holder below
the admin level writes neither an admin-level person's record (`admin`,
`hr`, `platform_admin` - status, transfer, history, pay: otherwise a raised
role could file the workspace owner in their division and terminate them
out of the app; filing a card for one is refused too, and
`GET /employees/available-users` leaves them out) - `employee_write_forbidden`
- nor their own beyond education and courses: events, work history and pay
on one's own card answer `cannot_edit_self_status`, since a free-typed event
is a forged `compensation_change` away. A person takes a position of the
caller's subtree or a workspace-wide one (no division); another
department's seat is `outside_division_scope`.

**In-scope** for a `manager` means the target employee belongs to a division that the manager (or their deputy) manages — directly or through any descendant in the division tree (`Division.parent_id`).

## `/employees/*` read matrix

Reads split in two: the card itself is a company directory, everything under
it is the HR record.

| Actor | `GET /employees` | `GET /employees/{id}` | `GET /employees/{id}/{sub-resource}` |
|-------|------------------|-----------------------|--------------------------------------|
| `platform_admin`, `admin`, `hr` | whole workspace, full schema | full schema | x |
| `manage` on `employees` (`manager` by default) | own subtree, full schema | full schema in-scope, directory schema outside | x in-scope, `403` outside |
| anyone else | whole workspace, directory schema | full schema for own card, directory schema for a colleague | own card only, `403` otherwise |

`GET /employees/me` answers the caller's own card in the full schema, or `404
employee_profile_not_found` when the account has no employee row.

**Who opens a card (HRP-829 REDO, QA 14.10).** One rule,
`readable_card_ids` in `employee/service.py`, decides whether
`GET /employees/{id}` opens at all - and the same rule decides whether an
employee's name is a link to `/employees/{id}` anywhere in the product:

| Caller's `employees` level | Card opens (name is a link) | Otherwise (name is text, card `404 employee_not_found`) |
|---|---|---|
| `none` | nobody's, one's own included | everyone |
| `view` / `manage`, admin-level role | everyone, any status | - |
| `view` / `manage`, a division head (`manager`) | own card and the managed subtree at any status, anyone else while `active` / `on_leave` | someone `inactive` / `terminated` outside the subtree |
| `view` / `manage`, anyone else (`recruiter`, `hiring_manager`, `employee`) | own card, anyone while `active` / `on_leave` | someone `inactive` / `terminated` |

The UI asks `GET /employees/card-access?ids=...` (up to 200 ids, answers the
openable ones) once per page for every name it renders - the
`EmployeeName` component, batched by 100 - and renders text until the answer
arrives or when the check fails. With the section closed it asks nothing:
every name is text, no transition bounces to the dashboard. The card route
stays outside the gate (`SHARED_READS`) so a closed card answers like an
unknown id rather than the gate's `403`. The global search lists no
employees at `none`; one's own "My profile" entries are gone there too.

Which row a caller lands in for the list is the role and the level: an
admin-level role, then `manage` on `employees` (HRP-829 - it used to be the
`manager` role), then everyone else. The card and its sub-resources follow
the read scope - own card, admin-level, or the subtree of the divisions the
caller heads - whatever the level; a `manage` holder heading nothing lists
only their own row, like a `manager` with no division before.

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

`compensation_change` events carry the amounts, so since HRP-829 the
timeline (`GET /employees/{id}/events`) leaves them out for a caller who
cannot read that card's pay tab - `hr` at `view`, a manager lowered to
`view` - while the person themselves keeps them: every change is mailed to
them anyway.

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

## The positions catalogue

`GET /api/positions` stays open to the workspace — a position picker is a
picker for every role — but since HRP-637 what a row carries depends on who
asks, in two classes that answer to **two different role sets**:

| Field class | Who reads it |
|-------------|--------------|
| title, division, headcount, employee count, lifecycle, source | everyone |
| `specialization_id` / `_title`, `grade_id` / `_title`, the `specializations[]` and `grades[]` option pools, `matrix_configured` | `platform_admin`, `admin`, `hr`, `manager`, **anyone the recruitment section is open to** (`recruiter`, `hiring_manager` by default) — and everyone else only while the tenant has `directory_show_grades` on |
| `salary_min`, `salary_max`, `salary_currency` | `platform_admin`, `admin`, `hr`, `manager` only — no tenant flag opens compensation |

The two rows are `can_see_position_grades()` and `can_see_compensation()` in
`app/core/access_scope.py`, and they are deliberately **not** the same
predicate. Hiring reads the pair because a requisition cannot be raised
without the grade and specialization of the position it fills — the form
fills its pickers from exactly these fields (HRP-180) — but a band is not a
recruiter's to read. Collapsing the two calls back into one
`is_employee_only()` would hand hiring the compensation data; the tests pin
the gap in both directions.

Grade and specialization ride `directory_show_grades` because they are the
other half of the join the employee directory opens: the directory publishes
"colleague -> position" to everyone, so a catalogue that publishes
"position -> grade" to everyone rebuilds any colleague's grade whatever the
flag says.

Filters go with the fields. `?grade_id=`, `?specialization_id=` and
`?matrix_unconfigured=` are ignored for a caller who does not get the
columns, because a predicate over a hidden field answers the same question
the field would, one request per grade. They start applying again the moment
the flag opens the columns.

`can_manage` on a position row is a different question — HRP-631, whether
this viewer may *edit* the row — and is not a visibility signal.

### Every route that carries these keys

The list is exhaustive as of HRP-637 and was built mechanically, by walking
every `GET` route's `response_model` for the sensitive field names rather
than by grepping the ones the ticket happened to name — the route that
turned out to matter most mentions neither positions nor specializations.
Rebuild it before assuming a new route is covered:

```
cd backend && ../.venv/bin/python scripts/audit_sensitive_read_routes.py
```

It prints every `GET` whose payload can carry these keys next to the gate
guarding it. Twenty-five of them still answer on bare authentication, and
that is not twenty-five holes: the assessment, PDP and talent-market
payloads carry a grade because they are *about* one person, and each is
scoped by its own module's rule (`get_visible_employee_ids`, the assessment
manager scope, HRP-209). What the audit gives you is the decision list —
every route where somebody has to have decided.

| Route | What the trimmed side loses |
|-------|-----------------------------|
| `GET /positions`, `GET /positions/{id}` | both classes, plus the three predicates |
| `GET /positions/{id}/matrix-status`, `/competences` | the pair ids, `grade_specialization_id` included — the specialization page turns that one back into a grade title |
| `GET /specializations/{id}/positions` | the pair — the same join under the specialization's own URL |
| `GET /specializations/{id}/grades`, `GET /specializations/{id}`, `GET /grade-system/specializations/{id}`, `GET /grade-system/divisions/{id}` | the bands only; the grade ladder itself says what grades exist, not who holds them |
| `GET /specializations/{id}/matrix-bulk` | the whole ladder (`grades: []`) — `grade_id` is a required uuid there, so the payload cannot be blanked field-by-field, and the grade-to-competence mapping it carries is half of the fingerprint oracle below |
| `GET /specializations/{id}/matrix` | 403 — it carries no grade key, but takes `grade_id` as a *query* parameter, which makes it the other half of that oracle |
| `GET /dictionaries/items/{id}/usage` | 403 below `manage` on dictionaries (admin and HR by default) — see below |

`GET /dictionaries/items/{id}/usage` was the cheapest way around all of the
above and it touches none of the routes the ticket named. On bare
authentication: `GET /dictionaries/grade` hands any member every grade id,
and one call per id answered the exact list of positions holding that grade,
by title. Joined with `position_title` from the employee directory that is a
named colleague's grade in N+1 requests. The route exists to tell an admin
what a delete would break, so it sits behind the same gate as the writes:
`manage` on the dictionaries section (HRP-827).

### Known remainders

Written down rather than closed, because closing them costs more than the
narrowing is worth. Re-price them if the threat model changes.

- **The specialization is the route, whatever the row shape.** On
  `/specializations/{id}/employees` and `/specializations/{id}/positions` the
  specialization is in the URL, so walking `GET /specializations` and calling
  each one still maps positions — and, through `user_name` on the directory
  row, people — to a specialization even with every field trimmed. Closing it
  means refusing the routes outright, which contradicts the HRP-633 decision
  that these lists stay whole for everyone. The fields are trimmed; the
  route-level fact is not.
- **Numeric narrowing.** `PositionMatrixStatus.link_count` survives the trim
  and `SpecializationGradeRead.competence_count` is published on the open
  grade ladder. A position whose link count matches exactly one rung's
  competence count is narrowed to that grade. This is a count collision, not
  an identifier: it is exact only where the ladder's rungs happen to have
  distinct competence counts, and it names nobody on its own. Gating the
  counters would cost the "matrix not configured" banner its number.
- **Divisional granularity.** `GET /divisions/{id}/specializations` publishes
  which specializations a division works in. That narrows a colleague's
  specialization to the set mapped to their division, never to one, and the
  mapping is org structure rather than a personal fact. Left open.

## Catalogues, and the one exception

`Competence`, `CompetenceGroup`, `Indicator`, `Material` and `AnswerScale`
carry `tenant_id` and nothing else — no division, no owner, no author. There
is no slice of them a division head could be scoped to, so HRP-631 answered
the question with the role instead: since 22.08.2026 the catalogue is an HR
asset.

| Surface | Mutations | Reads |
|---------|-----------|-------|
| competence groups, competences, indicators, materials | `manage` on `competences` (HRP-827; `admin`, `hr` by default); deleting also needs the `admin` role; a division head's own personal draft at `view` (HRP-632) | the tree, the card, skill levels: open whatever the matrix says — everyone builds assessments on them |
| skill-level ladder | `manage` on `competences` **and** the `admin` role | open whatever the matrix says |
| AI generation of the tree (`/competence-generation`) | `manage` on `competences` **and** the `admin` role, reads included | — |
| dictionaries (grades, specializations, competence types) | `manage` on `dictionaries` (HRP-827; `admin` (locked there) and `hr` by default) | open whatever the matrix says |
| answer scales | `admin`, `hr` | unchanged |
| specialization grade ladder and competence matrices | `admin`, `hr` by role; `company` only opens them (HRP-828) | open whatever the matrix says |
| `POST /ai/generate-competences`, `/ai/generate-indicators` | `manage` on `competences` (HRP-827) | — |
| positions | `manage` on `company` (HRP-828; `admin`, `manager` by default) **inside the caller's managed subtree**, admin-level roles the workspace; deleting needs the `admin` role | open to the workspace, trimmed per role — see "The positions catalogue" |

**HRP-632: a division head's personal competence draft** (Vladimir, Maxim
29.09). Below `manage`, the `manager` role at `view` adds a competence into
an existing group as its own draft (`POST /competences`, the bulk add),
renames and re-describes it (`PUT`, a change of group or visibility stays
`manage`'s) and deletes it. `competences.draft_owner_id` names the author;
publishing it (`manage`) clears the owner and the draft joins the
catalogue. Until then it is seen by its author and by `manage` alone:
`GET /competence-tree` leaves every personal draft out - every picker reads
it, and a draft is attached nowhere until published - and
`?drafts=true`, which the catalogue page asks for, brings in the caller's
own or, at `manage`, all of them; `GET /competences/{id}` of someone
else's draft is `404`. An author who lost the role still reads their draft
and no longer edits it; HR and admins see it and publish it, and deleting it
is the admin's, like any delete from the catalogue. A draft goes into one of
the tenant's own groups, never the built-in library, and coverage maps it
only once it is published. The catalogue's own unpublished rows are not personal
drafts and read as before - hiding every unpublished row was turned down:
the catalogue is created unpublished by hand and by AI and used as it is.
The section is self-guarded for this: every other write in it asks
`manage` itself.

**HRP-827: the competence catalogue and the dictionaries on the matrix.**
Authoring the catalogue is `manage` on `competences`; the level reaches all
of it, since no division owns a row. Deleting from it, the skill-level
ladder and the AI generation of the tree stay the `admin` role's on top of
`manage` (decision of 23.09): they were admin-only before the matrix, and
`hr`'s default `manage` is its authoring — a tenant that raises `manager`
to `manage` hands it the same authoring, not the deletes. Because
`competences` has no admin lock, lowering `admin` to `view` takes those
extras away too. Editing the dictionaries is `manage` on `dictionaries`,
including the usage preview before a delete - which names the positions
holding a grade (HRP-637), so raising a role to `manage` here hands it that
map whatever the directory settings say. The reads the rest of the
product is built on — the competence tree, one competence, its indicators
by level, the skill levels, a dictionary list or item — are `SHARED_READS`
in the registry: the gate leaves their `GET` alone, so closing either
section closes its page and its writes but not the picker in an
assessment, a vacancy or a profile. Their `usage` previews, the material
overrides and the audit log stay inside the section.

Pages outside the two sections read the row they write to: deleting a
specialization (a dictionary item) and adding one inline in the position
dialog ask `dictionaries`; adding a grade inline also chains it into the
grade system, which stays the `admin` role's. The AI matrix of a
specialization, its history tab and the position's AI card are the
competence generation, so they ask `admin` + `manage` on `competences`. The
grade page of a specialization under `/dictionaries` opens with the section;
its passing score writes the grade system and stays the `admin` role's.

**QA 13.10 on HRP-827: the defaults and `view`.** `dictionaries` opens to
`admin` and `hr` (`manage`) and to nobody else by default; `competences`
opens to `manager` at `view` and closes below it (`recruiter`,
`hiring_manager`, `employee` - the role order of the matrix). `none` there
takes the menu entry and the section's own reads (usage previews, material
overrides), not the catalogue: assessments, self-assessments, the competence
profile and every picker read it through `SHARED_READS`. `view` on
`dictionaries` opens the menu entry, every tab and the direct links
read-only - no add, edit or delete; the writes and the usage preview stay
`manage`'s. A specialization's matrix shows a competence's title rather than
a link to its card to a caller the competences section is closed to.
Defaults live in the registry and only deviations are stored, so a tenant
that never touched a cell reads the new default and a saved deviation
stays as it was.

The AI generators follow the surface they write to: the two that fill the
catalogue moved with it. `POST /ai/generate-positions` drafts the
workspace's job catalogue, so since the HRP-631 rework (QA 06.10) it asks
`manage` on `company` **and** an admin-level role (`admin`, `hr`,
`platform_admin`): a caller scoped to a subtree - a division head, or a role
the tenant raised to `manage` - gets `403 auth_insufficient_permissions`
before the run is charged and authors positions by hand inside the subtree.
The positions page mirrors it: the AI Generate button needs
`canGeneratePositions`, and the banner of AI drafts awaiting review renders
for admin-level roles only.

`Position` is the exception because it has `division_id`. Its gate was left as
`admin` / `manager` — `hr` reaches every other catalogue but not this one.
Since HRP-828 the gate is `manage` on `company`, where `hr` defaults to `view`,
so the inconsistency became a setting: a tenant that raises `hr` to `manage`
hands it the positions of the whole workspace (it is an admin-level role). A
division head keeps the level and a fence: `position_scope` on every mutating route, the target
division checked on create and on update so a position cannot be moved out of
the subtree that allowed the edit, and every id in a bulk approve checked
before any of them is applied. A position with no division is refused for a
scoped caller — `Position` has no author column, so nobody's subtree owns it.

Two reads moved with the catalogue rather than staying on `manager`: the
competence audit log and the AI-materials dialog's context options. Both are
editor surfaces, and leaving them behind would mean HR could edit what it
cannot open. Since HRP-827 both ask `manage` on `competences`.

`can_manage` on each position payload keeps the UI honest — the positions
list is readable workspace-wide, and the edit controls render per row. Below
`manage` on `company` it is `false` on every row (HRP-828; `hr` used to get
`true` and a button that answered 403).
`canManageCatalogues` in `use-permissions.ts` is the frontend twin of the
catalogue gate still on a role (answer scales, the specialization ladder
and matrices); the competence catalogue reads
`canManageSection("competences")`, and `canAdministerCompetences` is the
admin role on top of it.

## Division writes

`POST /divisions`, `PUT /divisions/{id}` and the specialization mapping under
`/divisions/{id}/specializations` ask `manage` on `company` (HRP-828; `admin`
and `manager` by default - it used to be those two roles). Anyone below the
admin level - a division head (or deputy), or a role the tenant raised - writes
only inside the subtree they manage — the set
`GET /divisions/scope` answers with — and gets `403 outside_division_scope`
elsewhere (HRP-819):

- editing or mapping requires the division itself to be in the subtree;
- creating requires the parent to be in it, so a top-level division is
  admin-only;
- moving is judged by the destination: a new `parent_id` must be in the
  subtree, and `null` (detach to the root) never is. Sending the current parent
  back unchanged is not a move;
- naming a head or deputy (`manager_id`, `deputy_manager_id`) requires someone
  of the subtree or the caller themselves (HRP-857, Vladimir 29.09): the seat
  grants the `manager` role, so a person from elsewhere is the admin's to
  appoint. A changed seat is judged on both sides - leaving it may take the
  role away - so a head below the admin level neither clears nor replaces a
  holder from elsewhere. A head sent back unchanged is not an appointment.
  Below the admin level the division forms offer only those people.

`DELETE /divisions/{id}` stays admin-only. The org chart itself
(`GET /divisions`, `GET /divisions/{id}`) is readable company-wide by design.

**HRP-828: the company section on the matrix.** `manage` on `company` shapes
the org chart: divisions and their specialization mapping, positions and
`POST /ai/generate-positions` (under `/ai`, so it asks the level itself), each
inside the caller's subtree. `hr` defaults to `view` (decision of 24.09): it
never wrote either, and its old `manage` cell came from the specialization
ladder and matrices, which stay on the `admin`/`hr` role like the answer
scales. Because `hr` writes those at `view`, the section is self-guarded: the
routes that shape the chart ask for `manage`, the gate closes `none`. The
grade system (`/grade-system` chains and links), the company profile, logo and
activity fields, `PUT /company`, `POST /onboarding/complete`, both deletes and
the section-access screen stay on the `admin` role - `company` is admin-locked,
so an admin always holds `manage` there, and a role raised to `manage` does not
get them. `platform_admin` gained division and position authoring (the matrix
never gates it), not the admin-role pieces. The reads every other section is
built on - the company, the onboarding status, the division tree, scope and
card, the position list and card, the specialization list and ladder, the
grade-system bands - are `SHARED_READS`: closing `company` to a role closes its
pages and the rest of its reads (occupancy, matrices, the specialization card,
the company profile), not the pickers of assessments, vacancies, profiles or
the dashboard. The position picker's quick-create files a position with no
division, so it renders only for an admin-level role at `manage`; AI drafts
are approved or rejected per row the caller may edit, deleting a position is
offered to the `admin` role alone, and a grade's attributes on the
specialization page (they live on the grade chain) are read-only below it.
`POST /ai/generate-positions` refuses any subtree-scoped caller
(`403 auth_insufficient_permissions`) before the run is charged (HRP-631).
Naming a division's head or deputy still rewrites roles (see "Role
lifecycle": the `manager` role is granted to the new head and taken from a
head left with no division), so a role the tenant raises to `manage` does that
too - inside its subtree, or across the workspace for `hr`.

**HRP-622: a plain employee keeps the overview.** A caller holding no role but
`employee` gets neither the Profile, Positions nor Specializations tab of the
company section, a direct link to them bounces to the dashboard with the
permission toast, and the reads behind them answer 403: the company profile,
the position drill-downs (employees, occupancy, matrix status, competences)
and the specialization card, positions, employees and matrices
(`require_company_details`). The pickers in `SHARED_READS` stay open. A tenant
that raises `employee` to `manage` on `company` hands the tabs back; any other
role keeps them at `view`. Frontend twin: `canViewCompanyDetails`.

**HRP-828: the dictionaries hint.** The Specializations tab points to
Settings → Dictionaries → Specializations (the hint and the empty state) only
for a caller with `manage` on `dictionaries` - the page it names.

## Assessments and development plans

Two questions are asked on every route that runs assessments. The first -
may this caller run assessments at all - is the tenant's matrix since
HRP-826: creating, editing, sending and calibrating single and mass
assessments, their participants, criteria and scale, external reviewers,
the detailed results and the criteria pickers, and every CPA route ask
`manage` on `assessments` in place of the `admin`/`manager` role list.
`admin` and `manager` hold it by default. `hr` defaults to `view`: it never
ran assessments, and its old `manage` cell came from the answer-scale
catalogue, which keeps its own `admin`/`hr` role gate (see "Catalogues").
`platform_admin` reaches `manage` like every section, so it gained CPA,
which the role list did not name. The second question, since HRP-638: is
this assessee theirs?

| Actor with `manage` | May create, edit, calibrate, re-plan |
|-------|--------------------------------------|
| `platform_admin`, `admin`, `hr` | anyone in the workspace |
| anyone else | their own employee record plus the managed subtree (`get_visible_employee_ids`) - a role raised to `manage` that heads no division reaches only itself |

Below `manage` the section is the respondent's: answering is a `POST`, so
the section is self-guarded - the gate closes `none`, the routes that run
it ask for `manage` themselves. What a reader sees follows one rule,
"an admin-level role or `manage`" (it was "admin-level or the `manager`
role"): drafts and results of the assessments in their read scope, on the
list, the grouped list, the detail, the results, a mass assessment and its
analytics. Anyone else sees the active assessments in their read scope or
that they take part in, without results - except their own, once done;
a mass assessment's analytics count only their own row for them. Taking
part is the other arm of the read scope, so whoever holds `manage` - a
raised role that heads no division included - reads drafts and results of
the assessments they take part in, as the `manager` role always did. `hr` at the default `view`
keeps that read through the admin tier; a `manager` lowered to `view`
loses drafts, results and every authoring route. The SPA follows the same
level: the section's pages, detailed results and the employee card's
"Create assessment" read `manage`, the card's Assessments tab needs the
section open. The card's development-plan entry reads `manage` on
`development` - each entry in that menu asks its own section.

For development plans the first question is the tenant's matrix since
HRP-825: every authoring route - create, edit, items, materials, reorder,
version restore and `POST /ai/suggest-pdp` - asks `manage` on
`development` in place of the admin/manager role list; the table above is
still the fence behind it. Two role checks became "an admin-level role or
`manage`": who sees other people's draft plans in `GET /pdp`, and who
walks the full status graph in `POST /pdp/{id}/status` (anyone else may
only submit their own plan for review). `hr` holds `view` by default and
keeps both through the admin tier, but authors nothing until raised. The
item toggle's review-time override stays admin-level only, as before.
`/analytics/pdp` (plan statistics, read by the analytics page) lost its
`admin`/`manager`/`hr` role list: the level opens it and the read scope
sizes it, so an employee counts their own plans - without the drafts
`GET /pdp` leaves out for anyone who does not run plans. The plan page
offers status actions on the same rule: the full graph to the admin tier
and `manage`, the owner's submit to the owner, nothing to anyone else.

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
outside it - HRP-638's rule applied to the children.

**Group runs are their author's** (HRP-640, Vladimir 29.09). A mass
assessment, a CPA round and a mass exam carry no assessee and no division,
only an author, so below the admin level the run is its author's. CPA rounds
(`GET /cpa` lists one's own; the round, its criteria, participants,
analytics and copy) and mass exams (`GET /mass-exams` lists one's own; every
route under `/mass-exams/{id}`) answer `403 not_the_author` otherwise - a
round that does not exist is refused the same way. A mass assessment's own
actions (rename, criteria, scale, bulk status) ask for the author on top of
the children rule, so a head does not reshape a run HR started over their
team; each assessment in it still follows the assessee rule on its own
routes, and the group's page and analytics keep their read scope - the
children in one's subtree and the ones one takes part in. The admin level
(`admin`, `hr`, `platform_admin`) keeps every run. Two reads stay on the
assessee scope as well: the CPA comparison on an assessment's page
(`GET /analytics/cpa-comparison`, one's own people across rounds) and an
employee's exams (`/exams`), where a head sees their people's exam from
another's mass exam. Narrowing by the participants instead of the author
waits for a request.

Development-plan reads follow their plan too: the plan itself
(`GET /pdp/{id}`, HRP-818), version list, version detail and
`GET /analytics/pdp/{id}/progress` all carry the plan's content, so they
answer only inside the reading scope and `403 outside_division_scope`
elsewhere. `GET /cpa/{id}/analytics` is a named
per-employee ranking and is scoped by assessee like `/analytics/cpa-comparison`.

What stays outside the fence:

- `GET /pdp/{id}`, `POST /pdp/{id}/status`, the plan's comments and versions
  and the item toggle (`POST /pdp/{id}/items/{item_id}/pass`) also admit the
  named reviewer (`reviewer_id` may point at any user — that is what naming
  one is for), and answers are gated on being a participant or that reviewer;
- the answer-scale catalogue is tenant-wide with no owning axis and is fenced
  by role instead (HRP-631).

`tests/unit/test_assessment_manager_scope.py` walks the route table and fails
on a mutating assessment/PDP route that carries no guard, so a route added
later cannot quietly reopen this.

## Exams

One menu entry, two audiences, and the tenant's `exams` row tells them
apart (HRP-823). `manage` runs the section: writing a mass exam, its
questions, pass marks and import, assigning employees, reading everyone's
results. `admin` and `manager` hold it by default, the setting moves it.

Reading a mass exam asks for `manage` too, not `view`, because a mass exam
carries the workspace's results and `view` means something else on this
section - the other audience. Everything under `/api/exams` is one
employee taking an exam of their own: `questions`, `answer` and `finish`
resolve the caller's own employee row and refuse anyone else (HRP-328),
`review` adds whoever's read scope covers the taker, and the list answers
that same read scope; its tabs and the To do count answer the caller's own
row (see "List tabs"). Those six are in `PERSONAL_PATHS`, so no level of
the matrix closes them outright - the assignment e-mail links straight to
`/exams`, and a section closed after the invitation went out must not
strand it. The page behind that link follows: it is outside the
front-end's section gate and renders the taker's own exams for anyone
below `manage`; the mass exam's own page (`/exams/{id}`) asks for
`manage`.

Outside the matrix is not outside the setting, though. On `exams: none`
the two routes that read more than one's own - the list and `review` -
narrow to the caller's own employee row, so closing the section still
closes everything of the section it can: a division head with `none` stops
reading their subtree's exams and keeps taking their own. Above `none` the
read scope answers as it always did.

What a mass exam does *not* have is an owning division, so below the
admin level it is its author's (HRP-640, see "Assessments and development
plans"): the list shows one's own mass exams and every route under
`/mass-exams/{id}` answers `403 not_the_author` for someone else's. Its
results table is not narrowed further: `GET /mass-exams/{id}/results` lists
every participant of that exam with their score, and the read scope only
decides whether the row links through to the profile (`can_view_profile`,
HRP-333) - the author sees how their own exam went.
Assignment (`POST /mass-exams/{id}/employees`) is not scoped either - it
refuses ids outside the tenant and takes any employee inside it, as it did
before the section was translated.

`platform_admin` reads the matrix as `manage` everywhere, so the mass
exams opened to it here; the role guard it replaced did not list it. That
follows the platform role's own rule - it is never gated - rather than
anything about this section.

## Analytics and the assessment export

Who opens the section is the tenant's `analytics` row in the section access
matrix (see "Section access"), not a role list: `view` reads the section's
charts, `manage` adds the two assessment exports and the development loop's
AI summary - the three writing methods. `admin`, `hr` and `manager` hold
`manage` by default, and the setting moves it (HRP-822). Two things the
page draws are not the section's to give: the plan statistics belong to
`development` and the salary figures to the payroll audience below, so a
role handed only `analytics` gets the page without them.

Aggregates and exports read the same rows the lists do, so since HRP-641 they
answer for the same scope. Seven routes used to call the service with a tenant
id and nothing else: `GET /analytics/assessments`, `/analytics/pdp`,
`/analytics/dev-loop`, `POST /analytics/dev-loop/ai-summary`,
`GET /analytics/cpa-comparison`, and both assessment exports.

| Actor | Figures cover |
|-------|---------------|
| `platform_admin`, `admin`, `hr` | the workspace |
| `manager` | their own record plus the managed subtree |
| anyone else the section is open to | their own record |

The level opens the page; the scope sizes the figures. That division is what
lets an admin hand analytics to a role that never had it without handing
over the workspace, so it has to hold on every payload the section serves -
HRP-822 closed the two it did not:

- `GET /analytics/compensation` and `/analytics/compensation/benchmark` were
  `require_role("admin")` and nothing else, so the role guard was the whole
  fence and there was no scope under it. They are read-scoped now, and they
  keep an audience of their own on top of the section: `admin` and a
  division manager, the same pair that reads an employee's compensation
  rows on their card (HRP-221), and deliberately not `hr`. Pay is a data
  class, not a level - an average over a one-person division is that
  person's salary, so the section opening cannot be what opens payroll. A
  manager reads their subtree's figures, which is the scope their card
  access already covers; `admin` reads the workspace. Since HRP-829 the
  audience is the card's pay tab itself - `manage` on `employees` (`admin`
  and `manager` by default, `hr` once raised) - and below the admin level
  the figures leave out the admin-level people that tab refuses.
- `GET /analytics/division-matrix` carried no guard at all, so any signed-in
  employee could read the workspace's division headcounts directly (the
  analytics page was its only caller). It is scoped by the managed subtree
  now - `get_visible_division_ids`, the divisions the caller manages.
  Narrower than the employee scope beside it on purpose: that one adds the
  caller's own record, and a manager whose own card sits in the parent
  division must not read the parent's headcount to see themselves in it.

`/analytics/my-loop` and its summary are personal and stay outside the
matrix. `/analytics/pdp` belongs to `development` (the registry's longest
prefix wins), so a role whose `development` is `none` is refused there -
the page leaves the two plan cards out rather than drawing the zeroes a
swallowed 403 would give it.

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

One menu entry, two audiences, and the tenant's `talent-market` row of the
section access matrix tells them apart (HRP-824). `manage` authors the
board: every writing route - creating, editing, publishing, closing,
staffing and deleting a card, its requirements and its candidate pool -
asks the matrix for it. `admin` and `manager` hold it by default, the
setting moves it. `view` is the candidate's half of the same entry: the
search, the cards one's own name is on, one's own match breakdown, the
reaction and the plan request. Three of those are `POST`s, so the section
is self-guarded (see "Section access"): the gate closes `none`, and the
routes that run the board ask for `manage` themselves.

The level says who runs the board. Whose card it is stays the org
structure's answer (HRP-639), on the two axes `TalentCard` carries:

| Actor | Reads | Writes (at `manage`) |
|-------|-------|--------|
| `platform_admin`, `admin`, `hr` | every card | every card |
| anyone managing a division, at either level | published cards, their managed subtree, the cards they authored, and cards they are a candidate on | their managed subtree and the cards they authored |
| anyone else, at `manage` | published cards, the cards they authored, and cards they are a candidate on | the cards they authored |
| anyone else, at `view` | published cards they are a candidate on (drafts only when appointed) | nothing |

Until HRP-824 the last two rows were one row told apart by role: "holds
neither admin nor manager" read only the cards their own name is on, so a
role the tenant raised to `manage` would have created a card and then not
found it. The scope reads the level now. A `manage` caller with no subtree
reads what they author; a division head the tenant lowers to `view` keeps
reading their subtree, as the org scope always let them, and loses every
write control - `view` is the candidate's half, not a read-only manager.

Authorship is in the write condition, as it is for vacancies, because a card
may be filed under no division at all and would otherwise belong to nobody.
That is only safe because `division_id` is fenced on the way in: `POST
/talent-market` and `PUT /talent-market/{id}` refuse a division the caller
does not manage, so "I created it" cannot become a way to author a card into
somebody else's department and keep editing it.

Hidden cards answer 404 `tm_card_not_found`, the way this module has always
hidden a card, so the answer does not confirm somebody else's draft exists;
refused writes answer 403 `outside_division_scope`, and a write below
`manage` answers 403 `auth_insufficient_permissions` before the card is
looked at. Every card payload carries `can_manage` - false below `manage`,
whoever authored the card - so the UI never renders a button that would
403: a published card from another department shows on the board with its
action menu gone.

Delete stood on an admin-only role guard with no scope while the list's
action menu already offered it to a division head on their own cards, and
answered 403; it is `manage` plus whose card it is now, like every other
write.

Two routes cross into other sections. Building a development plan from a
candidate's gaps (`POST /talent-market/{id}/candidates/{id}/development-plan`)
writes a `development` record, so it asks that section for `manage` as
well - the rule HRP-821 set for a Coverage gap raising a vacancy - and the
"Create plan" button in the match drawer reads both rows. `hr` raised to
`manage` on the board still holds `view` on plans by default and is
refused there. The plan also goes into the candidate's record, so the
candidate has to be in the author's scope, as for `POST /pdp`: the pool is
workspace-wide, and a division head planning for someone elsewhere is
refused (`403 outside_division_scope`, HRP-856) - that plan is for the
employee's own manager or HR. The drawer keeps the button inactive for
such a candidate and says why. The other way round, posting a vacancy to the market
(`POST /recruitment/vacancies/{id}/talent-card`) writes a talent card from
the recruitment section. Posting stays the vacancy's authority (`manage` on
`recruitment` since HRP-830; `admin` / `recruiter` in HRP-667), but the market has to be open to the caller at all -
`view` or better on `talent-market` - so a hidden section, or one closed for
the recruiter's role, takes no postings, and the vacancy page greys the
button out with that reason next to it. Adding someone off the internal
shortlist to the pipeline (HRP-711) is recruitment's own write and does not
ask the market, and neither does editing a posted vacancy's library
competences (`PATCH /recruitment/vacancies/{id}/competences`), which
rewrites the twin card's required competences and re-matches its shortlist:
the card is the vacancy's twin (HRP-667) and the sync is what keeps it one,
whatever the market row says; no e-mail fires from it. That the recruiter
cannot open the card they posted, reading it as a candidate would, is
unchanged.

Nothing of this section leaves the matrix. The lifecycle e-mails link to
the card, and a candidate whose role the tenant closed the section for lands
on 403 behind that link: unlike an assigned exam, a candidacy is an
invitation to read rather than an obligation to finish, so closing the
section closes it. `platform_admin` reads the matrix as `manage`
everywhere and authors the board now; the role guard it replaced did not
list it.

**What this does not close.** `GET /talent-market/{id}/candidate-pool` and
`GET /talent-market/{id}/candidates/{employee_id}/breakdown` rank
the whole workspace by competence match, which is assessment-derived data the
employee card withholds outside the subtree. Narrowing it would defeat what
internal mobility is for — the pool exists to find people elsewhere in the
company — so the boundary there is a product decision still open, and not
part of this fence. (The positions catalogue was the same class of question;
HRP-637 answered that one — see "The positions catalogue" above.)

A card its reader competes on - reacted to, or the twin of a vacancy the
recruitment fence keeps them out of - is theirs to read as an applicant only,
even to a division head at `manage` (HRP-971; see "Recruitment").

## Coverage (`/api/work`)

A process (a work container) is not tied to a division, so the fence is the
process itself (HRP-810): its visibility, its access rules and its owner.
Who runs the section is the tenant's `coverage` row in the section access
matrix (see "Section access"), not a constant: `manage` there means every
process, the agent registry (`/api/ai-workforce`) and everyone's
assignments. `admin` and `hr` hold it by default, and the setting moves it
(HRP-821).

| Actor | List | Read a process, its steps, coverage, To do, skills, runs | Edit steps, run AI, accept | Access panel | Change owner, delete | Hire need, register an agent |
|-------|------|------|------|------|------|------|
| `manage` on `coverage` (`admin`, `hr` by default; `platform_admin` reaches it like every section) | every process | x | x | x | x | x* |
| `admin` / `hr` the matrix leaves at `view` (HRP-810 REDO: they see every process whatever the matrix says) | every process | x | own only | own only | `403` | `403` |
| owner | own and readable ones | x | x | x | `403` | `403` |
| reader: the process is `company`-wide, a rule names their role / position / them, or they do or check one of its steps | readable ones | x | `403` `work_container_edit_forbidden` | `403` | `403` | `403` |
| anyone else | nothing | `404` | `404` | `404` | `404` / `403` | `404` / `403` |

\* A hire need is Recruitment's record, so opening one also asks the matrix
for `manage` on `recruitment` - handing Coverage to a role does not hand
them a section the matrix keeps closed (HRP-821). A rule naming the
`employee` role reaches every account, since every account holds that
baseline (HRP-832).

A hidden process answers 404 on every route that names it or one of its steps
or runs, so the answer does not confirm it exists. Every container payload
carries `my_access` (`manage`, `edit`, `read`), and `GET /auth/me` carries
`sections.coverage` - `manage` for the section's managers, `view` once the
caller reads at least one process, absent otherwise - which is what opens the
menu entry. The routes behind it need no process: a caller the matrix leaves
at `view` reads an empty list rather than a 403.
Skills in a profile never grant access: being able to do the work is not a
reason to read somebody else's process.

A reader outside the roles that read HR data (`admin`, `hr`, `platform_admin`,
`manager` - `access_scope.is_employee_only`, inverted) gets the coverage with
the matched colleague removed and an assignee's missing capabilities emptied;
the verdicts stay. `GET /api/work/containers/{id}/people` - the people an
editor can name as owner, rule or assignee - is the owner's and the managers',
tenant-wide rather than directory-scoped, and carries only what the directory
already shows plus `assignable`.

Leave follows the section level, not the HR roles (HRP-1020): an assignee, an
accountable or an owner on leave reads as on leave - and `assignable` as
false - only to a caller with `manage` on `coverage`; anyone else sees them at
work. Someone who left the company reads as gone to every reader (HRP-623,
HRP-959).

## Recruitment (`/api/recruitment`, `/api/reports`, and its `/api/v1` routes)

Who works in hiring is the `recruitment` row of the section matrix (HRP-830).
`manage` runs hiring; below it two roles keep a piece of their own on the
vacancies in their scope (Maxim, 25.09), so the section is self-guarded:
every write asks for `manage`, one of those two roles, or the admin / hr
role itself, and the gate closes `none`. The `employee` cell is capped at
`none` (a role ceiling, see "Section access"): the Employee role never
works in hiring, and the matrix screen shows the cell locked.

| Caller | Reads | Evaluate: questions, human scores, the candidate's stage | Hiring rounds: rounds, evaluators, scores, invites | Run hiring: vacancies, candidates, interviews, AI analyses, consents, reports, hiring-round scales |
|---|---|---|---|---|
| `manage` holding an admin-level role or `recruiter` (`admin`, `hr`, `recruiter` by default) | the whole workspace | x | x | x |
| `manage`, any other role (`manager`, `hiring_manager` raised by the tenant) | their vacancies | x | x | x, on their vacancies |
| `view` holding `recruiter` | the whole workspace | `403` | `403` | `403` |
| `view` holding `hiring_manager` | their vacancies | x, their own column of the scores | `403` | `403` |
| `view` holding `manager` | their vacancies | `403` | x | `403` |
| any other `view` | their vacancies | `403` | `403` | `403` |
| `none` | `403` | `403` | `403` | `403` |

"Their vacancies" is the HRP-629 scope: the vacancies they are the named hiring
manager of or that sit in a division they manage, and everything that hangs
off them; authorship alone no longer reaches a vacancy (HRP-830 REDO). An admin-level role (`admin`, `hr`, `platform_admin`) and the
`recruiter` role read the whole workspace at any level the section is open to
them (`UNRESTRICTED_ROLE_CODES` in `recruitment.scope`, HRP-830 REDO, QA
14.10); `manage` alone no longer does - a manager runs hiring on their own
divisions, a hiring manager on the vacancies they are named on. A write
outside the scope answers `403 outside_recruitment_scope`, a write the level
does not reach `403 auth_insufficient_permissions`.

`manage` inside the scope (`runs_hiring`): every hiring resource a `manage`
route names in its path resolves back to a vacancy in scope
(`PATH_SCOPE_KEYS`), a vacancy named in the body too (attaching a candidate).
Linking an existing candidate to a vacancy hands their card over, so a scoped
caller links only one already in their scope (`assert_candidate_linkable`,
fail-closed). Someone already a candidate elsewhere is attached by a recruiter
or HR: the duplicate warning (manual add, resume dedup preview) tells a scoped
caller the email is taken without naming the candidate - that the email exists
in the tenant is the price of one candidate per email. Archiving a candidate
is tenant-wide, so a scoped caller archives one only when every application
is theirs; otherwise they detach it from their own vacancy. Fan-out
notifications with no named recipient go only to the roles that run all of
hiring, and the twin card of a vacancy one applied to is fenced on the talent
market the same way as the vacancy (`UNRESTRICTED_ROLE_CODES`).
The writes that land outside every vacancy are the whole workspace's
(`runs_all_hiring`): a candidate added on their own - a scoped caller adds
candidates from one of their vacancies - and the section's onboarding and
demo data. Creating or re-homing a vacancy keeps it in the caller's scope
(`assert_vacancy_placement`): a division of their subtree, or - holding the
`hiring_manager` role - themselves as its hiring manager; authorship does not
count. The Division picker offers a manager their subtree, the Hiring manager
picker offers a hiring manager with no division only themselves. The
workspace summary (`/recruitment/analytics/summary`) counts the caller's
vacancies, and a bulk AI analysis only the applications of the vacancy in its
path.

Next to the level:

- **Scores belong to their evaluator.** Below `manage` the hiring manager
  edits and reverts their own column of the human scores; another
  evaluator's cell is `manage`'s (Maxim, 25.09). A hiring-round sheet is its
  evaluator's at every level - scoring it and submitting it. A stage change
  stays inside the vacancy's own funnel.
- **The HRP-971 fence** keeps a candidate off the vacancy they applied to
  below `UNRESTRICTED_ROLE_CODES` - a manager raised to `manage` included;
  the admin level and the recruiter stay unfenced, as they read everything.
- **A round's averages read like its sheets** (HRP-1081): every reader of
  the round in scope, live or closed, gets its per-competence averages and
  who gave which score (`GET /v1/assessment-rounds/{id}/aggregate`). An
  evaluator of a live round still sees only their own numbers until their
  sheet is in (HRP-373).
- **The tenant settings' writes stay the `admin` role's** - the funnel
  stages, the consent templates, the LLM and transcription providers, the
  interview-analysis scales (`/recruitment/settings/scales`), branding,
  retention and the assessment-matrix settings, as they were. The settings
  UI follows the audiences the APIs already admit (HRP-1045): the
  hiring-round scales tab (`/v1/assessment-scales`) is `manage`'s, reads
  and writes; branding and the consent templates read at `manage` or the
  admin role (`reads_hiring_settings`), with the save and create controls
  kept for admin; retention and the role list read as `admin` or `hr`, and
  saving retention stays admin's; the LLM and transcription provider tabs
  stay the admin role's alone. The menu entry and the settings hub show
  only the tabs the caller can open.
- **GDPR and the audit log stay `admin` and `hr`** - export, erasure, the
  request list, the audit log, and reading the retention and role settings.
  `manage` alone does not reach them; an `hr` the tenant lowers to `view`
  keeps them.
- **The AI analysis payload** is full for an unrestricted scope or `manage`
  (`RecruitmentScope.full_payload`), the hiring-manager slice for the
  `hiring_manager` role and
  stripped for everyone else (`resolve_user_role`). `platform_admin` reads it
  in full now; the old role list left it out.
- **The vacancy's candidate table** (`GET …/candidates/enriched`) reads at
  `view` in scope, like the assessment matrix beside it that carries the same
  AI scores. The role list used to leave `manager` out, and a division head's
  candidate table came up empty.
- **Notifications with no named recipient** (a consent signed after its
  requester left, a failed AI task) go to the roles the tenant's matrix gives
  `manage` on recruitment - `admin`, `hr` and `recruiter` by default, the
  list this used to be.
- **A position's grade pair** (`can_see_position_grades`) goes to anyone the
  section is open to rather than to the `recruiter` and `hiring_manager`
  roles: raising a requisition needs it.

The hiring rounds, the question sets and the scales live under `/api/v1`
next to the API-key surface. Their prefixes belong to the section, so
closing it closes them too; the evaluator and candidate token links
(`/v1/public/assessments/{token}`, `/recruitment/invite/{token}`,
`/recruitment/consent/{token}`, `/reports/share/{token}`) stay outside the
matrix.

Consequences taken with the defaults: `hiring_manager` defaults to `view` -
it never authored here, and its evaluation stays with the role; `hr` keeps
`manage`, and with the level replacing the `admin`/`recruiter` role list it
now authors hiring across the workspace - vacancies, candidates, interviews
and AI analyses, which spend credits. `platform_admin` reaches the matrix as
`manage` and so authors hiring as well.

Cross-section writes: a hire need raised from Coverage asks for `manage` here
(HRP-821); posting a vacancy to the talent market asks for `manage` here and
`view` on `talent-market` (HRP-824); editing a posted vacancy's library
competences rewrites its twin card, as HRP-824 accepted. Adding an employee
off the internal shortlist copies their current and previous employment and
education into the candidate's resume, which the caller then reads as a
candidate although the `employees` section shows them the directory only -
accepted (Maxim, 25.09): internal mobility is what the shortlist is for.
Compensation and events are not copied.

**A vacancy one applied to is out of one's scope** (HRP-971, Maxim 29.09).
Below the admin level and `manage`, the scope drops every vacancy the caller
applied to - a candidate on it, matched by their `Person` or their email (the
two keys an internal candidacy is reused by, HRP-711), or having reacted to
its talent-market twin before any recruiter moved them into the pipeline -
with everything hanging off it: its candidacies, internal shortlist,
interviews, analyses, questions, reports and rounds, the caller's own
candidacy included. A rival who also applied to a vacancy the caller does
reach stays readable there - their card and resume, and only the applications,
questions and question sets of that vacancy.
Hiding only one's own candidacy
would have left the rivals: a deputy head applying for their head's seat
reached the vacancy through their managed subtree and read the other
applicants' verdicts and scores, and as a `manager` could open a round on
any of them. The fence
- holds after the vacancy closes and the candidacy ends, so neither the
  rejected deputy nor the one who got the seat reads what was written about
  them or about the people who became their reports;
- outranks being the vacancy's creator or named hiring manager;
- leaves the admin level and `manage` alone - they run hiring for the
  workspace; an `hr` or a `recruiter` applying internally is a known
  remainder of this rule, taken up in HRP-1012;
- applies to the recruitment mail too, on the request path and in the
  background tasks: a notification about a vacancy - or about an interview
  of it - skips a recipient the fence keeps out of it; where the event falls
  back to the hiring users, they get it instead.

The vacancy stays with whoever else reaches it - the head of the parent
division, `hr`, the recruiters.

Nobody the fence keeps off a vacancy interviews or evaluates on it: naming
them an interviewer (`POST`/`PUT` of an interview) or a round's evaluator
answers `422 assignee_fenced_off`, and the interviewer and evaluator pickers
of a candidacy leave them out - they could open neither the interview nor
the sheet, and a pre-interview round's single slot would be stuck with them.
An evaluator link by email is refused for any candidate on the vacancy,
fenced or not: its token opens the sheet past the matrix, and a resend
checks again. Only who is added to an interview is checked, so one edited
later keeps whoever was already on it.

The fence is held by the candidate's link to the vacancy, and "Remove from
this vacancy" (`DELETE /recruitment/candidate-vacancies/{id}`) drops that
link together with everything hanging off it - the candidacy's interviews,
scores, AI analyses, evaluator invites, question sets and rounds. So a
candidacy with any of those is not removed (`409
candidate_vacancy_has_history`, HRP-1004, Maxim 29.09): it is closed by
stage, Rejected or Withdrew, and the fence stays. A bare link - someone
added by mistake - is removed as before and lifts the fence with it.

The fence reaches the talent market too (Maxim, 29.09). Below the admin level
a card the caller competes on - one they reacted to, or the twin of a vacancy
the fence keeps them out of - reads as it does for a rank-and-file applicant:
listed and opened only while they are on it and it has left Draft, their own
row and match breakdown only, and none of its actions are theirs (`403
outside_division_scope`), whatever division they head. A division head merely
matched to a card, without reacting, runs it as before. One who runs a card
may still react to it: the confirmation says that, once they compete, the
card is no longer theirs to run (admins and `hr` are never fenced and get
the plain confirmation). Nor do the card's letters about an employee - reacted,
appointed, cancelled, a plan asked for - reach the employee's manager while
that manager competes on the card: the letter would name a rival and their
outcome. A plan request then answers as if the division had no manager to
take it, which says nothing about who competes.

## Section access (the tenant matrix)

An admin narrows which menu sections each role opens on
`/settings/roles/section-access`, the Roles page's Configure entry
(`GET`/`PUT /api/settings/section-access`,
admin only): `none`, `view` or `manage` per section and role, or hidden for
everyone. The registry in `app/core/sections.py` is the source of truth -
which API paths make up a section, the defaults below, and the flags. Only
deviations from the defaults are stored (`tenant_section_settings`,
`tenant_section_access`), one row of `tenant_section_access_log` per save
carries the diff, and empty tables are exactly today's behaviour.

| Section | admin | hr | manager | recruiter | hiring_manager | employee |
|---|---|---|---|---|---|---|
| employees | manage | view | manage | view | view | view |
| company | manage | view | manage | view | view | view |
| assessments | manage | view | manage | view | view | view |
| development | manage | view | manage | view | view | view |
| exams | manage | view | manage | view | view | view |
| competences | manage | manage | view | none | none | none |
| coverage | manage | manage | view | view | view | view |
| talent-market | manage | view | manage | view | view | view |
| recruitment | manage | manage | view | manage | view | none |
| analytics | manage | manage | manage | none | none | none |
| dictionaries | manage | manage | none | none | none | none |
| import | manage | none | none | none | none | none |
| invitations | manage | manage | manage | none | none | none |
| roles | manage | none | none | none | none | none |
| ai-settings | manage | none | none | none | none | none |

The defaults are today's behaviour read from the code - the sidebar flags
for visibility, the privileged mutations for `manage` - oddities included
(`hr` does not write on `/employees`, `manager` does not edit the
competence catalogue). The `competences` and `dictionaries` rows were
narrowed on QA's request of 13.10 (HRP-827, see "Catalogues").
`test_section_defaults.py` pins this table.

**Every section reads the matrix.** HRP-821…831 put each section's routes
on `require_section`, so all three levels mean something everywhere and the
tenant may raise a role above its default as well as lower it. The clamp
that narrowed a section before its routes read the matrix went with
HRP-832: a section added later puts its own routes on `require_section`,
nothing narrows a raised level for it any more (`test_section_registry.py`
only makes sure the registry places every route). The one
global gate (`section_gate`, a `FastAPI(dependencies=[...])` entry)
answers `403 auth_insufficient_permissions` for `none` and for a hidden
section on every route of that section - for admins too. `platform_admin`
is never gated, and a caller holding none of the six configurable roles is
read as the `employee` baseline every account holds.

The gate also answers `403` when `view` meets a
writing method - except on a *self-guarded* one, where the section's own
dependencies rule the writes because they are finer than a method.
`coverage` is self-guarded: the process's owner edits it whatever their
role, and anyone the section is open to may ask for an agent for
themselves, while the routes that run the section - the processes and the
agent registry - ask the matrix for `manage`. The two internal mapping
routes (`/api/primitives/internal/*`, no UI, stripped from the public
OpenAPI) stay on `require_role("admin")`. `talent-market` is self-guarded
too: its `view` half is three `POST`s - the search, the reaction, the plan
request - while every route that runs the board asks for `manage` (see
"The talent board"). `development` likewise (HRP-825): the plan's owner
submits it for review, ticks items and comments, the named reviewer ticks
items during the review and comments - all `POST`s at `view` - while authoring asks for `manage` (see
"Assessments and development plans"). `assessments` too (HRP-826): the
respondent answers at `view`, everything that runs the section asks for
`manage`. `company` too (HRP-828): `hr` edits the specialization ladder and
matrices at `view` by role, everything that shapes the org chart asks for
`manage` (see "Division writes"). `employees` too (HRP-829): anyone writes
their own education and courses at `view`, every other write asks for
`manage` or the admin role (see the `/employees/*` write matrix).
`recruitment` too (HRP-830): the `hiring_manager` role evaluates and the
`manager` role runs hiring rounds at `view`, every other write asks for
`manage` or the admin / hr role (see "Recruitment"). The gate still closes
`none`.

**What the gate does not touch.** Routes outside the matrix (`/auth`,
`/v1` - the API-key surface; recruitment's own `/v1` routes belong to its
section, see "Recruitment" -, `/platform`, `/billing`, `/ee`, `/blog`, `/ai`, `/notifications`,
`/settings/notifications`, `/settings/email-logs`, `/webhooks`, `/files`,
`/api-keys`, `/demo`, `/signup-request`, `/public`, `/tasks`, `/feedback`);
WebSocket connections; routes with no user to narrow (token links - `/review/{token}`,
`/recruitment/invite/{token}`, `/recruitment/consent/{token}`,
`/reports/share/{token}`); and one's own profile, loop and exams -
`/employees/me`, `/analytics/my-loop`, `/analytics/my-loop/ai-summary`,
`/exams` and the four routes behind an exam id - whatever the matrix says;
and the catalogue and org-chart reads other sections are built on
(`SHARED_READS`, their `GET` only - see "Catalogues" and "Division writes"). A hidden `development` closes one's own plan
too (`/pdp/{id}` is not told apart by path), and HRP-825 kept it that way:
unlike an assigned exam, a closed section means the tenant stopped running
plans for that role. The dashboard does not read the plan, so it survives;
the employee card drops its Development tab. Since HRP-829 the employee list
and the card (`GET /employees`, `GET /employees/{id}`) are shared reads -
every people picker is built on the list - so a role whose `employees` is
`none` keeps the list in the API, while the pages bounce and the card's
sub-resources (events, experience, education, pay, competences) answer
`403`: one's own included, the same trade-off as one's own plan. The card
itself closes at `none` by its own rule (REDO QA 14.10, see "Who opens a
card"), as `404` like an unknown id.

**Lockout protection**, checked on `PUT` and again when resolving: the
admin block (`dictionaries`, `import`, `invitations`, `roles`,
`ai-settings`) and `company`, where the screen lives, keep `manage` for
`admin` and cannot be hidden (`400 section_access_admin_locked`,
`section_access_cannot_hide`); `employees` cannot be hidden either. An
unknown section or role code is `400 section_access_unknown_section`.

**Role ceilings** (HRP-831): a section may cap what the matrix hands a role
(`Section.ceilings` in `core/sections.py`) - `invitations` is `none` for
`recruiter`, `hiring_manager` and `employee`, `roles` at most `view` for
every role but `admin`, `employees` at most `view` for `recruiter`,
`hiring_manager` and `employee` (HRP-829 REDO). A save above the ceiling is
`400 section_access_role_ceiling`, a row stored before the cap is dropped
on read, and the effective level never goes above it. The screen locks the
levels above the ceiling - the whole cell when it is `none` - with the
reason in a hint. The recruitment cap (`employee` at `none`, HRP-830) is
described with its section.

`GET /auth/me` carries `sections` - every section the caller opens and how
far, the strongest of their roles; hidden and `none` are absent. Since every
account holds the `employee` baseline (HRP-832), the Employee column is the
floor of its row: a role set below it opens the section at the Employee
level anyway. The screen offers no level below that floor and explains a
cell saved under it (HRP-998); the API still stores such a cell as sent. Coverage
narrows its own entry further: `view` needs at least one readable process,
`manage` never does. The dynamics live in `/auth/me`
alone - the gate reads the matrix only, so a caller who reads no process
still gets the `/api/work` routes' own answers (an empty list, 404 for a
hidden process) rather than a blanket 403. The SPA hides a menu entry
whose section is absent, bounces a direct link to the dashboard, and
keeps a role flag on top only where a section says so. The admin block's
entries open at `view` (HRP-831; see "The admin block" below) -
`dictionaries` too since QA 13.10 on HRP-827, read-only below `manage`;
its pickers stay open to every role on the API (`SHARED_READS`).

Analytics has `none` cells by default, so it is
where the split by method shows: a role the tenant lowers to `view` keeps
every chart and loses the two exports and the AI summary, and the SPA
hides those two buttons rather than letting them answer 403. Its role flag
in the SPA is gone with the translation - the menu entry, the page and the
export button read `sections.analytics` alone. What the figures cover is a
separate question the read scope answers; see "Analytics and the
assessment export".

### List tabs (HRP-823…826)

The lists of exams, assessments, development plans and the talent market
open in tabs (QA 13.10). The section's own tab is the list as it was and
shows at `manage` only; the other two show at every level that opens the
page and answer for the caller's own employee row (assessments: the
caller as a participant) whatever their level or read scope - a division
head holding `manage` sees only their own there, not their subtree's.
`hr` sits at `view` on all four by default, so it reads only its own items
on these pages until the tenant raises it to `manage` - the admin tier's
read scope still answers the detail pages and the API without `tab`.

| Section | Tab | `?tab=` | What it lists |
|---|---|---|---|
| exams | My exams | `mine` | one's own exams whose mass exam left Draft |
| exams | To do (N) | `todo` | the same, `assigned` or `in_progress` |
| assessments | My assessments | `mine` | past Draft, where one takes part as Self |
| assessments | To do (N) | `todo` | neither Draft, Done nor Cancelled, where one takes part in any role and one's questionnaire is not completed |
| development | My plans | `mine` | one's own plans past Draft |
| development | To do (N) | `todo` | the same in `sent`, `in_progress` or `returned` |
| talent-market | I'm a candidate | `mine` | the cards past Draft one is a candidate on, and the Draft ones one is appointed on (`employee_read_filter`) |
| talent-market | I'm appointed | `appointed` | the cards one is appointed on, Cancelled aside |

One contract: `?tab=` on the list the page already reads (`GET /api/exams`,
`GET /api/assessments-grouped`, `GET /api/pdp`, `POST
/api/talent-market/search`), and `GET <that list>/todo-count` -> `{"count":
N}` for the To do label. Without `tab` every list answers as before. A tab
lists assessments one by one, mass ones included - the group card would
open everyone else's rows. The page keeps the tab in its URL, falls back
to the first visible tab for one it does not show, and the letters to the
person on a plan or an exam open the tab that holds it (To do while it
waits on them, My once closed); a reviewer's letter keeps the bare list.

## Error codes returned on `/employees/*` write rejections

| HTTP | `error_code`                | Reason |
|------|-----------------------------|--------|
| 401  | `employee_status_blocked`   | Actor's own employee card is `terminated`/`inactive` (auth-guard layer). |
| 403  | `auth_insufficient_permissions` | Below `manage` on `employees` (the router gate), or not the admin role on the admin-only routes. |
| 403  | `outside_division_scope`    | A `manage` holder wrote a target outside their managed subtree, or filed / moved someone into a division outside it (or into none). |
| 403  | `cannot_edit_self_status`   | A `manage` holder below the admin level mutated their own card or touched their own pay; use `PUT /auth/me`. |
| 403  | `employee_write_forbidden`  | Below `manage` writing on somebody else's education or courses (the self-service routes have no router gate), or below the admin level writing an admin-level person's record. |

## Self-edit policy

- `PUT /auth/me` accepts only allowlisted profile fields (first/last name, avatar, phone, language). Status, role, email, and tenant cannot be changed via this endpoint — the schema rejects unknown fields with `extra='forbid'`.
- All organisational fields (`division_id`, `position_id`, `position_title`, `status`) are mutated through `/employees/*` and require an admin-level role at `manage` on `employees` for self-edits (`admin` by default); a `manage` holder below the admin level cannot mutate their own card here.

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

Admin-only (`require_admin`, so the enterprise platform role passes too). The call replaces the user's tier role with the requested one and keeps the `employee` baseline beside it (`employee` itself means the baseline alone), leaving any `platform_admin` membership untouched — that role is granted platform-side and cannot be assigned or stripped here. Every change writes an `EmployeeEvent` of type `role_changed` carrying the old and new tier codes, `employee` standing for the baseline alone.

Rejections:

| HTTP | `error_code`              | Reason |
|------|---------------------------|--------|
| 400  | `role_code_not_found`     | Not a seeded system role, or `platform_admin`. |
| 422  | `cannot_change_own_role`  | Caller is the target. |
| 422  | `last_admin`              | Target is the workspace's only active admin. |
| 422  | `still_division_manager`  | Target still leads a division as manager or deputy. |

### The admin block: import, invitations, roles, AI settings (HRP-831)

The four entries follow the matrix like any other section: `view` reads
(the import history, the AI settings with their presets, models and
provider statuses, the role list, the invitations in one's scope), `manage`
writes (starting an import, saving or resetting the AI settings, writing a
role, sending, editing, cancelling and resending invitations). All four are
admin-locked and never hidden, so the admin keeps `manage` whatever the
tenant saves; `platform_admin`, which the literal `require_role("admin")`
used to keep out of import, roles and AI settings, reaches them like every
section. Two cells are capped (QA 15.10): `recruiter`, `hiring_manager`
and `employee` never reach invitations - an invitation is a seat in a
division they do not head - and no role but `admin` writes roles, since
`manage` there would add nothing to `view` with the matrix screen itself
the admin's. `GET /api/roles` is a shared read - the invitation form is built
on it - answered to whoever opens roles or invitations at `view` or
better (it carries how many people hold each role). `POST`, `PUT` and
`DELETE /api/roles` still create, rename and remove a tenant role at
`manage`, but nothing assigns one yet - neither the employee card nor an
invitation offers it - and its code is unique across the platform. Custom
roles that rule both sections and data wait for a customer request
(HRP-976).

Invitations narrow by org structure below the admin level. Admin-level
roles (`admin`, `hr`, `platform_admin`) see and run the whole registry;
anyone else - a `manager`, or a role the tenant raised - sees only the
invitations whose division is in the subtree they head, and sends, moves,
cancels or resends only there (`403 outside_division_scope` otherwise). An
invitation with no division is nobody's below the admin level: such a
caller neither sends one nor sees one, and a `manage` holder heading no
division sends nothing. The invitations page offers the pickers of
`/api/divisions/scope` accordingly. Which role an invitation may carry stays
the inviter hierarchy's (below), and changing the role of a sent invitation
(`PATCH /api/invitations/{id}` with `role_code`) stays the admin level's
(`403 only_admins_can_change_invitation_role`; the rbac seam, so the
enterprise platform role passes too). Re-addressing an invitation is
sending it, so editing, cancelling and resending are open only on
invitations whose role the caller could hand out (`403 role_above_inviter`
otherwise): `hr` never re-addresses an admin invitation to themselves, nor
a manager an `hr` one sent into their subtree. A position on an invitation
follows HRP-829: a seat of the caller's subtree or a workspace-wide one.
Consequence, on the record: `hr` and `manager` held `manage` on the API
before this ticket but no page; with the translation they open the
registry - `hr` the workspace's, `manager` their subtree's.

What stays by role: setting a role and resending the set-password link on
the employee card (`require_admin`), the company profile and the
section-access screen (the admin role, HRP-828), billing (enterprise).

### Invitation role hierarchy

`POST /api/invitations` and `POST /api/invitations/bulk` reject any `role_code` above the inviter's tier:

| Inviter role           | May invite                                                                    |
|------------------------|-------------------------------------------------------------------------------|
| `platform_admin`       | `platform_admin`, `admin`, `hr`, `manager`, `recruiter`, `hiring_manager`, `employee` |
| `admin`                | `admin`, `hr`, `manager`, `recruiter`, `hiring_manager`, `employee`           |
| `hr`                   | `hr`, `manager`, `recruiter`, `hiring_manager`, `employee`                    |
| `manager`              | `employee` (only)                                                             |
| `employee`, any other  | `employee` (only) - the floor of every inviter; whether such a caller invites at all is the invitations section's question (HRP-831) |

The invitations page mirrors this table; `frontend/src/__tests__/invite-tiers-parity.test.ts` fails if the two drift.

The invitation *registry* - listing, editing, cancelling and resending - is the
invitations section (`view` reads it, `manage` runs it; HRP-831), narrowed to the
caller's subtree below the admin level - see "The admin block" above. Before
HRP-831 it was admin-only (`require_admin()`), and `hr` and `manager` could
create through `POST /api/invitations` without a page for it.

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
