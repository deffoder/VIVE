"""Durable event store: in-memory reads, write-through to SQLite.

`docs/BLOCKERS.md` O4 left the persistence engine unchosen, so everything the
backend knew died with the process. That was acceptable while the pipeline was
being wired and is not acceptable for a product: a restart lost every analysed
call, and the Android app - which treats the backend as the source of truth -
came back to an empty history.

Design, and why this shape
--------------------------
This subclasses the in-memory store rather than replacing it. Reads stay
in-memory and therefore stay fast and lock-simple; every mutation also writes
through to SQLite; construction loads what is already there. The alternative -
querying SQLite on every read - would have put a database round trip inside
the packet path, which runs every second per session.

`sqlite3` is in the standard library, so durability costs no new dependency.
A single file is also the right scale: this is one node holding recent
sessions, not a cluster.

What is stored, and what deliberately is not
--------------------------------------------
Sessions, packets, transcripts and alerts are stored as the JSON their Pydantic
models already produce, so the schema cannot drift from the API contract.

**Raw audio is never written.** `SessionRecord.reference_audio` is skipped
entirely. Transcripts are stored because a call report is useless without
them, and `SECURITY_SPEC.md` §4 treats them as sensitive rather than
forbidden - retention is enforced by deleting sessions, which deletes their
rows.

`TemporalState` is persisted as its fields rather than pickled: the EMA, packet
count, level and escalation timings are what make risk progression survive a
restart, and pickling a live object into a database is how a schema becomes
un-migratable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

from app.risk.temporal import TemporalState
from app.schemas.models import (
    Alert,
    EscalationTimings,
    Packet,
    RiskLevel,
    Session,
    TranscriptLine,
)
from app.store.memory import InMemoryEventStore, SessionRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   TEXT,
    payload      TEXT NOT NULL,
    temporal     TEXT NOT NULL,
    next_seq     INTEGER NOT NULL DEFAULT 1,
    enrolment    TEXT
);
CREATE TABLE IF NOT EXISTS packets (
    session_id   TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    payload      TEXT NOT NULL,
    PRIMARY KEY (session_id, seq),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS transcript (
    session_id   TEXT NOT NULL,
    idx          INTEGER NOT NULL,
    payload      TEXT NOT NULL,
    PRIMARY KEY (session_id, idx),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id     TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    payload      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
"""


def _temporal_to_json(state: TemporalState) -> str:
    return json.dumps({
        "ema": state.ema,
        "packets": state.packets,
        "level": state.level.value,
        "peak_score": state.peak_score,
        "timings": {
            "first_anomaly_sec": state.timings.first_anomaly_sec,
            "first_warning_sec": state.timings.first_warning_sec,
            "first_high_sec": state.timings.first_high_sec,
            "first_critical_sec": state.timings.first_critical_sec,
        },
    })


def _enrolment_to_json(record: SessionRecord) -> str | None:
    """Serialises the enrolled voiceprint.

    The EMBEDDING is stored, never the audio it came from. A voiceprint is
    sensitive; keeping the recording as well would retain a copy of someone's
    voice for no purpose the embedding does not already serve
    (docs/SECURITY_SPEC.md 4).
    """
    if not record.reference_embedding:
        return None
    return json.dumps({
        "embedding": record.reference_embedding,
        "enrolled_at": record.enrolled_at,
        "label": record.enrolment_label,
    })


def _enrolment_from_json(record: SessionRecord, raw: str | None) -> None:
    if not raw:
        return
    data = json.loads(raw)
    record.reference_embedding = data.get("embedding")
    record.enrolled_at = data.get("enrolled_at")
    record.enrolment_label = data.get("label")


def _temporal_from_json(raw: str) -> TemporalState:
    data = json.loads(raw)
    timings = data.get("timings", {})
    state = TemporalState(
        ema=float(data.get("ema", 0.0)),
        packets=int(data.get("packets", 0)),
        level=RiskLevel(data.get("level", RiskLevel.LOW.value)),
        timings=EscalationTimings(
            first_anomaly_sec=timings.get("first_anomaly_sec"),
            first_warning_sec=timings.get("first_warning_sec"),
            first_high_sec=timings.get("first_high_sec"),
            first_critical_sec=timings.get("first_critical_sec"),
        ),
    )
    state.peak_score = int(data.get("peak_score", 0))
    return state


class SqliteEventStore(InMemoryEventStore):
    """In-memory store with write-through durability."""

    def __init__(self, path: str, max_packets_per_session: int = 10_000) -> None:
        super().__init__(max_packets_per_session=max_packets_per_session)
        self._path = path
        self._db_lock = threading.RLock()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        # check_same_thread=False because FastAPI serves WebSocket frames and
        # REST calls from different threads; every access is guarded below.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        with self._db_lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self._restore()

    # -- restore ----------------------------------------------------------
    def _restore(self) -> None:
        """Loads persisted sessions back into memory at start-up."""
        with self._db_lock:
            rows = self._db.execute(
                "SELECT session_id, payload, temporal, next_seq, enrolment "
                "FROM sessions",
            ).fetchall()
            for session_id, payload, temporal, next_seq, enrolment in rows:
                record = SessionRecord(
                    session=Session.model_validate_json(payload),
                    temporal=_temporal_from_json(temporal),
                    next_seq=int(next_seq),
                )
                _enrolment_from_json(record, enrolment)
                record.packets = [
                    Packet.model_validate_json(p) for (p,) in self._db.execute(
                        "SELECT payload FROM packets WHERE session_id=? ORDER BY seq",
                        (session_id,)).fetchall()
                ]
                record.transcript = [
                    TranscriptLine.model_validate_json(p) for (p,) in self._db.execute(
                        "SELECT payload FROM transcript WHERE session_id=? ORDER BY idx",
                        (session_id,)).fetchall()
                ]
                record.alerts = [
                    Alert.model_validate_json(p) for (p,) in self._db.execute(
                        "SELECT payload FROM alerts WHERE session_id=?",
                        (session_id,)).fetchall()
                ]
                # Straight into the parent's dict: going through create()
                # would write everything back out again on every start-up.
                self._records[session_id] = record

    # -- write-through ----------------------------------------------------
    def create(self, record: SessionRecord) -> None:
        super().create(record)
        self._persist_session(record)

    def _persist_session(self, record: SessionRecord) -> None:
        """Upsert, never INSERT OR REPLACE.

        SQLite implements REPLACE as DELETE followed by INSERT. With
        `foreign_keys=ON` and `ON DELETE CASCADE` on the child tables, saving a
        session therefore deleted every packet, transcript line and alert
        belonging to it. The symptom was silent: the session row looked
        correct, the write reported success, and the evidence was gone - which
        only showed up on restart.

        `ON CONFLICT ... DO UPDATE` updates the row in place, so the children
        are untouched.
        """
        with self._db_lock:
            self._db.execute(
                "INSERT INTO sessions "
                "(session_id, started_at, payload, temporal, next_seq, enrolment) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "started_at=excluded.started_at, payload=excluded.payload, "
                "temporal=excluded.temporal, next_seq=excluded.next_seq, "
                "enrolment=excluded.enrolment",
                (record.session.session_id, record.session.started_at or "",
                 record.session.model_dump_json(),
                 _temporal_to_json(record.temporal), record.next_seq,
                 _enrolment_to_json(record)))
            self._db.commit()

    def append_packet(self, session_id: str, packet: Packet) -> bool:
        accepted = super().append_packet(session_id, packet)
        if not accepted:
            return False
        record = self.get(session_id)
        with self._db_lock:
            self._db.execute(
                "INSERT INTO packets (session_id, seq, payload) VALUES (?,?,?) "
                "ON CONFLICT(session_id, seq) DO UPDATE SET payload=excluded.payload",
                (session_id, packet.seq or len(record.packets) if record else 0,
                 packet.model_dump_json()))
            self._db.commit()
        # The session row carries risk progression and next_seq, both of which
        # moved when this packet was analysed.
        if record is not None:
            self._persist_session(record)
        return True

    def append_transcript(self, session_id: str, line: TranscriptLine) -> None:
        super().append_transcript(session_id, line)
        record = self.get(session_id)
        if record is None:
            return
        with self._db_lock:
            self._db.execute(
                "INSERT INTO transcript (session_id, idx, payload) VALUES (?,?,?) "
                "ON CONFLICT(session_id, idx) DO UPDATE SET payload=excluded.payload",
                (session_id, len(record.transcript) - 1, line.model_dump_json()))
            self._db.commit()

    def append_alert(self, session_id: str, alert: Alert) -> None:
        super().append_alert(session_id, alert)
        with self._db_lock:
            self._db.execute(
                "INSERT INTO alerts (alert_id, session_id, payload) VALUES (?,?,?) "
                "ON CONFLICT(alert_id) DO UPDATE SET payload=excluded.payload",
                (alert.alert_id, session_id, alert.model_dump_json()))
            self._db.commit()

    def replace_alert(self, session_id: str, alert: Alert) -> None:
        super().replace_alert(session_id, alert)
        with self._db_lock:
            self._db.execute(
                "UPDATE alerts SET payload=? WHERE alert_id=?",
                (alert.model_dump_json(), alert.alert_id))
            self._db.commit()

    def touch_session(self, session_id: str) -> None:
        """Persists a session whose own fields changed (status, risk, language)."""
        record = self.get(session_id)
        if record is not None:
            self._persist_session(record)

    def delete(self, session_id: str) -> bool:
        removed = super().delete(session_id)
        with self._db_lock:
            # Cascades to packets, transcript and alerts. Deletion is real,
            # not a tombstone - SECURITY_SPEC forbids claiming a deletion the
            # system does not perform.
            self._db.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            self._db.commit()
        return removed

    def clear(self) -> None:
        super().clear()
        with self._db_lock:
            self._db.execute("DELETE FROM sessions")
            self._db.commit()

    def close(self) -> None:
        with self._db_lock:
            self._db.close()
