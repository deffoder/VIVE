"""Durable sessions: SQLite-backed store (docs/BLOCKERS.md O4).

Everything the backend knew used to die with the process, so a restart lost
every analysed call and the Android app - which treats the backend as the
source of truth - came back to an empty history.

These tests restart the store against the same file, which is the only way to
tell persistence from a cache that happens to still be warm.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.risk.temporal import TemporalState
from app.schemas.models import (
    Alert,
    AnalyzerStatus,
    AudioQuality,
    PacketRisk,
    RiskLevel,
    Session,
    SessionStatus,
    SourceType,
    TranscriptLine,
)
from app.store.memory import SessionRecord
from app.store.sqlite import SqliteEventStore


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as directory:
        yield os.path.join(directory, "vive.sqlite3")


def make_session(session_id: str = "VS-001") -> Session:
    return Session(
        session_id=session_id,
        status=SessionStatus.STREAMING,
        source_type=SourceType.IN_APP,
        started_at="2026-09-23T00:00:00Z",
    )


def make_packet(seq: int):
    from app.schemas.models import (
        AasistEvidence,
        AsrEvidence,
        BehaviorEvidence,
        ContextEvidence,
        EcapaEvidence,
        Intent,
        IntentEvidence,
        Packet,
    )
    return Packet(
        packet_id=f"P{seq:03d}",
        session_id="VS-001",
        seq=seq,
        timestamp="00:02",
        duration_sec=2,
        language="hi",
        quality=AudioQuality.GOOD,
        aasist=AasistEvidence(status=AnalyzerStatus.INSUFFICIENT_AUDIO),
        ecapa=EcapaEvidence(status=AnalyzerStatus.NO_REFERENCE),
        asr=AsrEvidence(transcript="नमस्ते", confidence=0.9),
        intent=IntentEvidence(label=Intent.NORMAL_CONVERSATION, confidence=0.8),
        behavior=BehaviorEvidence(),
        context=ContextEvidence(caller_verified=False),
        risk=PacketRisk(score=20 + seq, level=RiskLevel.LOW, confidence=0.8,
                        contributions={}, reasons=[]),
    )


def test_a_session_survives_a_restart(db_path):
    store = SqliteEventStore(db_path)
    store.create(SessionRecord(session=make_session()))
    store.close()

    reopened = SqliteEventStore(db_path)
    restored = reopened.get("VS-001")

    assert restored is not None, "the session did not survive the restart"
    assert restored.session.session_id == "VS-001"
    assert restored.session.source_type is SourceType.IN_APP
    reopened.close()


def test_packets_transcript_and_alerts_survive(db_path):
    store = SqliteEventStore(db_path)
    store.create(SessionRecord(session=make_session()))
    for seq in (1, 2, 3):
        store.append_packet("VS-001", make_packet(seq))
    store.append_transcript("VS-001", TranscriptLine(
        packet_id="P001", speaker="Caller", text="नमस्ते", language="hi"))
    store.append_alert("VS-001", Alert(
        alert_id="AL-001", session_id="VS-001", level=RiskLevel.HIGH,
        reason="Elevated social-engineering risk",
        raised_at="2026-09-23T00:00:05Z"))
    store.close()

    reopened = SqliteEventStore(db_path)
    restored = reopened.get("VS-001")

    assert [p.packet_id for p in restored.packets] == ["P001", "P002", "P003"]
    assert restored.packets[0].asr.transcript == "नमस्ते", "Unicode must round-trip"
    assert restored.packets[2].risk.score == 23
    assert len(restored.transcript) == 1
    assert len(restored.alerts) == 1
    assert reopened.all_alerts()[0].alert_id == "AL-001"
    reopened.close()


def test_risk_progression_survives_a_restart(db_path):
    """The EMA and escalation timings are what make a resumed call coherent.

    Without them a restart would restore the packets but reset the temporal
    state, so overall risk would start again from zero while the packet
    history said otherwise.
    """
    store = SqliteEventStore(db_path)
    record = SessionRecord(session=make_session())
    store.create(record)
    state: TemporalState = record.temporal
    for at, score in enumerate([10, 40, 80, 90]):
        state.update(score, 0.8, at)
    store.touch_session("VS-001")
    expected_ema = state.ema
    expected_level = state.level
    store.close()

    reopened = SqliteEventStore(db_path)
    restored = reopened.get("VS-001").temporal

    assert restored.packets == 4
    assert restored.ema == pytest.approx(expected_ema)
    assert restored.level is expected_level
    assert restored.timings.first_high_sec is not None
    reopened.close()


def test_an_ended_session_does_not_come_back_as_streaming(db_path):
    store = SqliteEventStore(db_path)
    record = SessionRecord(session=make_session())
    store.create(record)
    record.session.status = SessionStatus.ENDED
    record.session.ended_at = "2026-09-23T00:05:00Z"
    store.touch_session("VS-001")
    store.close()

    reopened = SqliteEventStore(db_path)
    assert reopened.get("VS-001").session.status is SessionStatus.ENDED
    reopened.close()


def test_deleting_a_session_removes_its_evidence_from_disk(db_path):
    """Deletion must be real, not a tombstone (docs/SECURITY_SPEC.md 4)."""
    store = SqliteEventStore(db_path)
    store.create(SessionRecord(session=make_session()))
    store.append_packet("VS-001", make_packet(1))
    store.append_alert("VS-001", Alert(
        alert_id="AL-001", session_id="VS-001", level=RiskLevel.HIGH,
        reason="x", raised_at="2026-09-23T00:00:05Z"))
    assert store.delete("VS-001") is True
    store.close()

    reopened = SqliteEventStore(db_path)
    assert reopened.get("VS-001") is None
    assert reopened.all_alerts() == [], "cascade did not remove the alerts"
    reopened.close()


def test_no_raw_audio_is_written_to_disk(db_path):
    """Enrolment audio and PCM must never reach the database file."""
    store = SqliteEventStore(db_path)
    record = SessionRecord(session=make_session())
    record.reference_audio = b"\x01\x02\x03RAWAUDIOMARKER\x04\x05"
    store.create(record)
    store.append_packet("VS-001", make_packet(1))
    store.close()

    with open(db_path, "rb") as handle:
        contents = handle.read()
    assert b"RAWAUDIOMARKER" not in contents, "raw audio reached the database"


def test_listing_survives_and_stays_ordered(db_path):
    store = SqliteEventStore(db_path)
    for index, sid in enumerate(["VS-001", "VS-002", "VS-003"]):
        session = make_session(sid)
        session.started_at = f"2026-09-23T00:0{index}:00Z"
        store.create(SessionRecord(session=session))
    store.close()

    reopened = SqliteEventStore(db_path)
    listed = [s.session_id for s in reopened.list_sessions(limit=10)]
    assert listed == ["VS-003", "VS-002", "VS-001"], "newest first"
    reopened.close()
