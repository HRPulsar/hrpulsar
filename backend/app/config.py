import logging
import re
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings


def _version_from_file() -> str:
    """Read ``__version__`` from version.py — /app in Docker, repo root in dev."""
    here = Path(__file__).resolve()
    for parent in (here.parents[1], here.parents[2]):
        candidate = parent / "version.py"
        if candidate.is_file():
            match = re.search(r'__version__\s*=\s*"([^"]+)"', candidate.read_text())
            if match:
                return match.group(1)
    # A packaged deployment should always ship version.py (HRP-396) — a
    # missing file means the build dropped it, so leave a trace.
    logging.getLogger(__name__).warning("version.py not found; reporting version 'dev'")
    return "dev"


class Settings(BaseSettings):
    # App
    # APP_VERSION build-arg overrides when set; empty → read version.py
    # shipped into the image (see backend/Dockerfile) or the repo root in dev
    version: str = Field(
        default="", validation_alias=AliasChoices("app_version", "version")
    )
    debug: bool = False
    deployment_mode: Literal["onprem", "saas"] = "onprem"
    edition: Literal["community", "enterprise"] = "community"
    cors_origins: str = (
        # comma-separated, e.g. "https://hrpulsar.com,https://app.hrpulsar.com".
        # Dev default covers the product app (3100) and the standalone
        # marketing site (3300) whose demo CTA calls the API cross-origin.
        "http://localhost:3100,http://localhost:3300"
    )
    # Base URL used to build tokenised share links (e.g. report sharing).
    # Empty → falls back to the first CORS origin.
    frontend_url: str = ""

    # White-label branding (HRP-393). Defaults reproduce the stock HRPulsar
    # brand; self-hosted operators override via env (docs/core/docs/
    # SELF_HOSTED.md, "Branding"). Frontend counterparts: NEXT_PUBLIC_BRAND_*.
    brand_name: str = "HRPulsar"
    # Absolute URL of the email-header logo; empty → the stock logo served
    # by the frontend at /brand/logo-horizontal-color-light.png.
    brand_logo_url: str = ""
    # Accent color used for email buttons and links.
    brand_accent_color: str = "#0066FF"

    # Database
    database_url: str = "postgresql+asyncpg://hrpulsar:hrpulsar@localhost:5435/hrpulsar"

    # Redis
    redis_url: str = "redis://localhost:6381"

    # Auth
    jwt_secret: str = "change-me-to-a-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # AES-GCM key for at-rest encryption of tenant BYOK secrets (LLM / STT
    # API keys configured per-tenant). urlsafe-base64; ≥16 raw bytes.
    # Empty in dev → derived from jwt_secret (see app.core.crypto).
    encryption_key: str = ""

    # AI (optional)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    llm_provider: str = "claude"  # claude, openai, gemini
    # HRP-71 phase 4: per-item delay for the synthetic indicator-stream so the
    # UI counter animates 1/N → N/N. Set to 0 to disable for matrices that
    # produce thousands of indicators.
    ai_progress_step_delay_s: float = 0.04

    # Transcription (optional, recruiting interview module — Phase R3)
    deepgram_api_key: str = ""
    assemblyai_api_key: str = ""
    transcription_provider_default: str = "whisper"  # whisper | deepgram

    # Email (optional) — Resend (SaaS) or SMTP (self-hosted)
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "HRPulsar <notifications@hrpulsar.com>"
    # Resend audience the moderated /api/signup-request flow mirrors
    # verified leads into.
    resend_signup_audience_id: str = ""

    # Moderated onboarding (HRP-259..262 — M-wave).
    # Cloudflare Turnstile secret used by POST /api/signup-request; empty
    # disables the bot guard (handy in dev / E2E). Production validator
    # below requires it once the public landing CTA is live.
    signup_turnstile_secret: str = ""
    signup_rate_limit_per_ip_per_hour: int = 5
    signup_verify_token_ttl_hours: int = 24
    magic_login_token_ttl_hours: int = 24

    # Comma-separated trusted-proxy CIDRs / exact IPs for the whole app.
    # Only when the direct socket peer falls into one of these is the
    # ``X-Forwarded-For`` header honoured for client-IP resolution
    # (rate-limit keying). Behind CF+DO LB set this to the edge ranges so
    # per-IP throttles key on the real client, not the shared LB IP, and a
    # forged XFF from a direct hit is ignored. Empty → XFF ignored.
    # Falls back to ``demo_trusted_proxies`` for backward compatibility
    # (see validator below).
    trusted_proxies: str = ""

    # Auth abuse throttles (HRP review P0-5). Per-IP limits on the
    # unauthenticated auth surface to blunt password spraying and
    # mail-bombing (Resend cost). slowapi window syntax.
    auth_rate_limit_login: str = "10/minute"
    auth_rate_limit_register: str = "5/minute"
    auth_rate_limit_email: str = "3/minute"  # forgot/reset/resend/magic
    auth_rate_limit_refresh: str = "30/minute"

    # Recruitment upload ceilings (review P2-34 — moved out of service.py so
    # they're deployment-tunable). Megabytes.
    recruitment_max_attachment_mb: int = 25
    recruitment_max_resume_mb: int = 10
    recruitment_max_bulk_total_mb: int = 100

    # Public API
    public_api_rate_limit: str = "60/minute"
    public_api_batch_max_items: int = 100

    # E2E testing
    e2e_mode: bool = False

    # Demo sandbox (HRP-249 — D1: Tenant lifecycle).
    # Lifetime of a demo tenant from creation. Default 4 h (HRP-297) —
    # enough for a full evaluation session without keeping abandoned
    # sandboxes around long enough to bloat the BD or hold a concurrency
    # slot. Demo access tokens share this TTL (see
    # ``create_demo_access_token``) so the JWT can't expire before the
    # tenant does.
    demo_session_ttl_seconds: int = 14400
    # Sliding inactivity timeout — purged once no auth'd request has
    # touched the tenant for this many seconds. Pinned to the same 4 h
    # as ``demo_session_ttl_seconds`` so the only way out of a demo
    # session is an explicit logout; the hard ``expires_at`` is what
    # actually reclaims the slot.
    demo_inactivity_ttl_seconds: int = 14400
    # Debounce window for the per-request ``last_active_at`` update so
    # we don't issue a write on every API call.
    demo_activity_touch_debounce_seconds: int = 60

    # Demo sandbox (HRP-251 — D3: POST /api/demo/start).
    # Master kill-switch. False → endpoint returns 503.
    demo_enabled: bool = False
    # Demo sandbox (HRP-252 — D4: AI cost guard).
    # Opt-in panic-button (HRP-264 review). When True, AI tasks
    # (transcribe + analyze) for is_demo tenants skip the real Whisper
    # / LLM calls and use the seed_data fixtures instead.
    # Default False — real provider calls are allowed for demo tenants
    # and capped by the 250-credit budget plus the concurrent-session
    # cap. Flip to True only as an emergency response to abuse; the
    # transcribe + analyze tasks check this flag at call time.
    demo_ai_killswitch: bool = False
    # Hard cap on live demo tenants to bound BD size in the worst case.
    demo_max_concurrent_sessions: int = 50
    # Bonus credits granted to a fresh demo tenant. ~5 full transcribe +
    # analyse cycles, or ~6 reruns of analyse alone (40 each).
    demo_initial_credits: int = 250
    # Per-IP throttle on session creation. 0 disables the throttle.
    demo_rate_limit_per_ip_per_hour: int = 5
    # Cloudflare Turnstile secret; empty string disables bot-guard
    # (handy in dev / E2E).
    demo_turnstile_secret: str = ""
    # Demo sandbox (HRP-253 — D5: outbound integration + upload guard).
    # Per-tenant cap on attachment uploads in one demo session. Counts
    # only S3-backed uploads (``init_interview_upload``); pasted text
    # transcripts don't burn from this budget. 0 disables the counter.
    demo_quota_uploads: int = 2
    # Max bytes for any single demo upload. Half of the regular 10 MiB
    # transcript ceiling — the demo sandbox is meant for snippets, not
    # full HR archives.
    demo_max_upload_mb: int = 5
    # Refresh-cookie attributes for /api/demo/start. ``secure`` should
    # stay True in any HTTPS deploy; ``samesite`` is ``lax`` for the
    # common subdomain layout (demo.hrpulsar.com hosting SPA + API)
    # and would need to be ``none`` for a split-host setup where the
    # SPA and API live on different eTLD+1s. ``domain`` is None →
    # cookie is host-scoped to the API host (sane default).
    demo_cookie_secure: bool = True
    demo_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    demo_cookie_domain: str = ""
    # Comma-separated list of trusted-proxy CIDRs or exact IPs
    # (HRP-276 / M5). Only when the direct socket peer falls into one of
    # these does the router honour the ``X-Forwarded-For`` header for
    # rate-limit keying. Empty list → XFF is ignored and the throttle
    # always keys on the socket peer. Production deployments set this
    # to the front-end edge (Cloudflare ranges, ingress LB CIDR, etc.).
    demo_trusted_proxies: str = ""

    # Sentry (optional)
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    sentry_environment: str = "development"

    # File storage (optional)
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "hrpulsar"
    # Hard cap on any single generic upload routed through the storage
    # service (``POST /files/upload``, ``POST /auth/avatar``). Guards
    # against trivial OOM/DoS from an unbounded ``await file.read()``.
    # Domain-specific ceilings (resume, interview attachment) stay stricter.
    max_upload_mb: int = 10

    model_config = {"env_file": "../.env", "extra": "ignore"}

    @model_validator(mode="after")
    def _resolve_version(self) -> "Settings":
        # Non-numeric values are not release versions: SaaS compose leaks
        # APP_VERSION=latest (its image-tag selector) into the container env,
        # and stale self-hosted .env files carry APP_VERSION=dev. Fall back
        # to version.py for those instead of reporting them (HRP-396).
        if not re.match(r"\d", self.version or ""):
            self.version = _version_from_file()
        return self

    @model_validator(mode="after")
    def _demo_requires_saas(self) -> "Settings":
        """HRP-391: the public-demo sandbox is enterprise-only.

        Community / self-hosted deployments (deployment_mode=onprem) must
        not run the demo contour at all — the router serves 404 and the
        purge beat entries are not scheduled. A config that enables the
        demo outside SaaS is a mistake; fail fast at startup instead of
        silently serving 404s.
        """
        if self.demo_enabled and self.deployment_mode != "saas":
            raise ValueError(
                "DEMO_ENABLED=true requires DEPLOYMENT_MODE=saas — the "
                "public demo sandbox is an enterprise-only feature."
            )
        return self

    @model_validator(mode="after")
    def _demo_secrets_required_in_prod(self) -> "Settings":
        """Refuse to start a production/staging deploy with the public
        demo enabled but no spend guard (HRP-276 / H4 + HRP-264 review).

        Dev environments stay permissive so a local ``DEMO_ENABLED=true``
        keeps working without Turnstile credentials. The check fires only
        when both ``demo_enabled`` is True AND ``sentry_environment`` is
        a deployed tier — keeping Sentry as the source of truth for "am
        I in prod" because it's already wired everywhere.

        LLM cost is bounded by ``demo_initial_credits`` plus
        ``demo_max_concurrent_sessions``; the kill-switch is no longer
        required by default. We still demand SOME spend ceiling — a
        config with zero credits AND zero concurrent cap AND no
        kill-switch is rejected, because that combo means "real LLM
        calls, unbounded concurrency, unbounded per-session spend."
        """
        if not self.demo_enabled:
            return self
        env = (self.sentry_environment or "").lower()
        if env not in {"production", "staging"}:
            return self
        if not self.demo_turnstile_secret:
            raise ValueError(
                "DEMO_ENABLED=true requires DEMO_TURNSTILE_SECRET to be "
                f"set in '{env}' environment. Refusing to start with "
                "public demo unprotected by bot guard."
            )
        spend_guard_present = self.demo_ai_killswitch or (
            self.demo_initial_credits > 0 and self.demo_max_concurrent_sessions > 0
        )
        if not spend_guard_present:
            raise ValueError(
                f"DEMO_ENABLED=true in '{env}' requires at least one "
                "LLM spend guard: set DEMO_AI_KILLSWITCH=true OR keep "
                "DEMO_INITIAL_CREDITS>0 AND DEMO_MAX_CONCURRENT_SESSIONS>0 "
                "(credits + concurrency are the primary regulators; "
                "killswitch is the panic button)."
            )
        return self

    # Default JWT secret shipped in the repo; must never survive into a
    # deployed tier. Kept as a module-comparable constant so the validator
    # below and any test can reference the exact literal.
    _DEFAULT_JWT_SECRET: ClassVar[str] = "change-me-to-a-random-string"

    @model_validator(mode="after")
    def _secrets_not_default_in_prod(self) -> "Settings":
        """Refuse to boot a deployed tier with placeholder secrets.

        ``jwt_secret`` seeds the derived ``encryption_key`` (see
        ``app.core.crypto``) and signs every access/refresh token, so a
        leaked default is a full auth + at-rest-crypto bypass. Dev and E2E
        stay permissive — the check fires only when ``sentry_environment``
        is a deployed tier (production/staging), matching the other
        prod-only validators above.
        """
        env = (self.sentry_environment or "").lower()
        if env not in {"production", "staging"}:
            return self
        if self.jwt_secret == self._DEFAULT_JWT_SECRET or not self.jwt_secret:
            raise ValueError(
                f"JWT_SECRET must be set to a strong random value in '{env}' "
                "environment. Refusing to start with the placeholder secret "
                "(it also seeds ENCRYPTION_KEY for at-rest BYOK crypto)."
            )
        # S3/MinIO configured but unauthenticated is a silent data-exposure
        # foot-gun: reject an endpoint with no secret key in prod.
        if self.s3_endpoint and not self.s3_secret_key:
            raise ValueError(
                f"S3_SECRET_KEY must be set when S3_ENDPOINT is configured in "
                f"'{env}' environment."
            )
        return self

    @model_validator(mode="after")
    def _trusted_proxies_fallback(self) -> "Settings":
        """Inherit ``demo_trusted_proxies`` when the global list is unset.

        The demo router shipped a trusted-proxy list first (HRP-276 / M5);
        the app-wide ``trusted_proxies`` generalises it. Existing deploys
        that only configured the demo variant keep working without a config
        change.
        """
        if not self.trusted_proxies and self.demo_trusted_proxies:
            self.trusted_proxies = self.demo_trusted_proxies
        return self

    @model_validator(mode="after")
    def _signup_turnstile_required_in_prod(self) -> "Settings":
        """Refuse to start a deployed tier with the public moderated
        signup endpoint exposed but no bot-guard secret (HRP-264 — M6
        review-fix).

        Mirrors :func:`_demo_secrets_required_in_prod`. The signup
        endpoint is always on (no master switch), so the validator
        fires whenever ``sentry_environment`` is production/staging
        and ``signup_turnstile_secret`` is empty.
        """
        env = (self.sentry_environment or "").lower()
        if env in {"production", "staging"} and not self.signup_turnstile_secret:
            raise ValueError(
                "SIGNUP_TURNSTILE_SECRET must be set in "
                f"'{env}' environment. Refusing to start with the "
                "moderated /api/signup-request endpoint exposed without "
                "a bot guard."
            )
        return self


settings = Settings()
