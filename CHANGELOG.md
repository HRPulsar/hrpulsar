# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]

## [1.20.0] - 2026-08-20

### Added
- Dashboard rebuilt as a management tool: a development-loop hero (assessed → gaps → developing → closed) and an action queue that turns detected problems (employees below the grade bar without a plan, overdue plans, stalled reviews, low assessment coverage) into deep-linked next steps
- On-demand AI summary of the development loop on the dashboard, cached per data state so repeat requests over unchanged data are free
- Demo seed now tells a problem story: a sales team scoring below the bar with no development plans, an overdue plan and a stalled review, so the dashboard opens on real actions in a fresh demo
- Personal employee dashboard: my loop stages, a personal action queue (pending surveys, returned/overdue plans, gaps without a plan), strengths with rare-skill highlights, growth direction to the next grade, and an assessment-history sparkline
- Coach-style personal AI summary on the employee dashboard, cached per data state
- YandexGPT (Yandex Foundation Models) as a first-class LLM provider: platform-wide key + folder id, effort-tier presets, model catalog discovery, and BYOK without a custom endpoint URL (HRP-599)

### Changed
- Dashboard "Open dev plans" KPI subtitle now shows the share of employees covered by an open plan instead of the unrelated org-wide active-employee percentage
- Dashboard "Closed" stage now counts gaps confirmed closed by a re-assessment within 90 days (with on-time plan completions as a sub-line) instead of the raw completed-plan count
- Dashboard decluttered per the management-loop design: employee/division counters, department bars, the calendar stub and the "Add employee" button removed (those live in Employees and Analytics)

### Fixed
- SMTP send-failure logs now name the relay host and port, making delivery incidents self-describing
- Header and profile avatar initials rendered the string "UNDEFINED" for accounts without a last name (e.g. ex-demo signups)
- Dev-loop and personal dashboards honor an explicitly configured passing bar of 0 instead of silently treating it as 75
- The personal dashboard no longer lists below-the-bar scores as strengths (nor feeds them to the AI coach as such)
- Personal-dashboard AI summary cache no longer misses on unchanged data (payload ordering is now deterministic), and both AI-summary endpoints accept the client's data fingerprint to skip re-aggregation on cache hits
- Daily AI-summary budget gains a per-user slice so one enthusiastic clicker cannot drain the whole workspace's allowance
- Dev-loop aggregation no longer expands the tenant's whole assessment history into a single IN clause (large tenants would hit the bind-parameter limit)
- The daily-cap message for AI summaries now reaches the user instead of a generic "try again" invitation
- Dashboard shows an error state with a retry button when the backend is unreachable instead of an empty-but-healthy page
- YandexGPT rows pointing at a gateway URL keep their model name verbatim (the folder-URI rewrite applied only to the official endpoint), and a tenant Yandex key that the dispatcher would silently ignore is now refused at save time with a clear message (HRP-599)
- Grade-ladder cells created without an explicit order are backfilled from the grade's own order, so the personal dashboard's "next grade" card renders on existing installations (HRP-612)

## [1.19.2] - 2026-08-18

## [1.19.1] - 2026-08-18

### Fixed
- Interview analysis label helpers no longer crash the page on analysis payloads without typed finding/flag items

## [1.19.0] - 2026-08-16

### Added
- Feedback widget in the app header: rate the product with a thumb up or down and leave a suggestion, in the interface language (HRP-586)

### Changed
- Evaluator invitation emails are now capped per recipient address per hour on top of the per-invitation resend cooldown; both windows are configurable, and refusals carry a `Retry-After` header readable by cross-origin clients (HRP-576)

### Fixed
- The interview page shows readable labels for the analysis verdict, process findings and red flags instead of raw codes, and switching vacancies on a candidate card no longer carries the previous sheet's autosave indicator and pending saves over (HRP-579)
- A submitted evaluator invitation that is later revoked keeps its evaluation readable from the invite menu, marked as no longer counted toward the round score (HRP-577)
- Onboarding: the invite step now asks for a name next to each address, reports which invitations failed, and keeps a way forward when some of them do (HRP-526)
- Status page: the whole 90-day uptime bar now reads under one formula — days rolled up before degraded minutes counted as half-up are restated on read instead of being shown side by side with the newer numbers (HRP-549)
- Recruitment lookups are indexed as the models always declared: the 14 indexes that carry the hot read paths are created, the rest are dropped from the models (HRP-581)
- Salary currency on the grade/specialization chain no longer carries a database-level RUB default: rows written outside the application now fail loudly instead of landing in the wrong currency (HRP-570)

## [1.18.2] - 2026-08-14

## [1.18.1] - 2026-08-14

## [1.18.0] - 2026-08-13

### Added
- Company → Specializations: a Status column (Active/Inactive) as the last column before the actions menu, matching the Dictionaries reference table (HRP-294)
- Language switcher on the signed-out pages — sign-in, registration, invitation acceptance and the external evaluator forms; invitation links now open in the language the email was written in (HRP-516)
- AI settings: a provider whose stored key can no longer be decrypted is flagged on the page with a prompt to re-issue it, instead of silently disappearing from the list (HRP-543)

### Changed
- Create & Edit Vacancy: the hiring manager can now be any active member of the company, not only admin-tier users; people whose employee record says they have left are not offered (HRP-441)
- Resending an external evaluator invitation is now throttled per invitation, so repeated clicks cannot flood the evaluator's inbox (HRP-545)

### Security
- Custom AI endpoint URLs (`base_url`) set by tenant admins on cloud deployments are now validated against internal address ranges on save and re-validated with connection IP pinning on every call; redirects are disabled and an operator allowlist (`AI_BASE_URL_ALLOWED_HOSTS`) covers vetted gateways. Self-hosted installs are unaffected — private endpoints (Ollama/vLLM) keep working (HRP-505)

### Fixed
- Deadline reminder emails name the entity kind in the reader's language instead of a raw ASSESSMENT/PDP/EXAM code (HRP-584)
- PDP completion and cancellation emails use dedicated nameless wording when the plan owner has no usable display name, and employee names and entity titles are HTML-escaped across notification email bodies (PDP, reminders, assessments, exams, certificates) (HRP-584)
- Database-driven notification emails are now rendered in the branded layout (logo, accent color, localized footer) instead of going out as bare HTML fragments; SMTP Message-IDs derive their domain from `EMAIL_FROM` instead of a hardcoded stock domain, and a branded install that leaves `EMAIL_FROM`/`FRONTEND_URL` at defaults gets a startup warning (HRP-568)
- Round averages, per-competence breakdowns and the candidate's manager score now exclude sheets belonging to revoked or declined external invitations (defence in depth; such invitations are currently only producible through the API directly) (HRP-383)
- External evaluators who arrive at a pre-interview round someone else already holds now get an explanation written for them instead of an internal rule about evaluator slots (HRP-383)
- AI Insights: the verdict chip, the run history and the next-step recommendation are translated instead of showing raw codes, and the invitation toast counts invitations in the reader's language (HRP-550)
- Manager assessments: switching to a vacancy without assessment rounds no longer leaves the previous vacancy's scoring sheet on screen (HRP-550)
- Augment indicators (AI) now follows the workspace content language, keeps the competence's own type and the skill levels its existing indicators sit on, and no longer loses suggested indicators whose skill level came back spelled differently (HRP-541)
- Public API: `GET /v1/dictionaries/{item_type}` now rejects an unknown type with 400 and the list of accepted types, instead of answering 200 with an empty page (HRP-382)
- Database-driven notification emails now render the installation's `BRAND_NAME` (the seeded invite template carried a hardcoded product name on branded installs) (HRP-515)
- Salary and compensation currency now defaults to the installation currency (`BILLING_CURRENCY`, USD out of the box) instead of a hardcoded RUB on grades and USD on compensations; the employee currency picker leads with it (HRP-439)
- Division page: the Specializations block no longer shows "(0)" on nested divisions — plates now cover the specializations the division's people actually hold, count the whole division subtree, and an "Include sub-divisions" switch narrows plates, filters and the employee list back to the division itself (HRP-58)
- A translation missing from a locale now renders the English text instead of the raw key name (HRP-511)
- Verification, password-reset and signup emails now follow the language chosen on the form itself, not just the browser's language setting; invitation and external-review links open the page in the language the email was written in (HRP-513, HRP-516)
- Error messages from the API now follow the interface language on deployments where the API runs on a separate origin (self-hosted, local dev) and for non-browser clients — the frontend states its locale on every call and access tokens carry the account locale (HRP-513)
- Background task failures and timeouts are now shown in the interface language instead of English, assessment status names keep their translated casing in bulk-status notices, and salary benchmarks use the site currency instead of a hardcoded dollar sign (HRP-512)
- Interview analysis served from cache wrote no assessments at all — cached competence ids were validated against the competence dictionary although they are derived from the vacancy profile, so the compact matrix stayed empty on demo tenants (HRP-275)
- Interview page: Analyze shows what it costs, warns when the balance cannot cover it, reports "analysis ready" when the result comes from cache, and a demo workspace out of quota now gets the credit banner instead of a silent success toast (HRP-275)
- Demo seed: cloned demo tenants open on a finished AI evaluation with citations — the seeded interviews now carry the assessment rows the matrix reads (HRP-250)
- A model whose provider cannot be determined from its name is now resolved through the model catalog, and refused outright when that fails, instead of being sent to whichever provider the installation defaults to (HRP-502)
- Vacancy → Questions: the tab now shows each candidate's latest question set instead of nothing, names candidates in the filter instead of printing their ids, and offers every vacancy competence in a multi-select filter (HRP-504)
- Create & Edit Vacancy: the Salary range fields are back on both forms, prefilled from the salary band of the chosen specialization and grade, and an inverted range is rejected before saving on every vacancy surface (HRP-440)
- Vacancy analytics: Hired, Rejected and In progress now count candidates by the funnel's terminal stages instead of a status field no flow updates, and the two terminal tiles carry the funnel's own stage names; closing a vacancy as hired moves that candidate to the hired stage (HRP-425)
- Candidate page: the right-hand blocks now follow the sourcing timeline — Parsed resume, Vacancy applications, AI Insights, Interview questions, Interviews, Manager assessments (HRP-424)
- Manager assessments: the autosave indicator no longer sits above the scoring sheet, so saving a score stops nudging the layout (HRP-370)
- Vacancy candidates table: the DIVERGENCE column now counts manager scores from assessment rounds and AI scores from resume-only analyses, compares them on the same scale, explains itself in a hover tooltip and opens Canvas filtered to the divergent cells (HRP-507)

## [1.17.1] - 2026-08-10

## [1.17.0] - 2026-08-09

### Added
- Interview questions: Add is now a split button — "Add custom question" opens a form with question text, goal, priority and an optional resume anchor, while "Add from competency indicator" opens a searchable competence tree and turns each picked competence into a question, mapping criticality to priority and carrying over its indicators, follow-up questions and rationale (HRP-485)
- Mass assessments: an Analytics block on the campaign page with growth zones, top competences, employees at risk and top performers, a filterable detailed-results view (average match gauge, employee table or competence/grade matrix) and a summary with a per-grade chart and the competence tree; built from completed child assessments only (HRP-528)
- Manager assessments: "+ Add evaluator" puts several colleagues on the same round, each with their own sheet and an email invitation; a colleague's sheet stays hidden until you submit yours. Pre-interview rounds stay single-evaluator (HRP-373)
- Manager assessments: a round menu with Complete, Reopen, Archive and Restore; an archived round keeps its scores but is excluded from the candidate's average (HRP-376)
- Manager assessments: each external evaluator invitation now has its own menu — Resend, Revoke and View submission (HRP-377)

### Fixed
- Status page: a single slow probe no longer paints a whole day amber (degraded is recorded only after 2 consecutive cycles), a failed `/health` fetch no longer marks four sub-components as outage (single shared fetch, unknown state shows amber), and degraded minutes count as half-up in daily uptime
- AI Insights: an interview that covered none of the profile's competences no longer wipes the candidate's AI score — the score carries forward from the previous analysis instead of the candidates table falling back to a dash (HRP-493)
- AI Insights: analysis notifications name the candidate instead of "None", say which mode ran, and link to the AI Insights block for that vacancy; resume-only and full analyses report separately, and a failed run is reported too (HRP-494)
- AI Insights: the block flags an analysis whose inputs have moved — a re-parsed resume, edited vacancy competences, a run older than 30 days, or a transcript the analysis never saw — and offers the re-run that fixes it; an edited resume also closes the discounted upgrade (HRP-489, HRP-492)
- AI Insights: the refresh icon, the duplicate data-completeness chip and the footer that repeated the Analyze action are gone (HRP-489, HRP-492)
- Vacancy candidates table: AI DATA now follows what the model can see rather than the last analysis that ran, AI VERDICT distinguishes "analyzing" from "nothing to analyse yet", and it no longer repeats the AI score or the divergence marker shown in neighbouring columns (HRP-493)
- Manager assessments: competence cards in the evaluation sheet now carry an expand chevron, on the internal sheet and the external evaluator page (HRP-368)
- Manager assessments: round tabs are ordered Pre-interview, Interview 1..N, Final instead of by creation time (HRP-372)
- Manager assessments: a Word resume on the external evaluator page is now shown as a preview instead of downloading itself on every page load; the file is only saved when the evaluator clicks Download (HRP-371)
- Manager assessments: "Mark as complete" now actually closes the round — sheets turn read-only and the external links are revoked, so an evaluator following one sees "This invitation was revoked" (HRP-376)
- Schedule interview: the dialog now asks for vacancy, assessment round, title, date and time, duration, interviewers and notes, and the new card appears at the top of the Interviews list (HRP-386)
- Interview page: the title is the heading and is editable, the subtitle names the vacancy and round, and Details and Notes blocks render the scheduled parameters with inline editing (HRP-387)
- Interviews block: one border, counter in the header, the title links to the interview, and each row carries a status chip, its round with the date it was added, and a kebab with Edit, Archive and Restore; archived interviews hide behind a "Show archived" filter, stay restorable for 90 days and are purged from storage afterwards (HRP-418)
- "Interview scheduled" email now goes to the assigned interviewers only, skips interviews scheduled in the past, and names the candidate and vacancy with the date in yyyy-mm-dd hh:mm (HRP-419)
- Send consent link without an active consent template now opens a modal explaining where to create one, instead of a snackbar that disappears before it can be read (HRP-472)
- **Breaking (self-hosted):** the stock self-hosted stack no longer crash-loops on the internal-S3 startup check — browser-facing file links fall back to `FRONTEND_URL` (bundled compose: `http://localhost` when even that is unset), so `S3_PUBLIC_ENDPOINT` is only needed when storage is served from another origin (HRP-496)
- AI model catalog is now the single source of truth end to end: disabling a model also stops the tenants that follow an effort preset, the model picker keeps showing the curated model instead of a newer dated snapshot, the older Claude ids keep their full output budget instead of truncating long generations, and OpenAI o-series models are called with the parameters they accept instead of failing every request (HRP-500)
- AI providers: a stored key that can no longer be decrypted is no longer reported as a working tenant key — the provider list shows the credential generation actually uses (HRP-514)
- AI providers (BYOK): a provider/model pair that cannot work together (e.g. OpenAI with a Claude model) is rejected on save, switching the provider in the form updates the suggested model, and existing mismatched rows are deactivated so they cannot become dispatch targets and fail every AI action (HRP-498)
- Interview transcription with a tenant's own speech-to-text key works again: the stored key was passed to the provider still encrypted, so every BYOK transcription failed authentication (HRP-506)
- AI provider clients are cached in a bounded LRU that closes the connection pool it evicts, so rotating tenant keys or endpoints no longer leaks file descriptors for the process lifetime (HRP-501)
- "Interview questions ready" and "Question generation failed" notifications now carry a link to the candidate card, anchored on the Interview questions block, with the generated set already open; in-app notifications that carry a link are clickable (HRP-442, HRP-460)
- Interview questions, Export to PDF: Format and Sort no longer resize with the chosen value, the format names spell out what they produce ("Compact (one page)", "Cards (for notes, for printing)"), and the content checkboxes are ordered Resume anchor / Expected indicators / Follow-ups / Why this question. The Export PDF button moved into the question-set card, next to Add and Re-generate, since it exports only the current set (HRP-484)
- Interview questions: "New set" now opens a dialog that asks which round the set is for (offering to open the next Interview N) and which completed interview it builds on, instead of silently generating another pre-interview set. The set is bound to its round, one set per round, and the generation reads the prior transcripts, AI analyses and blind spots so it deepens weak coverage instead of repeating answered questions (HRP-444)
- Interview questions: the pencil icon now opens every attribute for inline editing — text, goal, priority, linked competence, resume anchor, expected indicators, follow-ups and rationale — instead of only the question text (HRP-487)
- Interview questions: a question keeps and displays its link to the vacancy-profile competence, whether it was AI-generated or added by hand (HRP-503)
- Interview questions PDF, Compact format: table cells wrap on word boundaries instead of overflowing the column, and the font shrinks so the whole set still fits one portrait page (HRP-462)
- Interview questions PDF, Cards format: every question card now reserves a fixed-height ruled Notes area regardless of which content checkboxes are ticked (HRP-483)

### Changed
- AI Insights: the empty state follows the Interview questions block — a placeholder line with the Analyze split button directly beneath it, disabled until a resume is parsed, with both modes and their prices in the menu (HRP-488)
- Vacancy reports: the Generate dialog now asks for the candidate set (all active / finalists / custom), the sheets to include and the audience, and prices the run with the standard credit badge (HRP-521)
- Vacancy reports: the workspace logo is placed in the top-left corner of every sheet at a fixed 120x40 px instead of being stretched into the header area (HRP-522)
- Vacancy reports: the Summary sheet now carries the position/division/report-date line, an auto-generated data-completeness disclaimer, an AI-data column driven by each candidate's analysis readiness, a computed recommendation, and footnotes for partial AI coverage or manager-AI divergence (HRP-523)
- Vacancy reports: the Matrix sheet now merges competence groups with a separator, abbreviates the target level (Crit/Imp/Des), marks diverging cells with a warning glyph, flags AI columns backed by a transcript, and renders per-candidate totals as "score/max (percent)" coloured by threshold (HRP-524)
- Vacancy reports: Detail sheets are named after the candidate instead of "Detail Unknown" for resume-sourced candidates, and carry the full spec structure — resume paragraph, per-competence scores with their group, blind spots, process findings, red flags and the final verdict (HRP-525)
- Vacancy assessments: Open fullscreen now leads to a dedicated sidebar-less canvas page with view/round/scale controls, divergence and no-score filters, a cell-details footer, per-candidate totals, and XLSX/CSV export (HRP-510)
- Interview questions: goal and priority share one vocabulary across AI generation, manual add and display, and the interface shows readable names ("Clarify experience") instead of raw codes (HRP-486)
- Assessment Results and Detailed results now show the match percent as a colour-coded chip (green from 75%, yellow from 50%, red below 50%, muted dash when there is no result) instead of plain text (HRP-527)

### Removed
- **Breaking (self-hosted):** Report templates (settings page, CRUD endpoints and table) — the sheet set is chosen in the Generate dialog instead; saved template rows are dropped by the migration and are not restored on downgrade (HRP-521)

## [1.16.1] - 2026-07-31

### Added
- Manager assessments: the interview round header now shows the round's Average score (with its scale weight), and every competence shows its cross-evaluator average, highlighted with a warning when evaluators differ by the scale's divergence threshold or more (HRP-374)
- Uploading a file whose kind contradicts the interview's scheduled recording type now asks for confirmation before switching the type; interviews left as "I'll decide later" adopt the uploaded kind silently (HRP-405)

### Changed
- Manager assessments: scoring a competence's indicators now always re-derives its overall, and editing the overall by hand clears the indicator answers, so the two can no longer contradict each other; the "from indicators" chip is gone (HRP-378)
- Manager assessments: external evaluators' scores count toward round averages once they submit, instead of while their sheet is still a draft (HRP-374)

### Fixed
- German locale native-style proofread: 74 wording, grammar, and terminology fixes across UI catalogs, backend errors/emails, and notification templates (HRP-518)
- Manager assessments: picking a score no longer scrolls the candidate page away to a blank area (HRP-370)
- Interview transcripts (pdf, txt) can be uploaded again: the upload contract rejected the `text_transcript` kind, so every transcript failed validation and its interview stayed in `scheduled` (HRP-385)
- An uploaded pdf/txt transcript now has its text extracted into the interview, so it can be analysed like a pasted one instead of attaching as an unusable file (HRP-385)
- A failed interview upload that never reached storage now explains itself instead of surfacing the browser's raw "Failed to fetch" (HRP-385)
- Finalising an interview upload is pinned to the file type it was started for, so the transcript size ceiling cannot be sidestepped (HRP-385)
- Consent-link email addresses resume-sourced candidates by name instead of "(unnamed)"; the public consent page and the questions PDF resolve the candidate name the same way (HRP-384)
- Accept-invitation page pre-fills First and Last name by splitting the name from the invitation, and shows the invited email read-only instead of letting the browser autofill it into Last name (HRP-435)
- Admin sidebar section (Dictionaries, Invitations) is now admin-only: managers no longer see the group, and managers and employees opening a direct link get an error toast and a redirect to the dashboard instead of an empty page; the invitation registry API is admin-only to match (HRP-436)
- Division detail: the Employees block regained its Specialization filter, so specialization, position and grade can be combined (HRP-58)
- The Send invitation dialog opened from a division can now be closed; it no longer reopens itself on close or reload (HRP-174)
- The sidebar now shows the strongest role a user holds, and a manager downgraded to Employee keeps the Employee role instead of ending up with none (HRP-196)
- Assessments locked by a calibration now show Take this assessment and Evaluate greyed out with an explanatory tooltip instead of hiding them (HRP-329)
- Completed and cancelled exams without a description now show "No description" instead of an empty line (HRP-231)

## [1.16.0] - 2026-07-31

### Added
- Interface-locale foundation: deployment-level available/default locale settings, per-tenant default locale with a new onboarding "Language" step (interface + AI content language), and a per-user language preference in profile settings (HRP-474)
- Cookie-based interface-locale infrastructure (next-intl): per-request locale resolution with dynamic html lang, sticky NEXT_LOCALE cookie, and a header language switcher on multi-locale installs (HRP-475)
- All product UI copy now renders through i18n message catalogs (~4000 keys across 20 namespaces) with locale-aware number formatting; English output is unchanged (HRP-476)
- Backend user-facing errors now resolve through a locale-aware error catalog (~660 raise sites, 520 codes) with an additive machine-readable `code` field; pydantic validation messages localize too, and English output is unchanged (HRP-477)
- Outbound email renders in the recipient's locale: code templates read from an `email.*` catalog and DB notification templates gain per-locale rows with English fallback; English output is unchanged (HRP-478)
- Shipped reference data (grades, specializations, competence types, skill levels, assessment statuses/types, the default answer scale) now localizes via stable keys with verbatim fallback for tenant-created entries; English output is unchanged (HRP-479)
- AI content language can now be set to German: selectable in AI settings and onboarding; competence, indicator, position, learning-material, and development-plan generators emit content in the tenant's chosen language (HRP-480)
- German (de) interface locale: complete translations for the product UI including shipped reference data, backend errors, and outbound email — code templates and database notification templates alike (HRP-481)
- White-label theming: curated UI theme presets selectable per installation via `NEXT_PUBLIC_BRAND_THEME`, sidebar logo height override, and a customizable login/register background color or image (HRP-463)
- LLM provider registry with key-based gating: `/settings/ai` offers only providers with working credentials; local OpenAI-compatible servers (Ollama/vLLM/LM Studio) are supported via a custom endpoint, and workspace BYOK keys now apply to all AI generation (HRP-465)
- Dynamic AI model catalog with a daily discovery sweep: new provider model versions appear without a redeploy (HRP-466)

### Changed
- Anthropic tier models refreshed (balanced → Claude Sonnet 5, thorough → Claude Opus 4.8, optional Claude Fable 5), with sampling params gated per model family (HRP-464)

### Fixed
- Celery worker container no longer accumulates zombie processes from healthcheck probes until the pids limit is exhausted and background tasks fail — backend containers now run with an init process
- AI generation no longer fails on thinking-capable Anthropic models (balanced/thorough tiers): the adapter reads the first text content block instead of the first block (HRP-509)
- English copy: verb agreement in the candidates bulk-analysis banner ("1 candidate has") and the answer-scale delete confirmation no longer repeats "archived" (HRP-481)
- Backend now refuses to start when `S3_ENDPOINT` is an internal-only hostname and `S3_PUBLIC_ENDPOINT` is unset, instead of serving presigned file links browsers cannot reach (HRP-445)

## [1.15.5] - 2026-07-24

### Fixed
- Bulk AI competence generation no longer fails on large competence trees with a misleading "AI service error" (HRP-432)

## [1.15.4] - 2026-07-23

### Fixed
- Demo start and sign-up browser verification no longer dead-ends when Cloudflare escalates to an interactive challenge — the challenge is rendered in place instead of timing out invisibly

## [1.15.3] - 2026-07-22

### Changed
- Marketing site now builds from its own `marketing/content/` directory (release metadata, public changelog, docs) instead of reading monorepo-root files, in preparation for its extraction into a standalone repository (HRP-428)

## [1.15.2] - 2026-07-21

### Fixed
- Re-running AI candidate analysis (resume-only and full) no longer fails with a unique-constraint violation when a completed run already exists — prior runs are now archived before the new one completes (HRP-423)
- Recruitment AI generations (interview questions, vacancy profiles, reports, transcription) no longer default to Russian — all language defaults are English now (HRP-421)

### Changed
- Marketing site SEO: canonical links on all pages, Organization/SoftwareApplication JSON-LD on the landing page, deduplicated page titles, sitemap now covers methodology, personal-brand, security and all docs pages

## [1.15.1] - 2026-07-21

### Fixed
- Self-hosted compose now passes the white-label branding env vars to the frontend container, so UI branding from `.env` actually applies (HRP-393)
- Uploaded file links (company logo, interview media) now load on self-hosted installs: new `S3_PUBLIC_ENDPOINT` setting signs presigned URLs against the public host and the bundled Caddyfile proxies them to MinIO; logo upload UI no longer advertises unsupported SVG (HRP-412)
- Self-hosted Celery worker now receives the bundled MinIO connection env, fixing resume parsing and other storage-reading background tasks (HRP-412)

### Changed
- Self-Hosted guide: upgrading section now covers backup-first, downtime expectations and keeping local changes in a compose override file

## [1.15.0] - 2026-07-20

### Added
- White-label branding for self-hosted installs: logo, installation name, accent color and favicon configurable via env for both the web UI and outgoing emails (HRP-393)
- Self-serve registration for self-hosted installs, with account verification fallbacks when no email provider is configured
- Self-hosted root URL now redirects to the sign-in page
- CONTRIBUTING.md and SECURITY.md with development setup, contribution guidelines, and the vulnerability disclosure process

### Changed
- Product frontend no longer bundles the marketing site; the root URL always redirects to sign-in or the dashboard (HRP-389)
- Docker builds and CI install backend dependencies from pip-compile locks (`requirements*.txt`) for reproducible builds; `make lock` regenerates the pins (HRP-398)
- LICENSE now ships the full AGPLv3 text; the copyright statement and the Enterprise Edition section 7 linking permission moved to a new NOTICE file
- README facts refreshed: Python 3.14+, 500+ REST API endpoints, correct Swagger URLs for development and self-hosted setups
- CI: community e2e runs in onprem deployment mode; saas mode is set only when the EE package is present
- Demo sandbox is now enterprise-only: self-hosted (onprem) deployments serve 404 on `/api/demo/*`, hide demo endpoints from the API docs, skip demo purge jobs and refuse to boot with `DEMO_ENABLED=true`; `make demo` boots the full SaaS demo contour with the marketing site (HRP-391)

### Fixed
- Docker builds show the real release version in `/health` and the sidebar without manual build args (HRP-396)
- Community builds no longer request `/api/billing/*` (cost confirmation, AI settings, demo banner), removing 404 console noise on self-hosted installs (HRP-397)
- Create/edit modals for employees, positions and divisions now show backend errors inside the modal — validation errors under the fields, conflicts as a visible banner — instead of failing silently (HRP-399)
- Email links (verification, reset, invitations) now respect `FRONTEND_URL` on self-hosted installs
- Self-hosted Docker stack now works out of the box: fixed frontend build context, Celery worker/beat container commands, and the frontend healthcheck; ships a community Caddyfile (`deploy/selfhosted/`) and auto-creates the MinIO bucket on first boot
- Database migrations enable the pgvector extension automatically on fresh installs
- Self-Hosted guide and .env.example corrected: real service list, health check via the proxy, email provider required for sign-up verification links, `backup_db.sh` now ships in the public repo

## [1.14.3] - 2026-07-16

### Added
- Employee references in Assessments (list, detail, participants), Development plans and Exam results show the shared summary line: current position plus a status chip for non-active employees (HRP-333)
- Draft Talent Market cards can be cancelled straight from the Details block (Cancel button next to Publish) (HRP-334)

### Changed
- All date fields in Assessments, Development, Exams and Talent Market use the shared English-locale DatePicker instead of the browser-native date input (HRP-335)

### Fixed
- Start scoring this round on the Pre-interview tab creates the scoring sheet for the first evaluator instead of failing; only a second, different evaluator is rejected (HRP-369)
- Development plan grade pickers (Create plan and Draft PDP edit) are disabled until a specialization is chosen and offer only grades configured for that specialization, minus dictionary-deactivated ones; the saved grade stays selectable (HRP-293)
- Public API dictionary endpoints (/v1/specializations, /v1/grades, /v1/dictionaries) report the tenant-effective is_active flag, matching the Dictionaries page after a System item is deactivated for the tenant (HRP-380)
- Renaming a Position propagates the new title to every assigned employee, so lists, employee cards and summary lines stop showing the old name (HRP-332)
- Specialization and grade pickers in Assessments criteria, Development plans and Talent Market requirements list only active dictionary items; an already-saved deactivated item keeps its title and stays selectable (HRP-292)
- Completed and Cancelled Talent Market cards are fully frozen: candidate add/change/appoint, requirement edits and card details are rejected on the backend and hidden in the UI (HRP-291)
- Tenant deactivation of System dictionary items now applies everywhere: AI pickers and prompts, assessment criteria picker and the Specializations page respect the per-tenant override (HRP-337)
- Celery worker registers all model modules (including feature-split `*_models.py`) at init — interview analysis tasks no longer crash with NoReferencedTableError on manager assessment foreign keys; Alembic env now shares the same model import
- Restarting the demo from the marketing site resumes the visitor's live sandbox instead of provisioning a duplicate tenant with a second credit grant (cross-domain resume via a marketing-origin token copy)
- Exam question images render at natural size in the Take this exam sheet (no more upscale blur) and appear in the submitted-results sheet (HRP-328)
- Cancelling or completing an exam cascades to participant surveys: unfinished surveys are voided, submitted results stay visible and reviewable; concurrent cancel and submission can no longer overwrite each other (HRP-236)
- Declined external evaluator invitations are terminal: the link stays invalid after refresh and the invite cannot be extended (HRP-359)
- Candidate links from the vacancy assessment matrix, comparison table and questions tab carry the vacancy context; AI Insights and Manager assessments default to the vacancy the user navigated from (HRP-361, HRP-366)
- Active funnel stages always render blue across the Candidates block, kanban and stage popover; only terminal stages keep their own color (HRP-357)
- Vacancy division_id is validated against the tenant on create and update (HRP-338)
- Exam Pass Mark thresholds (percent and/or points) drive pass/fail instead of a hardcoded 60%; editing the mark re-grades finished participants (HRP-364)
- Dictionary delete gate walks every foreign key on dictionary items, blocking deletes referenced by Talent Market cards, vacancies and recommended grades (HRP-365)
- Vacancy competence profile inline-edit save is protected by an optimistic lock — a stale draft no longer overwrites a newer profile (HRP-339)
- Saved assessment calibration keeps the questionnaire closed for good, and previously calibrated Totals keep their chip when calibration is reopened (HRP-329, HRP-330)

## [1.14.2] - 2026-07-13

### Changed
- Exam pass mark can be edited in place (new pencil icon and Edit pass mark dialog) and managed on any active exam, not only drafts; terminal exams stay frozen (HRP-226)
- Exam Send button stays active when the deadline is past — clicking surfaces the "Deadline in the past" error, matching Assessments and Development plans (HRP-237)
- Create exam modal no longer highlights the empty Title in red before any input; the asterisk and disabled Create button carry the requirement (HRP-230)

### Fixed
- Deleting a custom Competence Type that is used by competences is blocked with the generic "has connections" error instead of silently untyping them (HRP-286)
- Talent Market "not considered" email no longer contains the Open card button — the removed employee has no access to the card (HRP-245)
- Talent Market candidate ranking treats experience as part of "all else equal": qualifying or longer experience ranks above a reaction, and the reaction only breaks exact ties (HRP-213)
- Vacancy Requirements, Responsibilities and Conditions are returned by the API again, so they no longer show empty after Save Draft / Save (HRP-344)
- DOCX resumes with table-based layouts parse correctly instead of failing with "Nothing to import" (HRP-345)
- Resume parsing extracts experience start date, end date and description onto the candidate card (HRP-346)
- Candidate page resume download serves the original PDF/DOCX file instead of a JSON envelope (HRP-347)
- Vacancy Candidates block renders each funnel stage in its configured color; Manage funnel stages drawer widened to remove the horizontal scrollbar (HRP-357)

## [1.14.1] - 2026-07-12

### Fixed
- Turnstile-gated buttons (landing demo CTA, /demo entry, signup request, demo save-access) no longer hang on "Verifying..." forever when the Cloudflare widget is blocked or errors — a clear message with a retry is shown after a 15s timeout

## [1.14.0] - 2026-07-12

### Added
- Public evaluation page for invited external evaluators: resume and interview questions next to the full competence sheet, autosave, critical-competence submit warning, re-edit after submit when allowed, strict CSP / noindex isolation (HRP-359)
- Recruitment section tabs (Vacancies / Candidates / Reports / Audit / Settings) on every top-level recruitment page; Settings visible to admins only (HRP-353)
- Vacancy hiring manager: admin-tier picker on create / edit / Overview inline edit, defaults to the creator (HRP-360)

### Changed
- AI vacancy profile generation no longer saves results directly: a Review for save banner opens the review matrix and the profile is written only after the recruiter applies it; one generation session per vacancy at a time, action buttons lock while a session is active (HRP-235)
- External evaluator invitations are refused until the vacancy profile has competences; the Invite button explains why it is disabled (HRP-352)
- Vacancy list: Position and Division columns, Owner shows the creator's full name, and the All statuses filter includes archived vacancies (HRP-363)

### Fixed
- Vacancy competences inline edit now covers criticality (select on each card) and adding new competences, indicators, interview questions, groups and subgroups (HRP-318)
- External evaluator invite statuses now progress pending → opened → in progress → submitted, and lapsed invites show expired in the recruiter list (HRP-358)
- Invitation email names the candidate instead of the evaluator, renders the personal message, and links to the new public evaluation page (HRP-351)
- Invite external evaluator modal: larger window keeps Remove inside, removing the last row clears it, and email addresses are format-validated on both client and server (HRP-350)
- Vacancy Assessments matrix: candidate names no longer render as Unknown for resume-sourced candidates, names link to the candidate card, and the funnel stage replaces the raw status (HRP-361)

## [1.13.19] - 2026-07-10

### Added
- Employees can now take sent exams in a side sheet: per-type answering with autosave and resume, submit locked until all questions are answered, score on the list, and a results review with the answer key highlighted; exams auto-complete when the last participant finishes (HRP-328)

### Fixed
- Manager assessment sheet now renders per-indicator score rows and a criticality chip per competence, and Mark as complete unlocks only after all critical competences are assessed; each evaluator sees their own sheet (HRP-348)

## [1.13.18] - 2026-07-09

### Added
- Interviews section on the candidate card: rounds list with processing statuses, Schedule dialog, consent banner with send-link action, and multi-file upload — several recordings at once, one interview per file (HRP-202)
- Auto-processing for interview uploads: optional transcribe-and-analyze chain that starts right after the file lands; AVI recordings accepted (HRP-202)
- Interview questions section on the candidate card with per-vacancy sets, Generate next set after a transcribed round, and auto-covering of questions answered in the analyzed transcript (HRP-205)
- Question set ready/failed notifications with a deep link to the candidate page, and a tenant setting that shows hiring managers the questions above the resume (HRP-205)

### Fixed
- New interviews created after the candidate signed the recording consent no longer demand a fresh signature — the latest signed consent is inherited (HRP-202)

## [1.13.17] - 2026-07-09

### Fixed
- Recruitment AI generation (vacancy profile, resume parsing, question sets, interview analysis) truncated large responses at the default 8192-token output budget and failed with a JSON parse error; all recruitment calls now request 32768 tokens (clamped per model), truncated LLM output raises a clear error, and vacancy profile generation retries once with a compact-profile instruction instead of failing (HRP-134)
- Health endpoint reported the hardcoded default version instead of the deployed release: settings now read the APP_VERSION baked into Docker images

## [1.13.16] - 2026-07-07

### Fixed
- Exams assign-employees dialog adds Division / Position / Specialization filters and a filter-aware Select all checkbox, matching the Mass assessment picker (HRP-225)
- Position filter in the Mass assessment and Exams employee pickers was dead: it called an endpoint removed with the structured Position entity; both now filter by position id and ignore stale filter responses (HRP-225)
- Manager assessment scoring sheet always claimed the vacancy profile has no competences: the profile is now fetched from its dedicated endpoint and the vacancy-bound assessment scale is exposed in the vacancy read (HRP-348)
- Public token endpoints (shared reports, consent links, invites) were rate-limited per full URL, so every distinct token got a fresh bucket and token grinding was never throttled; all rate limiters now bucket per endpoint
- Demo seed (self-hosted and SaaS) failed on fresh databases: PDPs were created without the required title and talent cards without the required start date
- Email delivery failures during registration, verification resend, password reset and external review invites are now logged instead of silently ignored

### Changed
- SQLAlchemy relationships in recruitment, competence and auth models now declare explicit lazy-loading policies (raise / selectin) with DB-cascade passive deletes
- Broad exception handling is now lint-enforced: every kept broad except carries a documented reason
- Frontend API client moved to src/lib/api/index.ts; two-layer convention (transport + typed domain modules) documented

## [1.13.15] - 2026-07-06

## [1.13.14] - 2026-07-06

### Fixed
- AI candidate scores pinned to the 0..1 contract in both analysis prompts and clamped at ingestion; normalized score now rebases raw onto the tenant scale by multiplication with an identity fallback (data backfill included), and score divergence compares normalized vs manager score (HRP-274)
- Recruitment e2e seed endpoint accepts `ai_analysis_mode` so the analysis-mode sub-badge specs assert the real badge (HRP-273)
- Vacancies and Talent Market header counters show the server total instead of the loaded page size when no client-side filter is active (HRP-290)
- Vacancy profile generation Dismiss/Cancel now pin the exact session id so a parallel running session can no longer be cancelled by dismissing a failed banner (HRP-134)

## [1.13.13] - 2026-07-05

### Changed
- Dictionaries capped at 100 chars for title and 250 for description across Grades, Specializations, Competence Types, Roles, Goals, Projects (HRP-282)
- Dictionaries list adds Source (System/Custom) and Status (Active/Inactive) filters with a Clear button (HRP-283)
- Dictionaries list shows Sort index column between Description and Source (HRP-284)
- Dictionaries list shows an item counter above the title search that respects the current filters (HRP-289)
- Dictionaries allow tenants to deactivate / reactivate System (origin) items per tenant — title / description / sort index stay frozen (HRP-285)
- Recruitment module decomposed into resource sub-routers, concern services and a tasks/ package; talent_market and assessment services split the same way — no API changes (project review)
- Recruitment GDPR candidate export offloaded to a Celery background task; erase stays synchronous (project review)
- LLM model names centralized in a single model registry; recruitment upload size ceilings moved to config (project review)
- Enterprise credit references removed from core code paths behind a community-safe seam (project review)
- python-jose replaced with PyJWT; Next.js bumped 16.2.3 → 16.2.9 (3 high CVEs)

### Security
- Auth abuse surface rate-limited per source IP (login, register, email flows, refresh), with trusted-proxy-aware client-IP resolution so forged X-Forwarded-For cannot mint fresh buckets
- Password change/reset revokes all previously issued tokens via a per-user token version
- Magic-login replay guard fails closed when Redis is unavailable
- Dev/E2E auth endpoints return 404 on deployed tiers even with a stray E2E_MODE=true
- Production startup fails fast on default secrets; file uploads validated for size and content
- CORS method/header allowlists tightened; runtime-env inline script escaping hardened

### Fixed
- Dictionaries delete error message simplified to a single generic line, Delete hidden from action menu for Source=System rows (HRP-286)
- Item counter on Development / Talent Market / Exams / Recruitment Vacancies now respects active filters (Assessments parity) (HRP-290)
- Competence tree row action menu adds Hide from users / Show to users for individual competences, mirroring the group toggle (HRP-118 redo)
- Competence Type picker on create/edit competence hides inactive types but keeps the currently selected one in edit mode so the saved value is preserved (HRP-287)
- Specialization Manage grades dialog keeps already-attached grades visible even when deactivated, spec page and matrix header render an "Inactive" chip next to such grades (HRP-288)
- Demo seed restores `/assessments` with cycles across draft / in_progress / done / cancelled — each carries an explicit `criteria_type`, and 180/360 reviews now pick up the assessee's Division Manager as a participant (HRP-314)
- Vacancy Overview applies the Show more / Show less collapse to Requirements, Responsibilities, Conditions, Main tasks, Additional tasks and KPI in view mode, and caps every long-text textarea at ~20 rows with internal scroll in edit mode (HRP-319)
- Competences & indicators on the vacancy page edits inline — Edit swaps the header to Cancel + Save (Save disabled until first change), and the modal dialog is reserved for AI Generate / Regenerate (HRP-318)
- Create Vacancy form replaces the freeform Specialization / Grade / Division text inputs and the Library refs block with dependent selects: Position (Active only) → Specializations → Grades → Division; every Specialization × Grade pick lands in `library_refs.specialization_grade_pairs` so Save Draft auto-fills Competences & indicators from the matching matrix (HRP-320)
- AI analysis writes both raw `cv.ai_score` and new `cv.ai_score_normalized` (raw rebased onto `[0..1]` against the tenant's active scale), unifies `InterviewAnalysisResult.verdict` with the resume-only enum, and mirrors the verdict onto `cv.ai_verdict` for full-mode runs; candidates table gains a Raw / Normalized toggle (HRP-274)
- Playwright recruitment suite gains `ai-resume-analysis.spec.ts` and `ai-bulk-analyze.spec.ts` — smoke coverage of the resume-only Analyze split-button, the verdict badge + mode sub-badge, and the bulk-analyze bar + confirm modal (HRP-273)
- Manager assessments `+ New round` button now opens a confirm dialog ("This will create Interview {N+1}.") before the round lands, matching the Confluence spec §3 (HRP-186 REDO)
- Vacancy profile generation failures surface inline on the vacancy page — the banner now renders the LLM error message and a Dismiss button (instead of silently disappearing and leaving an empty Competences & indicators block), and Dismiss flips the failed session to `cancelled` server-side so the next poll does not resurrect the banner (HRP-134 REDO)
- Recruitment questions PDF export switched from GET to POST so browser prefetch / retry cannot double-charge the 5-credit fee

## [1.13.12] - 2026-06-24

### Fixed
- HRP-305 migration now runs under the async (asyncpg) migrations engine — raw `%s` placeholders replaced with `sqlalchemy.text()` + named bind params, and `pg_constraint.confdeltype` cast to `text` so the snapshot insert receives a `str` instead of `bytes`

## [1.13.11] - 2026-06-24

### Changed
- Demo session lifetime trimmed from 10 h to 4 h (HRP-297)
- Demo seed binds Skill Levels and Grades to the origin System catalogue instead of cloning tenant-Custom duplicates so `/competences` and Dictionaries → Grades render a single coherent ladder (HRP-299, HRP-302)
- Demo seed leaves `/assessments` empty by default — the previous cycles shipped without Evaluation criteria and with broken Participants (HRP-300)
- Engineering parent division now wires a Manager and Deputy Manager so employees dragged under it resolve a chain of command for assessment / PDP flows (HRP-303)

### Added
- Demo seed ships one Material per (competence × Basic / Intermediate / Advanced) so the /competences "Materials" tab is no longer empty (HRP-298)

### Fixed
- Demo tenants now dispatch invitation and invitation-reminder emails so a prospective HR admin can walk through the full onboarding loop (HRP-301)
- Demo purge no longer aborts on `pdp_comments_user_id_fkey` and 13 sibling FKs; non-demo tenants and users are now refused by a database trigger so prod data cannot be wiped by accident (HRP-305)
- Demo purge `is_demo=false` TOCTOU race closed by `SELECT ... FOR UPDATE` + atomic guard so a concurrent flip cannot expose prod rows to the cascade delete (HRP-249)

## [1.13.10] - 2026-06-22

### Changed
- Demo session lifetime extended from 4 h to 10 h; sliding-inactivity timeout aligned with the hard TTL so only an explicit logout ends a demo session
- `POST /api/demo/start` now resumes the caller's existing demo session (`resumed=true`) when their bearer token still points at a live demo tenant, instead of stranding it in the pool by provisioning a new one

### Fixed
- Demo session access token TTL now matches the demo tenant lifetime (`DEMO_SESSION_TTL_SECONDS`) so visitors are no longer logged out after 30 minutes while their tenant is still alive
- Demo seed now ships 4 behavioral indicators per competence (one per skill level) and pre-fills assessment answers for `in_progress` / `done` cycles so `/competences` is no longer empty and `/assessments` scoring forms render correctly
- `assessment_answers.indicator_id` and `.answer_option_id` FKs now cascade so demo purge no longer fails with a ForeignKeyViolation when seeded answers reference indicators / options reaped via the tenant cascade
- Mobile layout for `/competences`, `/dictionaries`, `/employees/[id]` no longer overflows the viewport, and long dialog forms (Add Event / Experience / Education / Compensation) scroll inside the modal instead of hiding the submit button

## [1.13.9] - 2026-06-22

### Added
- Recruitment onboarding banner stays sticky across all `/recruitment/*` pages
- Auth pages logo links back to the landing

### Fixed
- Recruitment Select triggers show option labels instead of raw values (vacancy, candidate, position, stage, goal, priority, source, format pickers)
- Select triggers across assessments, settings, employees, talent-market now show option labels instead of raw enum codes
- AI analysis cancel path no longer crashes community builds when reaching the refund step — `ee.credits` import is now wrapped and the refund is skipped on community where there is no credit engine

## [1.13.8] - 2026-06-20

## [1.13.7] - 2026-06-20

### Changed
- Blog frontend stops fetching Confluence directly during SSR; `/blog` and `/blog/{slug}` now call the HRPulsar API and degrade to an empty state when the API isn't wired
- Drop `isomorphic-dompurify` from the frontend; sanitisation is handled server-side now

## [1.13.6] - 2026-06-20

### Fixed
- Demo start: creating a demo tenant on SaaS no longer redirects to the login form — the cross-domain handoff now reads `NEXT_PUBLIC_APP_DOMAIN` from the runtime env (`window.__ENV__` via `RuntimeEnvScript`) instead of the empty build-time inline in the CI-built frontend image, so the demo session lands on the app origin and opens straight into the demo
- Marketing login/register links now resolve the app domain from the runtime env too, so on SaaS they point straight at the app origin instead of taking an extra redirect hop through the marketing domain
- Employee delete: align the `has_connections` guard comment with the new `talent_candidates.employee_id` CASCADE so a future refactor cannot silently drop the application-level 409 protection
- Drop unused `resend_waitlist_audience_id` setting (HRP-260 retired the legacy waitlist exporter that read it)
- Middleware redirects: same-origin `/` → `/dashboard` / `/login` and post-login bounces now also send `Cache-Control: no-store` + 307 so a stale auth-state redirect cannot persist in the browser back/forward cache

## [1.13.5] - 2026-06-20

### Fixed
- Demo purge: `talent_candidates.employee_id` FK now cascades, so expired demo tenants with seeded TalentCandidate rows no longer fail tenant deletion with a ForeignKeyViolation
- WebSocket Redis listener: cancelled shutdowns no longer log `ws redis listener crashed` on every deploy — cancellation propagating through redis-py's `asyncio.timeouts` is now treated as a clean stop
- Frontend build: `/demo-handoff` no longer fails Next.js production build — `dynamic({ ssr: false })` is now wrapped in a Client Component as required by App Router

## [1.13.4] - 2026-06-20

### Fixed
- Blog: anonymous visitors no longer hit Atlassian login on inline post images or their wrapping links — the rewrite now handles absolute Confluence URLs and `<a href>` in addition to relative `<img src>`

## [1.13.3] - 2026-06-20

## [1.13.2] - 2026-06-19

### Fixed
- Blog: `/blog` index, `/blog/{slug}` posts and inline images render under any `CONFLUENCE_BASE` value (with or without `/wiki`) via a new `/blog-media` proxy

## [1.13.1] - 2026-06-19

### Fixed
- CI: dropped an obsolete one-shot waitlist exporter test + script after HRP-260 retired the public waitlist

## [1.13.0] - 2026-06-18

### Added
- Recruitment: AI Insights surfaces a "Resume updated — re-analyze" banner on the active resume-only run when the candidate uploads a fresh CV after the run was enqueued; the button re-runs resume-only (20 cr) and the worker archives the prior active run on success (HRP-272)
- Recruitment: resume-only AI Insights now renders backend-extracted `resume_excerpts` as clickable chips — click scrolls + 2 s ring-highlights the matching block in the parsed-resume editor (company+period match with dash/whitespace normalisation for Experience, two-way substring match elsewhere, fallback to the section header when no item matches) and auto-expands the section if collapsed; parsed-resume sections gain a chevron toggle inside an `<h3>` and Edit auto-expands the section (HRP-271)
- Recruitment: AI Insights in-flight card now renders all six pipeline stages (resume-only greys out Citations + Process analysis), polls every 3 s, and ships a Cancel button + confirm modal that revokes the Celery task, refunds 100 % credits when the run never reached the first LLM call (otherwise no refund), and writes an `ai.analyze_cancelled` audit entry (HRP-270)
- Recruitment: candidate card AI Insights gets a split-button — primary fires Resume only (20 cr), the chevron dropdown adds Resume + interview (40 cr), disabled with an "upload and transcribe an interview" tooltip when no transcript exists (HRP-269)
- Recruitment: consolidated XLSX report rewritten to a 4-sheet layout — Summary ranking (Manager + AI scores with computed recommendation), Competence Matrix with group separators + SUM total row + amber divergence highlight, one Detail sheet per candidate with scores + citations + verdict, and an always-present Incomplete-data sheet. Report wizard exposes an audience selector — Hiring-Manager runs swap raw process findings for a neutral reframe. Download pre-signed URL bumped to 24 h (HRP-268)
- Recruitment: vacancy candidates table gains per-row Manager % / AI % match (with the tenant `divergence_threshold` driving the cell-level Compact-matrix divergence count), a new **Divergence** column with an amber `N` badge linking to Canvas pre-filtered to that candidate, a tooltip preview of the top-5 divergent competences, and a By Manager / By AI / Custom Sort-control persisted in URL + per-tenant localStorage (HRP-267)
- Demo: every public sandbox now ships a populated tenant — 8 divisions, 17 positions, 22 competences with a 4-level skill ladder, 40 employees, 7 assessment cycles + 10 development plans across all statuses, 4 mass exams with assignments, 6 talent market cards, plus expanded recruitment funnel (+4 vacancies, +12 candidates, +4 interviews) so every sidebar section lands on real content instead of an empty state (HRP-281)
- Moderated signup: `signup_requests` table + `POST /api/signup-request` + `/verify` with Turnstile + per-IP rate limit + one-shot magic-login emailed after Slack approval (HRP-259, HRP-262)
- Demo: `POST /api/demo/save-access` lets a sandbox visitor capture their email as a moderated signup request (HRP-256)
- Demo: self-hosted demo stack via `make demo` and `docker-compose.demo.yml` on isolated ports 5436/6382/8200/3200 (HRP-256)
- Landing: hero CTAs replaced by "Try the demo" (starts a sandbox session) and "Create account" (moderated signup) (HRP-263)
- Frontend: dashboard `<DemoBanner/>` with session countdown, credits left and Save-access modal; new `/magic-login` page (HRP-256, HRP-263)
- Security: PII redaction extends to multi-locale identifiers — credit card, IBAN, US SSN, UK NIN, Spanish DNI, Italian Codice Fiscale (existing RU passport / INN / SNILS patterns kept)
- Recruitment: full Versions panel on the assessment Canvas — vacancy-scoped audit timeline with evaluator / candidate / date / "only divergence-triggering" filters and a Revert button (Manager scores only); HTTP 412 conflict resolution via `If-Match` on POST `/recruitment/candidate-vacancies/{cv}/assessments` plus a "Keep mine / Keep theirs" modal when a parallel edit lands (HRP-266)
- Recruitment: vacancy page gains an Assessments tab between Questions and Reports — Compact matrix with side-by-side `M:N / AI:N` cells, click-to-footer evaluator breakdown, AI vs Manager %-match per candidate (with AI `not_covered` excluded from the AI denominator), per-tenant `divergence_threshold` setting (HRP-265)
- Recruitment: resume-only AI analysis (20 cr) on the candidate card with split-button trigger, top-up upgrade to full (+20 cr, 30-day window), bulk fan-out from the vacancy candidates table, history modal and `[resume only]` / `[full]` sub-badges (HRP-204)
- PDP: hard cap of 3 active development plans per employee with 409 + descriptive error on the fourth Create (HRP-38)
- Talent Market: employee React action on Published cards + manager notification + Reacted chip on list/preview (HRP-213)
- Talent Market: Candidates block shows the last-match timestamp with a refresh action for managers (HRP-242)
- Assessment: Employee-only viewers see the Results block only when they are the assessee and the assessment is Done; peers / subordinates never see results on assessments they merely participated in (HRP-243)
- Exam: list filter bar — title search + multi-status filter — matching the Development plans page (HRP-227)
- Exam: per-question edit / delete on the detail page while the exam is in Draft (HRP-228)
- Exam: inline Title / Description / Deadline edit on the detail page until the exam reaches a terminal status (HRP-231)
- Employee profile: Goals progress KPI tile has an (i) tooltip spelling out the formula — average completion across open PDPs (not yet Done or Cancelled) (HRP-247)
- PDP: Progress Timeline now captures a version snapshot when the plan enters On review, and the timeline tooltip renders the status label instead of the raw code (HRP-21)
- PDP: email notifications now fire on the full lifecycle — reviewer on submit-for-review, owner on return, owner + reviewer on completion, and owner + reviewer on post-launch cancellation (HRP-244)
- Talent Market: removing a candidate from a Published card now emails the dropped employee with "You are not considered more: [Title]"; removals on Draft cards stay silent (HRP-245)

### Changed
- Recruitment: onboarding wizard is non-blocking now — sticky top banner across `/recruitment/*` with stepper + "Skip tour" replaces the full-page card; `/recruitment` redirects to `/recruitment/requisitions`
- Onboarding: public waitlist replaced by moderated signups — `waitlist_signups` table dropped, `/api/waitlist` removed, platform-admin Waitlist page gone, frontend WaitlistForm replaced by Demo + Request access CTAs (HRP-260)
- Competence matrix single-grade view swaps the narrow table for a list layout — colored level chips, section header with title + salary pill + remove icon, right-aligned 32×32 delete column, hover row highlight (HRP-157 REDO)
- Talent Market: narrowed the Match column in the Candidates table so right-aligned chips sit next to the Status column (HRP-173)
- Talent Market: per-competence chip in the drawer is coloured by the card threshold; the standalone Match/Below chip is gone (HRP-172)
- Talent Market: match drawer labels the spec row "Current position" even when min experience is set on the spec (HRP-210)
- Talent Market: appointment / cancellation emails skip the manager copy when the appointee manages their own division (HRP-211)
- Talent Market: locked Appointed checkboxes in the Change candidates picker render in muted colours so they read as non-actionable (HRP-214)
- Talent Market: Cancelled cards bring back the "Cancelled: yyyy-mm-dd" row in Details (HRP-92)
- Exam: status model unified across list, detail and Change-status dialog (Draft → Sent → In progress → Completed, any → Cancelled) with matching chip colors and per-status action buttons (HRP-236)
- Exam: list groups active first then completed then cancelled (newest first by the bucket date) and the rightmost column shows Created/Completed/Cancelled with no header; detail page swaps Deadline for Completed/Cancelled + date once terminal (HRP-233)
- Assessment: Question preview sheet no longer shows the standalone rating-scale banner or the per-indicator skill-level badge — layout fully matches the take-assessment sheet (HRP-165)
- Recruitment: AI profile prompt now includes Requirements / Responsibilities / Conditions and any uploaded attachments, and asks for ≥3 indicators and ≥3 interview questions per competence (HRP-135, HRP-235)
- Recruitment: profile generation banner with ETA and a Cancel button — generation runs in background and survives leaving the page (HRP-134, HRP-235)
- Recruitment: Generate competence matrix modal with clarification field, per-competence keep/drop checkboxes, inline edit/delete on groups, competences, indicators and questions, locked previously-saved rows, and race-safe cancel (HRP-134, HRP-235)
- Talent Market: Candidates table and Add/Change picker render the shared EmployeeSummaryLine (position under the name + status chip when the employee is not active) (HRP-258)
- DatePicker: digit-only yyyy-mm-dd input mask, header buttons that switch the calendar to month and year pickers, and the week now starts on Sunday (HRP-152 REDO)
- Recruitment: vacancy detail Overview shows Requirements / Responsibilities / Conditions blocks and edits them inline (HRP-239)

### Fixed
- Recruitment: demo kill-switch interview analysis now keys `AIAssessment` rows by the vacancy profile competence slug so the Compact matrix is populated, every analyze path bumps `interview.version` for consistent ETag invalidation, and orphan `interview_analysis_cache` indexes are dropped (HRP-275)
- Invitations: Send invitation modal now requires Division + Position before submit, and accepting a Manager invitation with a pre-selected division installs the new user as that division's manager (HRP-195)
- Division edit: assigning Manager / Deputy Manager surfaces a "promoted to manager" toast so the auto-upgrade is visible without leaving the page (HRP-196)
- Division detail: Position and Grade filter triggers now show the option title instead of the raw UUID after a value is selected (HRP-58)
- Division Add-employee dialog: Position / User select triggers no longer leak UUIDs, and the User picker now exposes a "?" tooltip plus an admin-only "+ Invite" shortcut into Invitations (HRP-174)
- Recruitment: Create vacancy redirects to the saved row immediately and runs profile generation in background, no frozen Saving spinner (HRP-238)
- Recruitment: Delete vacancy confirms with a single button, no type-the-title input (HRP-177)
- Recruitment: Stage select on the candidates table now renders the stage name instead of the raw UUID (HRP-181)
- Recruitment: Remove candidate from a vacancy directly in the list; candidate detail Back returns to the vacancy (HRP-181)
- Compensation tab now accepts the Manager role on employees within the manager's division subtree (view / add / edit / delete) with `403 outside_division_scope` outside it (HRP-221 REDO)
- Employee profile KPI tiles: Status "since" tracks the last status mutation, Tenure / "joined" anchors on first auth, Assessments sub spells out N open, Goals progress only counts non-terminal PDPs (HRP-246)
- PDP Return action: requires every item to carry at least one material (parity with Send) and rejects past-deadline attempts via a backend snackbar instead of disabling the button (HRP-187)
- PDP grade-driven materials: items seeded from the (specialization, grade) link now only include materials at or below the target skill level per competence (HRP-189)
- PDP Send button: past deadline is no longer a UI-side block — button stays enabled and the backend "Deadline is in the past" 400 surfaces in a snackbar (HRP-191)
- PDP Change-status modal: the (i) icon next to the disabled "In progress" option now exposes a hover tooltip explaining manual transition is not allowed (HRP-197)
- Assessment: reopening the Evaluation criteria sheet now shows the previously saved Passing score for recommended grade instead of resetting to 75 (HRP-183)
- Assessment: hovering the disabled In progress option in the Change status modal now shows the "Manual transition is not allowed" tooltip (HRP-192)
- Assessment: Change status modal trigger now shows the picked status label (e.g. "On review") instead of the raw code (HRP-194)
- Assessment: Detailed results "Percent for Skill level" now reflects calibrated Totals, and Cancel calibration refreshes the block without an F5 (HRP-185)
- Exam: Change status menu now sends `status_code` (was `status`, surfaced as `status_code: Field required`); the action menu is hidden for terminal Completed / Cancelled exams (HRP-234)
- Exam: send action rejects a deadline in the past with `Deadline in the past`; the Details block highlights the deadline date in red when it has already passed (HRP-237)
- Exam: Title is required on Create exam; "End date" is now "Deadline" and a pencil control on the detail page edits the deadline through PATCH `/mass-exams/{id}` (HRP-230)
- Exam: choice questions require ≥2 options and ≥1 correct (single choice exactly one); the Add question button stays disabled until those hold, the Type field shows the human label, and single choice options behave like radios (HRP-229)
- Exam: only one Pass Mark per test — `add_pass_mark` rejects duplicates, a delete button replaces Add once one is configured, and DELETE `/mass-exams/{id}/pass-marks/{pm_id}` restores the empty placeholder (HRP-226)
- Exam: Assign employees opens a searchable multi-select; the Results table renders the full name (linked to `/employees/{id}` when the viewer can see the profile); assigned employees now see the sent exam in their own `/exams` list (HRP-225)
- Dictionaries: deleting a Specialization or Grade now blocks with a 409 (and the confirm dialog enumerates the references) when assessments, assessment groups, PDPs, or exam pass marks point at it, instead of returning a 500 ForeignKeyViolationError

## [1.12.2] - 2026-06-09

### Fixed
- Recruitment: candidate card now mounts the Assessments section (rounds, manual scoring, invite external evaluator) so manager scoring is reachable from the UI (HRP-186)

## [1.12.1] - 2026-06-09

## [1.12.0] - 2026-06-09

### Added
- Recruitment: manual + bulk-finalize candidate add with duplicate-email detection on the active row only (HRP-181)
- Recruitment: enriched candidate list with AI verdict block, manager / AI score divergence flag and terminal-stage sort (HRP-181)
- Recruitment: per-vacancy funnel stage override with 409 on deleting a stage that still has candidates (HRP-181)
- Recruitment: soft-delete candidate with re-import support — the partial unique index ignores archived rows so the same email can come back (HRP-181)
- Recruitment: bulk resume upload with batch LLM parsing and duplicate-email preview (HRP-181)
- Recruitment: vacancy candidates UI rebuilt on the canonical model — single Add candidate modal with Upload / Manual tabs, FR-09 10-column candidates table with inline stage select and AI verdict popover, canonical candidate card page, and drag-and-drop Manage stages drawer with restore-default (HRP-181)
- Recruitment: parsed-resume sections on the candidate card are now inline-editable per section (Summary, Skills chip input, Experience, Education, Languages, Certificates) with `If-Match` concurrency (HRP-181)
- Recruitment: Playwright spec drives the canonical add-candidate path end-to-end (manual + bulk upload with deterministic E2E seed helpers, stage change, AI verdict popover, Manage stages drawer) (HRP-181)

### Changed
- Recruitment: canonical Candidate schema with optional `person_id`, denormalised display fields, partial unique on `(tenant_id, lower(email))`, AI block + `version` on `candidate_vacancies`, `resumes` renamed to `candidate_files` with `file_type` discriminator, and the spec-mandated 9-stage funnel seeded per tenant (HRP-181)
- Recruitment: bulk-upload limits bumped to 50 files × 10 MB with a 100 MB total batch guard, matching the Confluence spec (HRP-181)
- Recruitment: GDPR erase now drops S3 resume/interview blobs and blanks the canonical Candidate denorm columns (HRP-181)
- Recruitment: vacancy stages override rejects empty/all-terminal funnels and duplicate codes (HRP-181)

### Fixed
- Recruitment: candidate list shows externally-sourced candidates (person_id NULL) and search spans Person + canonical columns (HRP-181)
- Recruitment: tenant registration seeds default stages inside a savepoint so a seed failure no longer poisons the User insert (HRP-181)
- Recruitment: audit hook records failure rows when the wrapped service raises after partial side effects (HRP-181)
- Recruitment: bulk-finalize skips within-batch duplicate emails and refuses files whose parse hasn't reached completed (HRP-181)
- Recruitment: candidate-vacancies table sends `If-Match` on stage moves so 412 conflicts surface; bulk-upload poll sends `file_ids` as repeated query params (HRP-181)
- Recruitment: `patch_candidate` row-locks before the ETag check and re-derives denorm columns from `parsed_resume_jsonb` edits (HRP-181)
- Recruitment: parsing-status poll scopes empty `file_ids` by the requesting user so other recruiters' batches don't leak (HRP-181)

### Removed
- Recruitment: legacy v1.9.5 lite-candidate surface — `/lite-candidates` endpoints, the `VacancyCandidate` model and matching schemas, the singular `/candidates/upload` (upload_resume) endpoint, the `LiteCandidatesSection` component and `VacancyLiteCandidate` type, and the `Resume` model alias (HRP-181)

## [1.11.1] - 2026-06-05

### Fixed
- `/blog` and the Confluence attachment proxy no longer hang SSR when the Confluence integration is misconfigured — every upstream fetch is capped at a 5 s `AbortSignal.timeout` and falls through to the empty / null fallback on abort or parse failure

## [1.11.0] - 2026-06-05

### Added
- Talent Market lifecycle email notifications — publish (matched/not_matched), candidate added to a Published card, appointment (employee + manager), Completed (matched/not_matched), Cancel from Draft / Published with manager-level rollup; deep links into `/talent-market/{id}` and survive the login redirect (HRP-211)
- Specialization-delete confirm enumerates blocking positions and grade chains by name and locks the destructive button until the references are detached; backed by a new `GET /dictionaries/items/{id}/usage` preview endpoint (HRP-103)
- Shared `EmployeeSummaryLine` component renders Name + grayed Current position and an inline status chip when the employee is not active, so every cross-module employee reference picks up the same visual treatment (HRP-182)
- Custom `DatePicker` (Popover + Tailwind calendar) replaces every native `<input type="date">` in the Employee profile and Add-employee flows — always English labels, `yyyy-mm-dd` placeholder and value, min/max bounds wired per dialog (HRP-152)

### Changed
- Talent Market visibility for the Employee role is now scoped to cards they're a candidate on (Draft only when appointed); write affordances — title/description/dates pencils, Match%, Add/Change candidates, Appoint, Required spec/competence editors, status transitions, action menu — are hidden, "(it's me)" tag follows the viewer's own row, and the match drawer arrow only appears for self (HRP-209)
- Talent Market Experience match falls back to the employee's current Position when no qualifying WorkExperience entry exists: Match cell shows greyed "has experience" and the breakdown drawer labels the spec row "Current position"; tenured matches still take precedence and min-experience floors stay enforced (HRP-210)
- Talent Market Candidates status replaces the legacy `nominated` with `matched` / `not_matched` (rendered as "Matched" / "Not matched") so recruiters see at a glance which rows currently fit the card; auto-pool stamps `matched`, manual picks compute their status from the current matcher, `appointed` is preserved (HRP-214)
- Talent Market Appoint candidate now requires a confirm-dialog click so a stray button press can't pin a candidate (HRP-215)
- Talent Market Required competencies render as inline wrap-to-fit chips so the card-detail page stays compact (HRP-208)
- PDP status labels match Assessments: "Under review" → "On review", "Completed" → "Done" (HRP-188)
- PDP `sent → in_progress` is no longer a manual admin step — auto-promotes on the owner's first item tick; the list-page Change Status dialog disables In progress with a "Manual transition is not allowed" tooltip (HRP-197)
- PDP `returned` only allows submit-for-review or cancel; `returned → sent` is removed and `returned → review` is now part of the canonical transition map (HRP-198)
- Development Plan spec/grade is editable only in Draft; pencil affordances live next to each value, the bottom Change button is gone, and the dialog title + warning mirror Jira ("Development specialization & grade" / "All items will be replaced with the new specialization & grade set."). Saving in Draft rebuilds items + materials from the new (spec, grade) link (HRP-189)
- Development Plans list (`/development`) and employee Development tab (`/employees/[id]`) sort actives by Created desc, then Done by `finished_at` desc, then Cancelled by `finished_at` desc; employee tab drops the Deadline column and surfaces the bucket-anchor date with a "Created/Done/Cancelled" prefix (HRP-222)
- Assessment lifecycle: manual Sent → In progress is no longer allowed — the auto-flip from the first submitted answer is the only path. Details page hides the `in progress` button on Sent, Change status / Change status (all) modals grey the option out with a "Manual transition is not allowed" tooltip, and the backend rejects single + bulk attempts with a dedicated reason bucket (HRP-192)
- Talent Market match cell now opens the breakdown drawer via a dedicated chevron icon (chips are no longer the click target) and the icon stays in its active state for the row whose drawer is open (HRP-172)
- Match drawer Required competencies row colours the level percent green / yellow / red the same way the employee Competences tab does, surfaces a separate Match / Below chip against the card threshold, and the body scrolls when the requirement list overflows the panel (HRP-172)
- Match cell chips colour Competencies and Experience independently against their own thresholds — "no assessment(s)" and "no experience" are now muted instead of red, and copy switches to "no assessments" when the card has no Required specializations (HRP-173)
- Employee profile Experience tab enforces Company / Position / Start / End on Previous employment (past-only, Start ≤ End) and Start ≤ End on Current employment (HRP-219)
- Employee profile Education tab requires Institution / Degree / Field of Study / Start, requires Title + past-only Completed date on Courses, and the Courses dialog now picks Competences developed via the same group-tree picker used by Assessments (HRP-220)

### Fixed
- AI generation banner, per-target session badges, and background task progress now keep polling regardless of WebSocket state (HRP-232)
- AI competence generation drawer + status button stay in sync with the backend when WS pushes are dropped: REST polling (5s) now runs whenever the session is active, regardless of WebSocket state, so finished / cancelled sessions update without requiring a page refresh (HRP-122)
- Compensation: editing a record no longer returns a 500 with a half-saved row — the audit event now serialises date fields as ISO strings into JSONB instead of raw `datetime.date` (HRP-221)
- Compensation: schema, service, and Add/Edit dialog reject `end_date < effective_date` (422 / inline error) instead of saving an invalid range (HRP-221)
- Talent Market Required Competencies are now rebuilt from the union of current Required Specializations on PATCH (grade change) and DELETE — not just on initial add (HRP-171)
- Talent Market card detail drops the duplicated "Cancelled: yyyy-mm-dd" row from the Details block (the Status badge already names the terminal state); Completed cards keep the "Completed: yyyy-mm-dd" row (HRP-92)
- Talent Market card detail shows "No description" (no italic, no pencil) on terminal cards and keeps the italic "No description yet" + pencil on active cards (HRP-148)
- Talent Market publish now refuses cards whose End date has already slipped — the Draft → Published transition raises a 422 "End date is in the past" surfaced as the existing publish-failure toast, card stays in Draft (HRP-212)
- PDP Draft → Sent now refuses to launch a plan whose deadline already elapsed, returning 400 "Deadline is in the past"; the Send button surfaces the same reason as a tooltip (HRP-191)
- PDP Review → Returned applies the same past-deadline gate, blocking accidental return on an already-overdue plan (HRP-187)
- PDP progress percentage now recomputes when admins add items after launch — the cached `total_progress` no longer reports a stale ratio when the denominator grows (HRP-199)
- Passed PDP items + their materials are read-only: edit/delete pencils disappear and the API returns 403 on bypass attempts; unchecking the item (only possible in Review) restores edit access (HRP-200)
- PDP item order is stable: new items always land at the bottom regardless of the `sort_index` value the client sent, and the checkbox toggle never reshuffles the list (HRP-201)
- Assessment lifecycle emails (Evaluate yourself / Evaluate your employee / Evaluate employee / Your assessment has completed / Your employee assessment has completed) now deep-link to `/assessments/{id}` instead of the generic list; the auth middleware appends `?next=` for unauthenticated visitors so the login form bounces back to the deep link after sign-in. Cancellation emails also reach pending peer / subordinate / external reviewers — already-completed reviewers stay silent (HRP-84 REDO)
- Detailed results calibration: the Total Select now pre-fills with the auto-computed answer (instead of an empty "Total" placeholder), the trigger renders option titles instead of UUIDs, the Results table collapses Avg Score + Calibrated into a single calibration-aware Avg Score column, the per-level Results-by-level popup follows the calibration override, and Save only sends Totals that actually moved off baseline (HRP-185 REDO)
- Evaluation criteria sheet now reopens at the default `Passing score for recommended grade` (75) on every open instead of rehydrating the persisted value — the chart still consumes the DB value, only the edit form resets so HR sees a clean starting point (HRP-183 REDO)
- Mass Assessment action menu "Sent" with every child past-deadline now shows the "Deadline is in the past" toast instead of "No assessments updated" — `BulkStatusSkipReasons` now exposes `deadline_in_past` (and the other per-reason buckets the service already counted) so the frontend can swap the copy (HRP-83 REDO)
- AI competence generation drawer: the Refine request panel is no longer hidden behind the Indicators list's sticky counter and the `Expand to detailed form` toggle no longer trips the "This page couldn't load" reconciler crash — the panel now lives in its own DOM subtree below the scrollable suggestions list (HRP-96)
- Assessments listing filters (search + Type + Status) are now applied server-side and reset the page to 1, so the X-Y of N counter and paginator follow the filtered slice (e.g. filtering by Status=Cancelled no longer leaves the matches stranded on whichever page the user was on) (HRP-193)
- Assessments filter dropdown and Change status / Change status (all) modals now display status names ("In progress", "On review", …) instead of raw codes; backend titles renamed to sentence case via migration `hrp194stitles` (HRP-194)
- Division detail page no longer crashes with "TypeError: e1.map is not a function" — the positions fetch now unwraps the `{items, total}` envelope before passing the list to the Add-employee dialog (HRP-216)
- Specialization matrix save returns the freshly persisted snapshot — bulk upsert now mutates the `competence_links` collection via the relationship so the editor no longer renders an empty matrix until F5 (HRP-99)
- Recommended grade chart now hides grades whose required skill level sits above what the assessment actually covers — a Middle-targeted run no longer paints a phantom Senior bar fed only by Basic + Intermediate answers; migration `hrp170redo01` drops the cached payload so `scripts/recompute_recommendations.py` can backfill the corrected snapshots on deploy (HRP-170)
- Employee Competences tab now keeps the latest lower-level assessment visible under Other competences when the employee's position is bumped above the assessed level (Junior → Middle no longer hides the existing Basic result) (HRP-217)
- Employee Compensation Add/Edit validates Effective ≤ End and surfaces backend save errors inline so a failed PUT no longer toasts the user out of a non-rolled-back save (HRP-221)
- Talent Market: a single-appointee Published cancel now triggers the singular manager copy instead of the plural template ("Your employee's appointment cancelled" / "for X on …")
- Talent Market: lifecycle email dispatch (publish / candidate-added / appointed / completed / cancel) prefetches every candidate's Employee + User in one SELECT, replacing the per-candidate 2 round-trips
- Assessment cancellation mails to peer / subordinate / external reviewers now use a dedicated copy ("Evaluation cancelled") instead of the manager template and carry the same Open Assessment deep-link the other lifecycle mails do (HRP-84 follow-up)
- /blog HTML now goes through DOMPurify with an explicit allowed-URI scheme list; the Confluence attachment proxy parses the requested path with `new URL(path, origin)` and re-checks `origin` + `pathname` against the prefix allowlist
- Confluence-backed blog `/blog/{slug}` rejects numeric page ids longer than 16 digits so a crafted slug cannot keep hitting the Confluence REST API on every cache miss
- Login redirect `next=` parameter rejects backslash-prefixed paths (`/\evil.com`) that some browsers normalise into a protocol-relative URL

## [1.10.0] - 2026-06-03

### Added
- Recruiting: Schedule and upload interviews — chunked upload up to 500 MB with resume, support for audio/video/text transcripts, in-app player with speed control, archive/restore, antivirus scan (HRP-202)
- Recruiting: AI-generated individual interview questions per candidate (8 credits / set), dynamic per-round set evolution that skips covered questions and turns blind spots into next-round probes, manual + from-indicator question editing, soft-delete with regenerate-aware history, mark-as-covered (manual + auto-from-transcript), three-layout PDF export (Compact / Full / Cards), free sample-mode fallback when balance is below the generation threshold (HRP-205)
- Recruiting: Assessment scales dictionary (2–10 weighted levels, per-tenant default with seeded fallback) and per-vacancy scale binding with first-score snapshot lock (HRP-186)
- Recruiting: Multi-round candidate evaluation (pre-interview / interview-N / final) with parallel evaluator sheets, divergence highlighting, indicator → overall computed promotion, autosave, and last-complete-round-wins Manager score aggregation (HRP-186)
- Recruiting: External evaluator invitations by token with SHA-256-hashed storage, an isolated `/public/assessments/{token}` page (consent, inline-edit name, autosave, submit, expired/revoked error pages), per-IP rate limiting and brute-force deny-list (HRP-186)
- HRP-58 Added: Division detail Employees block gains Position + Grade dropdown filters that combine via AND with the existing Specialization plates; active filters surface as removable chips, header shows "X of Y", empty state distinguishes "no match" from "no employees in this division", and "Clear all" appears when 2+ filters are active
- HRP-174 Added: Contextual "Add employee" dialog on the Division detail page — Add-existing multi-select picker with cross-division confirm step, and Create-new mode with a locked Division field; opens from the Employees block header and the empty-state CTA
- AI generation: group / indicators modal lists every spec + division with linked ones pre-checked, a link marker + tooltip, and a search / Show-linked-only filter once the list exceeds 15 items; result preview shows existing items read-only next to new suggestions, a new/existing counter, and an only-duplicates banner that blocks Save (HRP-114)

### Changed
- Recruiting: Vacancy page redesigned — single-page layout (Overview + Competences & indicators + Candidates) with per-section inline edit, Position-linked Specialization/Grade multi-select, collapsible Description (HRP-180)
- HRP-175 Changed: Unified 7-column EmployeeListRow (Name → Position → Specialization → Grade → Division → Status → Hire Date) with sticky headers and tooltip-on-overflow shared by the positions drill-down, division detail and specialization employees tabs; drill-down widened to 960px with a readable counter
- HRP-196 Changed: Division manager / deputy assignment auto-syncs user roles — previous manager auto-downgraded to Employee on losing their last division (Admin / Platform Admin preserved), invitation role left untouched
- HRP-33 Changed: Position AI Generate now routes to the specialization AI-generate page with `?position=<id>`, locks the position's grade, names the position in a banner, and returns the operator to the position on Apply; positions and specializations list rows light up with an active-session badge while a matrix session is in flight
- HRP-51 Changed: Generate-materials dialog rebuilt with a full context picker — indicators per level, full specializations + divisions lists with linked-row highlighting and ≥15-row search/filter, sibling competences, company-description toggle, live materials/context summary; backed by a new `GET /api/competences/{id}/ai-generate-materials/context-options` endpoint and tri-state list semantics on the existing POST
- HRP-159 Changed: AI Generate matrix Divisions picker shows every tenant division with linked ones pre-checked, a link marker + tooltip, "(N of M selected, K linked)" counter, plus search and "Show linked only" filter once the list crosses 15 rows
- HRP-176 Changed: Competence detail page restructured with section icons + subtitles, shared level color tokens (Basic / Intermediate / Advanced / Expert) across Indicators and Materials, per-level counters and a "N materials for M indicators" gap warning, inline jump-to-section nav, primary-styled Generate-with-AI CTA, suspicious-text indicator warnings, click-to-edit Weight with tooltip and informational badge when weight = 0, and a "Context: {name}" badge with Reset on the Materials-by-context panel

### Fixed
- Recruiting: PATCH /recruitment/vacancies/{id} with `library_refs` no longer crashes on JSONB serialization (UUIDs now stringified before write)
- AI generation: 409 active-session conflict now opens a visible decision dialog (Open active / Cancel and try again) instead of silently redirecting via `window.location.href` (HRP-168)
- AI generation: generate button on /competences shows a `Checking session…` state while the active session is being resolved, rechecks the server before opening the confirm dialog, and the drawer keeps short-polling for ~30s if the session lands a beat after the click — no more empty "no active session" panel after Start (HRP-122)

## [1.9.5] - 2026-05-31

### Added
- Talent Market card detail allows inline edit of the card-level Match% on Draft cards via a pencil affordance (50–100, locked once Published) (HRP-179)
- Talent Market Match cell opens a per-candidate breakdown drawer (Required competencies + Experience rows), available from the Candidates list and the Add / Change picker dialogs (HRP-172)
- Recruiting: Edit, archive, restore and permanent delete actions for vacancies with kebab menu, list-row actions, archived filter, and ETag conflict guard (HRP-177)
- Assessment lifecycle email notifications: per-role Evaluate-yourself / Evaluate-your-employee / Evaluate-employee on Sent (and on late-add), `Your assessment has completed` + `Your employee assessment has completed` on Done, and matching cancellation emails for Sent / In Progress / On Review cancellations; the same events land in the in-app bell (HRP-84)
- Per-indicator Total calibration in Detailed results: reviewers pin a Total per indicator instead of calibrating raw scores; the per-competence percent / level inherit the override and a `calibrated` chip surfaces in the breakdown. Participant submissions are locked while calibration is in progress; `Cancel calibration` wipes every Total and restores the raw averages (HRP-185)
- Recruiting: Vacancy creation accepts company-library refs — positions, specialization+grade pairs, and divisions — and seeds vacancy competences from the linked grade matrices; the create / edit form now has multi-select pickers for Positions, Specializations, and Divisions (HRP-131)
- Recruiting: Manual Requirements / Responsibilities / Conditions text blocks plus per-vacancy file attachments (25 MB / 10 files max, PDF/DOCX/PPTX/XLSX/TXT/MD/CSV/JSON/PNG/JPEG/GIF/WebP/ZIP/EPUB) for AI prompt context; the Profile tab carries an upload widget with size / mime guards (HRP-135)
- Recruiting: Vacancy competence list — manual library picks, library inheritance, or AI-proposed — with replace-set PATCH endpoint (HRP-136)
- Recruiting: Lightweight candidate flow on the Vacancy → Candidates tab with separate recruiter / AI scores, Δ-marker, source, resume file link, and stage/status; inline Add candidate dialog (HRP-181)

### Changed
- Talent Market card detail hides the Dates row in Details when the card is Completed or Cancelled (the terminal-date row already carries the timestamp) (HRP-178)
- Required Specializations block renamed (plural) and asks for explicit confirmation when adding a second spec, editing, or deleting one — Required Competencies are recomputed on save (HRP-171)
- Talent Market Match cell renders the real Competencies % and Experience years with colour rules (green / orange / red / "no experience"); pool and candidate-list rows are ranked by qualifying first, then comp-only, then exp-only, then the rest (HRP-173)
- Recommended grade chart appears at On Review, supports Employees' current positions and Specialization-All grades, and recomputes per-grade match % as the mean of competence percents across levels up to the grade's required skill level (HRP-170)
- Detailed results hide skill levels above each competence's required level so only the indicators actually evaluated appear (HRP-184)
- Criteria sheet hides Passing score for Individual competences and labels it `Passing score for recommended grade` with the tooltip and formula toggle removed for Target / Current positions (HRP-183)
- Active assessment cap per assessee lowered from 5 to 3; Mass assessment now does a partial creation when only some employees are capped and reports the launch as 409 when every employee is capped (HRP-37)
- Draft → Sent transition with an elapsed deadline now returns 409 instead of 400 — the request itself is valid, the stored deadline is the conflict (HRP-83)
- Grouped Assessments list sorts active rows first by Created, then Done by Completed, then Cancelled by Cancelled date — matches the single-list ordering (HRP-166)
- Draft → Sent button label renders as `send` (imperative) instead of `sent` (HRP-190)

### Fixed
- Talent Market matcher projects assessment results to the required skill level using the per-level breakdown when a Done assessment ran at a higher level (HRP-129 REDO)
- Recruiting: AI vacancy profile generation runs inline instead of fire-and-forget Celery so the UI returns the saved profile or a real error (HRP-134)
- Recruiting: AI profile generation tracks an active session in `vacancy_profile_sessions` and the vacancy detail page polls it — a returning user sees `Generating…` or `Last generation failed` without re-clicking (HRP-134 REDO)
- Recruiting: CORS now exposes the `ETag` header so the cross-origin vacancy detail page can read it and send `If-Match` on PATCH; previous `If-Match required` toast on Save is gone
- Recruiting: Delete vacancy from the list now refreshes the rows in place via an `onDeleted` callback instead of a no-op router.push to the current URL

## [1.9.4] - 2026-05-27

### Changed
- Employee Competences tab replaces radar chart with Current position / Other competences view, level-breakdown popups, and unified percent math (HRP-153)
- Question preview opens as a side sheet matching the take-assessment layout (HRP-165)
- Assessments list groups by status with status-specific dates and unified status chips (HRP-166)
- Talent Market auto-populates candidates from Required competencies / specializations; skill-level filter honours assessments at or above the required level and the threshold change re-runs the matcher (HRP-129)
- Talent Market candidate management modal supports Change mode (HRP-95)
- Talent Market card detail page renders a "No description yet" placeholder with the edit pencil when Description is empty on non-terminal cards (HRP-148)
- Talent Market terminal cards show Completed/Cancelled date instead of Closed at (HRP-92)
- Talent Market list orders active cards before terminal ones with status-aware dates and overdue highlight (HRP-167)

### Fixed
- Add Current Employment dialog shows the Division name in the picker instead of its id (HRP-151 review)
- AI generation dialog on competences page now scrolls within viewport and keeps action buttons visible (HRP-169)
- Assessment send no longer rejects deadlines equal to today (HRP-164)
- Talent Market candidate names honour viewer role for profile links (HRP-149)

### Removed
- Grade match chart on Specialization-All-grades assessments (duplicated existing Recommended grade chart) (HRP-162)

## [1.9.3] - 2026-05-23

### Added
- AI Generate matrix brief now carries a preflight context picker — positions linked to the specialization, tenant divisions (pre-checked when touched by any of those positions), the company description, and existing matrix competences render as chips with × controls; new free-form refinement textarea appends to the prompt (HRP-159)
- Generate learning materials with AI from the competence detail page: dialog picks skill levels + optional specializations + count per level + free-form refinement, returns a review list, and bulk-saves the kept rows (HRP-51)
- "Add multiple" inline textarea on every skill-level block of the competence page: one line per indicator, transactional bulk insert via `POST /competences/{id}/indicators/bulk` (HRP-49)
- Development Plans list: filter bar matches Assessments (title search + multi-select Status with Clear), minus the type filter (HRP-147)
- Talent Market card Details block surfaces status transition commands per spec: Draft → Publish, Published → Complete (requires ≥ 1 appointed candidate) and Cancel; terminal statuses show no commands. Publish now also requires ≥ 1 candidate (HRP-150)
- Detailed results block on the assessment page (Platform admin / Admin / Manager) — per-competence type and required level, per-skill-level percent breakdown, per-indicator role answers with author-tagged comments and a Total row; `GET /assessments/{id}/detailed-results` powers it (HRP-154)
- Survey now opens in a side Sheet with vertical answer options and a per-indicator comment field; selections autosave on every change and rehydrate from `GET /assessments/{id}/my-answers` when the Sheet is reopened (HRP-146)

### Changed
- python-dateutil declared as a direct dependency
- WorkExperience.division / .position eager-load opted in per endpoint
- Date pickers and date display use English locale and `yyyy-mm-dd` format across the app (HRP-152)
- AI competence library: group-level AI generation now offers an "Augment existing items in the group" toggle — off keeps fresh-only behaviour, on adds new competences to existing subgroups and new indicators to existing competences, with matched nodes rendered locked in the review tree (HRP-155)
- Assessment detail page swaps the Deadline label for `Completed <dd.mm.yyyy>` / `Cancelled <dd.mm.yyyy>` on terminal assessments (read from `finished_at`, now also pinned on the Cancelled transition) and renders an overdue Deadline in red on active assessments (HRP-161)
- Talent Market list view: action menu always visible (no hover gate), hidden on Completed / Cancelled cards, collapsed to Change-status + Delete with capitalised status labels; detail page gains pencil-icon inline edit for Title / Description / Dates on non-terminal cards (HRP-148)
- Position detail page's Competences & indicators block renders as a compact two-level tree (group → competence with the required level badge); indicators sit behind a per-competence expander instead of a flat list (HRP-32)
- Headcount drilldown modal on `/company/positions` widens to `sm:max-w-3xl` and the list scrolls inside so every EmployeeListRow column (Name / Position / Division / Status / Hire Date) stays legible (HRP-61)
- Employee Experience tab: first block renamed Current Employment, captures Division/Position/Start with defaults from the card, and renders an elapsed-duration badge (days/months/years per HRP-151) instead of the project title shorthand (HRP-151)
- Employee Competences tab rebuilt as two blocks — Current position competences (tree from the grade-specialization, % from latest qualifying Done assessment, dash when no run covered the required level) and Other competences (flat list of every other assessed competence/level), replacing the opaque radar chart (HRP-153)

### Fixed
- Competence overview no longer fires per-assessment SQL on the employee page (HRP-153 review)
- Stuck AI competence-generation sessions are auto-reaped after 15 minutes (HRP-33 review)
- HRP-151 migration downgrade backfills NULL titles before reapplying NOT NULL
- LLM refinement input is stripped and sanitised against role-tag injections
- AI competence generation "active session already exists" 409 now carries the live session id+scope, a global banner surfaces in-flight sessions from every page, and worker crashes flip the row to `error` instead of leaving it stuck as `running` (HRP-33)
- PDP item checkboxes now toggle both ways for the plan owner in Sent / In progress / Returned, and for the division-manager reviewer (implicit reviewer when no `reviewer_id` is set) while the plan is Under review (HRP-19, HRP-130)
- Talent Market Candidates block now auto-fills from the card's requirements: last `done` assessment per Required Competence at the matching skill level, average % vs the card-level Match %, plus a Required Specialization position check (HRP-129)
- Talent Market Candidates block renders the employee name as a link to the profile instead of the raw uuid (HRP-149)
- Division detail page now lists assigned employees and the Edit dialog renders Manager / Deputy names instead of raw UUIDs — `/api/employees?limit=…` cap of 100 silently 422'd the page's `limit=500` requests and emptied both lists (HRP-59, HRP-160)
- Preliminary assessment results now recompute when a new respondent submits after the assessment is already in On Review, so Avg Score reflects the freshest survey set while calibration overrides keep Percent and Level (HRP-145)
- Manage grades dialog on the Specialization page now toggles already-attached grades (untick to detach) and is also reachable from the Company → Specializations row menu (HRP-158)
- Specialization matrix with a single grade now uses the full table width, the indicator dialog groups levels with bullet markers and per-level scroll, competence titles open in a new tab and tooltips snap-in at 100 ms (HRP-157)
- Add-competences dialog on the specialization matrix gains per-branch chevrons plus Expand all / Collapse all controls so deep trees stay manageable (HRP-100)

## [1.9.2] - 2026-05-22

### Added
- Talent Market card carries a card-level **Match %** (50–100) on Create/Edit card — editable until publish, drives the Required Competences matcher threshold for every competence (HRP-128)
- Edit employee dialog now lets admins/managers rename a person — Name and Last name fields drive a single PUT on `/employees/{id}` (HRP-121)
- Add-material dialog: Format becomes a 17-option select, Type a required 3-option select with icons (Theoretical / Practical / Feedback); material rows show the type icon (HRP-50)
- Bulk-add competences to a group: inline button next to each tenant group + multi-row dialog hitting a single `POST /competence-groups/{id}/competences/bulk` endpoint (HRP-108)
- Assessment Results table surfaces each competence's required skill level next to its title and exposes a `Results by level` popup with the per-skill-level percent breakdown (Basic / Intermediate / Advanced) up to the cascade limit (HRP-90)
- PDP plans in terminal statuses show the closing date instead of Deadline — "Completed at" / "Cancelled at" in both the list preview and the detail page (HRP-132)
- Admins and managers can delete specializations directly from the Company → Specializations list and detail page; the existing 409 guard against positions/grade chains still applies (HRP-103)

### Changed
- Required Competences picker rewritten — step 1 is now a tree with search and group-level select-all; pre-selects existing rows; the action button reads **Change** once the block has entries and saves the full set as a replace (HRP-128)
- Activating a competence group now cascades both up to ancestors and down to descendant groups; new children inside an inactive group default to inactive; Delete is hidden when the group is referenced by other services (HRP-118)
- Edit-group dialog hides the activate-by-default checkbox and shows a read-only «Used by client» affordance with tooltip when the group is referenced by matrices, assessments or development plans (HRP-137)
- Evaluation criteria summary block collapses Specialization + Grade into the Type line for target_position, drops the auto-pick hint from single assessments, and hides the aggregated Competences list on mass-assessment parents using current_positions (HRP-98)
- Extracted the duplicated HRP-40 scope/Draft predicate into one `apply_assessment_scope` helper used by every assessment list/detail/grouped/group-detail read endpoint (HRP-113)
- PDP item checkboxes in Under review can be toggled by admin / platform admin / assigned reviewer; Return button is disabled once every item is accepted (HRP-130)
- AI generation → competence library preflight modal lists every specialization, division and existing tree node with its own × control so the user can drop individual entries from the prompt context (HRP-143)
- AI generation: group / indicators preflight modal exposes related specializations, ancestor groups, descendant subgroups and sibling competences as per-item chips (HRP-114)
- AI competence/indicator generation prompts now require at least 3 indicators per skill level and ship explicit per-level calibration guidance (HRP-144)

### Fixed
- Competence cascade walkers now scope every ancestor/descendant query to the caller's tenant so a stray cross-tenant node in the tree can never be silently activated or deactivated (HRP-140)
- Required Specialization row no longer renders "Min. experience: 0 year(s)" when the value is `0`; deleting a row now requires explicit confirmation (HRP-127)
- Mass-assessment bulk-launch now surfaces a "Deadline is in the past" error when every child fails the deadline guard, instead of a misleading "Updated 0 of N" success toast (HRP-83)
- Editing a Work Experience or Course/Certification entry no longer fails when Competences developed keeps an existing competence — the link sync diffs the set instead of recreating every row (HRP-141)
- Recruitment AI profile generation works again — backend route now matches the frontend callers (HRP-134)
- Employees list search now hits the backend and finds matches across every page, not just the visible one (HRP-120)
- Competence page «Materials by context» dropdown now shows the selected specialization name instead of the raw value (HRP-52)
- Add-indicator / Add-material dialogs: skill-level dropdowns now show the selected level name (HRP-50)
- Assessment calibration now refreshes Percent, Level and overall result from the calibrated score and the override survives the on_review → done transition (HRP-126)
- PDP material modal aborts an in-flight file upload when the user clicks Cancel or outside the dialog, so the next open is clean instead of stuck on "Uploading…" (HRP-14)
- PDP plan owner can submit a Returned plan back for Review and freely toggle item checkboxes in Sent / In progress / Returned (HRP-19)
- PDP item completion is one-way for the plan owner — once ticked the checkbox locks (admin/reviewer keep full toggle in Review) (HRP-20)
- AI competence generation no longer fails with "AI returned an invalid response" or false "Background worker offline" during long runs (HRP-122)
- Division managers see PDP plans in Draft within their managed subtree, matching admin authoring visibility (HRP-142)

## [1.9.0] - 2026-05-19

### Added
- `make celery` target starts worker + beat together so developers don't accidentally skip `--beat` (HRP-122)
- Preflight modal for `whole_base` AI generation lets operators drop context categories (Specializations / Divisions / Company description) and add a refinement note before launch (HRP-123)
- Augment-mode preflight adds a fourth removable chip that drops the existing competence library from the prompt for fresh suggestions (HRP-124)
- Specialization-matrix brief gains "Generate indicators for existing competences" checkbox (visible when the matrix is non-empty); matrix-session ready emits a deduped toast with an "Open review" action (HRP-119)
- AI generation preflight extended to `group` and `competence_indicators` scopes: per-scope removable context chips (specializations / divisions / company / source_tree / sibling_competences / existing_indicators) plus the free-text refinement note (HRP-114)
- Expand all / Collapse all controls on the Competence DB tree and the Assessment competence picker; shared `useTreeExpansion` hook + `TreeExpandControls` component (HRP-109)
- Assessment detail surfaces each participant's `employee_id` + `can_view_profile`; the Participants block renders the name as a link to `/employees/{id}` when the viewer is in scope (admin = all, manager = own + subordinate divisions, employee = self) and plain text otherwise (HRP-85)
- Employees with role=employee can now manage their own Education and Courses entries on their profile (add/edit/delete); every other write action on `/employees` (list action menu, Edit profile, Add event / experience / compensation) is hidden for that role so the UI no longer offers buttons that 403 (HRP-66)
- Division detail page: Specializations grid plates show employee count per specialization and act as toggle-filters for the Employees block (HRP-58)
- Division detail page grows an inline Edit button + dialog (Name / Description / Parent / Manager / Deputy Manager) mirroring the company-tree dialog including the role-downgrade confirmation (HRP-59)
- Talent Card create/edit gains Start date (required, default today, ±5y window) and End date (optional, ≥ start, +5y); list preview and detail page now render `since DD.MM.YYYY` / `start – end` / `Closed: DD.MM.YYYY` per spec, and Details exposes Division / Dates / Closed at (HRP-92)

### Changed
- Assessment status UI exposes the On Review checkpoint everywhere — list page Change Status modal (HRP-115), detail page action buttons replace Done with On Review in In Progress (HRP-117) and surface Done / Cancelled in On Review (HRP-116)
- Title capped at 100 chars and Description at 250 across Assessment, Mass Assessment, PDP, Talent Card, and Mass Exam create/edit flows — frontend `maxLength` + Pydantic guard (HRP-89)
- Assessments list filters for Types and Statuses became multi-select (checkbox dropdown with `n types` / `n statuses` trigger label); single-value lock removed (HRP-86)
- Talent Market list grows a filter block matching Assessments: title search + multi-select Types / Statuses + Clear (HRP-88)
- Positions list: AI-draft entries are now surfaced in a dedicated card at the top of the page so they are reviewed before the approved-positions table (HRP-60)

### Fixed
- Dashboard pages stay browser-translatable again — the auto-translate guard from HRP-46 is now scoped to the AI generation drawer (open-state only) instead of the entire dashboard (HRP-133)
- AI generation drawer waits for three consecutive `/health/celery` failures (~45s) before flagging "worker offline", silencing false alarms during long LLM calls (HRP-122)
- AI Generate matrix Apply now surfaces a warning toast when zero competences and zero grade links were persisted instead of a misleading "Matrix applied" success (HRP-105)
- Specialization matrix header reworks salary into a bordered `$` pill, ships a destructive X icon for grade removal gated by a confirm dialog (replacing `window.confirm`), tints cells by skill-level rank as a heat map, and flags competence rows missing indicators / development materials at assigned levels (HRP-101)
- Specialization matrix gets an Add-competences modal with the full group tree, group-level cascade checkboxes (with a partial-selection badge), title/breadcrumb search, per-row external link to the competence detail page, and a counter-aware Save button; the legacy inline dropdown is gone (HRP-100)
- Launching an assessment (Draft → Sent, single or via Mass action menu) refuses an already-elapsed deadline with a 400, leaving the assessment in Draft so the operator can extend it first; bulk responses carry a new `deadline_in_past` skip reason and the snackbar enumerates it alongside missing-criteria/scale (HRP-83)
- `/api/positions?limit=200` no longer 422s — the cap moved from 100 to 500, so the Positions filter on the Employees list page actually populates instead of collapsing to "No options" (HRP-64)
- Positions list status menu now follows the same flow map as the detail page: a closed position only offers "Reopen → Active" instead of every other status (HRP-111)
- Inline-edit fields on entity detail pages (assessment title/deadline, position title/headcount/description) share a `useInlineEdit` hook + Enter/Esc keymap helper; assessment title and deadline now also commit on Enter (HRP-110)
- Talent Market Add candidate: replaced UUID input with a searchable employee picker showing computed match score (competence assessments first, work-experience years fallback) and matched / not matched status, with bulk attach (HRP-95)
- `/api/assessments/{id}/results` now returns 404 to callers who can't otherwise see the assessment (HRP-40 scope fence extended); admins and participants are unaffected (HRP-112)

## [1.8.2] - 2026-05-18

### Added
- Specialization-matrix cells deep-link to the competence detail page with `from=matrix&specialization_id=…`, the page swaps its breadcrumb for "Back to matrix", AI indicator sessions launched from there pick up the spec/grades/sibling competences in the prompt, and any indicator change on a referenced competence prompts the user before saving / before AI Apply (HRP-102)
- AI matrix brief form (`/company/specializations/{id}/ai-generate` and the Position AI card) now persists the typed brief in `localStorage` and restores it on refresh / remount; a `Clear draft` button and successful Apply wipe the saved state, matching the refinement-panel UX shipped earlier under the same ticket (HRP-97)

### Changed
- Position pages: list shows clickable spec/grade and inline "Set specialization"/"Set grade" CTAs when missing; Overview block grows its own Edit button; Competences & indicators block surfaces a state-aware CTA (Pick specialization → Pick grade + Open specialization → Configure matrix) instead of a generic empty hint; deep-links from positions to a specialization/matrix carry `from=position&position_id=…` so those pages swap the breadcrumb for "Back to position" (HRP-54)

### Fixed
- Competence detail page renames the AI button to "Augment indicators (AI)" when at least one indicator already exists, downgrades the matrix-context preflight so indicator generation no longer 422s on specs without grades, and the cross-tenant test now stages a real foreign-tenant spec and asserts the precise 404 (HRP-102)
- AI generation `regenerate` / `refine` no longer 500 on `ux_compgen_one_active_per_user` — service flushes the parent's status UPDATE before inserting the child and translates a still-racing IntegrityError into a clean 409, matching `start_session`
- AI generation refinement panel re-hydrates from the last submitted form when the drawer reopens / page refreshes / user hits Try again — backend persists the structured `{general, add, change, exclude}` snapshot in `session.params.refinement_form` and the drawer auto-expands the panel when sub-fields had values; «Clear data» wipes both the form snapshot and the composed prompt (HRP-97)
- Participant.is_completed now mirrors the questionnaire's skill-level cascade — when an AssessmentCompetence row carries a `skill_level_id`, only indicators at or below that level count as expected, so answering every visible question actually flips the participant to Completed=Yes (HRP-75)
- AI generation drawer header now shows the clickable competence-name link when indicator generation is launched from the competences list page — the list page's `targetTitleResolver` walks competences (not only groups) (HRP-93)
- Specialization-matrix AI generation no longer burns 5 retries on a degenerate prompt: `execute_session` short-circuits to `insufficient_data` when the spec snapshot has no grades, and the LLM client's default `max_tokens` bumped from 4096 to 8192 so realistic matrices fit (HRP-33)
- AI generation failure messages now include the underlying exception type and a short detail snippet so JSON-truncation vs. schema mismatch vs. provider error are distinguishable from the UI (HRP-33)
- Position page: when AI Generate runs but the position has no grade set, the success toast points to the specialization page (the only place the saved matrix is visible), and the matrix-empty state on the position page surfaces a "set a grade or view on specialization" hint (HRP-33)
- `/health/celery` falls back to Celery control-channel `ping` when the Redis heartbeat key is stale so the AI drawer stops surfacing a false "worker offline" banner while a single worker is busy with a long generation (HRP-46)
- Auto-translation (Google Translate, etc.) is disabled inside the dashboard area only — auto-translation was mutating React-managed DOM nodes in the AI generation drawer and triggering `NotFoundError: insertBefore` when the skeleton swapped to the indicator list; marketing pages keep browser translation so multilingual SEO visitors are unaffected (HRP-46)
- Live AI generation sessions (own + other tenant admins') now light up the affected group / competence / specialization / position row with a clickable Sparkles badge that opens the drawer; AI Apply now routes the user back to the entity it just populated (HRP-93)

## [1.8.1] - 2026-05-15

### Changed
- Position detail page (`/company/positions/{id}`) supports inline edits for Title, Description, Headcount, and Status; Specialization and Grade in Overview are clickable links (HRP-32)
- Assessment detail: "Preview questions" moved from Rating scale to the Details block (available whenever criteria and scale are picked); "Take this assessment" is hidden in Draft because the assessment is not running yet (HRP-104)

### Fixed
- Regular employees no longer see Draft assessments in the list or detail page when added as a participant (HRP-40); the detail page renders the "Assessment not found" placeholder instead of a toast on 404
- `/api/assessments-grouped` applies the same subtree/participant scope and Draft filter as `/api/assessments`, closing a leak that let employees see Draft (and other-employee) rows on the assessments list page (HRP-40)
- `GET /api/assessment-groups/{id}` (lazy-load fired when a user expands a group card) now applies the same scope/Draft filter and returns 404 when the caller can't see any of the group's children (HRP-40)

## [1.8.0] - 2026-05-14

### Fixed
- Recruitment vacancy detail page no longer crashes with a server-error screen — the `/vacancies/{id}/candidates` payload is unwrapped from `{items, total}` before the candidates table reads it
- Vacancy and candidate list empty states carry `recruitment-vacancy-empty` / `recruitment-candidate-empty` testids, and the interviews tab keeps `recruitment-interviews-tab` in its empty state
- `proxy.ts` treats `/recruitment/consent/{token}` and `/reports/share/{token}` as token-public routes — anonymous consent and share links no longer bounce through `/login`
- `proxy.ts` lets Next.js RSC / prefetch requests through the auth gate so background fetches without the `has_token` cookie can't 307 the tab to `/login` right after a `router.push`
- AuthProvider treats aborted in-flight refresh fetches (Chromium reports `TypeError: Failed to fetch` instead of `AbortError` when a client-side navigation tears down the page) as cancels, not logouts

## [1.7.7] - 2026-05-13

### Fixed
- E2E `access-scope.spec.ts` "regular employee only sees published cards" now seeds a Required Competence on the admin's card before publishing, matching the 1.7.5 publish-gate
- HRP-93 E2E spec deletes any pre-existing active AI generation session before starting a `competence_indicators` one for the target, so the `?compgen=open` deeplink reliably opens the drawer (was flaky on shared runners)

## [1.7.6] - 2026-05-13

### Fixed
- Integration test `test_publish_card` now seeds a Required Competence before publishing so the HRP-87 publish-gate (introduced in 1.7.5) doesn't break the Talent Market integration suite — and a companion test pins the 422-on-empty-block behaviour

## [1.7.5] - 2026-05-13

### Added
- AI generation drawer shows a "Cancel session" footer button with a confirm modal that discards the generated suggestions (HRP-91)
- AI generation drawer header turns the target competence name into a link back to its detail page (HRP-93)
- Indicators-list bulk select/deselect inside the AI generation drawer (HRP-94)
- Talent Market card detail page replaces free-text Requirements with two structured blocks: Required Specialization (spec + grade + optional min experience, auto-fills competences from the configured ladder) and Required Competences (three-step picker with skill level per competence and a shared match %) (HRP-87)
- Backend endpoints `POST/PUT/DELETE /talent-market/{card_id}/required-specializations[/{link_id}]` and `POST/PUT/DELETE /talent-market/{card_id}/required-competences[/{link_id}]` (HRP-87)

### Changed
- Apply-to-library dialog reads selected indicators directly when the session scope is `competence_indicators`, so the publish/draft buttons stop being permanently disabled (HRP-94)
- After applying generated indicators, the drawer redirects to the updated competence detail page regardless of where the session was started (HRP-94)
- `apply_session` propagates the `publish` flag into `_apply_indicators_only`: published indicators land active, drafts land inactive (HRP-94)
- Competence detail page surfaces any active AI session — including sessions from other scopes — through a clickable "AI generation in progress" / "Open active AI session" button with a Tooltip explaining the lock (HRP-47)
- Talent Market publish refuses to flip a card to `published` until at least one Required Competence is set; published cards become read-only for both Required blocks (HRP-87)
- Required-Specialization endpoint rejects (spec, grade) pairs that have no configured `GradeSpecialization` with 422 — direct API callers can't bypass the ladder UI (HRP-87)
- Three-step Required-Competences dialog preserves the skill-level picks for competences that survive a back-and-forth through step 1 (HRP-87)
- Indicators bulk select/deselect rolls per-row failures into a single summary toast instead of N individual ones (HRP-94)

## [1.7.4] - 2026-05-13

### Fixed
- Multi-select filters (Divisions / Statuses / Positions / Specializations / Grades) record every consecutive pick instead of overwriting the previous one — a stale snapshot in the toggle handler dropped earlier selections from the URL
- AI matrix-session router asserts `target_id` is set after the position-fallback branch so the type checker can prove the bootstrap call against the right specialization
- Specialization cold-start E2E spec uses the real `matrix-unsaved-bar-btn-save` testid and bootstraps grades through the new endpoint inside each scenario instead of relying on test ordering
- Employee detail back-button E2E accepts the `?page=…` query that the list page restores after the back navigation

## [1.7.3] - 2026-05-13

### Added
- Specialization page exposes a manual cold-start path: Add Grades modal picks grades from the dictionary, matrix columns become drag-and-drop sortable, salary edits inline in the header (HRP-57)
- AI Generate matrix brief requires a Grades multi-select; the backend pre-creates Spec×Grade pairs from the brief so a brand-new specialization can be configured end-to-end via AI (HRP-57, HRP-56)
- Position AI Generate prefills the spec's grades and locks the position's own grade as required so applying always lands a matrix the Position page can render (HRP-57, HRP-33)

### Changed
- `get_matrix_bulk` and matrix cascade order by the pair's `sort_index` instead of the DictionaryItem's, so drag-and-drop reorder is what the UI shows (HRP-57)

### Fixed
- Multi-select filters on the employees list (Divisions / Statuses / Positions / Specializations / Grades) keep their dropdown open between picks instead of closing after the first selection

## [1.7.2] - 2026-05-12

### Fixed
- PDP detail page no longer hides the admin transition graph when the admin is linked to the plan's employee — owner-only "submit for review" flow is now gated on `!canManage` so the e2e lifecycle walk (and any single-tenant demo account) works again (HRP-19 follow-up)
- Access-scope e2e seeds plans past Draft before asserting on the employee view, matching the HRP-19 rule that hides Draft plans from non-admin lists

## [1.7.1] - 2026-05-12

### Added
- Recruitment R4d: inline XLSX preview for completed reports — `GET /recruitment/reports/{id}/preview` returns sheets as JSON, frontend renders tabs + table on `/recruitment/reports/[id]` (SCR-82, FR-23)
- Recruitment R4d: shared system-screen components (401, 403, 404, 500, maintenance, browser-unsupported) plus Next.js `not-found` / `error` / `global-error` pages (SCR-M1..M7)
- Recruitment R4d: E2E sweep — `recruitment-onboarding`, `recruitment-share`, `recruitment-analytics` Playwright specs
- Recruitment R4c: 10 in-app + email notification types for recruitment events (§8.5, SCR-03)
- Recruitment R4c: onboarding wizard with welcome card and demo-data seed/cleanup (SCR-A1..A5)
- Recruitment R4c: tokenised report sharing with expiry, open tracking and audit (FR-22, SCR-84)
- Recruitment R4c: vacancy analytics tab, HR/HRD summary and comparison radar (SCR-16, SCR-28, SCR-56)
- Recruitment R4b: settings hub `/recruitment/settings` with scales / LLM providers (BYOK) / STT providers / branding / retention / roles sub-pages plus index card grid
- Recruitment R4b: AES-GCM crypto helper for tenant BYOK secrets — encrypted at rest, masked last-4 in API
- Recruitment R4b: tenant-wide audit log `/recruitment/audit-log` for mutating recruitment operations (FR-28)
- Recruitment R4b: GDPR endpoints `POST /recruitment/gdpr-export`, `POST /recruitment/gdpr-erase`, `GET /recruitment/gdpr-requests` plus per-candidate `/recruitment/candidates/[id]/gdpr` page (§9.2)
- Recruitment R4b: visibility-aware polling on interview detail (pauses while tab hidden) and active-scale lookup so analysis bars no longer hardcode the 5-point upper bound
- Recruitment R3b: Interview tab + Schedule dialog + chunked upload UI + Interview detail page with media player, transcript viewer (diarization, sync-scroll, inline-edit), 6-stage AI progress checklist, AI analysis sections (SCR-26, SCR-40..45, SCR-50..54)
- Recruitment R3b: candidate consent banner + send dialog, public consent magic-link page, admin Consent Templates settings page
- Recruitment R3b backend: `GET /interviews/{id}/media-url`, `GET /candidates/{id}/consent/latest`, `GET /candidate-vacancies/{cv_id}`
- Recruitment Canvas R2 leftovers: row virtualization (`@tanstack/react-virtual`), TSV paste, versions Sheet (SCR-77)
- Recruitment R4a: XLSX consolidated reports — `generate_report_task` Celery worker, up to 9 selectable section sheets, tenant-logo branding, presigned download (FR-23/24, SCR-80..83)
- Recruitment R4a: report templates CRUD with one-default-per-tenant + admin settings page `/recruitment/settings/report-templates` (SCR-81)
- Recruitment R4a: side-by-side candidate comparison `GET /vacancies/{id}/comparison?candidate_ids=…` with divergence and AI fallback; vacancy detail Compare button + `/recruitment/requisitions/{id}/compare` page (FR-25, SCR-55/56)
- Recruitment R4a: tenant-wide reports list `/recruitment/reports` with vacancy + status filters
- Recruitment R3b leftovers: Celery `task_failure` signal handler + beat job `cleanup_stuck_recruitment_tasks_task` (every 10 min, 15-min stale threshold) reset stuck `processing` rows in `interviews`, `consolidated_reports`, `resumes`
- Recruitment R3b leftovers: httpx mocks for Whisper + Deepgram providers covering 401 / 429 / timeout, plus cross-tenant access tests for interviews / reports / comparison
- Assessment lifecycle gains an `On Review` status between `In Progress` and `Done`: auto-entered when every participant has finished, manually reachable while at least one participant has answered, blocks `Done` until reviewers finalise the calibrated results (HRP-27)
- Entering `On Review` triggers preliminary result computation so the calibrator can adjust scores before the assessment is finalised (HRP-27)
- Assessment detail exposes `overall_percent` — mean of per-competence percents, half-up rounded — and renders it next to the `Results` heading on completed assessments (HRP-63)
- Company logo card supports drag-and-drop and a new `POST /api/settings/company-profile/logo/from-url` endpoint that pulls an image from a public URL (SSRF-guarded — loopback / private / link-local hosts are refused before any download happens) (HRP-53)
- New Position dialog gets inline "Add new specialization" / "Add new grade" actions so operators stay in the form: the grade flow also auto-creates the missing `GradeSpecialization` chain so the freshly-added grade is immediately selectable (HRP-54)

### Changed
- PDP status model simplified to Draft → Sent → In Progress → Review → Done with Returned and Cancelled side states; Awaiting approval / Approved / Expired removed (Expired is now a red-deadline UI cue, not a server status); legacy rows are remapped in-place by migration `pdp2a2b3c4d5e6` (HRP-16)

### Changed
- Recruitment R4d: M-5 split of `service.py` (3741 LOC → ~2060 LOC) into `interview_service`, `consent_service`, `report_service`; `service` keeps a module `__getattr__` shim so legacy callers keep resolving
- Recruitment R4d: rate-limited public token endpoints (consent, evaluator invite, share) per IP via `recruitment_public_limiter`

### Fixed
- Recruitment `complete_interview_upload` serializes concurrent completes via `SELECT FOR UPDATE`
- Recruitment `update_vacancy` / `close_vacancy` refresh the row in-context after commit so post-commit reads don't lazy-load
- Recruitment R4b.1: audit `list_events` user lookup is now tenant-scoped — stale `user_id` rows cannot leak email/name across tenants
- Recruitment R4b.1: global audit decorator covers every mutating recruitment service call (vacancies, candidates, interviews, consent, reports, stages, questions, assessments) — FR-28
- Recruitment R4b.1: token-based flows (`sign_consent`, `record_invite_assessment`) record audit rows in-body so anonymous signers and external evaluators show up in the tenant audit log — FR-28
- Recruitment R4b.1: `ENCRYPTION_KEY` required in SaaS and must decode to ≥32 bytes; onprem falls back to a sha256 of `jwt_secret` with a one-shot warning
- Recruitment R4b.1: settings page tolerates rotated/broken encryption keys via `key_status` instead of 500-ing the hub
- Recruitment R4b.1: `gdpr_erase` redacts `HumanAssessment.comment`, `AIAssessment.reasoning`/`citations`, `CandidateQuestion.{good,acceptable,poor}_answer`/`purpose`, and `Candidate.notes`
- Recruitment R4b.1: failed GDPR exports record `gdpr.export_failed` (with error) instead of masquerading as success in the audit timeline
- Recruitment R4b.1: branding endpoint resolves `logo_url` to a presigned URL via `tenant.logo_file_id`
- Recruitment R4b.1: partial unique index enforces at most one active scale per tenant (migration `r4b2c3d4e5f6`)
- Recruitment R4b.1: retention bootstrap survives concurrent first-touch races (IntegrityError → rollback + reselect)
- Recruitment R4b.1: audit list `total` now uses `SELECT count(*)` instead of materialising every row
- Recruitment R4b.1: audit-log page filters use a controlled `entity_type` select and stop double-fetching after Apply
- PDP material file links open inline again — S3 client signs presigned URLs with SigV4; the Add-material dialog requires Title + file/link and stays disabled while a file is uploading (HRP-14)
- PDP list rows show the assigned employee, render the row action menu without hover and hide it on terminal statuses and for the assigned employee, and highlight past-due deadlines in red (HRP-15)
- PDP detail page drops the redundant "terminal status — transitions are unavailable" notice; the action row is simply hidden on Done / Cancelled (HRP-29)
- PDP cannot move from Draft to Sent until every item carries at least one material — the Send button stays disabled with a tooltip and the server returns 409 on bypass (HRP-12)
- PDP item-passed toggle is owner-only and only available in Sent / In progress / Returned; admins viewing the plan see read-only checkboxes (HRP-13)
- PDP in terminal status (Done / Cancelled) is fully read-only — comment composer is hidden, `add_comment` and `mark_item_passed` return 409 (HRP-17)
- PDP list hides Draft plans from regular employees and managers; the detail page shows the assigned employee a single "submit for review" action that activates once every item is ticked (HRP-19)
- PDP auto-promotes from Sent to In progress the first time the assigned employee marks any item passed (HRP-20)
- PDP freezes the items+materials block for the assigned employee while the plan is under Review and rejects `mark_item_passed` with 409; the snapshot is cleared on Returned / Done / Cancelled (HRP-24)
- Deadline inputs for Assessment / Mass assessment / PDP / Mass exam reject dates in the past — date-only `<input>` with `min=today`, an in-form red-border + error hint, and a Pydantic `not_past_deadline` validator that turns server-side past-dated payloads into a 422 (HRP-23)
- Company logo upload sniffs magic bytes before writing to S3 so JPEGs that browsers mislabel as `application/octet-stream` keep the right `Content-Type` and render after upload (HRP-53)
- AI Generate matrix reference-files picker swaps the bare native input for a styled "Choose files" button plus an explicit `{n} files selected` counter, fixing the un-localized browser chrome on the Specialization / Position generation forms (HRP-55)
- Assessment per-competence percent and `avg_score` follow the role-mean algorithm from the spec: per-role indicator average → weighted level percent → mean across the competence's skill levels → mean across participating roles; neutral ("Don't know") answers and absent indicators are excluded (HRP-62)
- Existing `Done` assessments are recomputed in-place during the `asr1a1b2c3d4e5` migration so historical percentages line up with the new algorithm (HRP-62)
- Deleting an employee with timeline events no longer crashes with `NotNullViolationError` on `employee_events.employee_id` — the ORM relationship now cascades the delete instead of trying to null the FK

## [1.7.0] - 2026-05-10

### Added
- `PositionRead` exposes computed `salary_min` / `salary_max` / `salary_currency` (inherited from the `(specialization, grade)` pair in `GradeSpecialization`), `vacancy_count` (`headcount - employee_count`, clipped at 0), and `matrix_configured` (true iff the pair has at least one `GradeCompetenceLink`); single bulk lookup powers list responses (HRP-74)
- Position detail page renders an inheritance-aware matrix banner (✓ configured · N competences · salary, or ⚠ missing with a deep-link to Specialization), a salary row in Overview, a `●●●○○` headcount visual, and a vacancies pill alongside the headcount label (HRP-68)
- Position detail page exposes an inline Edit dialog with cascading Specialization → Grade selection (Grade options come from `/specializations/{id}/grades`, picking a new Spec resets the Grade), an in-dialog matrix-state banner for the chosen pair, a 600-character description-override counter, and an employee-impact warning when changing the profile on a position with assigned employees — driven by `employee_count > 0` and the spec/grade diff (HRP-68)
- `PositionEditDialog` now also drives Position creation. The Specialization/Grade cascade fires before Title is entered, Title auto-fills with `<Spec> <Grade>` while the operator hasn't customised it, and a salary-preview line shows the inherited range from `GradeSpecialization` so the operator can sanity-check the profile before saving. The list-page `/company/positions` switched to the same component, retiring the duplicated dialog (HRP-69)
- Specialization detail page exposes four inner tabs — Grades & matrix / Positions / Employees / AI history — with shareable URLs via the `?tab=` query-param. Employees tab calls a new `GET /api/specializations/{id}/employees` endpoint that aggregates everyone in any Position of the specialization, in the same row shape as `/positions/{id}/employees` so a single component renders both surfaces. AI-history tab ships as a placeholder; the live history feed lands with E5 (HRP-71) (HRP-70)
- `GET /api/positions` accepts three new filters — `lifecycle_status`, `has_vacancies` (true returns rows where `headcount > active employees`), and `matrix_unconfigured` (true returns rows whose Spec×Grade pair has no GradeCompetenceLink). The list page renders them as a status select plus two toggle pills, exposes a Matrix column with a ✓/⚠ icon, and a client-side group-by toggle (None / Division / Specialization) that inserts header rows above each bucket (HRP-72)
- `GET /api/competence-generation/sessions` returns a tenant-scoped slim history list with derived counts (grades / competences / indicators / accepted / rejected) and a compact summary brief; powers the AI-history tab (HRP-71)
- Specialization AI-history tab lazy-loads recent generation sessions, shows initiator / brief / counts / status, and exposes a «Repeat» button that spawns a child session (regenerate now accepts applied & cancelled parents) and redirects to the AI-generate page hydrated with the new session id (HRP-71)
- AI Review modal switches to a tri-state per-suggestion review (✓ Accept · ✎ Edit · ✕ Reject) with a pending-count banner, Accept-all / Reject-all bulk buttons and inline title rename; rename overrides ride alongside the selection map under `_edits` and apply at materialisation time so renamed groups, competences and indicators land in the tree with the operator's chosen title (HRP-71)
- AI Generate page replaces the plain «Status: running» block with a streaming-progress checklist (Thinking → Grades → Competences → Indicators 1/N → Matrix) driven by new `compgen.progress` WebSocket events; the worker emits a thinking event up-front, then replays parsed totals as discrete steps with a small per-indicator delay so the counter animates (HRP-71)

- Specialization detail page bundles the competence matrix and per-grade attributes into a single Builder under the Grades tab — operators no longer need to hop between the matrix sub-page and the attributes list. Drag-drop grade reorder, popover-style competence add and cascade-level preview land in phase 2 of HRP-67 (HRP-67)

### Fixed
- `DELETE /api/dictionaries/items/{id}` now returns 409 `in_use` with the offending row counts (`counts.positions`, `counts.chains`) when the operator tries to delete a Specialization or Grade that is still referenced by any Position or grade-chain. The previous behaviour relied on FK rules — Position would silently lose its profile (ondelete=SET NULL) and the matrix row would silently cascade out (ondelete=CASCADE on `GradeSpecialization`) (HRP-73)
- AI Generate matrix page (specialization + position) no longer fails with "Not authenticated" — the multipart upload now flows through the shared API client (HRP-56)
- `DELETE /api/employees/{id}` hard-deletes when the employee has no Assessments / PDPs / Exams / Talent candidates and is not a division manager / deputy, and returns 409 `has_connections` with the employee's full name otherwise; the old behaviour soft-flipped status to `terminated` while leaving the row visible (HRP-65)
- `manages_division_q` in `delete_employee` now scopes by `tenant_id`, matching the symmetric check in `downgrade_employee_role`
- `/specializations/{id}/employees` and `/positions/{id}/employees` now resolve avatars in a single bulk query and explicitly preload spec/grade/division to avoid per-row N+1
- `GET /api/competence-generation/sessions/{id}` is tenant-wide (mirroring the list endpoint), so the AI-history tab can open any admin's session read-only; mutating endpoints (refine / regenerate / apply / cancel / patch_selection) still require ownership
- `PositionEditDialog` grades fetch hardens the cascading-spec race with a latest-spec ref, so an A→B→A switch never commits stale grades
- `AIGenerateProgress` surfaces a "live progress paused" hint when the WebSocket disconnects, so the operator knows the parent page is falling back to polling
- `AIReviewModal` warns before discarding unsaved title edits (selection clicks are easy to redo, but typed-out renames aren't)

## [1.6.3] - 2026-05-08

### Added
- `PATCH /api/assessment-groups/{id}` renames a Mass Assessment and cascades the new title to every child; assessment-groups page exposes inline-edit pencil and the per-child pencil is hidden when an assessment has a parent group (HRP-35)
- Tooltip primitive (`@/components/ui/tooltip`) wired into the dashboard layout via `TooltipProvider` for consistent hover hints across pages
- Assessment detail exposes a "Preview questions" affordance that renders the same scale + indicator set reviewers will see, honouring the per-competence skill level (HRP-42)
- `GET /api/competences/{id}?skill_level_id=...` filters indicators and materials to the chosen level and every level below it (HRP-43)
- Competence detail page exposes a status-aware "Generate indicators (AI)" button that opens the existing competence-indicators session flow with the competence as target (HRP-47)

### Fixed
- Indicator and material edit dialogs on the competence detail page, the «Materials by context» and material-override picker on the same page, and the recommended-grade filter on the assessment-group detail page now render the selected entity's title (or `Base`) instead of the raw UUID by passing a Base UI `Select.Value` render function (HRP-48)
- `POST /api/competence-generation/sessions` (and refine / regenerate / specialization-matrix variants) no longer return `500 MissingGreenlet`: after the second commit that persists `celery_task_id`, the session row is `await db.refresh()`-ed before `_to_read` so the response serialiser does not trigger lazy-loading on an expired ORM instance
- `add_participant` integration and unit tests now use a separate peer employee instead of the assessee — the assessee is auto-attached as `self` on assessment create, so the old fixtures tripped HRP-18's duplicate-participant guard with 409
- Single + Mass Assessment hide the Evaluation criteria and Rating scale edit buttons once the assessment leaves draft, and the Evaluation criteria affordance is renamed Edit → Change for parity with the Rating scale block (HRP-36)
- Adding a participant to an assessment now rejects the same human in any role with 409, and the Add Participant picker hides everyone already in the assessment (HRP-18)
- `POST /api/assessments` rejects a new assessment with 409 once the assessee already has 5 active ones, so the assessee's queue cannot be drowned (HRP-37)
- `GET /api/assessments/{id}` returns 404 when a restricted caller is neither in the assessee's scope nor a participant, plugging the URL-fishing leak (HRP-40)
- Participant questionnaire only shows indicators of the picked skill level and lower levels for Individual-competences criteria (HRP-43)
- Celery worker now registers `app.modules.ai_competence_generation.tasks.run_generation_session`; AI competence generation no longer fails with `Received unregistered task of type` on the worker
- Cancelling an AI competence generation session now revokes the queued/running Celery task and the worker skips billing when status flips to `cancelled` mid-flight (HRP-46)
- Competence tree group/competence dropdown menus no longer wrap labels onto multiple lines, and the competence edit dialog widens to fit the indicators block (HRP-44)
- Every AI-generation entry point on `/competences` (group menu, competence menu, indicators editor) now shows a tooltip explaining the active-session lock instead of relying on a native `title` that browsers suppress on disabled buttons (HRP-45)
- Competence tree legend reads `competences: N` next to group titles, and the published / not-published / origin / in-use icons each carry an explanatory tooltip (HRP-41)
- Rating scale options no longer leak empty `()` for the neutral answer; admin view keeps weights, participant view drops them, and `is_neutral` always renders `(not counted)` (HRP-30)
- Bulk status change with "Apply to all → Cancelled" leaves terminal `done` children alone and reports them under `skipped_reasons.terminal` instead of silently overwriting completed assessments (HRP-26)
- Evaluation criteria sheet: Specialization picker lists every active dictionary item instead of only those wired into a grade chain; Selection trigger renders the picked level/specialization/grade title instead of a UUID; assessment summary shows the chosen skill level next to each Individual competence (HRP-39)

## [1.6.2] - 2026-05-07

### Added
- AI Generate launcher on position detail page: reuses specialization-matrix flow with `position_id`, applied competences land in a single group named after the position (HRP-33)

### Fixed
- Mass Assessment page now exposes a Rating scale block with picker; group-level scale is propagated to every draft child via `PUT /api/assessment-groups/{id}/scale`, locked once any child has left draft (HRP-34)
- WebSocket endpoint no longer floods `asyncio` ERROR logs with `keepalive ping timeout` on ungraceful client disconnects: protocol-level keepalive disabled, application-level heartbeat is the single source of truth

## [1.6.1] - 2026-05-07

### Added
- Position detail page (`/company/positions/{id}`) with the resolved competence matrix and the assigned employees rendered through the unified Name / Position (Specialization · Grade) / Division / Status / Hire Date columns, plus `GET /api/positions/{id}/competences` (HRP-32)

### Fixed
- `/company/profile` and `/company/specializations` no longer redirect to /dashboard on the SaaS app domain (HRP-31)
- Assessment detail keeps the rating scale visible after Sent by embedding the snapshotted scale in the detail response (HRP-11)

## [1.6.0] - 2026-05-06

### Added
- `PATCH /api/assessments/{id}` for inline edit of title and deadline (admin/manager only, blocked on terminal-status assessments) and assessment detail page wires inline-edit affordances; bulk status-change result returns `skipped_reasons` broken down by category (terminal / same_or_lower_status / already_cancelled / missing_criteria_or_scale) and the assessments list renders the per-reason breakdown
- Employees list: redesigned columns (Name+Email, Specialization·Grade), multi-select filters for Divisions/Statuses/Positions/Specializations/Grades, and `GET /api/divisions/scope` for manager-scoped division pickers
- RBAC: division manager assignment auto-upgrades user role; removal prompts confirm to downgrade; invitation role limited to inviter's level
- Company profile UI page at /company/profile (logo, description, industry, size, website) — admin-only edit
- Invitations: required Name field, Division column, table column reordering
- Invitations: inline edit of pending invitations + email change with re-send (admin only)
- Invitations: optimistic inline edit, tenant-scoped division/position validation, rate-limited email rotation with audit log
- Added `/personal-brand` landing page with Hoffman fluency quiz and `personal_brand` waitlist segment
- Phase CR1 foundation: `competences.is_published`, `competence_groups.can_deactivate`, per-tenant custom skill levels (`skill_levels.tenant_id` + `i18n_key`), `materials.comment` / `materials.material_type`, `competence_tree_audit_log` table
- Phase CR2 service layer: usage checks (matrix / employee card / assessment / IDP / talent market), cascade activate/deactivate with link guards, cycle-safe move for groups/competences/indicators/materials, publish/unpublish workflow, alphabetic tree ordering, `competences_count` rollup and `levels_completion` enrichment, audit log on every mutation
- Phase CR3 REST endpoints: `/competences|competence-groups|indicators|materials/{id}/usage`, `/publish|unpublish`, `/activate|deactivate`, `/move`, full `SkillLevel` CRUD (`POST/PATCH/DELETE /skill-levels`), `/competences/{id}/audit-log`
- Phase CR10b tenant AI settings: `/api/admin/ai-settings` (`GET`, `PATCH`, `POST /reset`, `GET /presets`) with content language (`en`), effort tiers (`fast`/`balanced`/`thorough`/`custom`), custom `llm_model` override, sampling temperature, retry budget, and company context
- Phase CR11 backend: AI competence generation sessions — `/api/competence-generation/sessions` with three scopes (`whole_base`/`group`/`competence_indicators`), partial unique index for one active session per user, frozen base snapshot, cascading selection state, refine/regenerate chains, and idempotent `POST /apply` that materialises checked nodes into the competence tree
- Phase CR12 realtime channel: `WS /api/ws?token=…` pushes `notification.new` (in-app notifications) and `compgen.session.updated` (running/ready/error) to the current user, with 30s ping/pong heartbeat and Redis pub/sub fan-out so events from Celery workers reach connected web replicas
- Phase CR13 frontend AI generation UI: status-button on `/competences`, confirmation dialog with «used data» drop-down, generation drawer with cascade-checkbox tree, refinement panel (general + add/change/exclude), apply dialog with publish-confirmation, preflight modal for cross-user sessions, group-level fill/extend and competence-level «generate indicators» triggers; `WebSocketProvider` with exp-backoff reconnect powers live status updates with a 5s polling fallback; backend `GET /api/competence-generation/sessions/active-others` powers the preflight modal
- `llm_client.generate_json` accepts an optional Pydantic `schema=` argument and validates the model response against it
- Phase CR15 Celery → WebSocket unification: every background task broadcasts `task.updated` (`STARTED`/`SUCCESS`/`FAILURE`) on the per-user WS channel via `task_prerun`/`task_postrun`/`task_failure` signals; `useTaskStatus(taskId)` hook and `postAndWait` switch to WS-first with polling fallback only when the socket is closed
- `useCostConfirmation`/`useCostConfirmationDialog` hook + reusable `CostConfirmDialog` component: AI actions whose credit cost meets the workspace warning threshold now require explicit confirmation before they run
- AI position generation on `/company/positions` shows a confirmation dialog with the credit cost before starting
- AI competence-generation drawer "Cancel generation" button switches to "Cancelling…" while the request is in flight; backend broadcasts a `cancelled` event so the status button on `/competences` returns to idle without waiting for the next polling tick
- Generation context panel inside the AI generation confirm dialog: filtered specializations/divisions chips, expanded company description preview, and deep-links into the dictionary / company profile / AI settings pages so admins can fix missing context before starting
- `GET /health/celery` (and alias `GET /api/health/celery`) returns `{available, last_seen?}` based on the Redis heartbeat key — used by the AI generation drawer to show a "Background worker offline" warning when a session is queued and Celery isn't responding
- Inline `IndicatorsEditor` on the competence edit dialog: lists existing indicators grouped by skill level, supports manual add / edit / delete via a side sheet, deep-links into AI generation, and exposes a "what are indicators?" help tooltip
- i18n cleanup: backend test docstrings, fixture data, and answer-scale level titles translated to English so the codebase outside `docs/plans|go-to-market|ops|legal|memory` is fully Cyrillic-free
- Phase CR10c AI Settings page (`/settings/ai`): admin UI for effort presets, model whitelist (Provider + Model select), temperature, retry budget, content language, company context, and a sticky save bar with a credit-spend preview; deep-link from the generation context tooltip
- `GET /api/admin/ai-settings/models` returns the platform whitelist with `credit_multiplier` per model; `AISettingsRead` exposes `effective_credit_multiplier`
- Phase POS0 quick wins on `/company/positions`: Division column in the list and clickable headcount cell that opens a drill-down dialog with assigned employees (`GET /api/positions/{id}/employees`)
- Phase POS1 schema groundwork: `positions.lifecycle_status` (active/on_hold/frozen/closed) backfilled from `is_active`; `grade_specializations` gains `requirements`, salary range and currency with a CHECK on min ≤ max; new `material_specialization_overrides` table (per-(material × specialization) add/hide) for the upcoming two-level material model
- Phase POS2 Specialization API: `GET /api/specializations`, `/{id}`, `/{id}/grades`, `/{id}/positions`, `GET/PUT /{id}/matrix?grade_id=` — read endpoints with grade/position/headcount roll-ups, and a bulk matrix upsert that validates competences and skill levels against the tenant scope
- Phase POS3 Specializations UI: `/company/specializations` list with roll-ups and `/company/specializations/{id}` detail page with Grades (inline description/requirements/salary editor) and Positions (grouped by division with assigned/plan + lifecycle status); shared Company-section tabs (Overview / Positions / Specializations)
- Phase POS4 competence matrix editor: `/company/specializations/{id}/matrix?grade_id=...` with a `Competence × Grade` table, dirty-cell highlighting, indicator tooltip (union of indicators up to the selected level), and an unsaved-changes bar; client-side cascade promotes lower-grade levels up the ladder and demotes higher grades down to the new ceiling
- `GET/PUT /api/specializations/{id}/matrix-bulk` and `GET /api/competences/{id}/indicators-by-level`: bulk matrix read/write across all grades of a spec with server-side cascade normalization (`level(N+1) ≥ level(N)`) and a level-grouped indicator listing for the matrix tooltip
- Phase POS5 AI Generate matrix on `/company/specializations/{id}/ai-generate`: multi-upload (`.pdf .docx .xlsx .xls .rtf .txt`, 10 MB/file, 50 000 chars combined via `app.modules.ai.file_parsing`), new `specialization_matrix` AI session scope reusing the CR11 lifecycle (refine/regenerate, bulk selection sync, idempotent apply with `created_grade_links`), and `AISettingsBanner` with a deep-link to `/settings/ai`
- Phase POS6 position lifecycle, occupancy and alerts: lifecycle status badge column with on-row status menu, closed positions read-only, `Filled / Plan` drill-down using a unified `EmployeeListRow` with a single highest-priority alert per person, `/admin/employees/unassigned` admin view, and a matrix-not-configured banner with a deep-link into the Spec×Grade matrix
- New position endpoints: `GET /api/positions/{id}/occupancy`, `GET /api/positions/{id}/matrix-status`, `POST /api/positions/{id}/status`, `GET /api/positions/{id}/employees?with_alerts=true`, `GET /api/employees?unassigned_only=true&with_alerts=true`
- Phase POS7 material specialization overrides: `GET /api/competences/{id}/materials?specialization_id=…` and `GET/POST/DELETE /api/competences/{id}/material-overrides` deliver per-(material × specialization) hide / add overrides; PDP creation seeds `PDPItemMaterial` rows from `get_materials_for_specialization`, and the competence detail page exposes a «Materials by context» panel with hide / add / restore default actions
- Drag-and-drop in the competence tree for moving groups and competences between branches
- Competence detail page (`/competences/{id}`) with publish/unpublish/hide controls and level-scoped indicator and material editors with drag-and-drop reordering
- Two-step wizard for creating competences (title/description/type, then group)
- Activate-by-default checkbox in the competence group dialog
- `useCompetenceTree()` hook with a shared, race-safe cache so every consumer (employees, assessments, criteria sheet, competence tree sheet) reflects the same payload

### Changed
- AI competence-generation confirm dialog displays the credit cost up-front and adapts the start button to "Confirm & start (N credits)" when the cost meets the warning threshold
- AI generation tasks (competences, indicators, PDP goals, positions) now read tenant-level AI settings: language directive and company context are merged into every system prompt, model and temperature default to the tenant's preset, and the retry budget for malformed JSON honors `max_retries`
- Development plan (PDP) detail page exposes editable items and materials (rename, reorder, delete), a Format select on the material modal, and a custom file picker that no longer leaks browser-localized placeholders
- PDP detail surfaces the reviewer (explicit `reviewer_id` or, when absent, the employee's division manager) and renders comment timestamps without seconds
- API error toasts format FastAPI 422 validation payloads instead of rendering `[object Object]`
- PDP status action buttons read as English verbs (send / cancel / start / …) so terminal actions match the rest of the dashboard

- PDP `draft → sent` transition emails the assigned employee with deadline and a link to the plan
- New PDP item / material edit endpoints: `PATCH/DELETE /api/pdp/{id}/items/{item_id}`, `POST /api/pdp/{id}/items/reorder`, `PATCH/DELETE /api/pdp/{id}/items/{item_id}/materials/{material_id}`

### Fixed
- Item checkboxes on draft PDPs are no longer interactive — completion can only be marked once the plan is sent
- PDP `draft → sent` email now includes the plan title in the subject and heading instead of the generic "Development plan assigned" placeholder
- AI competence generation tooltip: "Edit company profile" link pointed to user settings; now opens /company/profile, and company description fetch uses the correct /settings/company-profile endpoint
- `change_status` enforces `draft → sent` prerequisites: assessment must have both `criteria_type` and `scale_id` set, otherwise returns a precondition error
- Centralised `make_async_engine` / `make_sync_engine` in `app/database.py` apply `idle_in_transaction_session_timeout=5min` to every engine (FastAPI, Celery sync/AI tasks, Alembic) so orphaned `idle in transaction` backends can no longer hold locks indefinitely; Alembic also gets `lock_timeout=10s` so contended DDL fails fast instead of starving readers
- `snapshot_scale_for_assessment` now copies `AnswerScaleLevel.system_code` along with `system_title`. Origin scale levels seeded by the CR12 i18n migration carry `system_code` with `system_title=NULL`; the previous snapshot only copied `system_title`, so the cloned row had both columns NULL and broke the `ck_scale_level_code_or_title` check on every `draft → sent` transition

### Security
- Terminated/inactive employees are blocked from authenticating; status changes emit a user email; `PUT /auth/me` enforces a strict field allowlist
- RBAC: managers can only edit employees in their division scope; employees cannot edit profiles via /employees endpoints
- `compute_employee_alerts_bulk` accepts `tenant_id` and every SQL filter enforces it explicitly; off-tenant employees in a mixed-tenant cohort are short-circuited before the priority scan so a manager cannot leak rows from another tenant

## [1.5.0] - 2026-04-30

### Added
- Custom rating scales: HR creates, edits, and soft-deletes answer scales with 2–10 scoring options, an optional "I don't know" (neutral) option, and 0–100 percent levels (`POST/GET/PUT/DELETE /api/answer-scales[/{id}]`)
- Rating scale picker on the assessment detail page: empty Rating scale block ships "Add scale" / "Change" actions, the picker modal exposes a per-row "…" menu (Preview / Edit / Delete) plus a "Create scale" entry-point, drag-and-drop ordering of options via `@dnd-kit`, inline level validation, and save/delete/cancel confirmation dialogs; persisted via `PUT /api/assessments/{id}/scale`
- Snapshot-on-launch: when an assessment leaves `draft`, its scale is frozen into a snapshot copy so subsequent edits don't bleed into running assessments
- Evaluation criteria selection sheet on single and mass assessments — three modes (current positions / target position / hand-picked competences), competence tree picker with cascading checkboxes and search, per-competence skill-level editor; mass-criteria propagate to every active child assessment in the group
- Assessment results expose `percent` and resolved `level` per competence on transition to `done` (neutral answers excluded); detail page Results table renders Percent / Level columns with description tooltip, legacy rows show empty cells
- Passing score per grade in the specialization dictionary (default 75%) and per assessment / mass-assessment criteria; on `done`, an automatic grade recommendation (% match per grade with hierarchy + "not confirmed" fallback) is cached on the assessment and exposed via `GET /api/assessments/{id}.recommendation`
- PDP plans now carry a title with inline edit, auto-generate items from grade-specialization competences, and surface employee + formatted deadline in the detail view; specialization/grade can be changed after creation, auto-items recomputed while passed and custom items are preserved
- Load-test infrastructure under `backend/tests/load/` (pytest `load` marker, internal pool-stats endpoint) covering QueuePool capacity and disconnect-leak scenarios

### Changed
- PDP detail page status flow aligned with backend lifecycle (sent / in_progress / review / on_approval / approved / done / returned / cancelled / expired)
- `AssessmentRead.employee_name` now required; `GradeSpecializationRead.grade_title` and `AssessmentCompetenceRead.competence_title` are eager-joined so the UI no longer falls back to UUID slices
- Evaluation dialog reads the assessment's assigned scale instead of the first scale in the workspace list
- AI generation endpoints (`POST /api/ai/generate-{positions,competences,indicators}`, `POST /api/ai/suggest-pdp`) default to async (202 + `task_id`); legacy callers pass `?sync=true`
- Email sends in waitlist, notifications, and external-reviewer invites go through `enqueue_email` (Celery + inline fallback) instead of blocking the request
- Positions and competences AI wizards switched to `api.postAndWait` — POST 202, poll `GET /api/tasks/{id}` until SUCCESS / FAILURE

### Fixed
- AsyncPG pool sized up (`pool_size=10`, `max_overflow=20`, `pool_timeout=10`, `pool_recycle=1800`) and uvicorn access log re-enabled — addresses recurring `QueuePool limit reached` 500s under load
- AsyncPG engine: `pool_pre_ping=True` + server-side TCP keepalives (60/10/6) — guard against half-dead connections
- `add_participant` now 404s instead of crashing on commit when an Employee references a non-existent user; `assessment_participants.user_id` switched to `ON DELETE CASCADE` and orphaned rows cleaned up by migration `b8c4d2f1a9e3`
- Division edit modal exposes the **Manager** field; both selects submit `Employee.id` instead of `User.id`, fixing `400 Invalid manager` from `PUT /api/divisions/{id}`
- Access-scope leak on `/api/employees`, `/api/assessments`, `/api/pdp`, `/api/exams`, `/api/talent-market/search` — list endpoints filter by role (admin/hr → full tenant, manager → own subtree, employee → own record); `?managed=true` on `/api/employees` removed
- Talent Market list visibility: a regular employee now sees unpublished cards where they are a candidate, not only published ones
- `POST /api/ai/generate-positions` no longer 500s on `uq_position_tenant_title` when regenerating drafts; concurrent calls per tenant are serialized
- Bulk status change on the development list page sends the correct `status_code` payload
- `status.hrpulsar.com` no longer stuck on an empty placeholder — upstream Statuspage probes tolerate non-JSON responses
- Cross-domain redirects (marketing ↔ app split) use 307 + `Cache-Control: no-store` instead of 308/301, preventing browsers from caching stale routing rules
- `development/[id]` grade-change handler guards setState with a mounted ref to avoid post-unmount writes
- Removed duplicate `PDPUpdate` interface in frontend types

## [1.4.2] - 2026-04-28

## [1.4.1] - 2026-04-28

### Added
- Assessment detail page now shows two new cards — "Evaluation criteria" (with an "Add competences" button that opens the existing selector dialog) and "Rating scale" (read-only display of the assigned scale and its options). Until now the dialog existed but had no trigger and the scale block was missing entirely
- "Evaluatee" badge on the participants list so the assessed employee is visually distinguishable from peer/manager reviewers
- `frontend/src/lib/marketing-app-url.ts` — resolves auth links to the absolute app domain when `NEXT_PUBLIC_APP_DOMAIN` is set, so cross-domain `/login` and `/register` use plain `<a>` tags and skip Next.js RSC prefetch (no more cross-origin CORS errors on hover)
- E2E test `landing.spec.ts` adapted for the random-pick hero tagline

### Changed
- Creating any assessment (Single or Mass, type self/180/360) now auto-adds the assessed employee as a self-participant. Previously the participants list could be empty
- For type=180 / type=360 the existing GF6 division-manager auto-assignment still applies; for type=self it is now skipped (an employee assessing themselves should not auto-include their manager)
- Detail page hides the "Add participant" button for type=self and type=180 (those flows are fully auto-populated) and the role dropdown no longer offers "self" (already auto-assigned)
- Promtail now lowercases the log `level` field before labelling so Grafana renders log-level colours correctly (was case-sensitive)

### Fixed
- Assessment detail page: "Add participant", "Calibrate" and per-row "Evaluate" buttons are now hidden when the assessment is in a terminal status (`done`/`cancelled`). Backend `add_participant`, `add_competences`, `calibrate` and `change_status` reject mutations on terminal assessments
- Assessments list: the row-level action menu ("Change status") is hidden for assessments in `done`/`cancelled`, matching the no-next-status state already enforced on the detail page
- Mass assessment bulk cancel now cancels every non-cancelled child assessment (including those already in `done`); the success toast reports `Updated N of M assessments` instead of just the changed count, so administrators see how many were no-ops
- Assessment detail page now hides admin-only controls (status transition buttons, "Add participant", "Add competences", "Calibrate") from regular employees, who previously saw the buttons and got an "Insufficient permissions" backend error on click
- A "Take this assessment" CTA appears at the top of the detail page for the current user's pending participant entries, so employees can fill in their evaluation without needing the per-row Evaluate button. Per-row Evaluate is now scoped to rows the current user owns
- `POST /assessments/{id}/answers` now rejects (HTTP 403) attempts to submit answers for participant entries that don't belong to the requesting user — previously any authenticated user in the tenant could write into anyone's participant row. The same endpoint also rejects (HTTP 400) submissions on assessments in terminal status, and (HTTP 400) submissions where the indicator does not belong to any competence attached to the assessment
- For type=180, the "Add participant" button is shown again when the manager auto-assignment couldn't fire (employee has no division manager), so administrators can manually complete the participant set. Previously the button was always hidden for 180, leaving the assessment stuck without a manager reviewer
- Employee profile → Assessments tab: rows now link to `/assessments/{id}`, giving employees a way to navigate from their profile to take an assessment
- `deploy/deploy.sh` now pulls and force-recreates `celery-worker` and `celery-beat` on every release. Previously only `backend` and `frontend` were pulled, and workers were `up -d`-ed without `--force-recreate`, so beat could keep running an old image. That's how the `write_celery_heartbeat` task (added in v1.4.0) never started in production, leaving `status:celery:heartbeat` missing in Redis and `status.hrpulsar.com` stuck on `jobs = major_outage`
- Sign-in / sign-up links in marketing header, final CTA, and the cloud pricing page no longer trigger CORS-blocked RSC prefetches across `hrpulsar.com → app.hrpulsar.com`

## [1.4.0] - 2026-04-27

### Added
- Brand kit v3 — chronograph mark with teal→indigo gradient + cyan leading-pulse; Geist Mono `HR` + Geist Bold `Pulsar` wordmark. Adds horizontal/stacked lockups (white / black / color / color-light), web manifest, OG card (1200×630), Android PWA icons, SVG favicon
- `frontend/public/brand/logo-horizontal-color-light.png` — transparent-background PNG of the color horizontal lockup, generated for email clients that don't render SVG

### Changed
- Dashboard redesign: KPI strip with sparklines, headcount-by-department chart, active assessment cycle progress, "Needs your attention" inbox, and "This week" calendar strip
- Sidebar restructured into Workspace / Talent / Discover / Admin sections; tenant switcher moved from header to sidebar; width tightened to 232px
- Header: breadcrumbs auto-generated from path, ⌘K hint pill in search input, height reduced to 52px
- Employee detail page: identity card with KPI strip (Status / Tenure / Assessments / Goals progress / Last assessment) replacing the basic profile card
- Auth pages, marketing header/footer and sidebar render the horizontal lockup (mark + wordmark) — sidebar swaps the variant per theme
- Dark theme tokens recoloured to brand blue (`--accent`, `--ring`, `--chart-*`, `--sidebar-accent`, `--sidebar-primary`) so KPI bars, active nav items, focus rings and charts are visible (previous shadcn defaults were greyscale)
- `<head>` metadata advertises the SVG favicon (`/icon.svg`) alongside ICO fallback, links the web manifest, exposes `og:image` / `twitter:image`, and sets `viewport.themeColor` to `#060a14`
- Email templates now render the real horizontal HRPulsar logo (transparent PNG) in the header instead of the placeholder `H` square plus wordmark
- `status/web/public/` icons (`apple-touch-icon.png`, `icon.svg`) synced with `frontend/public/` so the public status page matches the main app's brand

### Fixed
- `/site.webmanifest` was being intercepted by the auth proxy and redirected to `/login`, causing a JSON parse error in the browser console — proxy matcher now excludes the `.webmanifest` extension

### Removed
- `dashboard-card-employees`, `dashboard-card-divisions`, `dashboard-card-active`, `dashboard-card-assessments` test ids — replaced by `dashboard-kpi-*`
- `header-btn-tenant-switcher` — tenant switcher now lives in the sidebar (`sidebar-tenant`)
- Legacy `logo-stars.jpg` brand asset

## [1.3.0] - 2026-04-25

### Added
- Position entity — structured job positions with optional grade, specialization, and division links
- AI-powered position generation with draft/approve/reject workflow
- Position management page at Company → Positions with CRUD, search, and filtering
- In-site documentation rendering — markdown docs displayed as styled pages on the landing site
- Cloud & Enterprise features page for potential SaaS customers

### Changed
- Employee and invitation forms now use position reference instead of free-text field
- `GET /employees/positions` endpoint removed — replaced by `GET /positions`
- Documentation architecture: core features.md contains only community features, enterprise features separated into dedicated files
- Added `OPENAI_API_KEY` and `GEMINI_API_KEY` to environment variables documentation
- Docs index page: replaced changelog card with Cloud & Enterprise card, reordered by user journey

## [1.2.10] - 2026-04-24

### Fixed
- `data-testid` on Select components moved to `SelectTrigger` for Playwright E2E visibility

## [1.2.9] - 2026-04-24

### Fixed
- Employee creation modal: replaced raw UUID text input with user select dropdown showing available users with origin badge (invited / self-registered)
- Added `GET /employees/available-users` endpoint for employee creation form
- AI service unit tests failing due to billing wrapper activation — force `DEPLOYMENT_MODE=onprem` in test conftest

## [1.2.8] - 2026-04-24

### Fixed
- Celery worker crash loop in production — removed unsupported `--quiet` flag (not valid in Celery 5.x)

## [1.2.7] - 2026-04-23

## [1.2.6] - 2026-04-23

### Added
- E2E test infrastructure — Playwright tests with `data-testid` attributes across all pages, test helpers, and CI pipeline
- `/auth/dev/auto-register` endpoint for E2E test automation (requires `E2E_MODE=true`)

### Changed
- Company page data loading uses `Promise.allSettled` for partial failure resilience

### Fixed
- Community `useEENavItems` missing return type broke TypeScript narrowing in sidebar
- Auth endpoint 401 responses (e.g. wrong password) triggering infinite token refresh loop
- Proxy middleware blocking `/verify-email` and `/accept-invite` for unauthenticated users
- `dev_auto_register` silently ignoring missing `platform_admin` role — now raises error
- Development plan card clicks intercepted by dropdown menu actions

## [1.2.5] - 2026-04-23

### Added
- `deployment_mode` field in user profile API response (allows frontend to detect SaaS vs on-prem)

### Changed
- Assessment participant API accepts `employee_id` instead of `user_id` — resolves to user internally; frontend shows employee dropdown instead of UUID text input
- Human-readable labels in mass assessment division/specialization select filters

## [1.2.4] - 2026-04-22

### Fixed
- Missing `resend` package in compiled requirements.txt

## [1.2.3] - 2026-04-22

## [1.2.2] - 2026-04-22

### Fixed
- `/metrics` endpoint filtered from access logs (Alloy scrape noise — 240 entries/hour)

## [1.2.1] - 2026-04-22

### Fixed
- Multi-line tracebacks split into separate log entries in Grafana (uvicorn loggers now use JSON formatter)
- Frontend app version resolved via `process.env` instead of `nextConfig.env`

## [1.2.0] - 2026-04-22

### Added
- Mass assessment creation — create assessments for multiple employees at once with grouped list view
- App version display across all pages

### Fixed
- Human-readable labels in Select triggers instead of UUIDs
- Duplicate index creation in `assessment_groups` migration (caused `DuplicateTableError` on prod)

