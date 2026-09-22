"""REST API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}

    ready = client.get("/api/v1/ready").json()
    assert ready["ready"] is True
    assert ready["api_version"] == "v1"
    # Every adapter must declare its mode so a demo is never mistaken for real.
    assert all(a["mode"] == "mock" for a in ready["adapters"].values())
    # Speaker has no enrolment source (BLOCKERS O3), so it is NO_REFERENCE.
    assert ready["adapters"]["speaker"]["status"] == "NO_REFERENCE"


def test_version_reports_mock_mode(client: TestClient) -> None:
    body = client.get("/api/v1/version").json()
    assert body["adapter_mode"] == "mock"
    assert body["api_version"] == "v1"


def test_legacy_v1_prefix_also_resolves(client: TestClient) -> None:
    """The external prompt uses /v1; CLAUDE.md uses /api/v1. Both must work."""
    assert client.get("/v1/ready").status_code == 200


def test_create_and_fetch_session(client: TestClient) -> None:
    created = client.post("/api/v1/sessions", json={"source_type": "VOIP"})
    assert created.status_code == 201
    body = created.json()
    assert body["session_id"].startswith("VS-")
    assert body["status"] == "READY"
    assert body["stream_path"].endswith("/stream")

    fetched = client.get(f"/api/v1/sessions/{body['session_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["session_id"] == body["session_id"]


def test_unknown_session_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/sessions/VS-999")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "SESSION_NOT_FOUND"
    assert error["request_id"]
    # No stack trace or internal detail may cross the boundary.
    assert "Traceback" not in response.text


def test_invalid_payload_returns_400_without_echoing_values(client: TestClient) -> None:
    response = client.post("/api/v1/sessions", json={"source_type": "NOT_A_SOURCE"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "NOT_A_SOURCE" not in response.text


def test_unknown_field_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions", json={"source_type": "VOIP", "unexpected": 1}
    )
    assert response.status_code == 400


def test_end_session_is_idempotent_guarded(client: TestClient, session_id: str) -> None:
    assert client.post(f"/api/v1/sessions/{session_id}/end").status_code == 200
    second = client.post(f"/api/v1/sessions/{session_id}/end")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "SESSION_ALREADY_ENDED"


def test_set_context(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/api/v1/sessions/{session_id}/context",
        json={"caller_verified": True, "session_authenticated": True},
    )
    assert response.status_code == 200
    assert response.json()["context"]["caller_verified"] is True


def test_policy_evaluate_gates_on_confidence(client: TestClient) -> None:
    low_confidence = client.post(
        "/api/v1/policies/evaluate",
        json={"risk_score": 92, "confidence": 0.2, "intent": "OTP_REQUEST"},
    ).json()
    assert low_confidence["should_alert"] is False

    high_confidence = client.post(
        "/api/v1/policies/evaluate",
        json={"risk_score": 92, "confidence": 0.85, "intent": "OTP_REQUEST"},
    ).json()
    assert high_confidence["should_alert"] is True
    assert high_confidence["recommended_action"] == "HOLD_SENSITIVE_ACTION"
    assert high_confidence["policy_version"]


def test_webhook_test_signs_but_does_not_deliver(client: TestClient) -> None:
    response = client.post("/api/v1/webhooks/test", json={"event": "VOICE_RISK_ESCALATION"})
    assert response.status_code == 200
    body = response.json()
    assert body["delivered"] is False, "must not claim delivery it did not perform"
    assert body["event_id"].startswith("evt_")
    # Payload carries metadata only - never transcript text.
    assert "transcript" not in body["payload"]


def test_models_report_mode_and_no_accuracy(client: TestClient) -> None:
    models = client.get("/api/v1/models").json()
    ids = {m["id"] for m in models}
    assert {"aasist", "ecapa-tdnn", "indic-conformer-600m", "risk-fusion"} <= ids
    assert "indicconformer" not in ids, "stale pre-selection ASR id must not resurface"
    for model in models:
        assert "accuracy" not in model, "no unmeasured metric may be published"
    assert all(m["mode"] == "mock" for m in models if m["id"] != "risk-fusion")


def test_delete_session_actually_removes_it(client: TestClient, session_id: str) -> None:
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
    assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404


def test_models_report_the_version_that_actually_loaded(client: TestClient) -> None:
    """A model reported AVAILABLE must also say WHICH model it is.

    `version` was hard-coded to "demo" for mock and "" for everything else, so
    in real mode the Model Information screen showed adapters as AVAILABLE
    with a blank version - status without identity. An operator checking what
    is deployed needs the version more than the status.
    """
    models = client.get("/api/v1/models").json()
    assert models, "the inventory must not be empty"
    for model in models:
        assert model["version"], (
            f"{model['id']} reports status {model['status']} with no version"
        )
