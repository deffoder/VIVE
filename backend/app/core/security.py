"""Security primitives: principals, ownership, rate limiting, audit and replay.

Implements the controls in docs/SECURITY_SPEC.md. Every control here is
implemented and tested, but **none of it is a certification**: this is a
prototype hardening pass, not an audited production deployment.

Nothing in this module is claimed to be production-secure. Where a control is
designed but not deployed, it is described as such.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock

from app.core.logging import get_logger

audit_log = get_logger("vive.audit")


class Role(StrEnum):
    """Coarse RBAC roles.

    Deliberately few. A role model finer than the product actually enforces
    would be decoration; these three map onto real capability differences.
    """

    VIEWER = "viewer"
    """Read sessions and alerts owned by the principal."""

    ANALYST = "analyst"
    """Viewer, plus create/stream sessions and acknowledge alerts."""

    ADMIN = "admin"
    """Analyst, plus delete sessions and read any principal's data."""


@dataclass(frozen=True)
class Principal:
    """An authenticated caller."""

    principal_id: str
    role: Role = Role.ANALYST

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    def can_write(self) -> bool:
        return self.role in (Role.ANALYST, Role.ADMIN)

    def can_delete(self) -> bool:
        return self.role is Role.ADMIN


ANONYMOUS = Principal(principal_id="anonymous", role=Role.ANALYST)
"""Used when auth is not enforced (development only).

app.main refuses to start in production without tokens, so this principal can
never be the production identity.
"""


def principal_for_token(token: str) -> Principal:
    """Derives a stable principal id from a token without storing the token.

    The id is a truncated HMAC-free digest: it identifies the caller in logs and
    ownership checks while never putting the credential itself in memory
    structures, logs or audit records (docs/SECURITY_SPEC.md 5).
    """
    digest = hashlib.sha256(token.encode()).hexdigest()[:16]
    return Principal(principal_id=f"p_{digest}", role=Role.ANALYST)


# --------------------------------------------------------------- rate limiting


@dataclass
class _Window:
    hits: deque[float] = field(default_factory=deque)


class RateLimiter:
    """Fixed-window-per-key limiter.

    In-process and therefore per-node: it is a guard against a runaway or
    careless client, not a defence against a distributed attacker. Stated
    plainly because claiming otherwise would overstate the control.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, _Window] = defaultdict(_Window)
        self._lock = RLock()

    def allow(self, key: str, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        with self._lock:
            window = self._windows[key]
            cutoff = current - self.window_seconds
            while window.hits and window.hits[0] < cutoff:
                window.hits.popleft()
            if len(window.hits) >= self.limit:
                return False
            window.hits.append(current)
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


# ------------------------------------------------------------ replay guard


class ReplayGuard:
    """Rejects a repeated event id within a bounded memory.

    Used for webhook idempotency. Bounded on purpose: an unbounded set of seen
    ids is a memory leak on a long-running process.
    """

    def __init__(self, capacity: int = 10_000) -> None:
        self._seen: deque[str] = deque(maxlen=capacity)
        self._index: set[str] = set()
        self._lock = RLock()

    def check_and_record(self, event_id: str) -> bool:
        """True when the id is new; False when it is a replay."""
        with self._lock:
            if event_id in self._index:
                return False
            if len(self._seen) == self._seen.maxlen and self._seen:
                self._index.discard(self._seen[0])
            self._seen.append(event_id)
            self._index.add(event_id)
            return True

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()
            self._index.clear()


# ------------------------------------------------------------------- audit


class AuditEvent(StrEnum):
    SESSION_CREATED = "session.created"
    SESSION_ENDED = "session.ended"
    SESSION_DELETED = "session.deleted"
    SESSION_ACCESS_DENIED = "session.access_denied"
    STREAM_OPENED = "stream.opened"
    STREAM_CLOSED = "stream.closed"
    AUTH_FAILED = "auth.failed"
    RATE_LIMITED = "rate.limited"
    WEBHOOK_TEST = "webhook.test"
    ALERT_RAISED = "alert.raised"


def audit(
    event: AuditEvent,
    principal: Principal | None = None,
    session_id: str | None = None,
    detail: str | None = None,
) -> None:
    """Records a security-relevant action.

    Carries identifiers only. Never a token, never transcript text, never audio
    (docs/SECURITY_SPEC.md 5).
    """
    audit_log.info(
        event.value,
        extra={
            "event": event.value,
            "session_id": session_id,
            "request_id": principal.principal_id if principal else None,
            "status": detail,
        },
    )


# ---------------------------------------------------------------- webhooks


def sign_payload(key: str, body: bytes) -> str:
    """HMAC-SHA256 signature for an outbound webhook."""
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(key: str, body: bytes, signature: str) -> bool:
    """Constant-time comparison, so a timing side channel cannot leak the key."""
    expected = sign_payload(key, body)
    return hmac.compare_digest(expected, signature)
