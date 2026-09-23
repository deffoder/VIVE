"""Structured error model.

Mirrors docs/API_SPEC.md 7. Every failure leaves the API as the same envelope
with a stable machine-readable `code`, so clients branch on the code rather
than on prose. Stack traces and internal detail never cross the boundary
(docs/SECURITY_SPEC.md 5).
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    PACKET_NOT_FOUND = "PACKET_NOT_FOUND"
    SESSION_ALREADY_ENDED = "SESSION_ALREADY_ENDED"
    RATE_LIMITED = "RATE_LIMITED"
    ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.PACKET_NOT_FOUND: 404,
    ErrorCode.SESSION_ALREADY_ENDED: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.ADAPTER_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ViveError(Exception):
    """Application error carrying an API error code.

    `detail` is optional and must stay safe to show a caller - never an
    exception repr, a path or a secret.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    @property
    def status_code(self) -> int:
        return _STATUS[self.code]


def session_not_found(session_id: str) -> ViveError:
    return ViveError(ErrorCode.SESSION_NOT_FOUND, f"No session with id {session_id}.")


def packet_not_found(packet_id: str) -> ViveError:
    return ViveError(ErrorCode.PACKET_NOT_FOUND, f"No packet with id {packet_id}.")


def validation_error(message: str) -> ViveError:
    """Rejects a malformed payload with a structured 400 rather than a 500."""
    return ViveError(ErrorCode.VALIDATION_ERROR, message)


def session_already_ended(session_id: str) -> ViveError:
    return ViveError(
        ErrorCode.SESSION_ALREADY_ENDED,
        f"Session {session_id} has already ended.",
    )
