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
git clone https://github.com/HRPulsar/hrpulsar.git
cd hrpulsar
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
JWT_SECRET=paste-the-output-of-openssl-rand-hex-32
POSTGRES_PASSWORD=a-strong-database-password
FRONTEND_URL=https://hr.yourcompany.com   # public URL of your instance
```

The backend refuses to start with an empty `JWT_SECRET` or the old
`change-me-to-a-random-string` placeholder. It also seeds `ENCRYPTION_KEY`,
the key protecting per-workspace AI provider keys (BYOK) at rest — if you
may want to rotate `JWT_SECRET` later, pin `ENCRYPTION_KEY` now
(`openssl rand -base64 32`); rotating without it leaves those stored keys
unreadable.

`FRONTEND_URL` is what links in outgoing emails (verification, password
reset, invitations) point at — without it they fall back to
`http://localhost:3100` and only work from the server itself. It is also
the default origin that browser-facing file links (logos, avatars,
attachments) are signed against, since the bundled MinIO is only
reachable inside the Docker network; leave `S3_PUBLIC_ENDPOINT` unset
unless storage is served from a different origin than the app.

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
update `FRONTEND_URL` in `.env` to the new domain — uploaded files (logos,
media) are served through the proxy at that origin. Set
`S3_PUBLIC_ENDPOINT=https://your-domain` only if storage is proxied from
somewhere other than `FRONTEND_URL`.

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
| `JWT_SECRET` | Yes | — | Secret signing every access/refresh token — generate with `openssl rand -hex 32`. The backend refuses to start while it is empty or left at the old `change-me-to-a-random-string` placeholder |
| `ENCRYPTION_KEY` | No | Derived from `JWT_SECRET` | AES-GCM key encrypting per-workspace AI provider keys (BYOK) at rest; urlsafe-base64 decoding to at least 32 bytes (`openssl rand -base64 32`). Left unset it is derived from `JWT_SECRET`, so rotating `JWT_SECRET` without pinning this value first makes every stored BYOK key unreadable. Required explicitly when `DEPLOYMENT_MODE=saas` |
| `POSTGRES_PASSWORD` | Yes | `hrpulsar` | PostgreSQL password |
| `DEPLOYMENT_MODE` | No | `onprem` | `onprem` or `saas`. Keep `onprem` for a self-hosted install — it enables the self-serve registration form and the sign-in redirect at the root URL. Must be set on **both** the backend and the frontend process when you run them outside the bundled compose file |
| `CORS_ORIGINS` | No | `http://localhost:3100,http://localhost:3300` | Comma-separated origins allowed to call the API. Set it to your public URL(s) on any deployed install — the default only covers local development |
| `DATABASE_URL` | No | Auto-configured | PostgreSQL connection string |
| `REDIS_URL` | No | Auto-configured | Redis connection string |
| `ANTHROPIC_API_KEY` | No | — | Claude API key (for AI features) |
| `OPENAI_API_KEY` | No | — | OpenAI API key (for AI features) |
| `GEMINI_API_KEY` | No | — | Gemini API key (for AI features) |
| `YANDEX_API_KEY` | No | — | Yandex Foundation Models API key (for AI features) |
| `YANDEX_FOLDER_ID` | No | — | Yandex Cloud folder id, required with `YANDEX_API_KEY` |
| `LLM_PROVIDER` | No | `claude` | LLM provider (`claude`, `openai`, `gemini`, `yandex`) |
| `ASSEMBLYAI_API_KEY` | No | — | AssemblyAI key for interview transcription (recruiting module) |
| `DEEPGRAM_API_KEY` | No | — | Deepgram key for interview transcription |
| `YANDEX_SPEECHKIT_API_KEY` | No | — | Yandex SpeechKit key for interview transcription; falls back to the `YANDEX_API_KEY` service account and uses `YANDEX_FOLDER_ID` |
| `TRANSCRIPTION_PROVIDER_DEFAULT` | No | `whisper` | Transcription provider tried first (`whisper`, `deepgram`, `assemblyai`, `yandex_speechkit`). Every key configured above joins the fallback chain |
| `SMTP_HOST` | No | — | SMTP server for email notifications |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_USER` | No | — | SMTP username |
| `SMTP_PASSWORD` | No | — | SMTP password |
| `FRONTEND_URL` | No | First `CORS_ORIGINS` entry | Public URL of your instance, used to build links in emails |
| `TRUSTED_PROXIES` | No | Private ranges | Comma-separated CIDRs/IPs of the reverse proxies in front of the app. `X-Forwarded-For` is honoured only from these peers, and the per-IP rate limits (login, password reset, sign-up) key on the client address it carries. The default covers the bundled Caddy; set it when the app is reached through a proxy on a **public** address (Cloudflare, an external load balancer) and list that proxy's ranges — otherwise every request keys on the proxy's own IP and one user hitting a limit throttles everyone |
| `S3_ENDPOINT` | No | — | S3/MinIO endpoint for file storage |
| `S3_ACCESS_KEY` | No | — | S3 access key |
| `S3_SECRET_KEY` | No | — | S3 secret key |
| `S3_BUCKET` | No | `hrpulsar` | S3 bucket name |
| `S3_PUBLIC_ENDPOINT` | No | `FRONTEND_URL` | Public base URL for file links when `S3_ENDPOINT` is internal-only (bundled MinIO). Set it only when storage is served from another origin than the app. File URLs are signed path-style (`<endpoint>/<S3_BUCKET>/<key>`), so give the bare storage host — if your provider serves buckets as subdomains, do **not** paste `https://<bucket>.<host>` here or every download fails with `NoSuchKey` |
| `MAX_UPLOAD_MB` | No | `10` | Hard size cap on a single generic upload (`POST /files/upload`, avatars). Domain-specific ceilings (resume, interview attachment) stay stricter |
| `BRAND_NAME` | No | `HRPulsar` | Installation name in outgoing emails and the API title |
| `BRAND_LOGO_URL` | No | Stock logo | Absolute URL of the email-header logo |
| `BRAND_ACCENT_COLOR` | No | `#0066FF` | Accent color for email buttons and links |
| `EMAIL_FROM` | No | `HRPulsar <notifications@hrpulsar.com>` | From header of outgoing emails |
| `NEXT_PUBLIC_BRAND_NAME` | No | `HRPulsar` | Installation name in the web UI (frontend) |
| `NEXT_PUBLIC_LOGO_URL` | No | Stock logo | Web UI logo for light backgrounds (frontend) |
| `NEXT_PUBLIC_LOGO_DARK_URL` | No | Stock logo | Web UI logo for dark backgrounds (frontend) |
| `NEXT_PUBLIC_BRAND_ACCENT_COLOR` | No | `#0066FF` | Web UI accent color, any CSS color (frontend) |
| `NEXT_PUBLIC_FAVICON_URL` | No | `/icon.svg` | Web UI favicon (frontend) |
| `NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT` | No | `28px` | Sidebar logo height, `px`/`rem` value (frontend) |
| `NEXT_PUBLIC_BRAND_THEME` | No | `default` | Theme preset: `default`, `teal`, `slate`, `violet` (frontend) |
| `NEXT_PUBLIC_BRAND_AUTH_BG_COLOR` | No | Stock dark | Login/register background color (frontend) |
| `NEXT_PUBLIC_BRAND_AUTH_BG_URL` | No | — | Login/register background image URL (frontend) |
| `AVAILABLE_LOCALES` | No | `en` | Comma-separated interface locales this install offers, e.g. `de,en` |
| `DEFAULT_LOCALE` | No | `en` | Fallback interface locale; must be listed in `AVAILABLE_LOCALES` |
| `NEXT_PUBLIC_AVAILABLE_LOCALES` | No | `en` | Frontend counterpart of `AVAILABLE_LOCALES` — keep both in sync |
| `NEXT_PUBLIC_DEFAULT_LOCALE` | No | `en` | Frontend counterpart of `DEFAULT_LOCALE` — keep both in sync |
| `SENTRY_DSN` | No | — | Backend error-tracking DSN. Empty disables Sentry entirely |
| `SENTRY_ENVIRONMENT` | No | `development` | Environment name reported with every backend event |
| `SENTRY_TRACES_SAMPLE_RATE` | No | `0.1` | Share of backend transactions sampled for performance tracing, `0`–`1` |
| `NEXT_PUBLIC_SENTRY_DSN` | No | — | Web UI error-tracking DSN. Read at runtime, so changing it needs a container restart, not a rebuild (frontend) |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | No | — | Environment name reported with every web UI event (frontend) |

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
  best; the sidebar renders them at 28px height by default. If your
  logo's proportions need a different size, set
  `NEXT_PUBLIC_SIDEBAR_LOGO_HEIGHT` to an exact `px`/`rem` value
  (e.g. `24px`).
- `NEXT_PUBLIC_BRAND_ACCENT_COLOR` accepts any CSS color and recolors
  links, accent-colored buttons and badges, focus rings, and charts.
  Hover/darker shades are derived automatically. The neutral dark
  (near-black) primary buttons and body text are intentionally not
  affected. The same accent is applied in both light and dark themes —
  pick a color with sufficient contrast in both.
- `NEXT_PUBLIC_BRAND_THEME` switches the whole UI to a curated theme
  preset — surfaces, accent, charts, sidebar and corner radius change
  together, in both light and dark mode. Available presets: `default`
  (stock navy + blue), `teal` (deep navy + teal accent), `slate`
  (neutral graphite + steel blue), `violet` (warm neutrals + violet
  accent). An explicit `NEXT_PUBLIC_BRAND_ACCENT_COLOR` still applies
  on top of the preset's accent for point tweaks.
- The login/register pages can carry their own background:
  `NEXT_PUBLIC_BRAND_AUTH_BG_COLOR` replaces the stock dark backdrop
  with a solid color; `NEXT_PUBLIC_BRAND_AUTH_BG_URL` (absolute
  `https://` or root-relative URL) shows a full-bleed image instead —
  it is scaled to cover the viewport on every screen size, and a dark
  scrim keeps the sign-in card readable on any image. Setting either
  hides the stock starfield decoration.
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

**On a branded install, always set `EMAIL_FROM`, `FRONTEND_URL` and
`BRAND_LOGO_URL` together with `BRAND_NAME`.** `EMAIL_FROM` defaults to
the stock HRPulsar sender — leaving its address on the stock domain
means recipients see the stock brand in the From header (and in the
SMTP Message-ID, which is derived from the sender's domain).
`FRONTEND_URL` is what links inside emails point at, and without
`BRAND_LOGO_URL` the email header renders the stock logo. The backend
logs a startup warning when `BRAND_NAME` is customized but any of the
three is left at its default.

Static assets that live in the frontend image (`site.webmanifest`,
`apple-touch-icon.png`, PNG icons) can be replaced by mounting your own
files over `/app/public/*` in the frontend container if you need a
fully branded install surface (PWA icons, home-screen name).

## Interface Languages

An install can offer more than one interface language. Set the pair on
both containers (backend reads `AVAILABLE_LOCALES` / `DEFAULT_LOCALE`,
frontend reads the `NEXT_PUBLIC_*` counterparts at runtime):

```bash
AVAILABLE_LOCALES=de,en
DEFAULT_LOCALE=de
NEXT_PUBLIC_AVAILABLE_LOCALES=de,en
NEXT_PUBLIC_DEFAULT_LOCALE=de
```

The onboarding wizard then asks for the workspace default language, and
every member can pick a personal language in profile settings. The
backend refuses to start when `DEFAULT_LOCALE` is not listed in
`AVAILABLE_LOCALES`. Single-locale installs (the default) hide the
language selects entirely. The wizard also records the AI content
language — the language the AI generates competences and development
plans in — which is independent of the interface language.

## Upgrading

**Back up first — every time, and without exception before a major
version.** Migrations run forward only: there is no downgrade path, so once
a release has rewritten the schema the only way back to the previous
version is restoring the backup you took before the upgrade.

Run `./scripts/backup_db.sh ./backups` (see [Backup & Restore](#backup--restore)),
check that it printed a dump size, then:

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
# Add: 0 3 * * * cd /path/to/hrpulsar && ./scripts/backup_db.sh ./backups
```

Each run writes two files: `hrpulsar_<timestamp>.sql.gz` (the database) and
`minio_<timestamp>.tar.gz` (the file-storage volume — resumes, interview
recordings, generated reports). The database dump alone restores an
instance where every attachment 404s, so keep the pair together.

If your `.env` has `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` /
`S3_BUCKET` set, both files are also uploaded there under the `backups/`
prefix (override with `BACKUP_S3_PREFIX`) — a backup that lives on the
same disk as the database is not a backup. Point those at a provider other
than the bundled MinIO; copying the file storage into itself is not an
off-site copy. With `SLACK_BOT_TOKEN` and `BACKUP_SLACK_CHANNEL` set, a
failed backup posts to that channel instead of failing silently.

### Restore

Restore both halves from the same timestamp. Stop the app containers first
so nothing writes while the data is being replaced:

```bash
docker compose -f docker-compose.self-hosted.yml stop backend celery-worker celery-beat frontend
```

Database — `ON_ERROR_STOP=on` is what makes a failed restore stop instead
of running to the end and leaving a half-old, half-new schema behind:

```bash
gunzip -c backups/hrpulsar_YYYYMMDD_HHMMSS.sql.gz | \
  docker compose -f docker-compose.self-hosted.yml exec -T postgres \
    psql --set ON_ERROR_STOP=on -U hrpulsar hrpulsar
```

File storage — the archive holds the MinIO `data` directory, so it unpacks
at the container root:

```bash
gunzip -c backups/minio_YYYYMMDD_HHMMSS.tar.gz | \
  docker cp - "$(docker compose -f docker-compose.self-hosted.yml ps -q minio)":/
```

Then start the stack again:

```bash
docker compose -f docker-compose.self-hosted.yml up -d
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
