"""Session lifecycle and the per-packet orchestrator.

This is the layer docs/ARCHITECTURE.md 3 describes: it owns session state, runs
the analyzer fan-out for one window, fuses the results, updates temporal risk
and decides whether policy raises an alert.

It calls analyzers only through app.adapters.interfaces, so the mock bundle and
a future real bundle are interchangeable.
"""

from __future__ import annotations

import itertools
import logging
import threading
from datetime import UTC, datetime

from app.adapters.interfaces import AdapterBundle, AudioWindow
from app.core import ids
from app.core.errors import session_already_ended, session_not_found
from app.risk import policy, sensitive
from app.risk.fusion import FusionInput, fuse
from app.schemas.models import (
    Intent,
    AasistEvidence,
    Alert,
    AnalysisWindow,
    AnalyzerStatus,
    AsrEvidence,
    BehaviorEvidence,
    ContextEvidence,
    CreateSessionRequest,
    EcapaEvidence,
    IntentEvidence,
    OodEvidence,
    Packet,
    PolicyEvaluateRequest,
    Session,
    SessionContext,
    SessionStatus,
    TranscriptLine,
)
from app.store.memory import InMemoryEventStore, SessionRecord

logger = logging.getLogger("vive.sessions")

WINDOW_SECONDS = 2.0
STRIDE_SECONDS = 1.0
"""Sliding window: 2s wide, 1s stride, so windows overlap (ARCHITECTURE 4)."""

_alert_counter = itertools.count(1)
_alert_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _next_alert_id() -> str:
    with _alert_lock:
        return f"AL-{next(_alert_counter):03d}"


class SessionManager:
    def __init__(self, store: InMemoryEventStore, adapters: AdapterBundle) -> None:
        self._store = store
        self._adapters = adapters

    # ------------------------------------------------------------ lifecycle

    def create(self, request: CreateSessionRequest) -> Session:
        session = Session(
            session_id=ids.next_session_id(),
            status=SessionStatus.READY,
            source_type=request.source_type,
            started_at=_now_iso(),
            language=None if request.language == "auto" else request.language,
            context=request.context,
        )
        self._store.create(SessionRecord(session=session))
        return session

    def get(self, session_id: str) -> Session:
        record = self._store.get(session_id)
        if record is None:
            raise session_not_found(session_id)
        return record.session

    def require_record(self, session_id: str) -> SessionRecord:
        record = self._store.get(session_id)
        if record is None:
            raise session_not_found(session_id)
        return record

    def _persist(self, session_id: str) -> None:
        """Flushes a session whose own fields changed.

        Packets and alerts persist as they are appended, but status, language
        and ended_at are mutated in place on the record. Without this a
        durable store would restore an ended call as STREAMING - the store
        would be holding the session as it looked when it was created.
        No-op on the in-memory store.
        """
        touch = getattr(self._store, "touch_session", None)
        if touch is not None:
            touch(session_id)

    def mark_streaming(self, session_id: str) -> Session:
        record = self.require_record(session_id)
        if record.session.status == SessionStatus.ENDED:
            raise session_already_ended(session_id)
        record.session.status = SessionStatus.STREAMING
        self._persist(session_id)
        return record.session

    def end(self, session_id: str) -> Session:
        record = self.require_record(session_id)
        if record.session.status == SessionStatus.ENDED:
            raise session_already_ended(session_id)
        record.session.status = SessionStatus.ENDED
        record.session.ended_at = _now_iso()
        self._release_adapter_state(session_id)
        self._persist(session_id)
        return record.session

    def enrol_speaker(self, session_id: str, pcm: bytes,
                      label: str | None = None) -> tuple[bool, str]:
        """Enrols a reference voice for this session.

        Returns (accepted, reason). The audio is embedded and then dropped -
        only the embedding is kept, because a stored recording of someone's
        voice serves no purpose the embedding does not already serve
        (docs/SECURITY_SPEC.md 4).
        """
        record = self.require_record(session_id)
        enrol = getattr(self._adapters.speaker, "enrol", None)
        if enrol is None:
            return False, "speaker model does not support enrolment"
        embedding = enrol(pcm)
        if embedding is None:
            return False, (
                "enrolment needs at least 3 seconds of clear speech; a shorter "
                "reference would anchor every later comparison badly"
            )
        record.reference_embedding = embedding
        record.enrolled_at = _now_iso()
        record.enrolment_label = label
        self._persist(session_id)
        return True, "enrolled"

    def clear_enrolment(self, session_id: str) -> None:
        """Removes the enrolled reference. Comparison returns to NO_REFERENCE."""
        record = self.require_record(session_id)
        record.reference_embedding = None
        record.enrolled_at = None
        record.enrolment_label = None
        self._persist(session_id)

    def set_context(self, session_id: str, context: SessionContext) -> Session:
        record = self.require_record(session_id)
        if record.session.status == SessionStatus.ENDED:
            raise session_already_ended(session_id)
        record.session.context = context
        self._persist(session_id)
        return record.session

    def delete(self, session_id: str) -> bool:
        self._release_adapter_state(session_id)
        return self._store.delete(session_id)

    def _release_adapter_state(self, session_id: str) -> None:
        """Drops any per-session audio an adapter is holding.

        The anti-spoofing adapter buffers recent real audio because its model
        needs a longer window than VIVE's packet (see audio_models). That
        buffer holds caller speech, so it is released as soon as the session
        ends rather than waiting for eviction - privacy first, memory second
        (docs/SECURITY_SPEC.md 4).
        """
        for adapter in (self._adapters.vad, self._adapters.antispoof,
                        self._adapters.speaker, self._adapters.asr):
            release = getattr(adapter, "release", None)
            if callable(release):
                try:
                    release(session_id)
                except Exception:  # noqa: BLE001 - cleanup must never fail a request
                    logger.debug("adapter release failed for %s", session_id)

    # ------------------------------------------------------------ analysis

    def process_window(
        self,
        session_id: str,
        *,
        pcm: bytes = b"",
        transcript_hint: str | None = None,
        speaker: str = "Caller",
    ) -> tuple[Packet, Alert | None]:
        """Run one analysis window end to end.

        Returns the packet and an alert when policy raised one. Every packet is
        traceable: session_id, packet_id, timestamp, duration, window, result,
        confidence and per-analyzer model/version metadata.
        """
        record = self.require_record(session_id)
        if record.session.status == SessionStatus.ENDED:
            raise session_already_ended(session_id)

        seq = record.next_seq
        record.next_seq += 1

        start = (seq - 1) * STRIDE_SECONDS
        end = start + WINDOW_SECONDS
        window = AudioWindow(
            session_id=session_id,
            seq=seq,
            start_sec=start,
            end_sec=end,
            pcm=pcm,
            transcript_hint=transcript_hint,
            # Without this the ASR decodes every session in the adapter's
            # default language. Measured: a Tamil session was transcribed as
            # Hindi, which also made the text heads run instead of declining
            # an unsupported language - defeating the O11 protection.
            language=record.session.language,
        )

        a = self._adapters
        # Sequential on purpose. Running the four window analyzers on a thread
        # pool was tried and MEASURED: median packet latency went from 938 ms
        # to 1197 ms on Hindi, and per-stage cost rose across the board
        # (ASR 273->584 ms, AASIST 395->741 ms, ECAPA 81->732 ms).
        #
        # The reason is that torch and onnxruntime each already use every core,
        # so concurrent analyzers oversubscribe the CPU and contend rather than
        # overlap. Concurrency here buys nothing and costs clarity, so it was
        # reverted. Parallelism would only pay once the models sit on separate
        # devices, which is a deployment question, not a code one.
        vad = a.vad.analyze(window)
        antispoof = a.antispoof.analyze(window)
        # Compare against the stored EMBEDDING when one is enrolled. The
        # older path re-embedded reference AUDIO once per packet and required
        # that audio to be retained; an embedding costs one forward pass at
        # enrolment and 192 floats thereafter. Falls back to the audio path
        # only for adapters that predate `compare` (docs/BLOCKERS.md O3).
        compare = getattr(a.speaker, "compare", None)
        speaker_result = (
            compare(window, record.reference_embedding) if compare is not None
            else a.speaker.analyze(window, record.reference_audio)
        )
        asr = a.asr.analyze(window)
        # Which language the text heads are asked about decides whether they
        # run at all, so it has to be the most reliable value available - not
        # simply the most recent one.
        #
        # A DECLARED session language wins. The caller told us, and in real
        # mode the ASR was decoded in that language, so its output is that
        # language by construction. `asr.language` is the fallback for a
        # session that declared nothing ("auto").
        #
        # Taking ASR's value unconditionally was wrong in exactly one
        # direction, and it was the dangerous one: the mock language guess is
        # keyword-based and does not recognise Tamil SCRIPT, so a session
        # explicitly declared `ta` carrying real Tamil text was reported as
        # `en` and both heads analysed it as English - returning
        # NORMAL_CONVERSATION with status AVAILABLE for a language VIVE cannot
        # read. That is precisely the O11 protection this line exists to
        # provide, defeated by trusting a guess over a declaration.
        text_language = record.session.language or asr.language
        intent = a.intent.analyze(asr.transcript, text_language)
        behavior = a.behavior.analyze(asr.transcript, text_language)

        # Rule-based sensitive-request evidence, over this window and the
        # previous one's transcript (app/risk/sensitive.py).
        current_text = asr.transcript if asr.status == AnalyzerStatus.AVAILABLE else None
        rule = sensitive.detect_in_context(current_text, record.last_transcript)
        record.last_transcript = current_text

        ctx = record.session.context
        fused = fuse(
            FusionInput(
                vad=vad,
                antispoof=antispoof,
                speaker=speaker_result,
                asr=asr,
                intent=intent,
                behavior=behavior,
                caller_verified=ctx.caller_verified,
                session_authenticated=ctx.session_authenticated,
                sensitive_request=Intent(rule.label) if rule else None,
            )
        )

        at_sec = int(end)
        current, overall = record.temporal.update(
            fused.risk.score, fused.risk.confidence, at_sec
        )

        packet = Packet(
            packet_id=ids.packet_id(seq),
            timestamp=f"{at_sec // 60:02d}:{at_sec % 60:02d}",
            duration_sec=int(WINDOW_SECONDS),
            language=asr.language or record.session.language or "en",
            quality=fused.quality,
            aasist=AasistEvidence(
                score=antispoof.score,
                status=antispoof.status,
                model_version=antispoof.model_version,
                inference_ms=antispoof.inference_ms,
            ),
            ecapa=EcapaEvidence(
                status=speaker_result.status,
                similarity=speaker_result.similarity,
                model_version=speaker_result.model_version,
                inference_ms=speaker_result.inference_ms,
            ),
            asr=AsrEvidence(
                transcript=asr.transcript,
                confidence=asr.confidence,
                status=asr.status,
                model_version=asr.model_version,
                inference_ms=asr.inference_ms,
            ),
            intent=IntentEvidence(
                label=intent.label,
                confidence=intent.confidence,
                status=intent.status,
                model_version=intent.model_version,
                inference_ms=intent.inference_ms,
            ),
            behavior=BehaviorEvidence(
                labels=behavior.labels,
                confidence=behavior.confidence,
                status=behavior.status,
                model_version=behavior.model_version,
                inference_ms=behavior.inference_ms,
            ),
            context=ContextEvidence(
                caller_verified=ctx.caller_verified,
                session_authenticated=ctx.session_authenticated,
                source_type=record.session.source_type,
                requested_action=ctx.requested_action,
                context_risk=fused.context_risk,
            ),
            risk=fused.risk,
            session_id=session_id,
            seq=seq,
            window=AnalysisWindow(start_sec=start, end_sec=end),
            language_confidence=asr.language_confidence,
            created_at=_now_iso(),
            ood=OodEvidence(state=fused.ood_state, uncertainty=fused.uncertainty),
            adapter_mode=a.mode,
        )

        if not self._store.append_packet(session_id, packet):
            # Cap reached; the packet is still returned so the caller sees the
            # result, but it is not retained (bounded memory).
            pass

        session = record.session
        session.status = SessionStatus.STREAMING
        session.packets_processed = len(record.packets)
        session.duration_sec = at_sec
        session.current_risk = current
        session.overall_risk = overall
        session.timings = record.temporal.timings
        if asr.language:
            session.language = asr.language

        if asr.transcript:
            line = TranscriptLine(
                packet_id=packet.packet_id,
                speaker=speaker,
                text=asr.transcript,
                language=asr.language,
                confidence=asr.confidence,
                timestamp=packet.timestamp,
            )
            self._store.append_transcript(session_id, line)

        alert = self._maybe_alert(record, packet)
        return packet, alert

    def _maybe_alert(self, record: SessionRecord, packet: Packet) -> Alert | None:
        decision = policy.evaluate(
            PolicyEvaluateRequest(
                session_id=record.session.session_id,
                risk_score=packet.risk.score,
                risk_level=packet.risk.level,
                confidence=packet.risk.confidence,
                intent=packet.intent.label
                if packet.intent.status == AnalyzerStatus.AVAILABLE
                else None,
                caller_verified=record.session.context.caller_verified,
            )
        )
        if not decision.should_alert:
            return None

        alert = Alert(
            alert_id=_next_alert_id(),
            session_id=record.session.session_id,
            level=packet.risk.level,
            raised_at=_now_iso(),
            reason="; ".join(decision.reasons),
            packet_id=packet.packet_id,
            intent=packet.intent.label,
            recommended_action=decision.recommended_action,
        )
        self._store.append_alert(record.session.session_id, alert)
        return alert
