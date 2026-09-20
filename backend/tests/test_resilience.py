"""Failure-mode tests.

The system must fail gracefully rather than collapse. Each test drives one of
the conditions the phase specifies and asserts the backend stays usable.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tests.conftest import drain_until, ws_send


# ------------------------------------------------------- connection failures


def test_abrupt_disconnect_leaves_the_session_usable(client: TestClient, session_id: str) -> None:
    """A dropped socket must not corrupt session state."""
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws_send(ws, "OTP sollunga now.")
        drain_until(ws, "packet.new")
        # Leaving the context manager closes without a clean client.end.

    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["packets_processed"] == 1
    assert session["status"] == "STREAMING"


def test_reconnect_after_drop_continues_the_session(client: TestClient, session_id: str) -> None:
    for expected in ("P001", "P002", "P003"):
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
            ws.receive_json()
            ws_send(ws, "OTP sollunga now.")
            assert drain_until(ws, "packet.new")["data"]["packet_id"] == expected


def test_second_connection_supersedes_the_first(client: TestClient, session_id: str) -> None:
    """A reconnect must not leave two live sockets on one session."""
    first = client.websocket_connect(f"/api/v1/sessions/{session_id}/stream")
    ws1 = first.__enter__()
    ws1.receive_json()

    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws2:
        assert ws2.receive_json()["type"] == "session.state"
        ws_send(ws2, "OTP sollunga now.")
        assert drain_until(ws2, "packet.new")["data"]["packet_id"] == "P001"

    try:
        first.__exit__(None, None, None)
    except Exception:
        pass  # the superseded socket may already be closed


# ------------------------------------------------------------ bad input


def test_malformed_json_does_not_kill_the_stream(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for junk in ("{", "[]", "null", "not json", '{"type":}'):
            ws.send_text(junk)
            assert drain_until(ws, "error")["data"]["code"] == "VALIDATION_ERROR"
        ws_send(ws, "OTP sollunga now.")
        assert drain_until(ws, "packet.new")["data"]["packet_id"] == "P001"


def test_oversized_audio_frame_is_rejected(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00" * 2_000_000)
        assert drain_until(ws, "error")["data"]["code"] == "VALIDATION_ERROR"


def test_transcript_length_is_bounded(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "client.audio", "transcript": "x" * 10_000})
        assert drain_until(ws, "error")["data"]["code"] == "VALIDATION_ERROR"


def test_invalid_context_is_rejected(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/api/v1/sessions/{session_id}/context",
        json={"caller_verified": "not a boolean"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_out_of_range_values_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/policies/evaluate", json={"risk_score": 500, "confidence": 2.0}
    )
    assert response.status_code == 400


# --------------------------------------------------------- degraded analysis


def test_empty_transcript_yields_insufficient_data_not_a_crash(
    client: TestClient, session_id: str
) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "client.audio", "transcript": ""})
        packet = drain_until(ws, "packet.new")["data"]

    assert packet["quality"] == "NO_SPEECH"
    assert packet["asr"]["transcript"] is None
    assert packet["asr"]["status"] == "INSUFFICIENT_AUDIO"
    assert packet["risk"]["score"] <= 15, "unusable audio must not raise risk"
    assert packet["risk"]["confidence"] < 0.5, "confidence must fall instead"


def test_no_audio_at_all_is_handled(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_bytes(b"")
        ws.send_json({"type": "client.audio"})
        packet = drain_until(ws, "packet.new")["data"]
    assert packet["quality"] == "NO_SPEECH"


def test_speaker_model_unavailable_reports_status_not_zero(
    client: TestClient, session_id: str
) -> None:
    """The speaker adapter has no enrolment, which is the model-unavailable case."""
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws_send(ws, "OTP sollunga now.")
        packet = drain_until(ws, "packet.new")["data"]

    assert packet["ecapa"]["status"] == "NO_REFERENCE"
    assert packet["ecapa"]["similarity"] is None, "must be null, never 0"
    # The session still produced a usable assessment without that signal.
    assert packet["risk"]["score"] >= 0


# ----------------------------------------------------------- lifecycle


def test_streaming_to_an_ended_session_is_refused(client: TestClient, session_id: str) -> None:
    client.post(f"/api/v1/sessions/{session_id}/end")
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        assert ws.receive_json()["data"]["code"] == "SESSION_ALREADY_ENDED"


def test_operations_on_a_deleted_session_return_404(client: TestClient, session_id: str) -> None:
    client.delete(f"/api/v1/sessions/{session_id}")
    for path in ("", "/packets", "/transcript", "/risk", "/report"):
        assert client.get(f"/api/v1/sessions/{session_id}{path}").status_code == 404


def test_packet_cap_bounds_memory(client: TestClient, monkeypatch) -> None:
    """The per-session packet cap must hold, or a long call exhausts memory."""
    from app.store.memory import InMemoryEventStore, SessionRecord
    from app.schemas.models import Session, SessionStatus, SourceType

    store = InMemoryEventStore(max_packets_per_session=3)
    session = Session(session_id="VS-X", status=SessionStatus.READY, source_type=SourceType.VOIP)
    store.create(SessionRecord(session=session))

    from app.schemas.models import (
        AasistEvidence, AnalyzerStatus, AsrEvidence, AudioQuality, BehaviorEvidence,
        ContextEvidence, EcapaEvidence, Intent, IntentEvidence, Packet, PacketRisk, RiskLevel,
    )

    def make(i: int) -> Packet:
        return Packet(
            packet_id=f"P{i:03d}", timestamp="00:02", duration_sec=2, language="en",
            quality=AudioQuality.GOOD, aasist=AasistEvidence(score=0.1),
            ecapa=EcapaEvidence(status=AnalyzerStatus.NO_REFERENCE), asr=AsrEvidence(),
            intent=IntentEvidence(label=Intent.NORMAL_CONVERSATION),
            behavior=BehaviorEvidence(), context=ContextEvidence(caller_verified=True),
            risk=PacketRisk(score=5, level=RiskLevel.LOW, confidence=0.9),
        )

    results = [store.append_packet("VS-X", make(i)) for i in range(1, 6)]
    assert results == [True, True, True, False, False]
    assert len(store.get("VS-X").packets) == 3


# ------------------------------------------------------------- demo reset


def test_demo_reset_clears_state(client: TestClient) -> None:
    client.post("/api/v1/sessions", json={"source_type": "VOIP"})
    client.post("/api/v1/sessions", json={"source_type": "VOIP"})
    assert len(client.get("/api/v1/sessions").json()) == 2

    body = client.post("/api/v1/demo/reset").json()
    assert body["reset"] is True
    assert body["sessions_cleared"] == 2
    assert client.get("/api/v1/sessions").json() == []


def test_demo_reset_makes_a_run_repeatable(client: TestClient) -> None:
    def run() -> list[int]:
        client.post("/api/v1/demo/reset")
        sid = client.post("/api/v1/sessions", json={"source_type": "VOIP"}).json()["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{sid}/stream") as ws:
            ws.receive_json()
            for line in ("Account blocked aagidum.", "OTP sollunga now. synthetic voice."):
                ws_send(ws, line)
                drain_until(ws, "packet.new")
        return [p["risk"]["score"] for p in
                client.get(f"/api/v1/sessions/{sid}/packets").json()]

    assert run() == run()


# ----------------------------------------------------------- performance


def test_measured_packet_latency_is_recorded(client: TestClient, session_id: str) -> None:
    """Records ACTUAL measured latency. No target is asserted and none is claimed."""
    latencies: list[float] = []
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for _ in range(10):
            started = time.perf_counter()
            ws_send(ws, "OTP sollunga now, account blocked.")
            drain_until(ws, "packet.new")
            latencies.append((time.perf_counter() - started) * 1000)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    print(f"\nMEASURED in-process packet latency: p50={p50:.1f}ms p95={p95:.1f}ms n={len(latencies)}")

    # Asserts only that measurement happened, not a performance claim. These
    # are in-process TestClient timings with mock adapters, not a benchmark of
    # a deployed system with real models.
    assert len(latencies) == 10
    assert all(v >= 0 for v in latencies)
