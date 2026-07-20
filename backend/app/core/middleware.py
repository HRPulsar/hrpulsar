"""Request middleware: Request ID generation and log context injection."""

import contextvars
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Context variables — accessible from any async code in the same request
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
tenant_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "tenant_id", default=None
)
user_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "user_id", default=None
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate or propagate X-Request-ID and inject into log context."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Use incoming header or generate new UUID
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)

        # Extract tenant/user from request state if auth middleware set them
        tenant_id_var.set(getattr(request.state, "tenant_id", None))
        user_id_var.set(getattr(request.state, "user_id", None))

        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
