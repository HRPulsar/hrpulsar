# HRPulsar Features

Complete reference of all platform capabilities. HRPulsar is an open source talent and competency management platform built for HR teams, managers, and employees.

---

## Employee Management

### Employee Profile header KPIs
Five tiles across the employee detail page header — Status, Tenure, Assessments, Goals progress, Last assessment. Each tile pulls from data already loaded in the page so the numbers stay consistent with what the role sees on the tabs below.

- **Status** sub-line reads "since {date}" where date is the last `employees.status_changed_at` mutation (falls back to `created_at` for rows that pre-date the column). Stamped server-side every time the status mutates so the value never drifts from the events log (HRP-246).
- **Tenure** anchors on the user's first successful login (`users.first_login_at`, stamped on first auth) — the tile reads "joined {first auth date}" and the duration counts time spent using the system, not the formal hire date. Falls back to `hire_date` for accounts that have never logged in (HRP-246).
- **Assessments** sub-line spells out the open count ("N open assessments") where "open" means `status_code not in (done, cancelled)`, instead of surfacing the latest row's status (which read as random) (HRP-246).
- **Goals progress** averages completion across the employee's open development plans (plans not yet Done or Cancelled). Each plan's progress is the share of items the owner has ticked off (`items completed / items total`). An (i) icon next to the tile label spells out the formula on hover so reviewers do not have to guess what "55%" means (HRP-247).
- **Last assessment** mirrors what the tab below shows — Employee viewers never see Draft assessments, so the "latest" row matches the visible list (HRP-246).
- Tile counts respect the same role-based visibility the tabs use: Employee viewers never see Draft assessments or Draft PDPs, so the KPI "N open …" sub-line matches the visible list below.

### Employee Profiles
Centralized employee records with position, division, hire date, and status tracking. Each employee is linked to a user account and can belong to an organizational division.

- Two ways to add employees:
  - **Via invitation** — send an email invite with role, position, and division; employee card is created automatically when the person accepts
  - **Manual add** — select from existing users who don't yet have an employee record; the dropdown shows each user's origin (invited / self-registered)
- Create, update, and view employee cards
- Profile avatar upload with hover-to-edit on profile page
- Avatars displayed in header, employee list, and employee detail pages
- Status lifecycle: active, inactive, on leave, terminated
- `terminated` and `inactive` revoke system access immediately — the auth guard, login, refresh, and tenant switch all reject blocked accounts with `error_code=employee_status_blocked`
- Status changes (`terminated`, `inactive`, reactivation back to `active`) email the affected employee directly
- Division assignment with hierarchical structure
- Hire date tracking and employment timeline
- Write-scope on `/employees/*` follows the role matrix: admins/HR/platform-admins edit any record; division managers edit only employees in their managed subtree (others get `403 outside_division_scope`); managers cannot edit their own card via these endpoints (`403 cannot_edit_self_status`) — profile self-edits go through `PUT /auth/me` (allowlisted fields only); the `employee` role is read-only on `/employees/*` and child resources (work experience, education, courses, previous employment, events, compensation)
- Manager role syncs with `Division.manager_id` / `deputy_manager_id` automatically: assigning an employee upgrades them to `manager`; clearing the assignment surfaces a confirm-dialog so an admin can downgrade the role back to `employee`. Admin / HR / platform-admin roles are never auto-modified. Invitations enforce the same hierarchy — an inviter cannot grant a role above their own tier (`403 role_above_inviter`).

### Employees List
Filterable directory of every employee in a tenant.

- Columns: Name + Email (stacked), Division, Position, Specialization · Grade, Status
- Multi-select filters for Divisions, Statuses, Positions, Specializations, and Grades — selections persist in the URL so views can be bookmarked or shared
- Specialization and Grade filters resolve through the employee's structured Position (`Position.specialization_id` / `Position.grade_id`)
- Managers see only the divisions they manage in the Divisions filter; admins/HR see the full tenant tree (`GET /api/divisions/scope`)
- Search input runs against the backend (`?q=…`) and matches first name, last name, full name, and email across every page of the list
- `GET /api/employees` accepts repeated query params (`division_id`, `status`, `position_id`, `specialization_id`, `grade_id`) for combined filtering with AND-semantics
- Edit dialog (list and detail page) edits Name, Last name, Position, Division, and Status in one PUT; admin/manager only, with the usual division-scope and self-edit guards

### Employee Events
Track important milestones and changes throughout an employee's career.

- Event types: hire, position_change, division_change, termination, compensation_change, certification_earned, assessment_complete, pdp_complete, exam_complete, grade_change
- Automatic events on position change, division change, termination, and compensation changes
- Change diff tracking with old/new values for position, division, and compensation changes
- Filter events by type on employee timeline
- Timeline view with chronological ordering
- Custom event descriptions and metadata

### Current Employment
Track Division/Position spells an employee has held within the current organization.

- Each record is anchored to a Division and a Position from the structured catalog
- Start date is required; End date is optional (ongoing spells supported)
- Free-text description for additional context
- Defaults — new records prefill Division, Position, and Start date from the employee card so the common "still in the current role" case is one click
- Tenure display — each record renders the elapsed duration (days under one month, months + days under one year, years + months above one) calculated against the End date (or today, when open-ended)
- Timeline view on employee detail page

### Previous Employment
Record employment history at other companies before joining.

- Company name, position, and dates
- Description of responsibilities
- Used for skills assessment and career path analysis
- Add/Edit dialog enforces Company name, Position, Start date and End date as required, restricts both dates to the past (max = yesterday in the picker) and rejects Start > End on the backend (HRP-219)

### Current Employment
Track in-company spells per division/position.

- Add/Edit dialog enforces Start ≤ End when an End date is provided — same backend guard runs on Pydantic, the picker also bounds the End date min by Start (HRP-219)

### Education
Formal education records — universities, colleges, degrees.

- Institution name, degree type, and field of study
- Start and end dates (ongoing education supported)
- Degree types: Secondary, Vocational, Bachelor, Master, PhD, Doctorate
- Institution, Degree, Field of Study and Start date are required on Add/Edit; Start ≤ End is enforced on both client and server when an End date is set (HRP-220)

### Courses & Certifications
Track professional development, training courses, and certifications.

- Course title and provider
- Certificate URL (external link to verification)
- Completion date and expiry date
- Expiry alerts — expired certificates are visually highlighted
- Supports both internal training and external certifications
- Title and Completed date are required; Completed date is bounded to the past (max = yesterday), Completed ≤ Expire is enforced when Expire is set (HRP-220)
- Competences developed is picked via the shared group-tree picker — same UX as Individual competences in Assessments, with expand/collapse, search, indeterminate group selection and Select-all per group (HRP-220)

### Salary & Compensation
Track employee compensation history — salaries, bonuses, and allowances. Admin / HR / Platform admin have full access across the tenant; division managers have the same view / add / edit / delete affordances on employees inside their own division subtree (own + children), and get `403 outside_division_scope` outside it (HRP-221 REDO).

- Compensation types: salary, bonus, allowance
- Amount in minor units with ISO currency code (USD, EUR, etc.)
- Effective date and optional end date for time-bound records
- Free-text notes for context
- Automatic employee event on compensation changes
- Full CRUD with compensation history timeline
- Add/Edit dialog rejects Effective > End on both the client and the Pydantic schema; backend save errors surface inline next to the form so a failed PUT no longer disappears as a fleeting toast (HRP-221)
- Compensation analytics: average salary by division, totals by type (salary/bonus/allowance)
- Analytics endpoint: GET /analytics/compensation (admin only)

### Competences tab
Two-block snapshot of the employee's competence profile, replacing the legacy radar chart that obscured which results belonged to which level.

- **Current position competences** — tree view (groups + subgroups, expand/collapse) of every (competence, skill level) pair the employee's position requires through its grade-specialization. Each row shows the percent from the latest Done assessment whose target level is at least the required level, averaged across breakdown rows from the lowest level up through the required level; a dash renders when no assessment ever reached the required level.
- A higher-level assessment cascades down via the HRP-90 breakdown — e.g. position requires Intermediate and the latest Done assessment targeted Advanced with breakdown Basic 100 / Intermediate 80 / Advanced 30 → the row renders 90% (average of Basic + Intermediate). Lower-level-only assessments never fill a higher required slot.
- **Other competences** — flat list with one row per competence the employee was assessed on at a level different from what Current position already shows. Includes assessments at a *higher* level than required (e.g. Junior with Advanced assessments) and at a *lower* level than required (e.g. Junior promoted to Middle with only Basic assessments — the Basic result stays visible). Skill level on the row is the highest assessed target; percent is averaged across breakdown rows from the lowest level up through that target. (HRP-217)
- Each row in both blocks exposes an `(i)` icon that opens a Skill level / Percent breakdown popup sourced from the latest Done assessment's cascade — same data shape the Assessments detailed results page uses.
- "Latest" means the assessment whose `finished_at` (then `ended_at`, then `updated_at`) is most recent — even when the newer assessment scored worse than an older one.
- Percent chips use frontend-only thresholds: ≥ 75% green, 50–74% yellow, < 50% red, `null` (no qualifying result) renders a grayed dash. Same scale applies to the per-level breakdown rows in the (i) popup. (HRP-207)
- Endpoint: GET /api/employees/{id}/competences (`/competence-overview` remains as a hidden alias for a few releases).

### Shared employee reference rendering
Every cross-module screen that names an employee (Assessment lists, PDP cards, Talent Market matches, …) uses the shared `EmployeeSummaryLine` component: Name + Last name on the top line, Current position grayed and slightly smaller underneath, and an inline status chip when the employee is not `active`. The Employees list (`/employees`) and the Employee profile (`/employees/{id}`) keep their own dedicated layouts. (HRP-182)

### Date inputs
Every date input across the Employee profile (Add employee, Events, Current and Previous Employment, Education, Courses, Compensation) renders the same custom `DatePicker` — a Tailwind-styled popover calendar with always-English month / weekday labels and per-field `min` / `max` bounds wired to the relevant validation. Native browser locale no longer leaks into the calendar. The input field applies a digit-only `yyyy-mm-dd` mask (non-digits are stripped and dashes inserted automatically). The popover header carries two clickable affordances — click the month label to flip the grid to Jan–Dec, click the year label for a 12-year grid — and the week starts on Sunday. (HRP-152)

---

## Organizational Structure

### Company Profile
Comprehensive company profile with industry and business sector information.

- Industry classification and company size ranges (1-10 to 5000+)
- Website and description fields
- Company logo upload (PNG, JPEG, SVG, WebP, ≤ 5 MB) with automatic replacement; supports drag-and-drop on the logo card, paste-and-import from a public URL (`POST /api/settings/company-profile/logo/from-url`, SSRF-guarded against loopback / private / link-local hosts), and magic-byte MIME detection so JPEGs browsers tag as `application/octet-stream` still land in S3 with the correct `Content-Type`
- Activity fields (business sectors) — configurable from dictionary
- Multiple activity fields per company (many-to-many)
- Logo and profile visible on public company page
- Dedicated UI page at /company/profile (tab in Company section, admin-only edit)
- Dedicated settings page: GET/PUT /settings/company-profile

### Divisions
Hierarchical organizational units (departments, teams, offices).

- Unlimited nesting depth (parent-child relationships)
- Tree view in UI with expand/collapse
- Employees assigned to divisions
- Division-level filtering across the platform
- Division manager assignment — display manager name on division tree
- Auto-assign division manager as assessment reviewer for employees in the division
- Role-aware list scope across employees / assessments / PDPs / exams / talent market: admins see the full tenant; division managers (and deputies) see their own row plus every employee in the managed subtree; regular employees see only their own records and any assessments they participate in. Talent market shows everything to admins and managers, and only published cards to regular employees
- Division detail page (`/company/divisions/{id}`) exposes inline Edit and a Specializations grid where each plate shows the exact employee count for that specialization within the division; clicking a plate filters the Employees block to that specialization
- Division detail Employees list uses the unified 7-column `EmployeeListRow` (Name → Position → Specialization → Grade → Division → Status → Hire Date) so the layout matches the positions drill-down and the specialization detail page (HRP-175)
- Division detail Employees block has AND-combinable filters: clickable Specialization plates plus Position and Grade dropdowns derived from the currently loaded employees. Active filters surface as chips with per-filter × buttons, a header counter shows "X of Y" while any filter is active, and a "Clear all" button appears when 2+ filters are set. The empty state distinguishes "no employees in this division" from "no employees match the current filters" (HRP-58)
- Division detail page exposes an "Add employee" action (in the Employees block header and as a CTA inside the empty state) that opens a contextual dialog with two tabs: Add existing (multi-select picker filtered to employees not yet in the division, optional Position override, confirm-step when picks come from a different division) and Create new (existing user picker with a "?" tooltip explaining who is listed and an admin-only "+ Invite" shortcut to `/settings/invitations`, hire date, optional Position; Division locked to the current page). All select triggers render the picked title — not the underlying UUID. Active filters and current selection are preserved across submits (HRP-174)
- Assigning a Manager or Deputy Manager to a division auto-upgrades the chosen user from Employee to Manager and surfaces a "promoted to manager" toast in the Edit dialog; reassigning auto-downgrades the previous manager back to Employee when they lose their last division (Admin and Platform Admin roles are preserved). The original Invitation row keeps the role it was sent with (HRP-196)

### Positions
Structured job positions with optional grade, specialization, and division links.

- Position management (Company -> Positions): create, edit, deactivate, delete
- AI-powered position generation with draft review workflow; expensive runs prompt for explicit confirmation when the cost meets the workspace warning threshold. Drafts awaiting validation are surfaced in a dedicated card at the top of the positions list so the operator reviews them before scrolling the approved table
- Position selector (combobox) in employee and invitation forms
- Headcount tracking per position with «assigned/headcount» indicator
- Division column in the positions list and clickable headcount cell that opens a drill-down dialog with the employees assigned to that position
- Lifecycle status (`active`, `on_hold`, `frozen`, `closed`) with a colored badge column and a row-level menu to switch state without opening the editor; closed positions are read-only until reopened
- Occupancy column (`Filled / Plan`) with click-through drill-down using a unified employee row that surfaces a single highest-priority alert per person (account inactive, profile incomplete, assessment overdue, assessment awaiting approval, PDP awaiting review)
- "Configure matrix" deep-link from the position editor to the matching `Specialization × Grade` matrix, with a "matrix not configured" banner when the pair has no competence links yet
- New Position dialog supports inline Specialization / Grade creation — the "Add new" prompts call `POST /api/dictionaries/specialization` and `POST /api/dictionaries/grade` respectively; the Grade flow also creates the missing `GradeSpecialization` chain so the newly-added value joins the picker without leaving the form
- Position detail page (`/company/positions/{id}`) with overview, the resolved competence matrix rendered as a compact two-level tree (group → competence with the required skill-level badge; indicators sit behind a per-competence expander with Expand-all / Collapse-all controls) plus a "Configure matrix" deep-link, and the assigned employees rendered with the unified 7-column `EmployeeListRow` (Name → Position → Specialization → Grade → Division → Status → Hire Date) — Specialization and Grade are separate columns, Division and Name are deep-links, and a sticky column-header row keeps labels visible while scrolling (HRP-175)
- Headcount drill-down dialog widens to 960px on desktop (full-screen sheet under 768px), shows a readable counter (`3 employees` / `Showing 2 of 3 employees`) instead of the cryptic `2/3`, and reuses the same 7-column row layout as the division detail and specialization employees tabs so the format is consistent across every employee list (HRP-175)
- "AI Generate" launcher on the position detail page redirects to the specialization AI-generate page (`/company/specializations/{specId}/ai-generate?position={posId}`) where the matrix brief, progress UI and review modal already live; the position page only shows the CTA and an "Open active session" shortcut when one is in flight. The destination surfaces a banner naming the position, locks the position's grade into the brief multi-select, tags the session with `position_id`, and returns the user to the position page on Apply (HRP-33)
- `/company/positions` and `/company/specializations` list rows light up (`bg-primary/5` tint + animated sparkles badge with tooltip) when an active AI matrix session targets the row's specialization, so the operator can spot in-flight work without leaving the list. Clicking the badge navigates straight to the live drawer via `activeSessionRoute(session)` (HRP-33)
- `/admin/employees/unassigned` admin view for HR to bulk-assign positions to employees that ended up without one
- Backed by `/api/positions/{id}/occupancy`, `/api/positions/{id}/matrix-status`, `GET /api/positions/{id}/competences`, `POST /api/positions/{id}/status`, `GET /api/positions/{id}/employees?with_alerts=true`, and `GET /api/employees?unassigned_only=true&with_alerts=true`

### Specializations
Dedicated section under Company that surfaces each specialization as a first-class profile, not just a dictionary entry.

- List view at `/company/specializations` with grade count, position count, and assigned/plan headcount
- Detail page (`/company/specializations/{id}`) with tabs for Grades and Positions
- Inline Spec×Grade editor: description, requirements, salary range (min/max/currency)
- Manage grades dialog (Specialization page + Company → Specializations row menu) lists every dictionary grade with the already-attached ones pre-checked — ticking adds and unticking detaches in one save, mapping to `POST/DELETE /specializations/{id}/grades` (HRP-158)
- Positions tab groups positions by division and shows assigned/plan + lifecycle status per position
- Competence matrix editor at `/company/specializations/{id}/matrix?grade_id=...` — `Competence × Grade` table with per-cell skill-level select, dirty-cell highlighting, indicator tooltip (union of indicators up to the selected level), and an unsaved-changes bar. Each cell is tinted by skill-level rank as a heat map; competence rows whose assigned levels are missing indicators or development materials show an amber warning icon linking to the competence detail page. Grade column headers carry a bordered `$` salary pill and a destructive X icon that opens a confirm dialog before removing the grade; competence rows can be dropped from the matrix the same way (HRP-101). With a single grade attached the editor swaps the table for a dedicated list layout (HRP-157 REDO): the grade title + salary pill + remove icon move into a section header above the list, every competence renders as a flex row with a colored level chip (Basic slate, Intermediate amber, Advanced emerald, Expert violet) wrapped around the level selector, all remove buttons align on a single right-side axis (32×32 with focus-visible ring), `divide-y` between rows and a hover row highlight keep the list scannable. Competence titles open in a new tab; the indicator dialog separates each skill level into its own bordered section with bullet markers and per-level scroll, and tooltips snap-in via the snappy 100 ms `TooltipProvider` (HRP-157). Adding competences opens a dedicated modal that renders the full origin + tenant tree with per-branch chevrons, Expand all / Collapse all controls, group-level cascade checkboxes (full / partial / empty), title-and-breadcrumb search, a new-tab link per competence, and a Save button gated by a counter so the matrix never receives a no-op submission (HRP-100)
- Client-side cascade rules: promoting a competence at grade N propagates to higher grades (auto-inherit); demoting a higher grade caps the lower ones; the server normalizes the matrix on save so the invariant `level(N+1) ≥ level(N)` always holds, even on direct API calls
- Backed by `/api/specializations` (`GET /`, `/{id}`, `/{id}/grades`, `/{id}/positions`, `GET/PUT /{id}/matrix?grade_id=`, `GET/PUT /{id}/matrix-bulk`) and `/api/competences/{id}/indicators-by-level`
- AI Generate matrix at `/company/specializations/{id}/ai-generate`: textareas for responsibilities, daily/weekly tasks, KPI, formal requirements + multi-upload (`.pdf .docx .xlsx .xls .rtf .txt`; per-file 10 MB, combined extracted text 50 000 characters). The model proposes thematic groups of competences with indicators per skill level and a level-per-grade mapping; the review modal materialises selected entries into the competence tree and writes `GradeCompetenceLink` rows. Backed by `POST /api/competence-generation/specialization-matrix-sessions` (multipart) plus the existing CR11 session lifecycle (refine / regenerate / idempotent apply). The on-page banner shows the effective AI model and effort tier with a deep-link to `/settings/ai`. The brief also carries a preflight context picker (positions linked to the specialization, the company description, and existing competences in the matrix) — each item renders as a chip with an × control so the user can drop it before generation, plus a free-form refinement textarea appended to the prompt. The Divisions block lists **every tenant division**: those reachable through the specialization's positions are pre-checked and carry a `link` marker with a tooltip, the rest are present but off so the operator can broaden context manually; a `(X of Y selected, N linked)` counter sits in the header, and once the list crosses 15 rows a search input plus a "Show linked only" filter appear (HRP-159).

### Specialization-Division Mapping
Define which specializations operate within each division.

- Assign specializations to divisions (many-to-many)
- Prevent duplicate assignments
- Supports both origin (system-wide) and custom specializations
- List active specializations per division

### Competency Frameworks
Define the skills and behaviors that matter for your organization.

- Competence groups with hierarchical structure (origin + tenant-custom)
- Individual competences within groups, with explicit publish / unpublish workflow; the tree row action menu carries the Hide from users / Show to users toggle that mirrors the group-level visibility action (HRP-118 redo)
- Indicators per competence with skill levels and weights, plus learning materials with comments and a typed format
- Per-(material × specialization) overrides on the competence detail page: pick a specialization in the «Materials by context» panel to hide a base material from PDPs of employees with that specialization, or surface a competence material in that context only. Endpoints: `GET /api/competences/{id}/materials?specialization_id=…`, `GET/POST/DELETE /api/competences/{id}/material-overrides`. Development plans created for a (specialization, grade) pair seed `PDPItemMaterial` rows from this resolver, so the override is the single source of truth for «which materials does this employee see»
- Origin (system-wide) and custom (tenant-specific) competences
- Custom skill levels per tenant (origin levels stay locked, tenant-defined levels can be added/edited/deleted)
- Cascade activation/deactivation with link guards: deactivation is blocked when a published client competence or any link to matrix / employee card / assessment / IDP / talent market exists
- Tree mutations (move groups/competences/indicators/materials) preserve referential integrity and reject cycles
- Bulk usage check endpoints (`GET /competences/{id}/usage`, group/indicator/material variants) surface where any element is referenced
- Audit log per competence (`GET /competences/{id}/audit-log`) captures every publish / move / activate / deactivate / delete with actor and timestamp
- Tree response includes `is_origin`, `is_used`, `competences_count` rollup (groups) and `levels_completion` hints (per-level indicator/material coverage) for client competences
- AI-powered competence generation from specialization descriptions
- Indicators editor on the competence edit dialog: list grouped by skill level, manual add / edit / delete, plus an in-place "Generate with AI" entry point and a help tooltip explaining how indicators feed into assessment grading
- Per-level bulk add for indicators: the "Add multiple" button on each skill level opens an inline textarea (one line per indicator) and saves the batch atomically through `POST /competences/{id}/indicators/bulk` (HRP-49)
- AI-generated learning materials per skill level on the competence page: "Generate materials with AI for '{competence}'" opens a dialog structured as Generation parameters (Skill levels, Materials per level) → Context → Refinement → live summary. The Context block lets the operator opt in/out of every signal the AI sees: a fixed Competence info block (title / type / description / group); Indicators grouped by skill level with all rows pre-checked and per-level dimming when its skill level is deselected; full tenant Specializations / Divisions lists with linked rows (through the matrix and through positions respectively) pre-checked, a link marker icon with tooltip, and a search + "Show linked only" filter that appears once a list passes 15 rows; Sibling competences (off by default); and a Company description toggle (on when the tenant has a description). The footer shows a live "N materials × M per level" tally plus context counts and surfaces an amber hint when the context shrinks to the competence alone. Backed by `GET /api/competences/{id}/ai-generate-materials/context-options` (which carries the `is_linked` flags) and `POST /api/competences/{id}/ai-generate-materials` (now tri-state: `null` lists keep auto-pick behaviour, empty lists mean "operator deselected this block"); kept rows still persist through `POST /competences/{id}/materials/bulk` (HRP-51)
- Drag-and-drop in the tree view: groups and competences can be moved between branches; origin elements expose a disabled handle so it is obvious why they cannot be reorganized
- Expand all / Collapse all controls on the Competence DB tree and on the picker dialog used by Assessment composition, so deep hierarchies can be flipped open or closed in one click (HRP-109)
- Competence detail page (`/competences/{id}`) with status badges, publish/unpublish/hide controls, an in-place «Generate indicators (AI)» button (status-aware: shows «AI generation in progress» or «Open active AI session» while a competence-indicator session is live for this competence) and per-skill-level editors for indicators and materials with their own drag-and-drop reordering. The page is split into three labelled sections — **Indicators by level** (Target icon, "what people should be able to demonstrate"), **Materials by context** (Layers icon, specialization-scoped overrides) and **Materials by level** (BookOpen icon, "how people get there") — with an inline **Jump to** menu in the header. Levels carry shared color tokens (Basic / Intermediate / Advanced / Expert) so the same level reads the same way across Indicators, Materials, the matrix, and the AI generation modal. Each level header shows a counter; Materials reuses the counter as "N materials for M indicators" and switches to an amber warning + inline "Generate with AI" CTA when indicators are present but no materials exist yet. Indicator rows replace the legacy `w N` abbreviation with a click-to-edit **Weight** affordance (0–5) wired to a tooltip describing how the value flows into scoring, an *informational* badge when weight = 0, and an amber warning icon on suspiciously short titles (≤ 3 chars). The Materials-by-context panel surfaces a prominent "Context: {name}" badge + **Reset to Base** action whenever a non-Base specialization is active. (HRP-176)
- Two-step wizard for creating a competence (title/description/type, then group selection)
- Activate-by-default checkbox in the group dialog so newly created groups land in the desired `is_active` state
- Single shared cache (`useCompetenceTree()`) for the tree across `/competences`, employee, assessment and criteria-sheet views — mutations on one screen invalidate every consumer in the same session

### AI Competence Generation UI

Session-based wizard that generates whole competence trees, single groups, or just indicators for one competence — all editable before they hit the database.

- Status-button on `/competences` adapts to the tenant's state: «Generate base», «Extend base», «Open active session», «Generation error», «AI generation in progress»
- Confirmation dialog with «generate indicators» toggle, a «used data» drop-down (specializations, divisions, company description, AI settings), and the credit cost of the upcoming run; when the cost meets the workspace warning threshold, the start button switches to «Confirm & start (N credits)»
- Drawer shows queued/running banner with skeleton during `pending`/`running`, cascade-checkbox tree on `ready`, dedicated error screen with retry on `error` (parse / service / insufficient-data / overload); when the Celery worker stops reporting heartbeats the drawer surfaces a "Background worker offline" warning so users don't sit on an empty spinner
- Cascade selection: parent toggle propagates to descendants, partial-state on parents when only some children are selected; existing items in the DB are locked (cannot be deselected) and new items are highlighted
- Refinement panel: short «general» textarea by default, with optional Add / Change / Exclude sub-fields — each refinement spawns a child session that links back via `parent_session_id`. The submitted form snapshot is persisted in `session.params.refinement_form`, so reopening the drawer (or pressing Try again) re-hydrates the textareas and auto-expands the detailed view when sub-fields had values; «Clear data» wipes both the form and the composed prompt so the next run starts from the original brief
- Apply dialog: «Add and publish» (with a second confirmation listing competences whose indicators are unselected) or «Add unpublished». Idempotency key generated client-side and reused across retries
- Preflight modal warns when other tenant admins have an active session, with «Go to my session» if the current user already has one
- Group-level «Fill / Extend group» and competence-level «Generate indicators» triggers (available both from the tree dropdown on `/competences` and as a dedicated button on the competence detail page) respect cross-scope locks: only one active session per user, enforced by a partial unique index in the DB
- Drawer state survives navigation — sessions live on the server, selection state is stored in JSONB and re-hydrated on remount
- Status sync: 5-second REST polling runs whenever a session is active so finished, cancelled, and errored runs surface without a refresh; WebSocket pushes over `/api/ws` (`compgen.session.updated`) shorten the typical latency to ~100 ms when delivery succeeds

### Grade System
Define career progression paths with specializations, grades, and required competences.

- Specializations (e.g., Backend Developer, Product Manager)
- Grades within specializations (e.g., Junior, Middle, Senior)
- Grade chains linking specializations to competence requirements
- Grade chains filterable by division — only show chains for specializations active in the division
- Per-grade `passing_score` (default 75%) acts as the reference threshold pulled into target-position assessments
- Used for assessment criteria, recommendation, and career path planning

### Dictionaries
Reference data management for standardized values across the platform.

- Specializations, skill levels, material types
- Origin (built-in) and custom (tenant-specific) entries
- Sort ordering and active/inactive status
- Title capped at 100 characters and description at 250 across every dictionary type (HRP-282)
- List page filters by Source (System / Custom) and Status (Active / Inactive) plus a Clear button alongside the title search (HRP-283)
- List page exposes the Sort index column (Title → Description → Sort index → Source → Status → actions) so the attribute is editable without a detail card (HRP-284)
- List page renders the filtered item counter above the title search across every dictionary type (HRP-289)
- System (origin) items support per-tenant active/inactive override stored in `dictionary_item_tenant_overrides` — title, description, and sort index of System items remain frozen for tenants (HRP-285)
- Delete on a Custom row that is referenced elsewhere returns a single generic 409 ("This item has connections with other object(s). It can't be deleted") and Delete is hidden from the action menu for System rows (HRP-286)
- Competence Type picker on add / edit / bulk-add competences hides inactive types; edit mode keeps the previously selected type in the list even if it has been deactivated (HRP-287)
- Specialization detail page and matrix header render an "Inactive" chip next to grades whose dictionary row was deactivated after the chain was built; the Manage grades dialog keeps the row checked so the operator can detach it explicitly (HRP-288)

---

## Assessments

### 360-Degree Assessment
Comprehensive evaluation gathering feedback from multiple perspectives.

- Assessment types: Self, 180-degree, 360-degree
- Participant roles: self, manager, peer, subordinate
- Competence-based evaluation with configurable indicators
- Answer scales with weighted options

### Taking a Survey
Participants answer assessments through a side sheet instead of a modal — surveys can be long, so the sheet gives room for the full question text and per-option labels.

- Answer options stack vertically (one per row, radio-style), with a comment field per indicator
- Every selection autosaves through an upserting `POST /assessments/{id}/answers`, so each `(participant, indicator)` keeps a single row even after multiple edits
- Comments save on a short debounce and on blur — closing the sheet via the X button, Esc, or an outside click preserves the in-flight selections
- Reopening the sheet rehydrates from `GET /assessments/{id}/my-answers`, restoring the participant's draft so partial progress survives navigation

### Evaluation Criteria Selection
Choose what to evaluate via a dedicated side sheet, available on single and mass assessments.

- Three modes: current employee positions, target specialization+grade, or hand-picked competences
- Target position pulls competences and skill levels from the grade ladder; "All grades" picks the highest level per competence
- Hand-picked mode opens a tree picker with cascading group/sub-group checkboxes, search, and a counter
- Skill level per competence is editable, with a banner reminding that higher levels include lower-level indicators
- Mass-assessment criteria propagate to every active child assessment in the group

### Rating Scale Picker
Pick or change the answer scale for a given assessment from the detail page, or for a whole mass assessment from the group page.

- Empty Rating scale block ships an explicit "Add scale" button; an assigned scale exposes a "Change" action — both open a modal with a radio list of scales available to the workspace
- The reference "Default answer scale" is always present, marked, and cannot be removed; tenant-defined custom scales appear underneath, sorted alphabetically
- Each row in the picker carries a "…" menu: default scales expose Preview only; custom scales expose Preview / Edit / Delete with confirmation dialogs
- Scale changes are blocked once an assessment reaches a terminal status (`done` / `cancelled`); group-level scale changes are blocked as soon as any child assessment leaves `draft`, since the per-child snapshot has already been taken
- Backed by `PUT /api/assessments/{id}/scale` for single assessments and `PUT /api/assessment-groups/{id}/scale` for mass assessments (the group endpoint propagates to every draft child); the `draft → sent` transition snapshots the assigned scale into a frozen copy so subsequent edits in the admin don't affect a running assessment

### Custom Answer Scales
Tenant-owned CRUD for answer scales, available from the rating-scale picker on any assessment.

- "Create scale" button at the bottom of the picker opens a side sheet for authoring a new scale: title, description, percent levels (validated to cover 0–100 without gaps) and a drag-and-drop list of answer options (`@dnd-kit`); the score for each option is its position in the list
- The "Don't know" toggle adds a neutral option that is pinned to the bottom and excluded from result computation
- Edit and delete are exposed only for custom scales (the default is read-only); save / cancel / delete actions show confirmation dialogs (edit-mode save warns that draft assessments will be updated; delete warns that draft assessments using the scale will be reassigned to default)
- Backed by `GET/POST/PUT/DELETE /api/answer-scales[/{id}]`; running assessments are unaffected by edits because the scale is snapshotted on launch (see Rating Scale Picker)

### Assessment Results
Per-competence percent and resolved level computed as a role-mean.

- Per-indicator: average of all non-neutral answers from the same role; neutral options ("Don't know") and missing answers are excluded
- Per skill level (per role): weighted average of indicator scores using `Indicator.weight` (defaults to 1 when no weight is configured), normalised against the scale's max weight, expressed as a percent
- Per competence (per role): mean of the level percents that produced at least one usable answer
- Final `percent`: mean of the per-role percents — roles with no usable answers are dropped
- Roles supported: `self`, `manager`, `peer`, `subordinate`; types map to participant counts (Self → 1 participant, 180 → 2, 360 → 2+)
- `avg_score` is the same value normalised to 0..1 (kept at 4-decimal precision); `percent` is rounded to an integer for UI display
- Resolved level: the percent range matching the snapshot scale's levels (e.g. 67% → "Meets expectations with growth areas")
- `percent` is `null` when no role produced any usable answer (e.g. all answers were neutral); legacy assessments without level metadata also return `null`
- The detail page Results table renders dedicated `Percent` and `Level` columns next to `Avg Score` / `Calibrated`; the level appears as a badge with the level description in a tooltip, and legacy rows show `—` / empty cells without breaking the layout
- Each Results row also surfaces the competence's required skill level next to its title and an info icon that opens a `Results by level` popup with the per-level breakdown (Basic / Intermediate / Advanced rows, percent per level); levels above the required one are hidden so the popup mirrors the questionnaire cascade
- Saving a calibration now refreshes that row's `Percent` and `Level` (and the overall percent next to the Results heading) from the calibrated score against the scale's max weight, and the override survives the on_review → done recompute so the manual decision sticks
- `AssessmentDetail.overall_percent` is the mean of per-competence percents (competences without a percent are skipped) rounded half-up to an integer; the detail page renders it next to the `Results` heading on completed assessments and hides the badge when no competence has a percent yet
- Employee-only viewers see the Results block only when they are the assessee (the `self` participant) **and** the assessment has reached `done`; peers / subordinates never see results on assessments they merely participated in (`GET /assessments/{id}` and `GET /assessments/{id}/results` return empty result lists otherwise, and the detail page suppresses the card render-side)

### Passing Score & Grade Recommendation
Configurable threshold per assessment plus an automatic grade recommendation on completion.

- HR sets a `passing_score` (0–100, default 75) on the criteria sheet of single and mass assessments for `Target position` and `Employees' current positions`. `Individual competences` hides the input and stores NULL — no chart is built for that criteria type
- The threshold is locked once the assessment leaves `draft` (criteria changes are blocked after `sent`)
- Applies to `target_position` (Specialization-All grades / specific grade) and `current_positions` assessments (specialization resolved from the assessee's `Position`). `Individual competences` assessments do not produce a chart
- Per-grade match %: per (grade, competence) average the skill-level percents from Basic up to the grade's required level, then mean across the grade's competences. Per-skill-level percent = role-weighted average of indicator means / max scale weight × 100; competences with no usable answers contribute 0%
- A grade is "confirmed" when its % ≥ `passing_score`. The recommendation picks the highest-`sort_index` confirmed grade; if none confirm, it falls back to the grade with the maximum % and flags it "not confirmed"
- Grades without competence requirements are excluded from the calculation; calibration does not override the raw average
- The recommendation (and the per-grade breakdown) is cached on the assessment and exposed via `GET /api/assessments/{id}.recommendation`. Legacy assessments with `passing_score=NULL` return `null`
- Chart visibility: unlocks at `on_review` (preliminary), stays for `done`, and survives a `cancelled` transition that crossed `on_review`. Cancellations from earlier states get no payload
- UI surfaces: the criteria sheet exposes the threshold input (`Passing score for recommended grade`) for `target_position` / `current_positions`, the assessment detail page renders a dedicated recommendation card with progress bars per grade whenever `recommendation` is populated, the mass-assessment summary lists the recommended grade per employee with a filter, and the specialization dictionary detail page lets HR edit `passing_score` per grade inline

### Assessments List
Single shared list view across the `/assessments` page and the employee profile Assessments tab.

- Rows group by status: active assessments first (ordered by `created_at` desc), then `Done` (ordered by `finished_at` desc), then `Cancelled` (also by `finished_at` desc)
- The trailing date column drops its header and renders a labelled date per row — `Created: yyyy-mm-dd` for active rows, `Completed: yyyy-mm-dd` for `Done`, `Cancelled: yyyy-mm-dd` for `Cancelled`
- Status chips share a single colour palette across both list views so the same code reads the same on the assessments page and inside an employee card

### Assessment Lifecycle
Structured workflow from creation to completion.

- Status flow: Draft → Sent → In progress → On review → Done (Cancelled is reachable from any state)
- Sent → In progress is auto-only — the first submitted answer flips the assessment server-side. Manual `change_status` / bulk `Change status (all)` requests targeting `in_progress` are rejected with `400 "Manual transition is not allowed"` so operators cannot bypass the auto-flow invariant the UI relies on; the action button is hidden on Details and the modal option is greyed out with the same tooltip
- `On review` is auto-entered when every participant has answered every required indicator (`is_completed=true`); a reviewer can also move there manually as long as at least one participant has finished — the request is rejected with `400` otherwise
- Entering `On review` triggers preliminary result computation so the reviewer can calibrate before approval; transitioning to `Done` re-runs the same computation and pins the recommendation
- Automatic timestamps on status transitions (`started_at` on first `In progress`, `finished_at` on both `Done` and `Cancelled`)
- Deadline tracking with email reminders. Date-only picker (no time component); past dates are blocked client-side with a red-border + error hint, and Pydantic's `not_past_deadline` validator backs that up with a 422 response on Assessment / Mass assessment / PDP / Mass exam payloads. On the assessment detail page an active assessment with a past deadline renders the Deadline value in red (still editable); terminal assessments swap the Deadline label for `Completed <dd.mm.yyyy>` or `Cancelled <dd.mm.yyyy>` (from `finished_at`, edit control hidden)
- Launching a stale assessment is blocked at the `Draft → Sent` transition itself (single, mass action menu, and child-page actions): if `ended_at` has already elapsed, the request returns 409 "Deadline is in the past" and the assessment stays in Draft; bulk responses surface a dedicated `deadline_in_past` skip-reason so the snackbar can call it out separately from missing criteria/scale
- Each assessee can have at most 3 active (non-terminal) assessments at a time. Single creation returns 409 when the cap is exceeded; Mass assessment creates only the children for employees with a free slot and reports `created_count` / `requested_count` / `skipped_capped_count` so the UI can render a `Created M of N assessments` snackbar (full-batch denials return 409)
- Lifecycle emails: every participant gets a per-role `Evaluate ...` email on `Draft → Sent`; a participant added after the assessment goes live gets a targeted Evaluate email; `On review → Done` sends `Your assessment has completed` (self) and `Your employee assessment has completed` (manager); cancelling out of Sent / In progress / On review sends matching `Your assessment cancelled` and `Your employee assessment cancelled` emails. Draft cancellations are silent — nobody was told the assessment was live

### Results & Calibration
Aggregate scores with optional manager calibration.

- Per-competence percent and `avg_score` follow the role-mean algorithm (see Assessment Results)
- `Calibrated Score` is a manual override on top of the raw average and is editable while the assessment is in `On review` (and any earlier non-terminal status); it persists alongside `avg_score` so reviewers can compare
- Preliminary results recompute on every survey submitted after the assessment reaches `On review`, so Avg Score reflects the freshest answer set while any existing calibration override keeps Percent and Level locked to the reviewer's decision
- Radar chart visualisation on the employee profile
- Results feed into development plans and grade decisions

### Detailed Results
Per-competence breakdown for reviewers calibrating an assessment.

- Visible to Platform admin, Admin, and Manager whenever the Results card is shown (statuses `On review`, `Done`, and `Cancelled` when cancellation happened from `On review`); Employees get 403 from `GET /assessments/{id}/detailed-results`
- For each assessed competence: type label (Hard skill / Soft skill / …), required skill level, and an expandable section with per-skill-level percent breakdown
- Only the skill levels that were actually evaluated are listed — indicators above the competence's required level are filtered out, matching the cascade Question preview and Take this assessment already walk
- For each indicator: per-role answers (self / manager / peer / subordinate / external), comments authored during the survey, and a Total row carrying the mean across roles
- Roles with no completed participants are dropped from the per-question row; `Don't know` answers render as the neutral marker and collapse to a dash when every role chose it
- `Specialization-All grades` evaluation falls back to the competence's highest configured skill level for the required-level chip
- `Calibrate` button (managers / admins / platform admins) starts a per-indicator Total override flow: the assessment is locked for participants, every competence expands, and each question shows a Total picker. `Save calibration` upserts the overrides — the per-competence percent / level recompute using the calibrated Total and a `calibrated` chip surfaces next to each pinned Total. `Cancel calibration` wipes every Total and restores the raw averages

### CPA (Batch Assessments)
Create and manage multiple assessments as a single campaign.

- Campaign-level configuration (type, scale, deadlines)
- Bulk assessment creation for multiple employees
- Unified tracking and reporting

### CPA Criteria & Participant Roles
Fine-grained CPA configuration with typed criteria and role-based participation.

- Criteria types: position-based, point-based, competence-based
- JSONB config per criteria (scale, weights, thresholds)
- Weighted criteria support for complex evaluations
- Participant roles: reviewer, calibrator, observer
- Role-based access within CPA campaigns

### CPA Analytics & Re-creation
Data-driven insights and campaign continuity.

- Employee ranking by average score across CPA assessments
- Score distribution analysis
- Completed vs total assessment tracking
- Copy CPA from previous round (criteria, participants, settings)
- Compare rounds with trend analysis

### External / Anonymous Reviewers
Invite people outside the system to provide assessment feedback.

- Generate unique shareable links per external reviewer
- No login required — token-based access
- Optional name and email for tracking
- Configurable link expiry (default: 30 days)
- Email notifications to external reviewers
- Responses aggregated with internal participants
- Admin sees who was invited but individual scores remain anonymous

---

## Development Plans (PDP)

### Personal Development Plans
Structured learning and growth plans tied to assessment results.

- Each plan has a free-form title shown in the list, detail view, and the employee's Development tab
- Hard cap of 3 active development plans per employee (active = status not in `done`, `cancelled`); the fourth attempt returns `409` with `Employee already has N active development plans (limit 3). Finish or cancel an existing one before starting another.` The Create plan dialog surfaces the message as a toast (HRP-38)
- Plan rows surface the assigned employee, progress bar, and deadline; past-due deadlines are highlighted in red on both the list card and the detail page so operators can triage at a glance. Row action menu (Change status) is rendered always for admin/manager on non-terminal plans and hidden entirely for the assigned employee and on terminal plans
- The Development Plans list carries the same filter bar as Assessments — title search and a multi-select Status filter — with a Clear affordance when any filter is active. The type filter is dropped because plans do not carry a type
- Inline-edit the plan title and deadline directly from the detail page (admin/manager); blocked once the plan reaches a terminal status (Done / Cancelled)
- Optional Development specialization + Development grade per plan; defaults are pre-filled from the employee's current position. Fields sit under Progress in the Details block and each carries a pencil affordance in Draft that opens the "Development specialization & grade" dialog; saving rebuilds items + materials from the new (spec, grade) link (HRP-189)
- Auto-fill plan items from the competences attached to the chosen (specialization, grade) pair via the grade ladder; each item's seeded materials are capped at the target skill level for that competence so a Junior plan only gets level-0 material and a Senior plan inherits level-0 → target instead of every material on the competence (HRP-189). Falls back to an empty item list when no chain is configured
- Spec/grade is editable only while the plan is still in Draft; pressing Send freezes the (specialization, grade) link for the rest of the lifecycle (HRP-189)
- Link PDP to assessment results and competence gaps
- Status workflow: Draft → Sent → In progress → On review → Done; with Returned (back to On review) and Cancelled terminal states. Status labels mirror Assessments — "On review" and "Done" — and the detail page renders the full transition graph with color-coded badges (HRP-188)
- "Sent → In progress" is no longer a manual admin step — the plan auto-promotes the first time the owner ticks an item. The list-page Change Status dialog disables In progress with an (i) hint icon; hovering the icon shows a "Manual transition is not allowed" tooltip (HRP-197)
- Returned plans accept "submit for review" or "cancel"; the old return-to-Sent step is gone (HRP-198)
- The admin cannot send an empty plan: the Send action stays disabled with a tooltip until every item carries at least one material. A past deadline is a backend-only gate — the button stays enabled (parity with Assessments / Talent market) and clicking it surfaces a "Deadline is in the past" snackbar from the 400 response (HRP-12 + HRP-191)
- The Return action in Review enforces the same contract as Send: button disabled until every item carries a material; a past-deadline attempt is a backend-only block, the click surfaces a "Deadline is in the past" snackbar from the 400 response (HRP-187)
- Regular employees only see plans from Sent onward; admins and division managers (incl. deputies, within their managed subtree) see Draft plans too so they can pick up plans authored for their team
- The plan owner is the only role allowed to tick items off; admins viewing the plan see the checkboxes disabled. The first tick in Sent auto-promotes the plan to In progress, and completion is one-way for the owner — once an item is marked passed the checkbox locks so an accidental click can't undo real progress (admin / assigned reviewer keep full toggle in On review)
- When the plan is Sent, In progress or Returned the owner gets a single "submit for review" action that activates once every item is marked passed
- Reviewer surfaced in the Details block: explicit `reviewer_id` if set, otherwise the employee's division manager (resolved via `Division.manager_id` → `Employee.user`)
- Status action buttons read as English verbs (send, cancel, start, submit for review, complete, …) so the action row matches the rest of the dashboard
- While the plan is under On review, the assigned employee sees the items block as it was at the moment of transition (snapshot stored in `pdps.on_review_items_snapshot`); the admin keeps editing live items, and the snapshot is cleared once the plan moves out of On review (Returned / Done / Cancelled)
- Terminal plans (Done / Cancelled) are fully read-only: item checkboxes are frozen, the comment composer is hidden, and every mutating endpoint returns 409
- Draft → Sent transition emails the assigned employee with the plan title in the subject and heading, the deadline, and a link to the plan
- Deadline tracking with email reminders
- Progress percentage stays in sync with the item set: it recomputes whenever items are added, removed, or toggled, so adding work after launch doesn't strand the cached `total_progress` value at a stale ratio (HRP-199)
- Development Plans list and employee Development tab order plans in three buckets — active (Created desc), then Done (Done date desc), then Cancelled (Cancelled date desc); the employee tab drops the Deadline column and surfaces the bucket-anchor date with a "Created/Done/Cancelled" prefix (HRP-222)

### PDP Items & Materials
Break development goals into actionable learning items.

- Items linked to specific competences
- Study materials with title, format (one of `course / book / article / video / practice`), link, and estimated study time
- File attachments on materials (upload files alongside or instead of links) via a custom file picker that surfaces only the file name (no localized browser placeholders). The Add button requires Title + either an uploaded file or an external link, and stays disabled while a file is still uploading so the dialog can't be confirmed with an empty material
- Mark items and materials as passed/completed. The plan owner can tick and untick item checkboxes while the plan is in `sent`, `in_progress`, or `returned` — unchecking never demotes the plan back to `sent` once it's auto-promoted on the first tick. Under review, the assigned reviewer (including a division manager who is the implicit reviewer when no explicit reviewer is set) and any admin / HR / platform admin can toggle items
- Custom or competence-linked items
- Edit item title/description, edit material title/format/link/file, delete items or materials inline; blocked once the plan reaches a terminal status. Items marked as passed are read-only — the edit / delete / "add material" affordances disappear and the API returns 403 on bypass attempts; unchecking the item (only possible in On review) restores edit access (HRP-200)
- Reorder items via up/down arrows on the detail page — change is persisted through `POST /api/pdp/{id}/items/reorder` with optimistic UI and automatic rollback on failure; new items always land at the bottom of the list regardless of the `sort_index` the client may have shipped, and the checkbox toggle never reshuffles the order (HRP-201)

### PDP Comments
Feedback loop between employee and manager.

- Comments at PDP level, item level, or material level
- Threaded discussion on development progress
- File attachments on comments (images displayed inline, other files as download links)
- Comment timestamps render with day-and-minute precision (no seconds)

### PDP History & Versioning
Automatic snapshots of PDP state at key status transitions.

- Auto-save version on: sent, review, returned, done
- Each version captures full PDP state (items, materials, progress, comments)
- List all versions: GET /pdp/{id}/versions
- View specific version snapshot: GET /pdp/{id}/versions/{version_id}
- Version numbering for tracking changes over time
- Restore from previous version: POST /pdp/{id}/versions/{version_id}/restore

---

## Exams

### Exam Management
Knowledge testing with configurable questions and pass criteria.

- Title is required on create; pencil controls on the detail page edit Title, Description and Deadline until the exam reaches a terminal state
- Status lifecycle Draft → Sent → In progress → Completed, with Cancelled reachable from any non-terminal state; the manager Change status menu is hidden once the exam is in a terminal state
- send action validates ≥1 question, ≥1 assigned employee, and a non-past deadline; past deadlines are highlighted in red
- The sent → in_progress transition fires automatically when the first participant submits an answer
- Single / multiple choice questions require at least 2 options and at least one correct answer; single choice enforces radio semantics
- Questions can be edited or removed while the exam is in Draft (locked after Send)
- Image attachments on exam questions (displayed in editor and exam view)
- Weighted questions for scoring
- Active/inactive question management
- Sort ordering for question sequence
- List page filters by Title and multi-status, mirroring the Development plans page
- List groups active first, then Completed, then Cancelled (newest-first by the bucket date) and surfaces Created / Completed / Cancelled date inline; the detail page swaps the Deadline row for Completed / Cancelled + date once the exam terminates

### Assigning Employees
- Assign employees through a searchable multi-select picker (name / email / division / position filter), backed by `/employees`
- Already-assigned employees are visually flagged and cannot be picked twice
- Assigned employees see the exam in their own `/exams` list as soon as the manager hits send (drafts stay hidden)

### Taking an Exam
Employees take sent exams in a side sheet, mirroring the assessment survey UX.

- A per-row Take this exam control opens the sheet; questions render by type (single choice radios, multiple choice checkboxes, essay textarea) with question images
- The answer key is never exposed while taking — a dedicated employee endpoint strips correct-option flags
- Every answer autosaves immediately (essays with a short debounce); closing the sheet keeps the survey In progress and reopening resumes from the saved draft
- Submit results stays locked until every question is answered (hover hint explains why); submission is validated server-side too
- Re-answering a question replaces the previous answer — scores never double-count
- Answering and finishing are owner-only: an exam can be taken solely by its assigned employee
- After submission the row shows the earned score, and a results control opens a read-only review sheet with correct/incorrect verdicts per question and the answer key highlighted (managers with scope over the employee can open the same review)
- The individual survey completes to Completed; when the last participant finishes, the whole exam flips to Completed automatically

### Pass Mark
Configurable passing criteria for the test.

- One Pass Mark per exam — once added, the Add button is replaced by edit and delete controls
- Editable on any active exam (draft, sent, in progress); finalized exams are frozen
- Minimum score percentage or absolute points
- Optional grade / specialization scope
- Automatic pass/fail determination

### Exam Results
Track employee exam performance.

- Full name renders on the results list (UUID fallback only when no Employee → User link exists); the row links to `/employees/<id>` when the viewer can see that profile
- Score and max score tracking
- Pass/fail status
- Start and finish timestamps
- Results linked to employee profile

### Exam Question Import
Bulk import exam questions from spreadsheet files.

- Import from Excel (.xlsx) with structured columns
- Question types: single choice, multiple choice, essay
- Up to 6 answer options per question with correct answer marking
- Configurable question weights
- Duplicate detection against existing questions
- Row-level error reporting for validation failures
- Downloadable template with example rows
- Markdown support in question text

---

## Talent Market

### Talent Cards
Internal job board for open positions and project opportunities.

- Card types for different opportunity categories
- Publish/unpublish workflow
- Division-linked positions
- Rich descriptions for requirements
- Each card carries a Start date (required, default today) and optional End date; list preview surfaces the term as `since DD.MM.YYYY` / `start – end` / `Closed: DD.MM.YYYY` and the Details block exposes Division, Dates, Created, Published at and Closed at instead of a Yes/No publish flag

### Requirements & Candidates
Match employees to opportunities.

- Structured Requirements: a card carries a **Required Specializations** block (each row is `specialization + grade + optional min. years of experience`) and a **Required Competences** block (each row is `competence + skill level`). Picking a specialization auto-fills its configured competences from the company's grade ladder, so the recruiter doesn't re-type the matrix. (HRP-87) Adding a second specialization, editing one, or deleting one prompts an explicit "Required competencies will be recomputed" confirmation, because the auto-derivation overwrites manual tweaks. (HRP-171)
- Required Specialization rows hide the "Min. experience" line when the value is `0` — entering `0` is treated as "no floor" and renders the same as an empty value. Deleting a row asks for explicit confirmation. (HRP-127)
- Required Competences picker is a tree with search and group-level select-all (matching the "Select competences for assessment" UX). Reopening the picker on a card with existing rows shows them pre-selected and labels the action button as **Change** — saving replaces the full set so a re-saved selection can drop as well as add rows. (HRP-128)
- Card-level **Match %** (50–100) on Create/Edit card — drives the Required Competences matcher threshold for every competence on the card. Editable until publish. (HRP-128) The card detail page exposes the same value via an inline pencil edit on Draft cards (auto-pool is re-run on save); the affordance is hidden once the card moves out of Draft. (HRP-179)
- Publish gate: a card can only flip to `published` once at least one Required Competence **and** at least one Candidate are attached (HRP-150). The Required Specialization block stays optional. Once published, both blocks become read-only — edits require unpublishing or cloning the card.
- Status transitions in the Details block: Draft shows **Publish**; Published shows **Complete** (≥ 1 candidate in `appointed` status required) and **Cancel**; Completed / Cancelled cards show no commands — the flow is closed. (HRP-150)
- Talent Market list view: action menu (`…`) is always visible (no hover gate) and hidden entirely on Completed / Cancelled cards. Menu items collapse to **Change status** (target-status submenu mirroring the backend transition guards) and **Delete**. Status badges render capitalised (Draft / Published / Completed / Cancelled). (HRP-148)
- Card detail page: inline pencil-icon edit for **Title**, **Description** and **Dates** on non-terminal cards (Draft / Published). Terminal cards drop the pencil affordance and stay read-only. Mirrors the assessment / development-plan detail UX. (HRP-148)
- Terminal cards (Completed / Cancelled) hide the **Dates** row in the Details block entirely — the dedicated "Completed: …" / "Cancelled: …" row below already carries the relevant timestamp. (HRP-178)
- Employee candidacy with status tracking
- Match scores for candidate-opportunity fit
- Appointment workflow with timestamps
- Auto-pool: the Candidates block fills automatically from the card's Required Specialization + Required Competence rows. An employee qualifies when their work-history on positions matching the required `(specialization, grade)` clears the `min_experience_years` floor (presence-based when the floor is unset; summed across spells when set) **and** their competence average clears the card-level Match %. The competence average uses the latest `done` assessment per Required Competence at the required skill level *or higher* (HRP-90 mechanic); when the assessment ran at a higher level the percent is projected down to the required level using the per-level breakdown (average of breakdown rows with `sort_index <= required_sort`, the same formula the Employee Competences tab uses); missing assessments contribute 0%. The picker on the Candidates header is labelled **Change** once the auto-pool is populated; recruiters use it to tweak the auto-selection. Manual nominees and already-appointed candidates survive auto recomputes; nominees fall out when the card-level Match % is raised past their score. (HRP-129)
- Candidates block renders the employee's full name as a link to their profile (not the uuid) — mirrors the candidate picker style. (HRP-149)
- Candidates table and Add / Change picker rows render the shared `EmployeeSummaryLine`: the position title sits underneath the name and a status chip appears next to it whenever the employee is not `active` (on_leave / inactive / terminated). Backend exposes `position_title` and `employee_status` on the `TalentCandidate` and `CandidatePoolItem` payloads so the matcher dialog and the saved list look identical. (HRP-258)
- Add candidate picker: instead of pasting a UUID, the Candidates block opens a searchable list of every tenant employee with a computed match score. Rows show matched / not matched and are sorted by match descending; checkboxes attach a batch in one call (HRP-95)
- Match cell renders Competencies % and (when the card carries Required specializations) Experience tenure as separately coloured chips — green when the row qualifies on both axes, orange when it passes one axis only, red when it fails both, and `no experience` when there is nothing to compute. Pool dialogs rank candidates qualifying-first → competence-only → experience-only → rest; the Candidates list keeps qualifying ones on top followed by manually added or no-longer-qualifying rows (HRP-173)
- Clicking the Match cell in the Candidates list or any picker dialog opens a Match drawer (shadcn Sheet) with the per-Required-Competence projected percent and the per-Required-Specialization tenure breakdown — the same numbers the matcher used (HRP-172)
- Experience match falls back to the employee's current Position when no WorkExperience entry covers a Required Specialization: Match cell shows greyed "has experience" and the breakdown drawer surfaces "Current position" muted; tenured matches still take precedence and `min_experience_years` floors keep working (HRP-210)
- Candidate status replaces the legacy `nominated` with **Matched** / **Not matched** / **Appointed**: the auto-pool stamps `matched`, the picker computes `matched` / `not_matched` per row at attach time, the Change picker pre-checks and locks `appointed` rows (HRP-214)
- Email notifications fire on every lifecycle event — publish (one mail per matched / not-matched candidate), candidate added to a Published card, appointment (employee + their manager), Completed (all matched / not-matched), Cancel from Draft (appointed employee + manager) and Cancel from Published (appointed + manager plural + matched/not-matched). Links point at the card detail page; the existing login-redirect flow drops the recipient back on the card after sign-in (HRP-211)
- Removing a candidate from a Published card also emails the dropped employee with the subject "You are not considered more: [Title]"; removals on Draft cards stay silent because the employee never saw the card (HRP-245)
- Compact requirement layout: Required competencies render as inline wrap-to-fit chips so cards with a dozen rows fit on screen without scrolling (HRP-208)
- Appointment confirmation: clicking **Appoint** opens a confirm dialog so a stray click can't pin a candidate (HRP-215)
- Publish guard: a Draft card whose End date has already slipped is blocked from publishing with a clear "End date is in the past" error — the card stays in Draft (HRP-212)
- Role=Employee view is scoped to cards they're a candidate on (Draft only when appointed); all write affordances are hidden, the viewer's own row gets an "(it's me)" tag, and the match drawer arrow only appears for self (HRP-209)
- Employees on a Published card can hit **React** in the Candidates Actions column; a confirmation dialog sends the reaction, their manager gets a "Your employee has reacted" email, the candidate row picks up a Reacted chip, and the same chip surfaces left of Status on the cards list (HRP-213). Reactions also break ties in the ranking — at equal score, reactors sort ahead of non-reactors
- Candidates block header surfaces the last auto-pool stamp ("today / yesterday / Month dd") with a refresh icon for managers; terminal cards and Employee viewers see the stamp without the refresh action. Refresh keeps Appointed candidates in place while it recomputes Matched / Not matched (HRP-242)

---

## User Invitations

### Invite by Email
Invite colleagues to join your organization on HRPulsar.

- Required: recipient name, email, division, and position — the modal blocks submit until all four are set so the new user always lands in a concrete spot
- Send invitations with pre-assigned role (admin, manager, employee)
- Invitation link with 7-day expiry
- Accepting creates the user account + employee card automatically
- When the invitation role is Manager and a division was pre-selected, accepting also installs the new user as that division's Manager — any previous manager auto-downgrades to Employee if they lose their last division (HRP-195)
- This is the primary way to onboard new employees into the system

### Invitation Management
Track and manage all invitations from a dedicated settings page.

- Columns: Name, Email, Role, Division, Position, Status, Invited by, Date, Actions
- Filter by status: pending, accepted, cancelled, expired
- Resend invitations (extends expiry)
- Cancel pending invitations
- Bulk invite: send up to 100 invitations at once (each row requires name + email)
- Inline editing of pending invitations: admins can change role / position / division / email; non-admin managers can edit only position and division
- Email change generates a fresh invitation link, resets the 7-day expiry, and re-sends the invite to the new address (the previous link stops working)
- Email rotation is rate-limited (5/min) and audit-logged; division and position selections are tenant-scoped

---

## Notifications

### In-App Notifications
Bell icon with unread count and notification list.

- Assessment assigned / deadline approaching
- PDP lifecycle: sent (to owner), submitted for review (to reviewer), returned (to owner), completed (owner + reviewer), cancelled after launch (owner + reviewer); deadline approaching
- Exam assigned
- Mark as read individually or in bulk

### Realtime WebSocket Channel
Live push of in-app notifications and AI generation session updates over a single WebSocket per user.

- Endpoint `WS /api/ws?token=<JWT>` (token in query because the browser WebSocket API does not support custom headers)
- Invalid/expired/refresh tokens are rejected with close code `1008`
- Server emits `notification.new` (new in-app notification), `compgen.session.updated` (AI session status changes — `running` / `ready` / `error`), and `task.updated` (any Celery task transitioning to `STARTED` / `SUCCESS` / `FAILURE`)
- `task.updated` payload: `{task_id, status, result?, error?, module, action}` — covers AI generation (`ai.generate_competences`, `ai.generate_indicators`, `ai.suggest_pdp`, `ai.generate_positions`, `ai.batch_embed`), data import, analytics export, and competence-generation refine/regenerate
- Frontend `useTaskStatus(taskId)` hook subscribes once and `GET /api/tasks/{id}` polling runs whenever the task is in a non-terminal state regardless of WebSocket state, so a dropped frame cannot strand the UI on `processing…` (HRP-232)
- Heartbeat: server sends `{"type":"ping"}` every 30 seconds; client replies `{"type":"pong"}`
- Cross-process delivery via Redis pub/sub channels `ws:tenant:{tid}:user:{uid}` and `ws:tenant:{tid}:broadcast`, so events from Celery workers and other web replicas reach the right socket
- Best-effort fan-out — Redis or socket failures never block the originating business commit

### Email Notifications
Automatic email delivery for important events.

- Branded HTML email templates (installation brand, white-label ready) with inline CSS and responsive layout
- Templates for: email verification, password reset, user invitation, assessment, PDP, exam, certificate expiry, deadline reminders, external review
- Configurable email preferences per user
- Resend API (SaaS) or SMTP (self-hosted)
- Non-blocking delivery via Celery background tasks
- Scheduled reminders via Celery Beat

### Email Delivery Tracking
Full delivery lifecycle tracking for all outbound emails.

- `email_logs` table records every email sent through the system
- Tracks status: sent, delivered, bounced, complained, failed
- Captures Resend message ID for cross-referencing
- Retry tracking (up to 3 attempts with 60-second delay)
- Admin endpoint: `GET /api/settings/email-logs` with status/recipient filtering
- Resend webhook integration (`POST /api/webhooks/email`) for real-time delivery status updates

### Notification Preferences
Per-user, per-event, per-channel notification settings.

- Event types: assessment assigned, assessment deadline, PDP sent, PDP deadline, exam assigned, invitation received, general
- Channels: email and in-app (independently configurable)
- Default: all notifications enabled
- GET/PUT API for reading and updating preferences
- Preferences checked before sending — disabled channels are silently skipped
- Per-user isolation — each user manages their own preferences

---

## Analytics & Dashboards

### Overview Dashboard
Key metrics at a glance for managers and admins.

- Employee count by status and division
- Active assessments and completion rates
- PDP progress summary
- Recent activity feed

### Reports
Data-driven insights across the organization.

- Assessment score distributions
- Competence heatmaps
- Division-level comparisons
- XLSX assessment export — async generation via Celery, download from S3

### Background Task Status
Generic task tracking for long-running operations.

- Poll task status via GET /tasks/{task_id}
- Supports PENDING, STARTED, SUCCESS, FAILURE states
- Used by data import, AI generation, report export, and batch embeddings

---

## Data Import

### Excel Import
Bulk data loading from spreadsheet files.

- Employee import: email, name, position, hire date, work experience, education, courses
- Dictionary import: specializations, grades, skill levels
- Drag-and-drop file upload
- Validation with row-level error reporting
- Import job tracking with progress and status
- Async processing via Celery — endpoint returns job ID immediately, import runs in background

---

## AI Features

### AI Competence Generation
Generate competence frameworks using LLM.

- Describe a specialization and generate relevant competences
- Review and edit generated competences before saving
- Supports Claude, OpenAI, and Gemini providers
- Async generation mode: endpoint returns task ID, poll for results
- Batch embedding generation for semantic search

### AI Competence Generation Sessions
Long-running, user-driven AI generation flow for the competence library. Available under `/api/competence-generation/*`, admin-only.

- **Four scopes** — `whole_base` (build a tree from scratch using the company's specializations and divisions), `group` (extend an existing group with new competences and subgroups), `competence_indicators` (add behavioural indicators to a single competence), and `specialization_matrix` (design a `Competence × Grade` matrix for a single specialization, see «Specializations»).
- **Lifecycle** — `pending` → `running` → `ready` → `applied` (or `error`/`cancelled`). A partial unique index enforces «one active session per user» at the database level; concurrent attempts return `409`. The 409 body carries `{error_code: "active_session_exists", session: {id, scope, target_id, status, position_id}}` so the UI can show the caller exactly what is in flight (HRP-33). The frontend opens an `ActiveSessionConflictDialog` with two explicit choices — «Open active session» (navigates to the in-flight review) or «Cancel active and try again» (DELETEs the session and replays the original Start) — instead of silently auto-redirecting through `window.location.href` the way the first iteration did (HRP-168). Unexpected worker crashes are caught and the row is flipped to `error` rather than left stuck as `running`, so the next AI Generate is never blocked by a ghost session.
- **Global in-flight banner (HRP-33)** — the dashboard layout renders a persistent banner whenever the caller has a `pending`/`running`/`ready` session, with a one-click link to the matching review page. `specialization_matrix` sessions (Position- or standalone-launched) always land on `/company/specializations/{spec}/ai-generate?session=<id>` (Position-launched sessions add `&position=<pos>` so the destination knows to return to the position on Apply). Tree/indicator scopes route to `/competences`. The banner is dismissible per session via `sessionStorage` and reappears on reload so users can keep working but are always one click away from finishing the generation.
- **Frozen base snapshot** — at session creation we copy the current tree (or target group/competence) into the row. Edits made by other users while the session is running do not leak into the LLM input or the final `apply` step.
- **Cascading selection** — every node in the LLM payload gets a `temp_id`. `PATCH /sessions/{id}/selection` updates `selection_state` and propagates: selecting a child marks all parents selected, deselecting a parent clears every descendant.
- **Refine and regenerate** — `POST /sessions/{id}/refine` opens a child session with the user's freeform notes (general / add / change / exclude); `POST /sessions/{id}/regenerate` retries the same prompt. Both cancel the parent.
- **Brief persistence across all generation flows (HRP-97)** — both the refinement panel inside the competence drawer and the matrix brief form on `/company/specializations/{id}/ai-generate` (and inside the Position AI card) restore the user's last input on remount, page refresh, or Try again. The refinement panel snapshots into `session.params.refinement_form` server-side; the matrix brief lives in `localStorage` (files cannot be serialised and stay in memory only). Both are wiped on Clear data, on cancel of the active session, and on a successful Apply.
- **Idempotent apply** — `POST /sessions/{id}/apply` accepts an `idempotency_key`; replaying the same key returns the original `applied_result` without creating duplicate rows. `publish=true` makes new competences immediately public; for `competence_indicators` scope the same flag toggles the new indicators between visible (`is_active=true`) and draft (`is_active=false`). Apply replies always carry `created_groups` / `created_competences` / `created_indicators` / `created_grade_links` as arrays — empty arrays are a valid outcome and the Position / specialization AI pages render a warning toast in that case instead of a misleading "Matrix applied" success (HRP-105).
- **Drawer UX** — the active-session drawer turns the target competence title into a navigable link, hosts a confirm-before-discard cancel modal, lets the user bulk-select/deselect generated indicators, and redirects to the freshly-updated competence detail page after a successful apply. The competence detail page surfaces any active AI session (any scope, any target) as a clickable "AI generation in progress" / "Open active AI session" button with a Tooltip explaining why a new generation cannot start.
- **Active-session state-machine on the generate button (HRP-122 re-spec)** — the generate button on `/competences` keeps a four-state machine: `loading` (`Checking session…` + spinner, disabled while the page is still resolving the active session), `idle` (`Generate library with AI` / `Extend library with AI`), `active-session` (`AI generation in progress` while pending/running, `Open active AI session` when ready), and `error` (`Generation error`). Clicking the button while it's in the active-session state opens the drawer; clicking it in `idle` re-checks `GET /sessions/active` one more time and routes to the drawer if a session has appeared since the page loaded (covers the WS-down race where another tab started a generation). The drawer itself renders a `Loading session…` skeleton while waiting on the first fetch, and `useGenerationSession` short-polls for ~30 s when the initial response is `null` so a freshly POSTed session that hasn't committed yet still surfaces without forcing the user to refresh the page.
- **Matrix → competence deep-link** — matrix cells on `/company/specializations/{id}/matrix` link to the competence detail page with `from=matrix&specialization_id=…`; the page replaces the breadcrumb with "Back to matrix", and indicator-generation sessions launched from there carry the spec id through `SessionParams.specialization_id` so the prompt sees the spec title, ordered grade ladder and sibling competences (calibrating level difficulty, avoiding overlap). Any indicator change — manual save, manual delete, or AI Apply — first surfaces a usage banner listing the consumer areas (matrices, employee cards, assessments, IDPs, talent market) so the operator confirms the cascade.
- **Honors AI Settings** — language directive, company context, effort tier (model + temperature) and retry budget all flow in from the tenant's AI Settings row.
- **Matrix augment + ready toast (HRP-119)** — the `specialization_matrix` brief gains an opt-in "Generate indicators for existing competences" checkbox (surfaced only when the matrix already has competences); when on, the LLM extends every existing competence with extra indicators in the same response while still suggesting new competences. Whenever a matrix session flips to `ready`, the Position card and the specialization AI-Generate page fire a deduped success toast with an "Open review" action so an operator who tabbed away gets pulled back.
- **Group augment toggle (HRP-155)** — the `group` confirm dialog adds an opt-in "Augment existing items in the group" checkbox (default OFF). When OFF the worker drops both `source_tree` and `descendants` from the prompt and the model produces only fresh branches under the target group. When ON the existing subgroups and competences (with their indicators) ship into the prompt, the LLM is told it may also return existing subgroups/competences with NEW children or indicators, and the worker post-processes the response to attach `snapshot_id` to matched titles. Matched groups, competences, and indicators are rendered as locked chips with the existing tri-state behaviour from HRP-124; on apply the existing competence rows are reused (no duplicate creation) and echoed indicators are skipped, so only the genuinely new suggestions land in the library.
- **Preflight context controls (HRP-123 / HRP-124 / HRP-114)** — every non-matrix confirm dialog (`whole_base`, `group`, `competence_indicators`) shows the categories the LLM will read as removable chips and exposes a free-text refinement note that lands in `SessionParams.refinement_prompt` (same field the in-session refinement panel writes to). Each removed chip is reversible from an "Add back" row; excluded keys are persisted to `SessionParams.context_excludes` and the worker simply skips fetching them. Per-scope chip catalogue:
  - `whole_base` — per-item picker (HRP-143): every specialization, division and existing group/competence renders as its own chip with a × control, plus per-section "Remove all" / "Add all back" shortcuts. Excluded items are persisted under granular keys (`specialization:<uuid>`, `division:<uuid>`, `group:<uuid>`, `competence:<uuid>`) and the worker drops only those items from the prompt while keeping the category. Category-wide keys (`specializations`, `divisions`, `company`, `source_tree`) still work and drop the whole category at once.
  - `group` (HRP-114, extended) — Specializations, **Related specializations** (subset whose matrix links cover any competence in this group's subtree), Divisions, Company description, group's existing competences (`source_tree`), Ancestor groups, Descendant subgroups (with competences). Each surfaces as its own per-item chip with × in the picker, and ships granular `context_excludes` keys (`specialization:<uuid>`, `related_specialization:<uuid>`, `division:<uuid>`, `group:<uuid>`, `competence:<uuid>`, `ancestor:<uuid>`, `descendant:<uuid>`).
  - `competence_indicators` (HRP-114, extended) — Specializations, **Related specializations** (subset whose matrix references this competence), Divisions, Company description, the competence's sibling competences in its group (`sibling_competences`, also drops matrix siblings when the session was launched from a matrix cell), and the competence's existing indicators (`existing_indicators`). Per-item chips with × emit `specialization:<uuid>`, `related_specialization:<uuid>`, `division:<uuid>`, `competence:<uuid>` keys; the existing-indicators block is a single category-wide toggle.
- **Linked-aware spec/division picker (HRP-114 re-spec)** — for `group` and `competence_indicators` scopes the `Specializations` and `Divisions` sections render the *full* tenant list as checkbox-chips. Specs/divisions reachable from the scope's competences (specialization via matrix links; division via positions tied to one of those specs) carry an `is_linked: true` flag, a `link` marker icon with a tooltip explaining the connection, and are pre-checked by default. Unlinked items render dimmed but selectable so the user can broaden the context manually. A `(X of Y selected, Z linked)` counter sits in the header, and once a list exceeds 15 items a search input plus a "Show linked only" filter appear. The backend supplies `is_linked` on `/context-options`; the dialog seeds `context_excludes` with every `specialization:<uuid>` / `division:<uuid>` whose flag is false so the worker never sees them unless the user explicitly opts them back in.
- **Result preview shows existing + new in one tree (HRP-114 re-spec)** — once a `group` or `competence_indicators` session reaches `ready`, the drawer surfaces the snapshot of what's already in the group/competence next to the freshly generated suggestions. Existing nodes render with a dashed border, `existing` badge, locked checkbox (with tooltip "edit it from the group page"), while new suggestions stay fully editable. A summary line at the top (`X new items will be added · Y existing items in this group`) updates as the user un-ticks new suggestions, and a `Show: All / New only` toggle hides the existing block when the user wants to focus on what's changing. When the LLM produced *only* duplicates (every suggestion matched a snapshot), the preview shows a banner ("Generated items duplicate existing ones — nothing new to add") and the existing `Add to library` button stays disabled until the user picks at least one new item. The data ships on the same `SessionRead` response via `existing_tree` (group/whole_base) and `existing_indicators` (indicators scope).
- Failed runs record an `error_code` (`service_error` / `overload` / `insufficient_data` / `parse_error`) so the UI can show a targeted message; an in-app notification is created on every terminal state.

### AI Settings
Per-tenant configuration applied to every AI generation call (competences, indicators, PDP goals, positions). Workspace administrators manage settings on `/(dashboard)/settings/ai`; the underlying admin-only API lives under `/api/admin/ai-settings` (`GET`, `PATCH`, `POST /reset`, `GET /presets`, `GET /models`).

- **Content language** — currently only `en` is supported. More languages will be added in the i18n phase; the underlying schema and API are forward-compatible.
- **Effort tiers** — pick a preset that controls model, sampling temperature, and the retry budget for malformed JSON responses.

  | Tier | Cost / Speed | Quality | Default model (Claude) |
  |------|--------------|---------|------------------------|
  | `fast` | Cheapest, fastest | Suitable for prototyping | `claude-haiku-4-5-20251001` |
  | `balanced` (default) | Mid-cost | Production-ready | `claude-sonnet-4-6` |
  | `thorough` | Most expensive, slowest | Highest quality | `claude-opus-4-7` |
  | `custom` | Configurable | — | Stored `llm_model` |

- **Model whitelist** — `llm_model` must come from the platform-managed allow list (`GET /models`). Free-text model IDs are rejected with HTTP 422. The whitelist is the single source of truth for both the picker UI and the public `/pricing` page.
- **Per-model credit multiplier** — every whitelisted model carries a `credit_multiplier` anchored to the Balanced tier (×1.0). Cheaper models scale down (Haiku/Mini/Flash ≈ ×0.4) and higher-quality models scale up (Opus ≈ ×3.0). Final cost = base price × multiplier, rounded **up** to the nearest 0.1 credit. Embeddings (`ai.semantic_search`, `ai.create_embedding`) keep a fixed price.
- **Custom model override** — pick a model from the provider/model selectors, or leave the model field on "Use preset default" to inherit the active tier's model. Setting the model, temperature, or retries flips `effort_level` to `custom`.
- **Company context** — up to 2000 characters appended to every system prompt. Example: `"Acme is a 200-person fintech focused on payment infrastructure for emerging markets."`
- **Retry budget** — `max_retries` (1–10) controls how many times the worker re-prompts the model when JSON parsing fails.
- **Spend preview** — when an unsaved change would alter the effective multiplier the save bar shows a `current → next` credit estimate based on a sample AI action.
- `POST /reset` returns the row to balanced + English + no override + no context.

---

## Public API

### REST API (v1)
Programmatic access for integrations and automation.

- API key authentication (generated per tenant in settings)
- Base URL: `/v1/` — all endpoints prefixed with version
- Rate limiting: 60 requests per minute per API key (slowapi)
- Validated pagination: `skip` and `limit` on all list endpoints

### Read Endpoints
- `GET /v1/employees` — list employees with pagination
- `GET /v1/employees/:id` — employee detail
- `GET /v1/assessments` — list assessments
- `GET /v1/assessments/:id` — assessment detail
- `GET /v1/divisions` — list divisions
- `GET /v1/specializations` — list specializations
- `GET /v1/grades` — list grades

### Batch Operations
Create multiple resources in a single API call.

- `POST /v1/employees:batch` — create up to 100 employees
- `PATCH /v1/employees:batch` — update multiple employees
- `POST /v1/divisions:batch` — create multiple divisions
- `POST /v1/specializations:batch` — create multiple specializations
- `POST /v1/grades:batch` — create multiple grades
- `POST /v1/assessments:batch` — assign assessments to multiple employees
- `POST /v1/exams:batch` — assign exams with division/specialization filters
- Per-item error reporting — partial success supported

### OpenAPI Specification
- `GET /v1/openapi.json` — auto-generated OpenAPI spec filtered to v1 paths
- Download and use with any API client or code generator

---

## Platform Features

### Waitlist
Public lead-capture endpoint for collecting interest while a deployment is closed (e.g. during a private beta or before a public launch).

- `POST /api/waitlist` — public, rate-limited to 10 requests/minute per IP
- Idempotent on email (duplicate signups return the existing record, no error)
- Captures interest type (`self_hosted` / `cloud` / `both`), role, company, free-form note, and source label
- Sends a branded confirmation email via Resend or SMTP
- Platform admins can list signups (`GET /api/waitlist`) and mark invitations sent (`POST /api/waitlist/{id}/invited`)

### File Storage
Secure file upload and management via S3-compatible storage.

- Upload files via multipart form upload
- S3-compatible backend (MinIO, Cloudflare R2, AWS S3)
- Presigned URLs for secure file access (1-hour expiry)
- Tenant-isolated file paths
- Avatar upload for user profiles (POST /auth/avatar, DELETE /auth/avatar)
- File attachments on PDP comments and materials
- Image uploads for exam questions

### Authentication & Security
- Email + password registration with email verification
- Self-serve registration UI on self-hosted installs (`/register` creates the company workspace + admin account; the root URL redirects to sign-in)
- No-email-provider fallback: accounts auto-verify at registration when no provider is configured; failed verification sends print the link to the backend log
- Verification email with 24-hour expiry link
- Resend verification endpoint (rate-limited, no email enumeration)
- JWT access tokens (30 min) + refresh tokens (7 days)
- Password reset via email
- Role-based access control (RBAC)
- Invitation flow auto-verifies email (invitation proves ownership)

### Role-Based Access Control
Three built-in roles with different permission levels.

- **Admin**: full access — manage users, roles, assessments, settings
- **Manager**: create assessments, PDPs, view team data
- **Employee**: view own profile, assessments, PDPs; complete assigned tasks

### Multi-Tenancy
Complete data isolation between organizations.

- Each organization (tenant) has its own data space
- Users, employees, assessments — all tenant-scoped
- Self-hosted mode runs a single tenant

### Multi-Tenant Login & Tenant Switching
One person can belong to multiple organizations with a single email address.

- Login detects all tenants associated with the email
- Single tenant: JWT issued immediately (no extra steps)
- Multiple tenants: organization picker shown on login — select which tenant to enter
- `POST /auth/select-tenant` — complete login for a chosen tenant
- `POST /auth/switch-tenant` — switch to a different organization without re-entering password
- `GET /auth/tenants` — list all organizations available to the current user
- Tenant switcher in header: dropdown with organization name, slug, and role badge per tenant
- If only one tenant, the switcher shows the name without a dropdown
- Each tenant shows the user's role (admin, manager, employee)

### Dark Mode
Full dark mode support across the entire application.

- Toggle: light / dark / system preference
- Persisted in localStorage + cookie (for SSR)
- All pages and components tested in both themes

### Responsive Design
Works on desktop, tablet, and mobile.

- Collapsible sidebar on mobile
- Horizontal scroll for tables on small screens
- Full-screen dialogs on mobile
- Tested on 375px (iPhone SE), 768px (iPad), 1024px+

### Global Search
Quick navigation with keyboard shortcut.

- Press Cmd+K (or Ctrl+K) to open search
- Search across employees, assessments, PDPs, exams
- Instant results with keyboard navigation

### Self-Hosted Deployment
Run HRPulsar on your own infrastructure.

- Docker Compose deployment
- PostgreSQL + Redis included
- Caddy for automatic SSL
- MinIO for file storage (S3-compatible)
- White-label branding: installation name, logos, accent color and favicon configurable via environment variables for the web UI and outgoing emails — no source changes needed (see the Branding section of the Self-Hosted Guide)
- See [Self-Hosted Guide](SELF_HOSTED.md)

---

## Onboarding Wizard

First-login wizard for newly registered organizations to guide initial setup.

### Detection
- Automatically shown when a tenant has 0 employees and onboarding is not yet completed
- Dashboard redirects to the wizard when onboarding is needed
- Wizard is skippable — marks onboarding as complete without requiring any steps

### Steps
1. **Company Info** — set industry, company size, website, and description
2. **Create Division** — create one or more divisions for the organization, with the option to add more
3. **Invite Team** — enter email addresses to invite colleagues (sent as pending invitations)
4. **Competences** — choose to browse the built-in competence library or set up later

### Completion
- "Finish setup" marks onboarding as complete in tenant settings (not shown again)
- "Skip setup" available on every step to bypass the wizard entirely
- Onboarding status is persisted per tenant via `onboarding_completed` flag

## Recruitment

### First-touch onboarding
- Non-blocking sticky banner on every `/recruitment/*` page guides a fresh tenant through the five canonical steps — create a vacancy, add a candidate, schedule an interview, run the AI analysis, generate a consolidated report
- Steps advance automatically as the backend observes meaningful mutations (state lives in `Tenant.recruitment_onboarding`); banner hides itself when `step === "done"` or the user explicitly clicks **Skip tour**
- `Use demo data` on the first step seeds a demo vacancy + candidates that auto-expire after 14 days
- `/recruitment` redirects to `/recruitment/requisitions` so the dashboard is always usable — the banner sits above the live content instead of replacing it
- Section tabs on every top-level recruitment page — Vacancies / Candidates / Reports / Audit / Settings — mirror the Company section navigation; the Settings tab is visible to admin-tier users only (HRP-353)

### Vacancies & Candidates
- Vacancy CRUD with structured fields (specialization, grade, division, salary, KPIs)
- Vacancy list shows Title / Position / Division / Status / Candidates / Owner (creator's full name) / Created columns; the **All statuses** filter includes archived vacancies (greyed rows with an `archived` badge) while concrete status filters and the dedicated Archived view behave as before (HRP-363)
- Every vacancy carries a **Hiring manager** (admin-tier user, defaults to the creator) editable on the create / edit forms and the Overview inline edit; the picker is fed by `GET /recruitment/hiring-managers` and the API validates the user is an active admin of the tenant (HRP-360)
- Single-page vacancy view stacks Overview / Competences & indicators / Candidates with per-section inline Edit + Save; secondary tabs (Questions / Reports / Analytics) sit above the sections; closed and archived vacancies switch to read-only (HRP-180)
- Position-linked Specialization and Grade multi-selects on the vacancy form — picking a Position constrains the spec/grade pool to that Position and the API rejects values outside the pool with 422; legacy single-value `specialization` / `grade` text fields stay around for back-compat (HRP-180)
- Description, Requirements, Responsibilities, Conditions, Main tasks, Additional tasks and KPI longer than 300 characters all collapse with Show more / Show less (`aria-expanded`) in view mode; edit mode renders the matching textareas with min-height 6 rows and an internal scrollbar after ~20 rows so long copy never blows out the form (HRP-180, HRP-319)
- Vacancy lifecycle actions: Edit / Archive (90-day retention) / Restore / Delete permanently (draft + no candidates + no profile); kebab menu in card header and list rows; ETag (`If-Match`) protects against parallel-edit overwrites; archive deactivates pending reviewer invites (HRP-177)
- AI-generated competency profile from vacancy description and tasks (synchronous endpoint parks the generated payload on the session row for review — nothing is saved until the recruiter applies it — or returns a 502 with the upstream error; only one generation session per vacancy runs at a time, a second `POST /profile/generate` returns 409)
- Generate competence matrix modal: confirm screen previews the vacancy context that will reach the prompt (title, description, employment type, location, requirements, responsibilities, conditions) and exposes a free-form clarification textarea passed through to the LLM (`clarification` field on `POST /recruitment/vacancies/{id}/profile/generate`); review stage renders the generated tree with per-competence keep/drop checkboxes, inline edit on names / Why important / How it manifests / indicators / interview questions / good-acceptable-poor answers, and a trash icon on every node (group, subgroup, competence, indicator, question); previously-saved competence rows stay locked with a `Saved` chip and cannot be dropped; Save selection calls `PUT /recruitment/vacancies/{id}/profile` with the kept + edited subset — the only path that writes the profile; Discard and Cancel simply retire the pending session (the saved profile is never touched during generation), and a race-safe guard on the backend keeps a late LLM response from resurrecting a dismissed run; while a session is running or its result awaits review, a page banner shows progress or a **Review for save** button and the Generate / Regenerate / Edit / Add from dictionary actions stay locked (HRP-134, HRP-235)
- Vacancy creation pulls company-library refs — positions, specialization+grade pairs, divisions — and seeds vacancy competences from the linked grade matrices; manual Requirements / Responsibilities / Conditions text blocks feed into the AI prompt; per-vacancy attachments (PDF / DOCX / PPTX / XLSX / TXT / MD / CSV / JSON / PNG / JPEG / GIF / WebP / ZIP / EPUB, 25 MB × 10 max) ingested for context (HRP-131 / HRP-135)
- Create Vacancy form is dependent-cascading: Position (single, Active only) → Specializations (multi, locked until a Position is chosen) → Grades (multi, locked until a Specialization is chosen) → Division (single, from Company → Divisions); the legacy freeform Specialization / Grade / Division text inputs and the separate Library refs block were retired in favour of these wired selects, and Save Draft forwards every Specialization × Grade pick into `library_refs.specialization_grade_pairs` so the Competences & indicators block auto-fills from the matching matrix on first load (HRP-320)
- Vacancy competence list (manual / library / AI source) editable from the Competences & indicators section via PATCH replace-set (HRP-136)
- Competences & indicators block edits inline — clicking Edit swaps the header into Cancel + Save (disabled until at least one change) while Regenerate and Add from dictionary stay docked; the modal dialog is reserved for the AI Generate / Regenerate flow only. Edit mode covers the full structure: criticality is a select on every competence card, new competences (with indicators and interview questions) can be added into any subgroup, and new groups / subgroups are created in place — an empty section stays local until its first competence is saved (HRP-318)
- Canonical candidate add on the vacancy page: required Full Name plus email or phone, optional LinkedIn / location / current position / years of experience; duplicate email against an active candidate inside the tenant returns 409 with `existing_candidate_id` so the modal can prompt link-or-create; archived twins are invisible so the same address can be re-imported after a soft-delete (HRP-181 REDO)
- Batch finalize from parsed resumes: the modal posts a list of parsed file IDs (optionally each tagged with `link_candidate_id` after the dup prompt) and the backend creates one canonical candidate per file or links to the chosen existing row, attaching each to the vacancy's first active stage (HRP-181 REDO)
- Bulk resume upload with batch LLM parsing — up to 50 PDFs/DOCXs per upload (10 MB each, 100 MB total), parsed asynchronously; the modal polls status and surfaces a duplicate-email preview before the user clicks Import (HRP-181 REDO)
- Enriched candidate list shows last position (from parsed resume), years of experience, current stage, manager score, AI score, AI verdict (`pending` / `recommended` / `needs_check` / `not_recommended`) with strength / risk / mitigation snippets, and a `score_divergence` flag when the manager and AI scores diverge by ≥ 1.0; default sort keeps terminal stages at the bottom and orders the rest by manager score descending (HRP-181 REDO)
- AI score column renders either the raw LLM mean (back-compat default) or a `[0..1]` normalized score rebased against the tenant's active scale via a per-vacancy Raw / Normalized toggle; backend stores both fields on `candidate_vacancies` so cross-tenant comparisons stay safe, and `InterviewAnalysisResult.verdict` shares the resume-only enum so the candidates table reads one consistent verdict word for full-mode and resume-only runs alike (HRP-274)
- Candidate stage / manager score PATCH is `If-Match` ETag-gated against `candidate_vacancies.version` (412 on stale token); the AI block is internal-only — only the parser and verdict generator write to it (HRP-181 REDO)
- Candidate card endpoint returns the canonical fields plus every CandidateVacancy attachment (vacancy, stage, manager / AI scores, AI verdict snippet, added-at) and the full file list in one round-trip; PATCH supports inline edits to every visible section and accepts a full `parsed_resume_jsonb` overwrite for experience / skills inline edits, also ETag-gated; DELETE soft-deletes by stamping `archived_at` so the partial unique index frees the email for re-import (HRP-181 REDO)
- Per-tenant default funnel stages (9 spec stages — `new` → `screening` → `tech_interview` → `manager_interview` → `final_interview` → `offer` → `hired` / `rejected` / `withdrew`) seeded at tenant create and exposed via a dedicated tenant endpoint; per-vacancy override replaces the funnel wholesale (PUT) with `stage_type` controlling the active / terminal-positive / terminal-negative / terminal-neutral classification, and deletion of a stage that still has candidates returns 409 with `affected_candidate_count` (HRP-181 REDO)
- Vacancy → Candidates section UI on the canonical model: one Add candidate modal with Upload resume / Enter manually tabs; the upload tab drives the bulk-resume flow (drop-zone → 2.5 s parsing-status poll → dedup-aware import summary with per-file link-or-create radios), the manual tab handles required name + email/phone with a link-existing prompt on a 409 (HRP-181 REDO Stage 4)
- Vacancy candidates table renders Candidate / Last position / Experience / inline Stage select / Manager score / AI score / AI data readiness / AI verdict badge with details popover / Added (FR-09); terminal-stage moves prompt before mutating; manager and AI score cells share an amber background when they diverge by ≥ 1.0 (HRP-181 REDO Stage 4)
- Canonical candidate card page (`/recruitment/candidates/{id}`) is a single long page with header contact links, inline-edit Personal info (ETag-gated PATCH), per-section inline editors for the parsed resume (Summary / Skills chip input / Experience / Education / Languages / Certificates — each Save ships the full `parsed_resume_jsonb` back under `If-Match`), Files list with resume download, and Vacancy applications with per-attachment AI verdict (HRP-181 REDO)
- Manage funnel stages drawer on the vacancy page: drag-and-drop sortable rows, inline name / code / color / stage-type editing, Restore default reseeds from the tenant template, and Save surfaces an explanatory confirm dialog when the backend returns 409 with `affected_candidate_count` (HRP-181 REDO Stage 4)
- Candidate persons (multi-role: candidate / employee / external evaluator)
- Resume upload with automatic LLM parsing into structured candidate data
- Funnel stages with tenant-level customization and per-vacancy overrides
- Side-by-side candidate comparison (up to 5) with score divergence indicator
- Status history with timestamps and authoring user

### Consolidated XLSX report — 4-sheet layout (HRP-268)
- Every report always carries the same four kinds of sheet, in order: **Summary** (one row per candidate with profile snippet, Manager / AI %, data readiness, computed recommendation), **Matrix** (competences × candidates with side-by-side Manager / AI columns, group separators, amber divergence fill and a SUM-based Total row), **Detail · {candidate}** (one sheet per candidate with resume summary, per-competence scoring + citations, blind spots, red flags, process findings, verdict), and **Incomplete data** (always emitted, even when every candidate is complete)
- Audience selector in the report wizard — `recruiter` keeps the raw process-findings text on Detail sheets; `hiring_manager` replaces it with `positive_reframe` / a neutral "Recommendation for the next interview" so candidate-side issues never reach the manager unfiltered
- `POST /recruitment/vacancies/{id}/reports` accepts an optional `candidate_vacancy_ids` whitelist; omitted means every attached candidate
- Download pre-signed URL TTL bumped from 1 h to 24 h so a recruiter can email the link and the hiring manager can still open it the next day
- All copy is English; no language switch ships — language hooks land when more locales arrive

### Candidates table — % match + Divergence column + Sort-control (HRP-267)
- Per-row Manager % / AI % match badges underneath each numeric score, mirroring the Compact matrix (HRP-265) and honouring the tenant `divergence_threshold` for the cell-level divergence count
- New **Divergence** column between AI score and AI data with an amber `N` badge + tooltip preview of up to 5 divergent competences; click opens Canvas
- Sort-control above the table (By Manager / By AI / Custom + asc/desc) persists in URL and per-vacancy localStorage so the recruiter's view round-trips between sessions
- Terminal stages (positive / negative / neutral) stay pinned to the bottom of any non-Custom sort

### Canvas Versions panel + conflict resolution (HRP-266)
- Full audit timeline of assessment edits per vacancy via `GET /recruitment/vacancies/{id}/assessment-history` with evaluator / candidate / date-range / `only_divergence` filters (the divergence cut-off uses the tenant's `divergence_threshold`)
- **Revert** button restores any prior Manager-side score via `POST /recruitment/candidate-vacancies/{cv}/assessments/{competence}/evaluators/{evaluator}/revert` with the source audit-event id in the body; the revert itself is audited and billed as one `recruitment.revert_assessment`
- Assessment writes (`POST .../assessments`, `PATCH /assessments/{id}`) now honour an `If-Match: W/"{version}"` header — a stale snapshot returns HTTP 412 instead of silently overwriting a parallel editor
- Canvas reacts to the 412 by freezing the cell and surfacing a Keep mine / Keep theirs dialog; choosing Mine retries with a fresh `If-Match`, choosing Theirs drops the local edit. Toast warns the user without blocking other cells

### Assessments tab — Compact matrix (HRP-265)
- Vacancy page gains an **Assessments** tab between Questions and Reports rendering a Compact matrix `candidates × competences` with side-by-side `M:N / AI:N` cells, sticky candidate column and per-row `% match` badges for Manager and AI
- Matrix rows show the candidate's denormalised full name (resume-sourced candidates have no Person row) as a link to the candidate card, with the current funnel stage name underneath; the cell-detail footer links the name too (HRP-361)
- Per-candidate aggregates: Manager %-match uses the full profile as denominator; AI %-match drops competences the AI explicitly marked `not_covered` from its denominator so a candidate with only two skipped competences out of 22 is not unfairly diluted
- Per-cell divergence flag fires when `abs(manager_avg - ai_score) >= tenant.divergence_threshold`; cells turn amber + ⚠️, the per-row badge shows `N/M competences`
- Per-tenant `manager_ai_divergence_threshold` setting (`GET / PUT /recruitment/settings/matrix`, admin-only on write); defaults to 1.0 — the historical hard-coded value — so existing tenants see no behavioural change until they opt in
- Click any cell to open a footer-info popover with every evaluator's score + comment and the latest AI score with reasoning + citations; **Open fullscreen** jumps to the existing Canvas page for inline editing

### Questions & Assessments
- AI-generated interview questions per candidate × vacancy from resume + profile
- Manual question editing, importance/purpose tags, draft / good / acceptable / poor expected answers
- Per-candidate individual question sets that evolve across interview rounds: initial / regenerated / dynamic-next modes; questions carry text, goal, priority, source (AI / manual / from indicator / from blind spot), resume anchor, expected answer indicators, follow-ups, rationale; mark-as-covered (manual + auto-from-transcript) so the next round skips answered ground; blind spots from prior analyses become next-round probes; soft-delete keeps the row so regenerate never resurrects it; sample-mode preview when AI generation is unavailable; PDF export in Compact / Full / Cards layouts; the section lives on the candidate card with a per-vacancy selector, a Generate next set button once a round is transcribed, ready/failed notifications with a deep link, and questions whose competences were assessed in the analyzed transcript are auto-marked as covered; a tenant setting reorders the section above the resume for hiring managers
- Human assessment grid (canvas) with per-evaluator scoring and version history
- External evaluator invites (token-based, no account required)
- Last-write-wins per evaluator × competency with explicit version tracking

### Manager assessments (HRP-186)
- Tenant-scoped Assessment scales (2–10 weighted levels with optional reference descriptions); one default per tenant; default seed shipped out of the box (1 Not suitable → 4 Exceeds expectations)
- Vacancy binds a scale and freezes a snapshot on the first written score; the snapshot is then read-only — switching scales requires a new vacancy
- Per candidate-vacancy rounds: `pre_interview`, `interview-N` (unbounded), `final`; new rounds via `+ New round`; archived rounds drop out of aggregation
- Per-evaluator assessment sheets inside a round (multiple internal evaluators + external invitees); each evaluator writes only into their own sheet
- Indicator-level and competence-level scoring; if any indicator is scored, Overall is computed and tagged `from indicators`; manual override still wins
- Autosave with `Saving…/Saved` indicator, progress counter, mark-as-complete button
- Round divergence highlight when evaluator spread on a competence ≥ the scale's threshold (default 2)
- Aggregated Manager score on `candidate_vacancies` = mean level of the latest *complete* round (fallback: latest with any scores); recomputed on every score / round status change; row keeps a pointer to the source round
- External evaluator invitations: hash-stored tokens (`SHA-256`), per-IP rate limit (60 req/min with deny-list after 5 invalid tries in 5 minutes), per-tenant max expiration (default 30 days), `Allow re-editing` toggle, optional personal message rendered in the email; invitations are refused until the vacancy profile has competences (no empty sheets); the email names the candidate and links straight to the public evaluation page
- Invite status model: `pending` → `opened` (first link visit) → `in progress` (first saved score) → `submitted`; non-terminal invites past their deadline show `expired` in the recruiter list, and expired links answer `410 Gone` with a dedicated page
- Public `/public/assessments/{token}` page: token-only access (no tenant JWT, no navigation into the app), strict per-request CSP with nonce'd scripts plus `X-Robots-Tag: noindex` and a no-referrer policy; consent gate, inline-edit evaluator name, two-pane layout — resume viewer and AI interview questions next to the full competence sheet (Overall radios, indicators, comments, progress, 1.5 s autosave); submit warns when under half of the critical competences are scored; after submit the form stays editable until expiry when re-editing is allowed, otherwise turns read-only; dedicated `expired` / `revoked` / `invalid` error pages with `410 Gone` responses
- Recruiter UI: list of invites per round with status chips (`pending` / `opened` / `in progress` / `submitted` / `expired` / `declined` / `revoked`); Resend / Extend / Revoke actions

### Interviews & AI Analysis
- Schedule interviews with title, timezone, duration, type (audio / video / text transcript), multiple interviewers, and notes — directly from the candidate card
- Interviews section on the candidate card: per-vacancy rounds list with upload / transcription / analysis statuses, consent banner with send-link action, and links to each interview's detail page
- Multi-file upload: drop several recordings at once — one interview per file — with per-file progress
- Auto-processing: optional transcribe-and-analyze chain kicks off right after the upload lands (falls back to the manual buttons when declined)
- Interview lifecycle: scheduled → uploading → uploaded / upload_failed → archived (90-day restore window before purge)
- Audio (mp3, wav, m4a), video (mp4, webm, mov, avi) up to 500 MB and text transcripts (PDF, TXT, paste) up to 10 MB
- TUS-style chunked upload with persistent client session: pause / resume, automatic retry of failed chunks, resume after browser reload from the right offset, cancel safely (S3 multipart aborted)
- Pre-signed playback URLs default to a 5-minute TTL and auto-refresh; SSE-encrypted, tenant-prefixed S3 keys; antivirus stub runs after upload and flips the row to `upload_failed` on `infected`
- In-app player: audio / video, speed 0.75x–2x, ±15 s skip, fullscreen, keyboard shortcuts (Space, J/L, arrows, F); PDF transcript viewer via `<object>`
- Inline-paste transcript path: speaker labels (`Interviewer:` / `Candidate:`) parsed into segments, skips S3 and antivirus
- ETag-guarded PATCH on metadata edits (`If-Match: W/"{version}"`) prevents silent overwrite by concurrent editors
- Consent capture flow (template + magic-link signing) required before upload init
- Pluggable transcription providers: OpenAI Whisper, Deepgram (diarized)
- AI-driven analysis pipeline: data completeness, competence scores, blind spots, process findings, red flags, verdict
- Two analysis modes (HRP-204): **resume-only** (20 cr, 4-of-6 stages — pre-check, competences, blind spots, verdict; never returns `recommended`; emits `ResumeExcerpt` references in place of transcript citations) and **full** (40 cr, six stages, interview-anchored). The candidate card surfaces an AI Insights section with a per-vacancy selector, a split-button (primary "Resume only" + chevron dropdown for "Resume + interview" — disabled with a tooltip when no transcribed interview exists, HRP-269), and a history modal interleaving resume-only and full runs by timestamp
- **Top-up upgrade** turns a prior resume-only run into a full one for the delta only (+20 cr instead of 40); auto-blocked when the prior run is older than 30 days or the vacancy's competence profile has been edited since
- **In-flight progress + cancel** (HRP-270): the candidate card renders all six pipeline stages (resume-only mode greys out Citations + Process analysis), polls every 3 s, and exposes a Cancel button on the in-flight card that revokes the Celery task and refunds 100 % credits if the run never reached the first LLM call (otherwise no refund, the model call has already been billed)
- **Click-to-locate resume citations** (HRP-271): the active resume-only run renders each `ResumeExcerpt` as a clickable chip grouped by section — clicking one scrolls to the matching block in the parsed-resume editor (company + period match for Experience, substring match elsewhere), auto-expands the section if collapsed, and applies a 2 s ring highlight. Parsed-resume sections gain a per-section chevron toggle so a recruiter can fold any block while keeping the citation jump-target alive
- **Outdated-resume banner** (HRP-272): each resume-only run stamps a SHA256 of the candidate's parsed-resume at enqueue time. When the candidate uploads a fresh CV after the run finished, AI Insights surfaces a "Resume updated — re-analyze" callout that re-runs resume-only (20 cr); the worker archives the prior active run on success so the candidate row never reads two completed analyses for the same pair. Legacy runs without a stamped hash and full-mode runs do not show the banner
- **Bulk fan-out**: the vacancy candidates table shows a one-click "Bulk analyze" bar for every candidate that has a parsed resume but no AI verdict yet; charges resume-only × N up front and reports per-row queue / skip results
- Sub-badges `[resume only]` / `[full]` next to the verdict in the candidates table and on the candidate card so a recruiter never confuses a resume-only pre-screen with a full assessment
- Role-aware redaction at read time (hiring managers see process reframes, no raw red flags); invited evaluators get playback only when the tenant opts in
- Stuck-task recovery via Celery `task_failure` signal + periodic sweeper; orphan upload-session cleanup task aborts inactive S3 multiparts after 24 h

### Reports
- XLSX consolidated report generation as a Celery task (presigned download URL)
- Up to 9 selectable section sheets: vacancy summary, competence profile, candidates, comparison grid, interview analyses, human assessments, process findings, red flags, verdict
- Saved report templates with one default per tenant; admins can disable templates without deleting
- Tenant-wide report list at `/recruitment/reports` with vacancy + status filters
- Tenant-logo branding embedded on the cover sheet when a logo is configured

### Settings hub
- Single `/recruitment/settings` landing page with sub-pages for scales, LLM and STT providers, branding, retention, roles, report templates, consent templates
- Per-tenant scoring scales with active picker — UI components read the upper bound dynamically instead of hard-coding 5
- Bring-Your-Own-Key for LLM and STT providers (Anthropic, OpenAI, Gemini, Azure, Yandex, GigaChat, Whisper, Deepgram, AssemblyAI, faster-whisper); keys are encrypted with AES-GCM at rest and only the last 4 characters are returned by the API
- Branding: accent / secondary colors and report watermark stored as JSON on tenant; live preview of report cover
- Retention windows (days) for interviews, resumes, consents and reports with sub-30-day legal warning
- Read-only role matrix: admin / recruiter / hiring_manager / hr / hrd permissions

### Compliance
- Append-only audit log of mutating recruitment actions with payload diffs, IP, user agent
- Tenant-wide audit page `/recruitment/audit-log` with entity_type / action filters, expandable diffs, pagination (admin/hrd only)
- GDPR data export: gathers person, candidate, resumes, candidate-vacancies, questions, interviews, segments, human + AI assessments, consents into a single JSON document with a 7-day presigned download URL
- GDPR soft-erasure: replaces PII in person, resumes, interview transcripts, segments and consent rows with `[redacted]`, preserves audit trail

## Monitoring & Observability

Infrastructure for production monitoring, error tracking, and operational health.

### Prometheus Metrics
- `/metrics` endpoint exposing Prometheus-format metrics
- Request count (`hrpulsar_http_requests_total`) with method, path, status labels
- Request latency histogram (`hrpulsar_http_request_duration_seconds`) with configurable buckets
- In-progress request gauge (`hrpulsar_http_requests_in_progress`)
- Response size histogram (`hrpulsar_http_response_size_bytes`)
- Path normalization (UUIDs and integer IDs collapsed to `{id}`) to control label cardinality
- `/metrics` endpoint itself is excluded from instrumentation

### Structured Logging
- JSON-formatted log output via python-json-logger to stderr (Promtail-ready)
- Automatic `request_id` injection into every log entry via context variables
- `tenant_id` and `user_id` context propagation when available
- `service: "hrpulsar"` field in every log entry
- Request ID middleware generates 16-char hex ID or propagates incoming `X-Request-ID` header
- `X-Request-ID` response header returned on every response for client-side correlation

### Error Tracking (Sentry)
- Backend: `sentry-sdk[fastapi]` with FastAPI and SQLAlchemy integrations
- Frontend: `@sentry/nextjs` with client, server, and edge configs
- PII filtering via `before_send` — email, first_name, last_name, phone, password stripped from events
- Configurable via `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_ENVIRONMENT` env vars
- Frontend: `NEXT_PUBLIC_SENTRY_DSN` and `NEXT_PUBLIC_SENTRY_ENVIRONMENT`
- Source maps upload with automatic deletion after upload
- Graceful no-op when DSN is not configured (zero overhead in development)

### Health Checks
- `/health` — full health check with DB, Redis, and S3 connectivity checks
  - Returns `200 OK` with `"status": "ok"` when all checks pass
  - Returns `503` with `"status": "degraded"` when any check fails
  - Each check reports latency in milliseconds
  - S3 check skipped automatically when not configured
  - Includes application version in response
- `/health/ready` — Kubernetes readiness probe
  - Checks database and Redis only (required for serving traffic)
  - Returns `200` with `"ready": true` or `503` with `"ready": false`
- Health check requests filtered from access logs to reduce noise
