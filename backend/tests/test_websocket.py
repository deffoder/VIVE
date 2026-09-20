"""WebSocket lifecycle, sequencing and failure tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import drain_until, ws_send

SCAM_LINE = "OTP sollunga, illa account close aagidum. This is a synthetic voice."


def test_connect_receives_session_state(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "session.state"
        assert frame["session_id"] == session_id
        assert frame["seq"] == 1


def test_unknown_session_is_rejected(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/sessions/VS-999/stream") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert frame["data"]["code"] == "SESSION_NOT_FOUND"


def test_ended_session_is_rejected(client: TestClient, session_id: str) -> None:
    client.post(f"/api/v1/sessions/{session_id}/end")
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        frame = ws.receive_json()
        assert frame["data"]["code"] == "SESSION_ALREADY_ENDED"


def test_packet_frame_is_fully_traceable(client: TestClient, session_id: str) -> None:
    """Every packet event must carry the traceability fields the spec requires."""
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws_send(ws, SCAM_LINE)
        frame = drain_until(ws, "packet.new")

    packet = frame["data"]
    assert packet["session_id"] == session_id
    assert packet["packet_id"] == "P001"
    assert packet["timestamp"]
    assert packet["duration_sec"] == 2
    assert packet["risk"]["score"] >= 0
    assert 0.0 <= packet["risk"]["confidence"] <= 1.0
    assert packet["aasist"]["model_version"] == "demo"
    assert packet["adapter_mode"] == "mock"
    assert packet["window"]["start_sec"] == 0.0
    assert packet["window"]["end_sec"] == 2.0


def test_sequence_numbers_are_monotonic(client: TestClient, session_id: str) -> None:
    seqs = []
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        seqs.append(ws.receive_json()["seq"])
        for _ in range(3):
            ws_send(ws, SCAM_LINE)
            seqs.append(drain_until(ws, "packet.new")["seq"])
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_windows_overlap_with_two_second_window_one_second_stride(
    client: TestClient, session_id: str
) -> None:
    windows = []
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for _ in range(3):
            ws_send(ws, SCAM_LINE)
            windows.append(drain_until(ws, "packet.new")["data"]["window"])

    for w in windows:
        assert w["end_sec"] - w["start_sec"] == 2.0
    for a, b in zip(windows, windows[1:]):
        assert b["start_sec"] - a["start_sec"] == 1.0
        assert b["start_sec"] < a["end_sec"], "windows must overlap"


def test_malformed_frame_returns_error_and_keeps_connection(
    client: TestClient, session_id: str
) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_text("{not json at all")
        error = drain_until(ws, "error")
        assert error["data"]["code"] == "VALIDATION_ERROR"

        # The connection must survive a bad frame.
        ws_send(ws, SCAM_LINE)
        assert drain_until(ws, "packet.new")["data"]["packet_id"] == "P001"


def test_unknown_frame_type_is_rejected(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "client.nonsense"})
        assert drain_until(ws, "error")["data"]["code"] == "VALIDATION_ERROR"


def test_invalid_base64_audio_is_rejected(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "client.audio", "audio_b64": "!!!not-base64!!!"})
        assert drain_until(ws, "error")["data"]["code"] == "VALIDATION_ERROR"


def test_pause_suppresses_processing_and_resume_restores(
    client: TestClient, session_id: str
) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "client.pause"})
        ws_send(ws, SCAM_LINE)
        ws.send_json({"type": "client.resume"})
        ws_send(ws, SCAM_LINE)
        packet = drain_until(ws, "packet.new")["data"]

    # Only the post-resume window was analysed.
    assert packet["packet_id"] == "P001"


def test_client_end_closes_the_session(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "client.end"})
        drain_until(ws, "session.ended")

    assert client.get(f"/api/v1/sessions/{session_id}").json()["status"] == "ENDED"


def test_reconnect_continues_sequence_and_backfills(
    client: TestClient, session_id: str
) -> None:
    """Reconnect safety: seq keeps climbing and missed packets are fetchable."""
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws_send(ws, SCAM_LINE)
        first = drain_until(ws, "packet.new")
    last_seq_before = first["seq"]

    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        state = ws.receive_json()
        assert state["seq"] > last_seq_before, "sequence must not restart on reconnect"
        ws_send(ws, SCAM_LINE)
        second = drain_until(ws, "packet.new")

    assert second["data"]["packet_id"] == "P002"

    # A client that missed P001 can backfill it over REST.
    backfill = client.get(
        f"/api/v1/sessions/{session_id}/packets", params={"since_seq": 1}
    ).json()
    assert [p["packet_id"] for p in backfill] == ["P002"]


def test_risk_update_frame_carries_separate_score_and_confidence(
    client: TestClient, session_id: str
) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws_send(ws, SCAM_LINE)
        update = drain_until(ws, "risk.update")["data"]

    assert update["current_risk"]["score"] is not None
    assert update["current_risk"]["confidence"] is not None
    assert update["current_risk"]["score"] != update["current_risk"]["confidence"]
    assert update["packets_processed"] == 1
