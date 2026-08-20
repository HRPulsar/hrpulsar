# Roadmap

What we're building, what we just shipped, and what's next.

Tags signal where each item lives:

- **[Both]** — available in Community Edition (self-host) and the cloud
- **[Cloud]** — only on hrpulsar.com (managed cloud)
- **[Self-host]** — only relevant to Community Edition deployments

Updated continuously. Plans shift as we learn — treat the upcoming sections as direction, not commitments.

---

## In progress

### Internationalization [Both]

Full multi-language UI with runtime language switch. English stays the base; community translations land as a single JSON file per language via PR.

### White-label for the cloud [Cloud]

Per-tenant branding on managed plans — your logo, product name, colors, and favicon across the app and outgoing emails, plus custom domains. Builds on the white-label support that shipped for self-hosted installs in v1.15.

---

## Up next (next two quarters)

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

### AI Assistant [Both]

In-app chat that answers questions about your org and a proactive advisor that surfaces stale plans, calibration gaps, and attrition risks.

### Open-source adoption [Self-host]

Plugin API, Helm chart, and official SDKs for embedding HRPulsar into your own stack.

---

## Recently shipped

Highlights — full per-version list lives in the [changelog](/changelog).

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
