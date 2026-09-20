"""Shared dependencies: application state, authentication and authorization.

Auth model (docs/SECURITY_SPEC.md 2): bearer token on REST, the same token on
the WebSocket. When no tokens are configured the boundary is present but not
enforced, which is the documented development posture - and app.main refuses to
start in production without tokens, so "open" can never be the production state.

Ownership (SECURITY_SPEC 2): a principal may only read its own sessions.
Cross-principal access returns 404 rather than 403, so session ids cannot be
probed for existence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

from app.adapters.interfaces import AdapterBundle
from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode, ViveError, session_not_found
from app.core.security import (
    ANONYMOUS,
    AuditEvent,
    Principal,
    RateLimiter,
    ReplayGuard,
    audit,
    principal_for_token,
)
from app.core.session_manager import SessionManager
from app.store.memory import InMemoryEventStore
from app.ws.manager import ConnectionManager


@dataclass
class AppState:
    settings: Settings
    store: InMemoryEventStore
    adapters: AdapterBundle
    sessions: SessionManager
    connections: ConnectionManager
    rate_limiter: RateLimiter
    create_limiter: RateLimiter
    replay_guard: ReplayGuard
    owners: dict[str, str] = field(default_factory=dict)
    """session_id -> principal_id. Ownership is tracked outside the session
    record so the wire schema carries no identity data."""


def get_state(request: Request) -> AppState:
    return request.app.state.vive


def get_sessions(state: Annotated[AppState, Depends(get_state)]) -> SessionManager:
    return state.sessions


def get_store(state: Annotated[AppState, Depends(get_state)]) -> InMemoryEventStore:
    return state.store


def _token_from_header(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def resolve_principal(settings: Settings, header: str | None) -> Principal:
    """Authenticates, or raises UNAUTHENTICATED when auth is enforced."""
    if not settings.auth_enforced:
        return ANONYMOUS
    token = _token_from_header(header)
    if token is None or token not in settings.tokens:
        audit(AuditEvent.AUTH_FAILED, detail="invalid or missing bearer token")
        raise ViveError(ErrorCode.UNAUTHENTICATED, "Valid bearer token required.")
    return principal_for_token(token)


async def require_principal(request: Request) -> Principal:
    settings = get_settings()

    # TLS enforcement, when the deployment says it terminates TLS upstream.
    if settings.require_tls:
        forwarded = request.headers.get("x-forwarded-proto", request.url.scheme)
        if forwarded != "https":
            raise ViveError(ErrorCode.FORBIDDEN, "TLS is required for this endpoint.")

    principal = resolve_principal(settings, request.headers.get("authorization"))

    state: AppState = request.app.state.vive
    if not state.rate_limiter.allow(principal.principal_id):
        audit(AuditEvent.RATE_LIMITED, principal)
        raise ViveError(ErrorCode.RATE_LIMITED, "Too many requests. Try again shortly.")

    request.state.principal = principal
    return principal


def claim_ownership(state: AppState, session_id: str, principal: Principal) -> None:
    state.owners[session_id] = principal.principal_id


def require_owned(
    state: AppState,
    session_id: str,
    principal: Principal,
) -> None:
    """Raises SESSION_NOT_FOUND when the principal does not own the session.

    404 rather than 403 on purpose: a 403 would confirm the session exists,
    turning the endpoint into an id oracle.
    """
    owner = state.owners.get(session_id)
    if owner is None:
        return  # created before ownership tracking, or auth disabled
    if owner != principal.principal_id and not principal.is_admin:
        audit(AuditEvent.SESSION_ACCESS_DENIED, principal, session_id)
        raise session_not_found(session_id)


PrincipalDep = Annotated[Principal, Depends(require_principal)]
SessionsDep = Annotated[SessionManager, Depends(get_sessions)]
StoreDep = Annotated[InMemoryEventStore, Depends(get_store)]
StateDep = Annotated[AppState, Depends(get_state)]

# Retained for routes that need authentication without the principal object.
AuthDep = Annotated[Principal, Depends(require_principal)]
