"""In-memory event store.

docs/BLOCKERS.md O4 records that no persistence engine has been chosen and
that in-memory is sufficient through the live-wiring phase. This is that
implementation, kept behind a narrow interface so swapping in a real engine is
a constructor change and nothing above the data layer moves.

Everything here is process-local and lost on restart. That is a deliberate
privacy property for now, not an oversight: audio and transcripts do not touch
disk (docs/SECURITY_SPEC.md 4).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol

from app.risk.temporal import TemporalState
from app.schemas.models import Alert, Packet, Session, TranscriptLine


@dataclass
class SessionRecord:
    """Everything the backend knows about one session."""

    session: Session
    packets: list[Packet] = field(default_factory=list)
    transcript: list[TranscriptLine] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    temporal: TemporalState = field(default_factory=TemporalState)
    next_seq: int = 1
    reference_audio: bytes | None = None
    """Legacy raw-audio reference. Superseded by `reference_embedding`.

    Kept only so the older `analyze(window, reference)` adapter path still
    compiles; nothing sets it. Storing a recording of someone's voice to use
    as a reference keeps a copy of their voice for no purpose the embedding
    does not already serve (docs/SECURITY_SPEC.md 4).
    """

    reference_embedding: list[float] | None = None
    """Enrolled speaker voiceprint, as an embedding rather than audio.

    None means nobody is enrolled, which yields `NO_REFERENCE` - never a
    mismatch (docs/BLOCKERS.md O3).
    """

    enrolled_at: str | None = None
    enrolment_label: str | None = None


class EventStore(Protocol):
    def create(self, record: SessionRecord) -> None: ...
    def get(self, session_id: str) -> SessionRecord | None: ...
    def list_sessions(self, limit: int, offset: int) -> list[Session]: ...
    def delete(self, session_id: str) -> bool: ...


class InMemoryEventStore:
    """Thread-safe dict-backed store.

    A lock rather than plain dict access because the WebSocket handler and REST
    routes touch the same records from different tasks.
    """

    def __init__(self, max_packets_per_session: int = 10_000) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._lock = threading.RLock()
        self._max_packets = max_packets_per_session

    def create(self, record: SessionRecord) -> None:
        with self._lock:
            self._records[record.session.session_id] = record

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._records.get(session_id)

    def list_sessions(self, limit: int = 20, offset: int = 0) -> list[Session]:
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda r: r.session.started_at or "", reverse=True)
        return [r.session for r in records[offset : offset + limit]]

    def append_packet(self, session_id: str, packet: Packet) -> bool:
        """Returns False when the per-session cap is reached (bounded memory)."""
        with self._lock:
            record = self._records.get(session_id)
            if record is None:
                return False
            if len(record.packets) >= self._max_packets:
                return False
            record.packets.append(packet)
            return True

    def append_alert(self, session_id: str, alert: Alert) -> None:
        with self._lock:
            record = self._records.get(session_id)
            if record is not None:
                record.alerts.append(alert)

    def append_transcript(self, session_id: str, line: TranscriptLine) -> None:
        with self._lock:
            record = self._records.get(session_id)
            if record is not None:
                record.transcript.append(line)

    def all_alerts(self) -> list[Alert]:
        with self._lock:
            return [a for r in self._records.values() for a in r.alerts]

    def find_alert(self, alert_id: str) -> tuple[str, Alert] | None:
        with self._lock:
            for session_id, record in self._records.items():
                for alert in record.alerts:
                    if alert.alert_id == alert_id:
                        return session_id, alert
        return None

    def replace_alert(self, session_id: str, alert: Alert) -> None:
        with self._lock:
            record = self._records.get(session_id)
            if record is None:
                return
            record.alerts = [
                alert if a.alert_id == alert.alert_id else a for a in record.alerts
            ]

    def delete(self, session_id: str) -> bool:
        """Removes a session and everything derived from it.

        Real deletion, not a tombstone - docs/SECURITY_SPEC.md forbids claiming
        deletion the system does not perform.
        """
        with self._lock:
            return self._records.pop(session_id, None) is not None

    def clear(self) -> None:
        """Demo reset / test seam."""
        with self._lock:
            self._records.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._records)
