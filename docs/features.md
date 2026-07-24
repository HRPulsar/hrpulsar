# HRPulsar Features

HRPulsar is an open source platform for talent and competency management. This page describes what each module does in the current release. For installation see [Getting Started](/docs/getting-started); to run it on your own servers see the [Self-Hosted Guide](/docs/self-hosted).

---

## Employee Management

### Employee Profiles

A central record for every person in the company: position, division, hire date, status, and avatar.

- Two ways to add an employee: send an email invitation (the card is created when the person accepts) or create a card manually for an existing user
- Status lifecycle: active, on leave, inactive, terminated. Inactive and terminated accounts lose access immediately, and the employee is notified by email
- The profile header shows five summary tiles: Status, Tenure, Assessments, Goals progress, and Last assessment. Tile counts respect role visibility, so employees never see drafts hidden from them
- Goals progress averages completion across the employee's open development plans; a hint next to the tile explains the formula
- Edit rights follow the role matrix: admins and HR edit any record, division managers edit only employees in their own subtree, the employee role is read-only
- Assigning someone as a division manager or deputy upgrades their role automatically; removing the assignment asks for confirmation before the downgrade

### Employees List

A filterable directory of everyone in the workspace.

- Columns: name and email, division, position, specialization and grade, status
- Multi-select filters for divisions, statuses, positions, specializations, and grades. Selections persist in the URL, so a filtered view can be bookmarked or shared
- Search runs on the server and matches first name, last name, full name, and email across all pages
- Managers see only the divisions they manage in the filter; admins and HR see the full tree
- An edit dialog changes name, position, division, and status in one step, with the usual scope guards

### Employee Events

A timeline of milestones and changes through an employee's career.

- Event types: hire, position change, division change, termination, compensation change, certification earned, assessment complete, development plan complete, exam complete, grade change
- Events are recorded automatically on position, division, compensation, and status changes, with old and new values side by side
- Filter by event type; custom events with free-text descriptions are supported

### Employment History

Two blocks on the profile cover work history inside and outside the company.

- **Current employment** tracks division and position spells in this organization. Start date is required, end date is optional, and each record shows the elapsed duration. New records prefill from the employee card
- **Previous employment** records jobs at other companies: company, position, dates, and responsibilities. Dates are validated so the start never lands after the end

### Education

Formal education records: universities, colleges, degrees.

- Institution, degree type, and field of study, with start and end dates (ongoing education supported)
- Degree types: Secondary, Vocational, Bachelor, Master, PhD, Doctorate

### Courses & Certifications

Training courses and professional certifications.

- Course title, provider, completion and expiry dates, and a certificate URL for verification
- Expired certificates are highlighted in the list
- Each course can be linked to the competences it develops, picked from the same competence tree used in assessments

### Salary & Compensation

Compensation history per employee: salaries, bonuses, and allowances.

- Amounts are stored in minor units with an ISO currency code
- Effective date plus an optional end date for time-bound records, with free-text notes
- Every change writes an employee event automatically
- Admins and HR see all records; division managers see records inside their own subtree only
- Compensation analytics: average salary by division and totals by type

### Competences Tab

A snapshot of the employee's competence profile in two blocks.

- **Current position competences**: a tree of every competence the employee's position requires, with the score from the latest completed assessment at the required level. A dash renders when no assessment has reached that level yet
- **Other competences**: everything the employee was assessed on at a different level than the position requires, so results above or below the requirement stay visible
- Every row opens a per-level score breakdown from the latest completed assessment
- Score chips are color-coded: green at 75% and above, yellow from 50 to 74%, red below 50%

---

## Organizational Structure

### Company Profile

- Industry classification, company size, website, and description
- Company logo upload (PNG, JPEG, SVG, WebP, up to 5 MB) with drag-and-drop or import from a public URL
- Activity fields (business sectors) picked from a configurable dictionary
- The logo and profile appear on the public company page

### Divisions

Hierarchical organizational units: departments, teams, offices.

- Unlimited nesting depth with an expand/collapse tree view
- A manager and a deputy manager per division; the division manager becomes the default assessment reviewer for its employees
- List visibility follows the same scope everywhere: admins see the whole workspace, managers see their subtree, employees see their own records
- The division page shows specializations with employee counts per plate, plus an employee list with combinable filters by specialization, position, and grade
- An "Add employee" dialog attaches existing employees or creates new ones without leaving the page, with a confirmation step when someone is pulled from another division

### Positions

Structured job positions linked to grades, specializations, and divisions.

- Lifecycle status per position: active, on hold, frozen, closed. Closed positions are read-only until reopened
- Headcount planning with a filled/plan indicator and a drill-down list of assigned employees. Each row surfaces the person's highest-priority alert: inactive account, incomplete profile, overdue assessment, assessment awaiting approval, or a plan awaiting review
- The position page shows the resolved competence matrix as a compact tree with required skill levels, plus a deep link to configure the matrix
- Positions can be generated with AI from a text brief, with a mandatory draft review before anything is saved
- A dedicated admin view lists employees without a position for bulk assignment

### Specializations

Each specialization is a full profile, not just a dictionary entry.

- List view with grade count, position count, and headcount; detail page with Grades and Positions tabs
- Per grade: description, requirements, and a salary range
- The competence matrix editor is a competence-by-grade table with per-cell skill levels, a heat-map tint by level, indicator tooltips, and warnings on competences that lack indicators or materials
- Matrix consistency is guaranteed: a higher grade never requires a lower level than the grade below it, both in the editor and on the server
- A matrix can be generated with AI from a structured brief (responsibilities, tasks, KPIs, requirements) plus uploaded files (PDF, DOCX, XLSX, RTF, TXT). The result opens in a review screen where every suggestion can be edited or dropped before saving

### Competency Framework

The competence library: groups, competences, indicators, and learning materials.

- Hierarchical groups with two origins: built-in (system-wide) and custom (workspace-specific)
- Indicators per competence with skill levels and weights; learning materials with a typed format and comments
- Materials can be overridden per specialization: hide a base material for one audience or show an extra one only there. Development plans pick up these overrides automatically
- Explicit publish/unpublish workflow, plus visibility toggles per group and competence
- Custom skill levels per workspace; built-in levels stay locked
- Deactivation is guarded: an element used in a matrix, employee card, assessment, plan, or talent card cannot be silently removed, and usage checks show where anything is referenced
- Drag-and-drop reorganization of the tree with referential integrity checks
- A per-competence audit log records every publish, move, activation, and deletion with actor and timestamp
- The competence page groups indicators and materials by skill level, with editable indicator weights and drag-and-drop ordering

### Grade System

Career progression paths built from specializations and grades.

- Grades within specializations (for example Junior, Middle, Senior) linked to competence requirements through grade chains
- A passing score per grade (75% by default) used as the reference threshold in assessments
- Grade chains feed assessment criteria, grade recommendations, and career planning

### Dictionaries

Reference data shared across the platform: specializations, grades, skill levels, material types.

- Built-in and custom entries with sort ordering and active/inactive status
- Built-in entries can be switched on or off per workspace; their titles stay fixed
- Deleting a custom entry that is referenced elsewhere is blocked with a clear message

---

## Assessments

### Assessment Types

- Self, 180-degree, and 360-degree assessments
- Participant roles: self, manager, peer, subordinate
- Competence-based evaluation with configurable indicators and weighted answer scales

### Evaluation Criteria

What to evaluate is chosen in a dedicated panel, on single and mass assessments alike.

- Three modes: the employee's current position, a target specialization and grade, or hand-picked competences
- Target position mode pulls competences and levels from the grade ladder; "All grades" takes the highest level per competence
- Hand-picked mode opens a tree picker with group-level checkboxes and search
- The skill level per competence stays editable; on mass assessments, criteria propagate to every active child

### Answer Scales

- A default scale ships out of the box; workspaces can create their own
- The scale builder validates that percent levels cover 0–100 without gaps, orders options by drag-and-drop, and supports an optional "Don't know" answer that is excluded from scoring
- The scale is frozen into the assessment at launch, so editing a scale never changes a running assessment

### Taking a Survey

- Surveys open in a side panel with room for full question text and per-option labels
- Every answer saves automatically; comments save on a short debounce
- Closing the panel keeps the draft, and reopening restores it, so partial progress survives navigation

### Assessment Lifecycle

- Status flow: Draft → Sent → In progress → On review → Done, with Cancelled reachable from any state
- The first submitted answer moves the assessment to In progress automatically; review starts when every participant finishes, or earlier by hand once at least one participant is done
- Deadline tracking with email reminders; past dates are rejected at creation and at launch
- Each employee can have at most 3 active assessments. Mass launches skip employees at the cap and report how many were created
- Participants get an email when the assessment goes live, when it completes, and when it is cancelled after launch

### Results & Calibration

- Scores aggregate per role: indicator answers average within a role, roll up to skill levels using indicator weights, then to a per-competence percent, and the final score is the mean across roles. "Don't know" answers never count
- Each competence shows a percent, a resolved level from the scale, and a per-level breakdown
- The overall score is the mean of per-competence percents and appears next to the results once the assessment completes
- Reviewers can calibrate: override per-question totals while the assessment is locked for participants. Calibrated values are marked, survive recomputes, and can be reverted in one step
- A detailed results view for reviewers shows per-role answers and comments for every indicator
- Employees see their own results when the assessment is done; peers and subordinates never see results of assessments they only participated in

### Passing Score & Grade Recommendation

- A configurable passing score (default 75%) on position-based assessments, locked once the assessment leaves Draft
- On completion the platform computes a match percent per grade and recommends the highest grade that clears the threshold; if none does, it shows the closest grade marked as not confirmed
- The recommendation renders as a card with progress bars per grade, and the mass assessment summary lists the recommended grade per employee

### Mass Assessments

Run one campaign across many employees.

- Campaign-level type, scale, deadline, and criteria applied to every child assessment
- Unified tracking, per-employee recommendations, and score analytics: ranking, distribution, completed versus total
- Copy a previous round (criteria, participants, settings) and compare rounds over time

### External Reviewers

Collect feedback from people outside the system.

- Unique shareable links per reviewer, no login required, with a configurable expiry (30 days by default)
- Responses aggregate with internal participants; admins see who was invited, but individual external scores stay anonymous

---

## Development Plans

### Personal Development Plans

Structured growth plans tied to assessment results.

- At most 3 active plans per employee; the platform blocks a fourth until one finishes
- Each plan links to a development specialization and grade, prefilled from the employee's position. Plan items are then seeded from the competences that pair requires, with materials capped at the target skill level
- Status flow: Draft → Sent → In progress → On review → Done, with Returned and Cancelled. The first item the owner ticks moves the plan to In progress automatically
- Only the plan owner ticks items off; a ticked item locks so accidental clicks cannot undo real progress. Reviewers and admins keep full control during review
- A plan cannot be sent until every item has at least one material
- During review the employee sees a frozen snapshot of the items while the reviewer keeps editing live
- Past-due deadlines are highlighted in red in the list and on the plan page
- The assigned employee gets an email when the plan is sent; deadline reminders follow

### Items & Materials

- Items link to specific competences or stand alone
- Materials carry a title, format (course, book, article, video, practice), link or attached file, and estimated study time
- Items and materials reorder by hand; completed items become read-only until unchecked during review
- Progress recomputes whenever items are added, removed, or toggled

### Comments

- Comments at the plan, item, or material level with file attachments; images render inline
- A threaded discussion between the employee and the reviewer lives next to the work itself

### History & Versioning

- The platform snapshots the full plan state on every key transition: sent, review, returned, done
- Any version can be viewed or restored later

---

## Exams

### Exam Management

Knowledge testing with configurable questions and pass criteria.

- Single choice, multiple choice, and essay questions, with images, weights, and ordering
- Questions are editable while the exam is in Draft and lock at launch
- Status flow mirrors assessments: Draft → Sent → In progress → Completed, with Cancelled available until the exam terminates
- Launch validates at least one question, at least one assigned employee, and a future deadline

### Assigning & Taking

- Employees are assigned through a searchable picker filtered by name, email, division, or position
- The exam opens in a side panel; answers save automatically and a closed panel resumes from the draft
- The answer key is never exposed while taking the exam
- The submit button stays disabled until every question is answered; after submitting, the employee sees the earned score and a read-only review with correct answers highlighted
- When the last participant finishes, the exam completes automatically

### Pass Mark & Results

- One pass mark per exam: a minimum percent or absolute points, optionally scoped to a grade or specialization
- Automatic pass/fail per participant, with scores, timestamps, and links back to the employee profile

### Question Import

- Bulk import from Excel with a downloadable template
- Up to 6 answer options per question, weights, and Markdown in question text
- Duplicate detection against existing questions and row-level error reporting

---

## Talent Market

### Talent Cards

An internal job board for open positions and project opportunities.

- Card types for different opportunity categories, with a start date, optional end date, and rich descriptions
- Status flow: Draft → Published → Completed or Cancelled. A card publishes only when it has at least one required competence and one candidate
- Published cards freeze their requirements; edits require unpublishing

### Requirements & Matching

- **Required specializations**: rows of specialization, grade, and an optional minimum of years of experience
- **Required competences**: rows of competence and skill level. Picking a specialization prefills its competences from the grade ladder
- A match threshold per card (50–100%) controls how strict the competence matcher is
- The candidate pool fills automatically: an employee qualifies on work experience at matching positions and on assessment results for the required competences. Results from higher-level assessments project down to the required level
- The match cell shows competence and experience scores as separate chips; clicking it opens a breakdown with the exact numbers the matcher used

### Candidates

- Candidate statuses: matched, not matched, appointed. Manual nominees and appointed candidates survive automatic recomputes
- Employees on a published card can react to express interest; their manager gets an email, and reactions break ties in the ranking
- Appointment asks for confirmation, so a stray click cannot pin a candidate
- Emails go out on every lifecycle event: publish, being added to a live card, appointment, completion, cancellation, and removal from a published card
- Regular employees see only published cards and cards where they are a candidate; all write controls stay hidden

---

## User Invitations

- Invite colleagues by email with a pre-assigned role, division, and position; accepting creates the user account and the employee card in one step
- Invitation links expire after 7 days; an inviter can never grant a role above their own
- Bulk invite up to 100 people at once
- A management page tracks all invitations with status filters (pending, accepted, cancelled, expired), resend and cancel actions, and inline editing of pending invites
- Changing the email on a pending invite issues a fresh link, resets the expiry, and disables the old link

---

## Notifications

### In-App Notifications

- A bell icon with an unread count and a notification list
- Covers assessments, development plans, exams, and approaching deadlines
- Mark as read individually or in bulk

### Real-Time Updates

- A single WebSocket connection per user pushes new notifications, AI generation status changes, and background task updates without a page refresh
- Polling backs up the socket, so a dropped connection never strands the interface on a stale state

### Email Notifications

- Branded HTML templates, white-label ready, with a responsive layout
- Templates cover verification, password reset, invitations, assessments, plans, exams, certificate expiry, deadline reminders, and external reviews
- Delivery through the Resend API (cloud) or SMTP (self-hosted), sent in the background so the interface never waits on mail

### Delivery Tracking

- Every outbound email is logged with its status: sent, delivered, bounced, complained, failed
- Automatic retries on failure and a webhook for real-time delivery updates
- Admins can browse the log with status and recipient filters

### Preferences

- Per-user settings by event type and channel (email and in-app independently)
- Everything is on by default; disabled channels are skipped silently

---

## Analytics & Dashboards

- An overview dashboard with employee counts by status and division, active assessments, completion rates, plan progress, and recent activity
- Reports: assessment score distributions, competence heatmaps, and division comparisons
- Assessment export to XLSX, generated in the background with a download link when ready
- Long-running operations (imports, exports, AI generation) report their status through a single task-tracking mechanism

---

## Data Import

- Bulk employee import from Excel: email, name, position, hire date, work experience, education, courses
- Dictionary import: specializations, grades, skill levels
- Drag-and-drop upload, validation with row-level errors, and background processing with progress tracking

---

## AI Features

### Competence Generation

Generate competence structures with an LLM and review everything before it lands in the library.

- Four scopes: a whole competence base from scratch, an extension of one group, indicators for a single competence, and a competence-by-grade matrix for a specialization
- Every run starts from a confirmation dialog that shows exactly which data the model will read: specializations, divisions, company description, existing items. Each item can be excluded, and a free-text note refines the brief
- Results open in a review tree with cascade checkboxes: existing items are locked, new suggestions are editable and selectable. Nothing is saved without an explicit apply
- Refine a result with follow-up notes or regenerate from the same brief; the session history links refinements together
- Apply is idempotent, so a retried request never creates duplicates. New competences can land published or as drafts
- One active session per user; sessions survive navigation and page reloads, and a persistent banner links back to any generation in flight
- Learning materials can also be generated per skill level, with the same context controls and review step

### AI Settings

Per-workspace configuration that applies to every AI call.

- Effort tiers: fast, balanced (default), and thorough, each mapping to a model and a retry budget; a custom tier opens model, temperature, and retry controls
- Models come from a managed allow list, so only vetted models can be selected
- A company context field (up to 2000 characters) is appended to every prompt
- Supported providers: Claude, OpenAI, and Gemini

---

## Public API

### REST API (v1)

Programmatic access for integrations and automation.

- API key authentication, generated per workspace in settings
- All endpoints live under `/v1/` with a rate limit of 60 requests per minute per key and validated pagination
- Read endpoints for employees, assessments, divisions, specializations, and grades
- Batch operations create or update up to 100 resources per call — employees, divisions, specializations, grades, assessments, and exams — with per-item error reporting and partial success
- An OpenAPI specification at `/v1/openapi.json` works with any API client or code generator

---

## Platform

### Authentication & Security

- Email and password registration with email verification; self-hosted installs get a self-serve registration page that creates the workspace and admin account
- JWT access tokens (30 minutes) with refresh tokens (7 days), password reset by email, and rate-limited verification resend without email enumeration
- Installations without an email provider still work: accounts verify automatically at registration
- Invitation sign-ups skip verification, since the invitation itself proves ownership of the address

### Roles & Access Control

- Three built-in roles: **Admin** (full access), **Manager** (team assessments, plans, and data), **Employee** (own profile and assigned tasks)
- The same scope rules apply across every list in the product: admins see the workspace, managers see their subtree, employees see their own records

### Multi-Tenancy

- Complete data isolation between organizations; self-hosted mode runs a single workspace
- One email can belong to several organizations: login shows an organization picker, and a header switcher changes workspaces without re-entering the password

### File Storage

- S3-compatible storage (MinIO, Cloudflare R2, AWS S3) with tenant-isolated paths and presigned URLs
- Used for avatars, logos, plan attachments, and exam question images

### Interface

- Full dark mode: light, dark, or system preference, persisted across sessions
- Responsive layout tested on phone, tablet, and desktop sizes
- Global search on Cmd+K / Ctrl+K across employees, assessments, plans, and exams

### Waitlist

- A public signup endpoint for collecting interest before launch or during a private beta, idempotent by email and rate-limited
- Captures the interest type (self-hosted, cloud, or both), role, and company, and sends a branded confirmation email

### Self-Hosted Deployment

- Docker Compose deployment with PostgreSQL, Redis, MinIO, and Caddy for automatic SSL
- White-label branding: installation name, logos, accent color, and favicon set through environment variables, for the web UI and outgoing emails alike
- See the [Self-Hosted Guide](/docs/self-hosted) for the full walkthrough

---

## Onboarding Wizard

A first-login wizard for newly registered organizations.

- Shows automatically while the workspace has no employees and setup is not finished; skippable on every step
- Four steps: company info, first divisions, team invitations, and a look at the built-in competence library

---

## Recruitment

### Getting Started

- A non-blocking banner walks a new workspace through the first cycle: create a vacancy, add a candidate, schedule an interview, run the AI analysis, generate a report. Steps advance automatically as the work happens
- Demo data seeds a sample vacancy with candidates and cleans itself up after 14 days

### Vacancies

- Structured vacancy fields: position, specializations, grades, division, salary, KPIs, requirements, responsibilities, conditions
- Selects cascade from the company library — position constrains specializations, specializations constrain grades — and the competence profile prefills from the matching grade matrix
- Every vacancy has a hiring manager, defaulting to the creator
- Lifecycle: edit, archive with a 90-day retention window, restore, or permanently delete a draft without candidates
- Parallel edits are protected: a stale save is rejected instead of silently overwriting someone else's change
- Per-vacancy attachments (documents, spreadsheets, presentations, images; 25 MB each, up to 10) feed context into AI generation

### Competency Profiles

- Generate a vacancy's competence profile with AI from the description, tasks, and attachments; a clarification note passes straight into the prompt
- The review screen supports keep/drop per competence, inline edits to names, indicators, and interview questions, and shows previously saved rows as locked
- Nothing writes to the profile until the recruiter saves the reviewed selection

### Candidates

- Add candidates by hand (name plus email or phone) or by bulk resume upload: up to 50 PDF and DOCX files at once, parsed by an LLM into structured data
- Duplicate emails are caught before import with a link-or-create choice per file
- The candidate page carries contact details, the parsed resume with per-section inline editing, files, and every vacancy application with its scores
- Funnel stages ship with a 9-stage default (new through hired, rejected, withdrew) and can be customized per workspace or per vacancy; stage changes into a terminal state ask for confirmation
- The vacancy table shows last position, experience, current stage, manager score, AI score, and AI verdict, and flags rows where the manager and AI diverge

### Interview Questions

- Question sets per candidate and vacancy, generated from the resume and the competence profile, with manual editing throughout
- Sets evolve across rounds: covered topics are marked (by hand or from the transcript) so the next round skips answered ground, and blind spots from prior analyses become probes
- PDF export in compact, full, and card layouts

### Manager Assessments

- Workspace-defined assessment scales (2–10 weighted levels); each vacancy freezes its scale on the first score
- Assessment rounds per candidate (pre-interview, numbered interviews, final) with a separate sheet per evaluator
- Indicator-level and competence-level scoring with autosave and a completion marker; evaluator disagreement above the scale threshold is highlighted
- External evaluators join through secure token links with expiry, no account needed. The public evaluation page shows the resume and question list next to the scoring sheet and keeps the platform itself closed off
- Recruiters track invite status (pending, opened, in progress, submitted, expired) with resend, extend, and revoke actions

### Interviews & AI Analysis

- Schedule interviews with type, timezone, duration, and interviewers directly from the candidate page
- Upload audio (mp3, wav, m4a) and video (mp4, webm, mov, avi) up to 500 MB, or text transcripts up to 10 MB, several files at once
- Uploads are chunked and resumable: pause, resume, retry, and continue after a browser reload
- Consent capture with magic-link signing runs before any upload
- Transcription through pluggable providers, including Whisper and Deepgram with speaker separation; an in-app player covers audio and video with speed control and keyboard shortcuts
- The analysis pipeline reports data completeness, competence scores, blind spots, process findings, red flags, and a verdict
- Two modes: resume-only (a fast pre-screen that never returns "recommended") and full (interview-anchored, with citations from the transcript). A prior resume-only run upgrades to full for the price difference
- Progress renders stage by stage with a cancel option; resume citations click through to the matching resume section
- When a candidate uploads a newer CV after a run, the platform flags the analysis as outdated and offers a re-run
- Bulk analyze queues a resume-only run for every candidate that has a parsed resume but no verdict yet
- Hiring managers see reframed process findings rather than raw red flags; access is role-aware throughout

### Reports

- Consolidated XLSX reports generated in the background: a summary sheet, a competence matrix of candidates against the profile, a detail sheet per candidate, and a data-completeness sheet
- An audience switch keeps recruiter-only findings out of the hiring manager's copy
- Saved report templates with one default per workspace, a report list with filters, and download links valid for 24 hours
- Workspace logo branding on the cover sheet

### Settings

- A single settings hub for scales, AI and speech-to-text providers, branding, retention, roles, and templates
- Bring your own keys for LLM and transcription providers (Anthropic, OpenAI, Gemini, Azure, Yandex, GigaChat, Whisper, Deepgram, AssemblyAI, faster-whisper); keys are encrypted at rest and never returned in full
- Retention windows per data type with a warning on legally short values

### Compliance

- An append-only audit log of every mutating action with change diffs, IP, and user agent, browsable with filters
- GDPR export gathers everything about a person into one JSON document with a 7-day download link
- GDPR erasure replaces personal data with redaction markers across resumes, transcripts, and consents while preserving the audit trail

---

## Monitoring & Observability

For teams running HRPulsar on their own infrastructure.

- A Prometheus metrics endpoint with request counts, latency histograms, and in-progress gauges, with path normalization to keep label cardinality under control
- Structured JSON logs with a request ID on every entry and an `X-Request-ID` response header for correlation
- Optional Sentry error tracking for backend and frontend, with personal data stripped from events before they leave the server
- Health endpoints for load balancers and Kubernetes: a full check covering the database, Redis, and S3, plus a lightweight readiness probe
