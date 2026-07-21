# Self-Hosted Deployment Guide

Deploy HRPulsar on your own infrastructure using Docker Compose.

## Prerequisites

- Docker 24.0+
- Docker Compose 2.20+
- 2+ vCPU, 4+ GB RAM, 20+ GB SSD (minimum)
- A domain name (optional, for HTTPS)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/hrpulsar/hrpulsar.git
cd hrpulsar
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
JWT_SECRET=your-random-secret-string-here
POSTGRES_PASSWORD=a-strong-database-password
FRONTEND_URL=https://hr.yourcompany.com   # public URL of your instance
```

`FRONTEND_URL` is what links in outgoing emails (verification, password
reset, invitations) point at — without it they fall back to
`http://localhost:3100` and only work from the server itself.

Configuring an email provider (`SMTP_*` or `RESEND_API_KEY` in `.env`) is
recommended but not required to get started:

- **No email provider configured** — new accounts are verified automatically
  at registration, so you can sign up and log in right away. Outgoing emails
  (invitations, password resets, notifications) are skipped.
- **Email provider configured** — registration sends a standard verification
  email. If delivery fails, the backend prints the verification link to its
  log (`docker compose -f docker-compose.self-hosted.yml logs backend`, look
  for `EMAIL VERIFICATION LINK`) so you can complete the signup manually.

Email links are built from `FRONTEND_URL` (falling back to the first
`CORS_ORIGINS` entry) — point it at your instance's public URL.

### 3. Start all services

```bash
docker compose -f docker-compose.self-hosted.yml up -d --build
```

The first start builds the backend and frontend images (several minutes) and
starts 8 services:
- **Caddy** — Reverse proxy (ports 80/443)
- **Backend** — FastAPI application (port 8000 internal)
- **Frontend** — Next.js application (port 3000 internal)
- **Celery worker** — Background jobs (emails, AI processing)
- **Celery beat** — Periodic task scheduler
- **PostgreSQL** — Database with pgvector extension
- **Redis** — Cache and task queue
- **MinIO** — S3-compatible file storage (plus a one-shot `minio-init`
  container that creates the storage bucket on first boot)

### 4. Access the application

- **HTTP**: http://your-server-ip
- **HTTPS**: https://your-domain.com (if you configured a domain in the Caddyfile)

The root URL takes you to the sign-in page. Create your first account at
`/register` — the form creates your company workspace and its admin account
in one step. Without an email provider configured the account is verified
automatically and you are signed in immediately (see step 2 above).

## HTTPS with a Domain

To enable automatic HTTPS:

1. Point your domain's A record to your server IP
2. Edit `deploy/selfhosted/Caddyfile`: replace `:80` with your domain (e.g., `app.yourcompany.com`)
3. Restart Caddy: `docker compose -f docker-compose.self-hosted.yml restart caddy`

Caddy will automatically obtain a Let's Encrypt certificate. Remember to
update `FRONTEND_URL` in `.env` to the new domain, and set
`S3_PUBLIC_ENDPOINT=https://your-domain` so uploaded files (logos, media)
are served through the proxy — without it, file links point at the
internal MinIO address and won't load in the browser.

## Running Without Docker Compose

The compose file passes `DEPLOYMENT_MODE` to both the backend and the
frontend containers. If you run the services yourself (systemd, bare
`next start`), set `DEPLOYMENT_MODE=onprem` in the environment of **both**
processes — the frontend uses it to serve the self-serve registration form
and the sign-in redirect at the root URL; without it the app falls back to
the hosted-product entry surface.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET` | Yes | `change-me-to-a-random-string` | Secret key for JWT tokens |
| `POSTGRES_PASSWORD` | Yes | `hrpulsar` | PostgreSQL password |
| `DATABASE_URL` | No | Auto-configured | PostgreSQL connection string |
| `REDIS_URL` | No | Auto-configured | Redis connection string |
| `ANTHROPIC_API_KEY` | No | — | Claude API key (for AI features) |
| `OPENAI_API_KEY` | No | — | OpenAI API key (for AI features) |
| `GEMINI_API_KEY` | No | — | Gemini API key (for AI features) |
| `LLM_PROVIDER` | No | `claude` | LLM provider (`claude`, `openai`, `gemini`) |
| `SMTP_HOST` | No | — | SMTP server for email notifications |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_USER` | No | — | SMTP username |
| `SMTP_PASSWORD` | No | — | SMTP password |
| `FRONTEND_URL` | No | First `CORS_ORIGINS` entry | Public URL of your instance, used to build links in emails |
| `S3_ENDPOINT` | No | — | S3/MinIO endpoint for file storage |
| `S3_ACCESS_KEY` | No | — | S3 access key |
| `S3_SECRET_KEY` | No | — | S3 secret key |
| `S3_BUCKET` | No | `hrpulsar` | S3 bucket name |
| `S3_PUBLIC_ENDPOINT` | No | — | Public base URL for file links when `S3_ENDPOINT` is internal-only (bundled MinIO). Set to your site origin, e.g. `https://hr.yourcompany.com` |
| `BRAND_NAME` | No | `HRPulsar` | Installation name in outgoing emails and the API title |
| `BRAND_LOGO_URL` | No | Stock logo | Absolute URL of the email-header logo |
| `BRAND_ACCENT_COLOR` | No | `#0066FF` | Accent color for email buttons and links |
| `EMAIL_FROM` | No | `HRPulsar <notifications@hrpulsar.com>` | From header of outgoing emails |
| `NEXT_PUBLIC_BRAND_NAME` | No | `HRPulsar` | Installation name in the web UI (frontend) |
| `NEXT_PUBLIC_LOGO_URL` | No | Stock logo | Web UI logo for light backgrounds (frontend) |
| `NEXT_PUBLIC_LOGO_DARK_URL` | No | Stock logo | Web UI logo for dark backgrounds (frontend) |
| `NEXT_PUBLIC_BRAND_ACCENT_COLOR` | No | `#0066FF` | Web UI accent color, any CSS color (frontend) |
| `NEXT_PUBLIC_FAVICON_URL` | No | `/icon.svg` | Web UI favicon (frontend) |

## Branding

The platform is white-label ready: logo, installation name, accent color
and favicon can all be replaced through environment variables, without
touching the source code. A default installation is identical to the
stock HRPulsar build.

Frontend (web UI) variables — set on the frontend container:

```bash
NEXT_PUBLIC_BRAND_NAME="Acme Talent"
NEXT_PUBLIC_LOGO_URL=https://cdn.acme.example/logo-light-bg.svg
NEXT_PUBLIC_LOGO_DARK_URL=https://cdn.acme.example/logo-dark-bg.svg
NEXT_PUBLIC_BRAND_ACCENT_COLOR="#AA0044"
NEXT_PUBLIC_FAVICON_URL=https://cdn.acme.example/favicon.png
```

- `NEXT_PUBLIC_BRAND_NAME` replaces the name in browser titles, page
  metadata and every place the UI mentions the platform by name.
- Logos: `NEXT_PUBLIC_LOGO_URL` is used on light surfaces (sidebar in
  light theme); `NEXT_PUBLIC_LOGO_DARK_URL` on dark surfaces (auth
  pages, sidebar in dark theme). If only `NEXT_PUBLIC_LOGO_URL` is set,
  it is used everywhere. Horizontal logos around 5:1 aspect ratio work
  best; they render at ~20–31px height.
- `NEXT_PUBLIC_BRAND_ACCENT_COLOR` accepts any CSS color and recolors
  links, accent-colored buttons and badges, focus rings, and charts.
  Hover/darker shades are derived automatically. The neutral dark
  (near-black) primary buttons and body text are intentionally not
  affected. The same accent is applied in both light and dark themes —
  pick a color with sufficient contrast in both.
- The variables are read at runtime on every request, so a prebuilt
  image (GHCR) picks them up from the container environment — no
  rebuild needed.

Backend (email) variables — set on the backend container:

```bash
BRAND_NAME="Acme Talent"
BRAND_LOGO_URL=https://cdn.acme.example/email-logo.png
BRAND_ACCENT_COLOR="#AA0044"
EMAIL_FROM="Acme Talent <notifications@acme.example>"
```

Outgoing emails then carry the custom name, header logo (rendered at
31px height) and button/link color. `EMAIL_FROM` controls the From
header.

Static assets that live in the frontend image (`site.webmanifest`,
`apple-touch-icon.png`, PNG icons) can be replaced by mounting your own
files over `/app/public/*` in the frontend container if you need a
fully branded install surface (PWA icons, home-screen name).

## Upgrading

Back up the database first (see below), then:

```bash
cd hrpulsar
git pull
docker compose -f docker-compose.self-hosted.yml build
docker compose -f docker-compose.self-hosted.yml up -d
```

Migrations run automatically on backend startup. Building happens while
the old version keeps serving; expect well under a minute of downtime
during the final `up -d` switchover.

Local changes and upgrades:

- Keep your customizations out of `docker-compose.self-hosted.yml` —
  put them in a separate override file and pass both files on every
  command, e.g.
  `docker compose -f docker-compose.self-hosted.yml -f docker-compose.local.yml up -d`.
  An edited compose file will conflict on `git pull`.
- The one file you are expected to edit in place is
  `deploy/selfhosted/Caddyfile` (your domain). If an upgrade touches it,
  `git pull` will ask you to merge — re-apply your domain line.

## Backup & Restore

### Backup

```bash
./scripts/backup_db.sh ./backups
```

Or set up a daily cron job:

```bash
crontab -e
# Add: 0 3 * * * /path/to/hrpulsar/scripts/backup_db.sh /path/to/backups
```

### Restore

```bash
gunzip -c backups/hrpulsar_YYYYMMDD_HHMMSS.sql.gz | \
  docker compose -f docker-compose.self-hosted.yml exec -T postgres psql -U hrpulsar hrpulsar
```

## Troubleshooting

### Check service status

```bash
docker compose -f docker-compose.self-hosted.yml ps
```

### View logs

```bash
docker compose -f docker-compose.self-hosted.yml logs backend
docker compose -f docker-compose.self-hosted.yml logs frontend
```

### Health check

The backend port is not published on the host — query it through the proxy:

```bash
curl http://localhost/health
```

`"status": "ok"` means database, Redis, file storage, and the Celery worker
are all reachable.

## Hardware Recommendations

| Users | CPU | RAM | Disk |
|-------|-----|-----|------|
| Up to 100 | 2 vCPU | 4 GB | 20 GB SSD |
| 100-500 | 4 vCPU | 8 GB | 50 GB SSD |
| 500+ | 8 vCPU | 16 GB | 100 GB SSD |
