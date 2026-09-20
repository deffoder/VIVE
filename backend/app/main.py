"""FastAPI application factory.

Mounts the API at /api/v1 (CLAUDE.md, docs/API_SPEC.md) with a /v1 alias so the
shorter form in external documents also resolves. Every failure leaves through
the structured error envelope in docs/API_SPEC.md 7.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.adapters.mock import build_mock_bundle
from app.api.deps import AppState
from app.api.routes import sessions as sessions_routes
from app.api.routes import system as system_routes
from app.core.config import API_PREFIX, LEGACY_API_PREFIX, Settings, get_settings
from app.core.errors import ErrorCode, ViveError
from app.core.logging import configure_logging, get_logger
from app.core.security import RateLimiter, ReplayGuard
from app.core.session_manager import SessionManager
from app.store.memory import InMemoryEventStore
from app.ws import stream as ws_stream
from app.ws.manager import ConnectionManager

log = get_logger("vive.api")

DESCRIPTION = """
Real-time voice integrity verification and social-engineering risk analysis for
**authorized** voice communication.

VIVE is decision support. It does not transfer money, retrieve credentials,
bypass authentication or make banking decisions. Synthetic speech is not
automatically fraud, and a genuine human voice is not automatically safe.

**Risk score and confidence are separate measures.** Confidence is never a
fraud probability.

In this build every analyzer is a **MOCK/DEMO adapter**: outputs are
deterministic scripted values, not model inference, and must never be cited as
accuracy or detection capability. `GET /ready` reports the mode per adapter.
"""


def build_state(settings: Settings) -> AppState:
    store = InMemoryEventStore(max_packets_per_session=settings.max_packets_per_session)
    adapters = build_mock_bundle()
    return AppState(
        settings=settings,
        store=store,
        adapters=adapters,
        sessions=SessionManager(store, adapters),
        connections=ConnectionManager(),
        rate_limiter=RateLimiter(
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        ),
        create_limiter=RateLimiter(
            limit=settings.rate_limit_session_creates,
            window_seconds=settings.rate_limit_window_seconds,
        ),
        replay_guard=ReplayGuard(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    # Refuse to run open in production rather than silently accepting anything.
    if settings.env == "production" and not settings.auth_enforced:
        raise RuntimeError(
            "VIVE_API_TOKENS must be set in production; refusing to start without auth."
        )

    app.state.vive = build_state(settings)
    log.info(
        "backend started",
        extra={"event": "startup", "status": settings.env},
    )
    yield
    log.info("backend stopped", extra={"event": "shutdown"})


def create_app() -> FastAPI:
    app = FastAPI(
        title="VIVE API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    for prefix in (API_PREFIX, LEGACY_API_PREFIX):
        app.include_router(system_routes.router, prefix=prefix)
        app.include_router(sessions_routes.router, prefix=prefix)
        app.include_router(ws_stream.router, prefix=prefix)

    # Unprefixed operational endpoints, per docs/API_SPEC.md 2.
    app.include_router(system_routes.router, include_in_schema=False)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        # Path and status only. Never the query string, which can carry a token.
        log.info(
            f"{request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "status": response.status_code,
                "latency_ms": elapsed_ms,
                "event": "http",
            },
        )
        return response

    @app.exception_handler(ViveError)
    async def handle_vive_error(request: Request, exc: ViveError) -> JSONResponse:
        return _error_response(request, exc.code, exc.message, exc.detail, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Field locations only - never the submitted values, which may carry
        # transcript content (docs/SECURITY_SPEC.md 5).
        fields = ", ".join(".".join(str(p) for p in e.get("loc", [])) for e in exc.errors()[:5])
        return _error_response(
            request,
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed.",
            f"Invalid or missing: {fields}" if fields else None,
            400,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "unhandled error",
            extra={"request_id": getattr(request.state, "request_id", None), "event": "error"},
        )
        # Deliberately opaque: no exception text, no stack trace.
        return _error_response(
            request, ErrorCode.INTERNAL_ERROR, "An internal error occurred.", None, 500
        )

    return app


def _error_response(
    request: Request,
    code: ErrorCode,
    message: str,
    detail: str | None,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code.value,
                "message": message,
                "detail": detail,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


app = create_app()
