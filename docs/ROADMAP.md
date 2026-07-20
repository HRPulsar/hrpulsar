# Roadmap

What we're building, what we just shipped, and what's next.

Tags signal where each item lives:

- **[Both]** — available in Community Edition (self-host) and the cloud
- **[Cloud]** — only on hrpulsar.com (managed cloud)
- **[Self-host]** — only relevant to Community Edition deployments

Updated continuously. Plans shift as we learn — treat the upcoming sections as direction, not commitments.

---

## In progress

### AI-powered Recruiting [Both]

End-to-end hiring module: open positions, candidate sourcing, resume parsing, screening cards, structured interview assessment, and an AI co-pilot that drafts shortlists, parses interview audio, and ranks fit against the role.

---

## Up next (next two quarters)

### Internationalization [Both]

Full multi-language UI with runtime language switch. English and Russian first; community translations welcome.

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

### v1.4.0 — Brand kit v3 and dashboard redesign

- New chronograph mark, Geist wordmark, horizontal/stacked lockups, high-res social card
- Dashboard redesign — KPI strip with sparklines, department headcount, active cycle progress, attention inbox, weekly calendar
- Sidebar restructured (Workspace / Talent / Discover / Admin) with tenant switcher moved here
- Employee detail page leads with an identity card surfacing status, tenure, and assessment progress
- Dark theme recoloured to brand blue so charts, KPIs, and focus rings are visible
- **[Cloud]** Public waitlist for early access with confirmation email and platform-admin invite flow

### v1.3.0 — Positions and rendered docs

- Structured job positions replacing free-text titles
- AI-powered position drafting with approve / reject flow
- In-site documentation rendering — markdown docs styled as landing pages
- Cloud & Enterprise features page

### Earlier in 2026

- **Multi-tenant authentication** — login, tenant select, in-app switcher
- **[Cloud]** Platform admin panel with tenant management, dashboard, and impersonation
- **Onboarding wizard** — 4-step setup with auto-detect and skip
- **Email** — verification, transactional notifications, configurable provider
- **[Cloud]** Credit-based billing with monthly free tier
- **File uploads** — avatars, dev plan attachments, exam question images
- **Observability** — metrics, error tracking, structured logging, health probes
- **First production deploy** — managed cloud live at app.hrpulsar.com
- **RBAC and responsive UI** — role-based screens, mobile-first
- **Dark mode** across every page
- **Automated testing** — backend and end-to-end coverage
- **UX polish** — global ⌘K command palette, pagination, in-app notifications
- **Demo and onboarding** — seed data, mass import, AI competency drafting

---

## Want to influence what comes next?

- File a feature request on [GitHub Discussions](https://github.com/hrpulsar/hrpulsar/discussions)
- Email `support@hrpulsar.com` for enterprise priorities
