# HRPulsar

**Open source talent & competency management platform.**

Manage competencies, run 360° assessments, build development plans, and track employee growth — all in one place. Self-host on your servers or use the cloud.

## Features

- **Competency Frameworks** — Build hierarchical competency trees with skill levels, behavioral indicators, and learning materials
- **360° Assessments** — Self, 180°, and 360° assessments with configurable answer scales and calibration
- **Personal Development Plans** — Goal-based development plans tied to assessment results with progress tracking
- **Grade System** — Career ladders linking specializations, grades, and required competencies
- **Exams & Knowledge Tests** — Mass and individual exams with multiple question types and auto-scoring
- **Talent Market** — Internal marketplace for vacancies, projects, and talent matching
- **AI-Powered** — LLM-based competency generation, indicator suggestions, and semantic search
- **Analytics & Reports** — Assessment statistics, competency matrices, and Excel exports
- **Multi-tenant** — Isolated data per organization with system-wide reference data
- **API-First** — 500+ REST API endpoints with Swagger documentation

## Quick Start

### Self-Hosted (Docker)

```bash
git clone https://github.com/HRPulsar/hrpulsar.git
cd hrpulsar
cp .env.example .env
# Edit .env: set JWT_SECRET, POSTGRES_PASSWORD, and an email provider
# (SMTP_* or RESEND_API_KEY) — sign-up confirmation links arrive by email
docker compose -f docker-compose.self-hosted.yml up -d --build
```

Open http://localhost and create your account. See the
[Self-Hosted Deployment Guide](docs/SELF_HOSTED.md) for details.

### Development

```bash
git clone https://github.com/HRPulsar/hrpulsar.git
cd hrpulsar
docker compose up -d          # Start PostgreSQL + Redis
make install-dev               # Install dependencies
make migrate                   # Run database migrations
make run                       # Start backend (8100) + frontend (3100)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.14+ / FastAPI |
| Frontend | Next.js 16 / React 19 / TypeScript |
| Database | PostgreSQL 17 + pgvector |
| Cache | Redis 7 |
| AI/ML | Direct SDKs (Anthropic, OpenAI, Gemini) + pgvector |
| UI | shadcn/ui + Tailwind CSS |
| Deploy | Docker Compose (self-hosted) |

## API Documentation

After starting the backend, visit http://localhost:8100/api/docs (development) for interactive Swagger UI. In the self-hosted Docker setup, Swagger is served through the reverse proxy at http://localhost/api/docs.

## Documentation

- [Self-Hosted Deployment Guide](docs/SELF_HOSTED.md)
- [Environment Variables Reference](docs/SELF_HOSTED.md#environment-variables)

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and guidelines, and [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

HRPulsar Community Edition is licensed under the [GNU Affero General Public License v3.0](LICENSE), with an additional section 7 permission for combining with Enterprise Edition modules — see [NOTICE](NOTICE).

An Enterprise Edition with additional features (admin panel, billing, advanced analytics) is available under a separate commercial license. Contact support@hrpulsar.com for details.
