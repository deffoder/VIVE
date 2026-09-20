package com.vive.domain

import com.vive.core.ViveError
import com.vive.data.model.EscalationTimings
import com.vive.data.model.Packet
import com.vive.data.model.RiskSummary
import com.vive.data.model.Session
import com.vive.data.model.TranscriptLine

/**
 * Lifecycle of a live analysis session, as seen by the UI.
 *
 * Distinct from [com.vive.data.model.SessionStatus], which is the BACKEND's
 * view. This one also covers client-side conditions the backend cannot know
 * about - [Connecting], [Reconnecting] and [Failed].
 */
sealed interface LiveSessionState {
    data object Idle : LiveSessionState
    data object Connecting : LiveSessionState
    data object Active : LiveSessionState
    data class Reconnecting(val attempt: Int) : LiveSessionState
    data object Stopping : LiveSessionState
    data object Completed : LiveSessionState
    data class Failed(val error: ViveError) : LiveSessionState
}

/**
 * Everything the active-call screen renders, accumulated from backend events.
 *
 * Packets are appended incrementally - never re-fetched wholesale on each event
 * (docs/ARCHITECTURE.md 8). [riskSeries] is derived here so the risk graph and
 * the packet timeline can never disagree.
 */
data class LiveSession(
    val sessionId: String,
    val state: LiveSessionState = LiveSessionState.Idle,
    val session: Session? = null,
    val packets: List<Packet> = emptyList(),
    val transcript: List<TranscriptLine> = emptyList(),
    val alertCount: Int = 0,
    val lastSeq: Int = 0,
    val isDemo: Boolean = true,
) {
    val currentRisk: RiskSummary? get() = session?.currentRisk
    val overallRisk: RiskSummary? get() = session?.overallRisk
    val timings: EscalationTimings get() = session?.timings ?: EscalationTimings()
    val packetCount: Int get() = packets.size
    val durationSec: Int get() = session?.durationSec ?: 0

    /** Score per packet, in order - the series behind the overall risk graph. */
    val riskSeries: List<Int> get() = packets.map { it.risk.score }

    /** Appends a packet, keeping the list ordered and free of duplicates. */
    fun withPacket(packet: Packet, seq: Int): LiveSession {
        if (packets.any { it.packetId == packet.packetId }) return this
        return copy(
            packets = packets + packet,
            lastSeq = maxOf(lastSeq, seq),
            isDemo = packet.ood != null || isDemo,
        )
    }

    /** True when the stream skipped a sequence number and a backfill is needed. */
    fun hasGap(incomingSeq: Int): Boolean = lastSeq != 0 && incomingSeq > lastSeq + 1
}
