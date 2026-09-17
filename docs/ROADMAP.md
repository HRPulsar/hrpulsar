# Roadmap

What we're building, what we just shipped, and what's next.

Tags signal where each item lives:

- **[Both]** — available in Community Edition (self-host) and the cloud
- **[Cloud]** — only on hrpulsar.com (managed cloud)
- **[Self-host]** — only relevant to Community Edition deployments

Updated continuously. Plans shift as we learn — treat the upcoming sections as direction, not commitments.

---

## Up next (next two quarters)

### AI workforce screen [Both]

The agent registry behind the Coverage verdicts already runs as an API — the built-in packs, the agents your company runs, their assignments to employees and the workflows they take part in. A screen that manages all of it from inside the app is next.

### Power-user features [Both]

- Audit log — who changed what, when
- Built-in calendar for assessments, dev plan check-ins, and interviews
- PDF export for assessments, dev plans, and employee profiles
- Keyboard shortcuts beyond the existing ⌘K palette

### Integrations [Both]

- Outbound webhooks
- Slack and Telegram notifications
- HRIS connectors
- **[Cloud]** SSO / SAML on managed plans
- **[Cloud]** Custom domains on managed plans

### AI Assistant [Both]

In-app chat that answers questions about your org and a proactive advisor that surfaces stale plans, calibration gaps, and attrition risks.

### Open-source adoption [Self-host]

Plugin API, Helm chart, and official SDKs for embedding HRPulsar into your own stack.

---

## Recently shipped

Highlights — full per-version list lives in the [changelog](/changelog).

### v2.0 — Coverage: who covers each step of a process

- Describe a process or a project in plain language; the AI drafts the ordered steps and tags each one with the capabilities it needs, from a fixed catalog of seventeen **[Both]**
- Per step, a verdict on who covers it: an agent type from the built-in packs or an agent you registered, a person on the team by their assessments or grade, or nobody yet — with the automation mode and a quality rating next to it
- Hours a year and what they cost per process, from the hours you correct and one hourly rate you set; the share that moves to an agent, to review, or stays with people
- A gap opens a draft vacancy in Recruitment; a step an agent can take gets a `SKILL.md` you download and run in your own tools
- Process access: an owner, visibility per role, position or person, and a history of changes
- An AI workforce registry as an API (`/api/ai-workforce/*`): built-in agent packs, the agents your company actually runs, their assignments to employees with a supervision level and an accountable owner, multi-agent workflows and an audit feed — a screen for it is next **[Both]**
- Imported employees receive an email with a link to set their own password, resendable from the employee card, instead of a shared one **[Both]**
- One password reset link covers every organization an email address has an account in **[Both]**
- **[Cloud]** Branded workspaces for a single organization on a shared deployment: its own logo, a theme preset, an accent color and no version badge, set by our team on managed plans

### v1.16–v1.23 — Multi-language interface

- Full English and German UI with a runtime language switch, covering the app, emails and the reference catalogs **[Both]**
- English stays the base and the hard fallback; a new language lands as one JSON file per side via PR, with parity checks in CI **[Both]**
- Interface language, AI content language and region are three independent settings **[Both]**

### v1.15 — Self-hosted, ready out of the box

- White-label branding for self-hosted installs: logo, installation name, accent color, and favicon via env — applied to the web UI and outgoing emails **[Self-host]**
- Self-serve registration with verification fallbacks when no email provider is configured **[Self-host]**
- Docker Compose stack that works on first boot: bundled reverse proxy, storage auto-setup, background workers **[Self-host]**
- Contribution guidelines and a vulnerability disclosure policy
- **[Cloud]** Two-domain setup: hrpulsar.com for the site, app.hrpulsar.com for the product

### v1.13–v1.14 — Recruiting completed, exams in-app

- AI Insights on candidates: resume-only or full analysis, bulk runs, history, and clickable resume citations
- Vacancy assessment matrix comparing manager scores against AI match, with divergence tracking, audit trail, and revert
- Interview rounds on the candidate card: scheduling, consent links, media upload, automatic transcription and analysis
- Public evaluation page for invited external evaluators — full competence sheet with autosave, no account required
- Employees take exams in-app: autosave and resume, scored results with the answer key, configurable pass marks
- **[Cloud]** Live demo sandbox with a fully populated example company
- Security hardening: per-IP auth rate limiting and token revocation on password change

### v1.9–v1.12 — Recruiting build-out

- Vacancy management: structured create flow seeded from your competence library, single-page vacancy view, AI profile generation with review-before-save
- Candidate management: bulk resume upload with AI parsing (PDF, DOCX, scans with OCR), inline-editable parsed resumes, drag-and-drop funnel stages
- Interview uploads up to 500 MB with an in-app player; AI-generated per-candidate interview questions
- Multi-round evaluation sheets with divergence highlighting and external evaluator invitations
- Consolidated XLSX reports, candidate comparison, GDPR export and erase
- Talent market lifecycle emails and match scoring; assessment calibration with locking

### v1.5–v1.8 — Competence library rework

- Competence tree with publish/unpublish, drag-and-drop, and an audit log; per-tenant skill levels; learning materials with specialization overrides
- AI competence generation with live progress, scoped runs, and tenant-level AI settings
- Structured positions with inheritance-aware competence matrices, lifecycle, and occupancy tracking
- Custom rating scales, evaluation criteria selection, and automatic grade recommendation
- Development plans with auto-generated items from grade competences

### Earlier in 2026

- **Multi-tenant authentication** — login, tenant select, in-app switcher
- **[Cloud]** Platform admin panel with tenant management, dashboard, and impersonation
- **Dashboard redesign** — KPI strip with sparklines, headcount, cycle progress, attention inbox
- **Onboarding wizard** — 4-step setup with auto-detect and skip
- **Email** — verification, transactional notifications, configurable provider
- **[Cloud]** Credit-based billing with monthly free tier
- **File uploads** — avatars, dev plan attachments, exam question images
- **Observability** — metrics, error tracking, structured logging, health probes
- **First production deploy** — managed cloud live at app.hrpulsar.com
- **RBAC, responsive UI, and dark mode** across every page
- **UX polish** — global ⌘K command palette, pagination, in-app notifications

---

## Want to influence what comes next?

- File a feature request on [GitHub Discussions](https://github.com/HRPulsar/hrpulsar/discussions)
- Email `support@hrpulsar.com` for enterprise priorities
