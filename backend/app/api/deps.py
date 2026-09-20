"""Shared dependencies: application state and the authentication boundary.

Auth model (docs/SECURITY_SPEC.md 2): bearer token on REST, the same token on
the WebSocket. When no tokens are configured the boundary is present but not
enforced, which is the documented development posture - and app.main refuses to
start in production without tokens, so "open" can never be the production state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.adapters.interfaces import AdapterBundle
from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode, ViveError
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


def check_token(settings: Settings, header: str | None) -> None:
    """Raises UNAUTHENTICATED when auth is enforced and the token is absent/wrong."""
    if not settings.auth_enforced:
        return
    token = _token_from_header(header)
    if token is None or token not in settings.tokens:
        raise ViveError(ErrorCode.UNAUTHENTICATED, "Valid bearer token required.")


async def require_auth(request: Request) -> None:
    settings = get_settings()
    check_token(settings, request.headers.get("authorization"))


AuthDep = Annotated[None, Depends(require_auth)]
SessionsDep = Annotated[SessionManager, Depends(get_sessions)]
StoreDep = Annotated[InMemoryEventStore, Depends(get_store)]
StateDep = Annotated[AppState, Depends(get_state)]
