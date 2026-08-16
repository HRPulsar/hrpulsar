import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.routing import Route

from app.config import settings
from app.core.logging import setup_logging
from app.core.sentry import init_sentry

setup_logging(level="DEBUG" if settings.debug else "INFO")
init_sentry()


class InternalEndpointFilter(logging.Filter):
    """Suppress access logs for high-frequency internal endpoints."""

    _SUPPRESSED = ("GET /health", "GET /metrics")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(ep in message for ep in self._SUPPRESSED)


logging.getLogger("uvicorn.access").addFilter(InternalEndpointFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — runtime resources only. Static wiring (event-bus
    # subscriptions, service-wrapper patches) lives in
    # register_core_extensions() below, which runs at import time.
    from app.core.websocket import manager as ws_manager

    # CR12: start Redis pub/sub listener so messages from Celery workers
    # and other web replicas reach this process's local WebSocket clients.
    try:
        await ws_manager.start_listener()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("ws listener failed to start")

    # HRP-466: fold moderation-approved catalog multipliers into the
    # in-memory model whitelist so billing keeps its fast path after a
    # restart (approvals land in the registry immediately; this replays
    # them from the DB on boot). Best-effort — a cold DB must not block
    # startup, /models lazily falls back to the row values.
    try:
        from app.database import async_session
        from app.modules.ai import model_catalog_service

        async with async_session() as db:
            await model_catalog_service.sync_registry_from_catalog(db)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("model catalog registry sync failed")

    try:
        yield
    finally:
        # Shutdown
        with contextlib.suppress(Exception):
            await ws_manager.stop_listener()


app = FastAPI(
    title=settings.brand_name,
    description="Open source talent & competency management platform",
    version=settings.version,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

# Rate limiting
from app.modules.public_api.router import limiter  # noqa: E402

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# i18n (F3): code-based user-facing errors. AppError carries a stable
# code; the handler resolves the request locale (NEXT_LOCALE cookie →
# Accept-Language → deployment default) and renders the message from
# backend/app/i18n/{locale}.json. ``detail`` stays a plain string for
# backward compatibility with the API client and tests; ``code`` is
# additive.
from app.core.errors import AppError  # noqa: E402
from app.core.i18n import (  # noqa: E402
    resolve_locale_from_request,
    translate,
    validation_key_for_message,
)


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    locale = resolve_locale_from_request(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.localized_detail(locale), "code": exc.code},
        headers=exc.headers,
    )


app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]

# i18n (F3): localize framework validation messages where a translation
# exists (errors.validation.<type> in the catalog); everything else keeps
# the stock pydantic wording, so the default-locale output is unchanged.
from fastapi.exception_handlers import (  # noqa: E402
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError  # noqa: E402


async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    locale = resolve_locale_from_request(request)
    if locale != "en":
        translated = []
        for err in exc.errors():
            key = f"errors.validation.{err.get('type', '')}"
            message = translate(key, locale, **(err.get("ctx") or {}))
            if message == key and err.get("type") == "value_error":
                # Custom ``raise ValueError("...")`` in a pydantic validator:
                # map the exact English message back to its catalog key (the
                # schemas keep plain English strings on purpose).
                custom_key = validation_key_for_message(
                    str(err.get("msg", "")).removeprefix("Value error, ")
                )
                if custom_key is not None:
                    key = custom_key
                    message = translate(custom_key, locale)
            if message != key:
                err = {**err, "msg": message}
            translated.append(err)
        exc = RequestValidationError(translated, body=exc.body)
    return await request_validation_exception_handler(request, exc)  # type: ignore[return-value]


app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]

# Middleware (order matters — outermost first)
from app.core.metrics import PrometheusMiddleware  # noqa: E402
from app.core.middleware import RequestIdMiddleware  # noqa: E402

# RequestIdMiddleware uses BaseHTTPMiddleware — load tests can disable it
# to bisect connection-leak bugs on client-cancel. Never set in prod.
if os.getenv("LOAD_TEST_DISABLE_REQUEST_ID_MIDDLEWARE", "").lower() not in (
    "1",
    "true",
    "yes",
):
    app.add_middleware(RequestIdMiddleware)
app.add_middleware(PrometheusMiddleware)


# HRP-391: the public-demo sandbox is enterprise-only. The router-level
# dependency only fires after a path+method match, so a wrong-method probe
# would leak a 405 where a truly absent route answers 404. This gate runs
# before routing and makes /api/demo/* uniformly 404 outside SaaS.
@app.middleware("http")
async def _demo_saas_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.url.path.startswith("/api/demo") and settings.deployment_mode != "saas":
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)


# CSRF invariant (review #39): authentication is Bearer-token only — the
# access token travels in the ``Authorization`` header (localStorage on the
# client), never in a cookie. The only cookie in play is the non-authenticating
# ``has_token`` SSR render hint (frontend/src/proxy.ts), which grants no access
# on its own. A forged cross-site request cannot attach the bearer token, so
# mutating endpoints are not CSRF-able and no CSRF token is required. If auth
# state ever moves into cookies, this ``allow_credentials=True`` + wide CORS
# surface makes every mutating endpoint CSRF-able — add CSRF tokens (or
# SameSite=Strict + strict Origin checks) *before* doing so.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    # Explicit method/header allowlists instead of "*" — with
    # allow_credentials=True a wildcard is needlessly broad. These cover the
    # full app surface (REST verbs + preflight; auth, JSON, optimistic-lock
    # If-Match, and the public-API key header).
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # X-Locale (HRP-513): the caller's effective interface locale, so error
    # bodies are localized when the NEXT_LOCALE cookie cannot cross origins.
    allow_headers=[
        "Authorization",
        "Content-Type",
        "If-Match",
        "X-API-Key",
        "X-Locale",
    ],
    # HRP-177: ETag is not on the CORS-safelisted response-header list, so
    # cross-origin browsers can't read it via fetch unless we expose it
    # explicitly. The vacancy edit page needs it to send If-Match on PATCH.
    # HRP-576: Retry-After joins it — a cross-origin client can't read the
    # throttle's "come back in N seconds" hint unless it is exposed.
    expose_headers=["ETag", "Retry-After"],
)

# Routers
from app.core.task_router import router as task_router  # noqa: E402
from app.modules.ai.router import router as ai_router  # noqa: E402
from app.modules.ai_competence_generation.router import (  # noqa: E402
    router as ai_compgen_router,
)
from app.modules.ai_settings.router import router as ai_settings_router  # noqa: E402
from app.modules.analytics.router import router as analytics_router  # noqa: E402
from app.modules.assessment.router import router as assessment_router  # noqa: E402
from app.modules.auth.router import router as auth_router  # noqa: E402
from app.modules.company.router import router as company_router  # noqa: E402
from app.modules.competence.router import router as competence_router  # noqa: E402
from app.modules.data_import.router import router as data_import_router  # noqa: E402
from app.modules.demo.router import router as demo_router  # noqa: E402
from app.modules.dictionary.router import router as dictionary_router  # noqa: E402
from app.modules.employee.router import router as employee_router  # noqa: E402
from app.modules.exam.router import router as exam_router  # noqa: E402
from app.modules.feedback.router import router as feedback_router  # noqa: E402
from app.modules.grade_system.router import router as grade_system_router  # noqa: E402
from app.modules.notification.router import router as notification_router  # noqa: E402
from app.modules.position.router import router as position_router  # noqa: E402
from app.modules.public_api.router import router as public_api_router  # noqa: E402
from app.modules.recruitment.manager_assessment_router import (
    public_router as recruitment_public_assessment_router,  # noqa: E402
)
from app.modules.recruitment.manager_assessment_router import (
    router as recruitment_manager_assessment_router,  # noqa: E402
)
from app.modules.recruitment.router import router as recruitment_router  # noqa: E402
from app.modules.recruitment.settings_router import (
    router as recruitment_settings_router,  # noqa: E402
)
from app.modules.signup.router import router as signup_router  # noqa: E402
from app.modules.specialization.router import (
    router as specialization_router,  # noqa: E402
)
from app.modules.storage.router import router as storage_router  # noqa: E402
from app.modules.talent_market.router import (
    router as talent_market_router,  # noqa: E402
)

app.include_router(auth_router, prefix="/api")
app.include_router(company_router, prefix="/api")
app.include_router(employee_router, prefix="/api")
app.include_router(dictionary_router, prefix="/api")
app.include_router(competence_router, prefix="/api")
app.include_router(grade_system_router, prefix="/api")
app.include_router(assessment_router, prefix="/api")
app.include_router(exam_router, prefix="/api")
app.include_router(notification_router, prefix="/api")
app.include_router(talent_market_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(position_router, prefix="/api")
app.include_router(specialization_router, prefix="/api")
app.include_router(storage_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(ai_settings_router, prefix="/api")
app.include_router(ai_compgen_router, prefix="/api")
app.include_router(data_import_router, prefix="/api")
app.include_router(public_api_router, prefix="/api")
app.include_router(recruitment_router, prefix="/api")
app.include_router(recruitment_settings_router, prefix="/api")
app.include_router(recruitment_manager_assessment_router, prefix="/api")
app.include_router(recruitment_public_assessment_router, prefix="/api")
app.include_router(task_router, prefix="/api")
app.include_router(demo_router, prefix="/api")
app.include_router(signup_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")


# Load-test endpoints (guarded by LOAD_TEST_MODE — never enable in prod)
if os.getenv("LOAD_TEST_MODE", "").lower() in ("1", "true", "yes"):
    from app.core.load_test_routes import router as load_test_router

    app.include_router(load_test_router)


# Enterprise module (loaded if ee/ package is present on disk)
try:
    from ee import register_enterprise

    register_enterprise(app)
except ImportError:
    pass


def register_core_extensions(app: FastAPI) -> None:
    """Single sanctioned core-bootstrap entry point.

    All core-side static wiring — event-bus subscriptions and startup
    service-function wrappers — registers here, mirroring how
    ``ee.register_enterprise(app)`` is the single enterprise entry point.
    Call it exactly once per process, AFTER ``register_enterprise``: the
    audit wrappers must wrap OUTSIDE the billing wrappers installed by
    ``ee.register_billing()`` so an audit row is only written when
    billing didn't reject the call.
    """
    # GF11: event-driven notification handlers (bell feed / email).
    from app.core.event_notifications import on_employee_event
    from app.core.events import subscribe

    # FR-28 / R4b.1: post-success audit-log wrappers around recruitment
    # mutating service functions.
    from app.modules.recruitment.audit_registry import register_audit_hooks

    # R4c: recruitment events (§8.5, SCR-03) — 10 notification types fan
    # out via the same bell-feed pipeline.
    from app.modules.recruitment.notifications import (
        register as register_recruitment_notifications,
    )

    subscribe("employee.event_created", on_employee_event)
    register_recruitment_notifications()
    register_audit_hooks()


register_core_extensions(app)


# Filter internal/enterprise endpoints from public OpenAPI spec
_HIDDEN_TAGS = {"platform-admin", "enterprise-billing", "billing", "tasks"}
_HIDDEN_PATH_PREFIXES = ("/api/auth/dev/",)
_original_openapi = app.openapi


def _filtered_openapi() -> dict:
    # Shallow-copy the cached base schema: the hidden-tag set depends on
    # runtime settings (demo visibility below), so the cache must keep the
    # full path table across calls.
    schema = dict(_original_openapi())
    hidden_tags = set(_HIDDEN_TAGS)
    # HRP-391: the public-demo sandbox is enterprise-only. Community builds
    # serve 404 on /api/demo/* — keep the spec consistent with that.
    if settings.deployment_mode != "saas":
        hidden_tags.add("demo")
    filtered_paths: dict = {}
    for path, methods in schema.get("paths", {}).items():
        if any(path.startswith(prefix) for prefix in _HIDDEN_PATH_PREFIXES):
            continue
        filtered_methods: dict = {}
        for method, operation in methods.items():
            tags = operation.get("tags", [])
            if not hidden_tags.intersection(tags):
                filtered_methods[method] = operation
        if filtered_methods:
            filtered_paths[path] = filtered_methods
    schema["paths"] = filtered_paths
    return schema


app.openapi = _filtered_openapi  # type: ignore[method-assign]


# Health checks & metrics
from app.core.health import health, health_celery, health_ready  # noqa: E402
from app.core.metrics import metrics_endpoint  # noqa: E402

app.routes.append(Route("/health", health))
app.routes.append(Route("/health/ready", health_ready))
app.routes.append(Route("/health/celery", health_celery))
app.routes.append(Route("/api/health/celery", health_celery))
app.routes.append(Route("/metrics", metrics_endpoint))
