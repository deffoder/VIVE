"""Security and privacy tests.

These verify controls actually behave as claimed. Passing them is NOT a
security certification — it is evidence that a designed control is wired up.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.core import ids
from app.core.config import get_settings
from app.core.logging import JsonFormatter, SensitiveDataFilter, redact
from app.core.security import (
    RateLimiter,
    ReplayGuard,
    Role,
    principal_for_token,
    sign_payload,
    verify_signature,
)
from app.main import create_app

TOKEN_A = "token-alpha-0123456789"
TOKEN_B = "token-bravo-9876543210"


@pytest.fixture
def secure_client(monkeypatch) -> TestClient:
    """A client with authentication actually enforced."""
    monkeypatch.setenv("VIVE_API_TOKENS", f"{TOKEN_A},{TOKEN_B}")
    get_settings.cache_clear()
    ids.reset_for_tests()
    app = create_app()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------ authentication


def test_unauthenticated_request_is_rejected(secure_client: TestClient) -> None:
    response = secure_client.get("/api/v1/sessions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_wrong_token_is_rejected(secure_client: TestClient) -> None:
    response = secure_client.get("/api/v1/sessions", headers=auth("not-a-real-token"))
    assert response.status_code == 401


def test_malformed_authorization_header_is_rejected(secure_client: TestClient) -> None:
    for header in ({"Authorization": TOKEN_A}, {"Authorization": "Basic abc"},
                   {"Authorization": "Bearer"}):
        assert secure_client.get("/api/v1/sessions", headers=header).status_code == 401


def test_valid_token_is_accepted(secure_client: TestClient) -> None:
    assert secure_client.get("/api/v1/sessions", headers=auth(TOKEN_A)).status_code == 200


# ------------------------------------------------------------- authorization


def test_one_principal_cannot_read_anothers_session(secure_client: TestClient) -> None:
    created = secure_client.post(
        "/api/v1/sessions", json={"source_type": "VOIP"}, headers=auth(TOKEN_A)
    ).json()
    session_id = created["session_id"]

    # Owner can read it.
    assert secure_client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(TOKEN_A)
    ).status_code == 200

    # A different principal cannot, and gets 404 rather than 403 so the id
    # cannot be probed for existence.
    other = secure_client.get(f"/api/v1/sessions/{session_id}", headers=auth(TOKEN_B))
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_cross_principal_packet_access_is_denied(secure_client: TestClient) -> None:
    session_id = secure_client.post(
        "/api/v1/sessions", json={"source_type": "VOIP"}, headers=auth(TOKEN_A)
    ).json()["session_id"]
    assert secure_client.get(
        f"/api/v1/sessions/{session_id}/packets", headers=auth(TOKEN_B)
    ).status_code == 404


def test_cross_principal_delete_is_denied(secure_client: TestClient) -> None:
    session_id = secure_client.post(
        "/api/v1/sessions", json={"source_type": "VOIP"}, headers=auth(TOKEN_A)
    ).json()["session_id"]
    assert secure_client.delete(
        f"/api/v1/sessions/{session_id}", headers=auth(TOKEN_B)
    ).status_code == 404
    # The owner's session survived the attempt.
    assert secure_client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(TOKEN_A)
    ).status_code == 200


def test_principal_id_is_derived_not_the_token(secure_client: TestClient) -> None:
    principal = principal_for_token(TOKEN_A)
    assert TOKEN_A not in principal.principal_id
    assert principal.principal_id.startswith("p_")
    assert principal.role is Role.ANALYST


# ----------------------------------------------------------- websocket auth


def test_websocket_rejects_missing_token(secure_client: TestClient) -> None:
    session_id = secure_client.post(
        "/api/v1/sessions", json={"source_type": "VOIP"}, headers=auth(TOKEN_A)
    ).json()["session_id"]
    with secure_client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert frame["data"]["code"] == "UNAUTHENTICATED"


def test_websocket_accepts_token_query_param(secure_client: TestClient) -> None:
    session_id = secure_client.post(
        "/api/v1/sessions", json={"source_type": "VOIP"}, headers=auth(TOKEN_A)
    ).json()["session_id"]
    with secure_client.websocket_connect(
        f"/api/v1/sessions/{session_id}/stream?token={TOKEN_A}"
    ) as ws:
        assert ws.receive_json()["type"] == "session.state"


# ------------------------------------------------------------- rate limiting


def test_rate_limiter_blocks_past_the_limit() -> None:
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert [limiter.allow("k", now=0.0) for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_window_expires() -> None:
    limiter = RateLimiter(limit=1, window_seconds=10)
    assert limiter.allow("k", now=0.0)
    assert not limiter.allow("k", now=5.0)
    assert limiter.allow("k", now=11.0)


def test_rate_limiter_is_per_key() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("a", now=0.0)
    assert limiter.allow("b", now=0.0)


def test_session_create_is_rate_limited(secure_client: TestClient, monkeypatch) -> None:
    # The configured create limit is 20 per window.
    codes = [
        secure_client.post(
            "/api/v1/sessions", json={"source_type": "VOIP"}, headers=auth(TOKEN_A)
        ).status_code
        for _ in range(25)
    ]
    assert 429 in codes, "session creation must be rate limited"
    assert codes[0] == 201


# ---------------------------------------------------------- replay protection


def test_replay_guard_rejects_a_repeated_event_id() -> None:
    guard = ReplayGuard()
    assert guard.check_and_record("evt_1")
    assert not guard.check_and_record("evt_1")
    assert guard.check_and_record("evt_2")


def test_replay_guard_memory_is_bounded() -> None:
    guard = ReplayGuard(capacity=3)
    for i in range(5):
        assert guard.check_and_record(f"evt_{i}")
    # The oldest has been evicted, so it is accepted again - bounded memory is
    # the deliberate trade-off, and it is stated rather than hidden.
    assert guard.check_and_record("evt_0")


# ------------------------------------------------------- webhook signatures


def test_signature_round_trips() -> None:
    body = b'{"event":"TEST"}'
    signature = sign_payload("k3y", body)
    assert verify_signature("k3y", body, signature)


def test_signature_rejects_a_tampered_body() -> None:
    signature = sign_payload("k3y", b'{"event":"TEST"}')
    assert not verify_signature("k3y", b'{"event":"TAMPERED"}', signature)


def test_signature_rejects_a_wrong_key() -> None:
    signature = sign_payload("k3y", b"body")
    assert not verify_signature("other", b"body", signature)


def test_webhook_test_never_claims_delivery(secure_client: TestClient) -> None:
    body = secure_client.post(
        "/api/v1/webhooks/test", json={"event": "VOICE_RISK_ESCALATION"}, headers=auth(TOKEN_A)
    ).json()
    assert body["delivered"] is False


# -------------------------------------------------------------------- privacy


def test_webhook_payload_carries_no_transcript(secure_client: TestClient) -> None:
    body = secure_client.post(
        "/api/v1/webhooks/test", json={"session_id": "VS-001"}, headers=auth(TOKEN_A)
    ).json()
    serialized = str(body["payload"]).lower()
    assert "transcript" not in serialized
    assert "audio" not in serialized


def test_redact_never_leaks_content() -> None:
    transcript = "OTP sollunga, account verify pannanum"
    out = redact(transcript)
    assert "OTP" not in out and "account" not in out
    assert out == f"<redacted:{len(transcript)}>"


def test_log_filter_scrubs_bearer_tokens() -> None:
    import logging

    record = logging.LogRecord(
        "t", logging.INFO, "f", 1, "Authorization: Bearer supersecrettoken123", None, None
    )
    SensitiveDataFilter().filter(record)
    assert "supersecrettoken123" not in record.getMessage()
    assert "<redacted>" in record.getMessage()


def test_log_filter_scrubs_api_keys() -> None:
    import logging

    record = logging.LogRecord(
        "t", logging.INFO, "f", 1, 'api_key="abcd1234efgh"', None, None
    )
    SensitiveDataFilter().filter(record)
    assert "abcd1234efgh" not in record.getMessage()


def test_json_formatter_omits_stack_traces() -> None:
    import logging

    try:
        raise ValueError("secret detail in here")
    except ValueError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, "f", 1, "failed", None, sys.exc_info())
    output = JsonFormatter().format(record)
    assert "Traceback" not in output
    assert "error_type" in output


def test_session_deletion_actually_deletes(secure_client: TestClient) -> None:
    session_id = secure_client.post(
        "/api/v1/sessions", json={"source_type": "VOIP"}, headers=auth(TOKEN_A)
    ).json()["session_id"]

    with secure_client.websocket_connect(
        f"/api/v1/sessions/{session_id}/stream?token={TOKEN_A}"
    ) as ws:
        ws.receive_json()
        ws.send_json({"type": "client.audio", "transcript": "OTP sollunga now."})
        for _ in range(6):
            if ws.receive_json()["type"] == "risk.update":
                break

    assert secure_client.get(
        f"/api/v1/sessions/{session_id}/transcript", headers=auth(TOKEN_A)
    ).json() != []

    assert secure_client.delete(
        f"/api/v1/sessions/{session_id}", headers=auth(TOKEN_A)
    ).status_code == 204

    # Everything derived from the session is gone, not tombstoned.
    assert secure_client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(TOKEN_A)
    ).status_code == 404
    assert secure_client.get(
        f"/api/v1/sessions/{session_id}/packets", headers=auth(TOKEN_A)
    ).status_code == 404


def test_raw_audio_is_not_retained_by_default() -> None:
    get_settings.cache_clear()
    assert get_settings().retain_raw_audio is False
