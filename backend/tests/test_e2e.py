"""End-to-end mock session.

Walks the exact Phase 3 acceptance flow:

  create session -> connect WebSocket -> send demo packet -> receive result
  event -> query session -> retrieve event history -> evaluate policy ->
  trigger test webhook -> disconnect -> reconnect

and the DEMO_SPEC scenarios that carry the product's claims.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import drain_until, ws_send

# Scripted scenario lines. Scenario data, not model output.
S3_SYNTHETIC_SCAM = [
    "Vanakkam, naan bank-la irundhu pesuren.",
    "Unga account-la oru problem irukku.",
    "Account blocked aagidum, seekiram pannunga.",
    "OTP sollunga now. synthetic voice.",
]
S2_HUMAN_SCAM = [
    "Namaste, main aapke bank se bol raha hoon.",
    "Aapke account mein suspicious transaction hua hai.",
    "Turant verify kijiye, warna account blocked.",
    "Aapka OTP bataiye immediately.",
]
S1_NORMAL = [
    "Hello, just calling about our meeting.",
    "Shall we say tomorrow afternoon?",
    "That works for me, thank you.",
]


def test_full_acceptance_flow(client: TestClient) -> None:
    # 1. create session
    created = client.post("/api/v1/sessions", json={"source_type": "VOIP"}).json()
    session_id = created["session_id"]
    assert created["status"] == "READY"

    # 2-4. connect, send demo packets, receive result events
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        assert ws.receive_json()["type"] == "session.state"
        for line in S3_SYNTHETIC_SCAM:
            ws_send(ws, line)
            packet = drain_until(ws, "packet.new")["data"]
            assert packet["adapter_mode"] == "mock"

    # 5. query session
    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["packets_processed"] == len(S3_SYNTHETIC_SCAM)
    assert session["status"] == "STREAMING"
    assert session["current_risk"] is not None
    assert session["overall_risk"] is not None

    # 6. retrieve event history (both spellings of the route)
    packets = client.get(f"/api/v1/sessions/{session_id}/packets").json()
    events = client.get(f"/api/v1/sessions/{session_id}/events").json()
    assert packets == events
    assert [p["packet_id"] for p in packets] == ["P001", "P002", "P003", "P004"]

    # 7. evaluate policy against the final packet
    final = packets[-1]
    decision = client.post(
        "/api/v1/policies/evaluate",
        json={
            "session_id": session_id,
            "risk_score": final["risk"]["score"],
            "risk_level": final["risk"]["level"],
            "confidence": final["risk"]["confidence"],
            "intent": final["intent"]["label"],
            "caller_verified": False,
        },
    ).json()
    assert decision["recommended_action"] in {
        "MONITOR", "WARN_USER", "SECONDARY_VERIFICATION", "ESCALATE", "HOLD_SENSITIVE_ACTION"
    }

    # 8. trigger the test webhook
    hook = client.post("/api/v1/webhooks/test", json={"session_id": session_id}).json()
    assert hook["delivered"] is False

    # 9-10. disconnect happened above; reconnect and continue
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        state = ws.receive_json()
        assert state["type"] == "session.state"
        ws_send(ws, "Transfer the money now.")
        assert drain_until(ws, "packet.new")["data"]["packet_id"] == "P005"

    assert client.post(f"/api/v1/sessions/{session_id}/end").json()["status"] == "ENDED"


def test_s3_synthetic_scam_escalates_and_alerts(client: TestClient) -> None:
    session_id = client.post("/api/v1/sessions", json={"source_type": "VOIP"}).json()["session_id"]
    alerts_seen = 0
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for line in S3_SYNTHETIC_SCAM:
            ws_send(ws, line)
            for _ in range(6):
                frame = ws.receive_json()
                if frame["type"] == "alert.raised":
                    alerts_seen += 1
                if frame["type"] == "risk.update":
                    break

    packets = client.get(f"/api/v1/sessions/{session_id}/packets").json()
    scores = [p["risk"]["score"] for p in packets]
    assert scores[-1] > scores[0], "risk must escalate across the call"
    assert max(scores) >= 65
    assert alerts_seen >= 1, "policy must raise an alert on a critical scam"


def test_s2_human_scam_escalates_without_synthetic_evidence(client: TestClient) -> None:
    """The most important scenario: a genuine human voice is not automatically safe."""
    session_id = client.post("/api/v1/sessions", json={"source_type": "VOIP"}).json()["session_id"]
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for line in S2_HUMAN_SCAM:
            ws_send(ws, line)
            drain_until(ws, "packet.new")

    packets = client.get(f"/api/v1/sessions/{session_id}/packets").json()
    assert max(p["risk"]["score"] for p in packets) >= 65
    for p in packets:
        assert p["aasist"]["score"] < 0.2, "anti-spoof evidence must stay low in S2"


def test_s1_normal_conversation_stays_low(client: TestClient) -> None:
    session_id = client.post("/api/v1/sessions", json={"source_type": "VOIP"}).json()["session_id"]
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for line in S1_NORMAL:
            ws_send(ws, line)
            drain_until(ws, "packet.new")

    packets = client.get(f"/api/v1/sessions/{session_id}/packets").json()
    assert all(p["risk"]["level"] == "LOW" for p in packets)
    alerts = client.get("/api/v1/alerts", params={"session_id": session_id}).json()
    assert alerts == [], "a benign call must not raise alerts"


def test_transcript_and_report_are_populated(client: TestClient) -> None:
    session_id = client.post("/api/v1/sessions", json={"source_type": "VOIP"}).json()["session_id"]
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws_send(ws, "OTP sollunga now.")
        drain_until(ws, "packet.new")

    transcript = client.get(f"/api/v1/sessions/{session_id}/transcript").json()
    assert len(transcript) == 1
    assert transcript[0]["packet_id"] == "P001"

    report = client.get(f"/api/v1/sessions/{session_id}/report").json()
    assert report["packets_processed"] == 1
    assert "timings" in report


def test_determinism_same_input_same_output(client: TestClient) -> None:
    """Demo mode must be repeatable, or a demo cannot be rehearsed."""

    def run() -> list[int]:
        sid = client.post("/api/v1/sessions", json={"source_type": "VOIP"}).json()["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{sid}/stream") as ws:
            ws.receive_json()
            for line in S3_SYNTHETIC_SCAM:
                ws_send(ws, line)
                drain_until(ws, "packet.new")
        return [p["risk"]["score"] for p in
                client.get(f"/api/v1/sessions/{sid}/packets").json()]

    assert run() == run()
