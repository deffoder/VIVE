package com.vive.data.remote

import com.vive.data.model.Alert
import com.vive.data.model.EscalationTimings
import com.vive.data.model.Packet
import com.vive.data.model.RiskSummary
import com.vive.data.model.Session
import com.vive.data.model.TranscriptLine
import com.vive.core.ViveError

/**
 * Typed WebSocket events.
 *
 * Mirrors the frame envelope in docs/API_SPEC.md 6. Each subtype corresponds to
 * one `type` value, so the UI layer never parses raw JSON and an unhandled
 * event is a compile error.
 *
 * [seq] is monotonic per session; a gap means packets were missed and the
 * client should backfill over REST with `since_seq`.
 */
sealed interface ViveEvent {

    val sessionId: String

    /** `session.state` - full session snapshot. */
    data class SessionState(
        override val sessionId: String,
        val session: Session,
    ) : ViveEvent

    /** `packet.new` - one completed analysis window. */
    data class PacketNew(
        override val sessionId: String,
        val seq: Int,
        val packet: Packet,
    ) : ViveEvent

    /** `risk.update` - aggregate risk changed. */
    data class RiskUpdate(
        override val sessionId: String,
        val currentRisk: RiskSummary,
        val overallRisk: RiskSummary,
        val timings: EscalationTimings,
    ) : ViveEvent

    /** `transcript.append` - a new transcript line. Sensitive content. */
    data class TranscriptAppend(
        override val sessionId: String,
        val line: TranscriptLine,
    ) : ViveEvent

    /** `alert.raised` - policy raised an alert. */
    data class AlertRaised(
        override val sessionId: String,
        val alert: Alert,
    ) : ViveEvent

    /** `session.ended` - final summary follows over REST. */
    data class SessionEnded(
        override val sessionId: String,
        val session: Session,
    ) : ViveEvent

    /** `error` - server-reported problem. Not necessarily fatal. */
    data class Failure(
        override val sessionId: String,
        val error: ViveError,
    ) : ViveEvent
}

/** Connection state of the live stream, so the UI can show Offline distinctly. */
sealed interface StreamState {
    data object Idle : StreamState
    data object Connecting : StreamState
    data object Connected : StreamState
    data class Reconnecting(val attempt: Int) : StreamState
    data class Disconnected(val error: ViveError?) : StreamState
}
