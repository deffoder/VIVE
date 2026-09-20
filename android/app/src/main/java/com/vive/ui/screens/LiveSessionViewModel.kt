package com.vive.ui.screens

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vive.core.ServiceLocator
import com.vive.core.ViveError
import com.vive.core.ViveResult
import com.vive.data.remote.StreamState
import com.vive.data.remote.ViveEvent
import com.vive.domain.LiveSession
import com.vive.domain.LiveSessionState
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Drives a live session from backend events.
 *
 * The UI is entirely backend-driven: this holder does no analysis, hard-codes
 * no risk value, and never calls a model. It appends packets as they arrive and
 * derives everything the screens need from them.
 *
 * Gap handling is the reconnect-safety contract: if a sequence number skips,
 * the missed packets are backfilled over REST with `since_seq` instead of being
 * silently lost (docs/API_SPEC.md 6).
 */
class LiveSessionViewModel(private val sessionId: String) : ViewModel() {

    private val _live = MutableStateFlow(LiveSession(sessionId = sessionId))
    val live: StateFlow<LiveSession> = _live.asStateFlow()

    private var streamJob: Job? = null
    private var connectionJob: Job? = null

    fun start() {
        if (streamJob != null) return
        _live.value = _live.value.copy(state = LiveSessionState.Connecting)

        connectionJob = viewModelScope.launch {
            ServiceLocator.sessions.connectionState.collect { transport ->
                _live.value = _live.value.copy(
                    state = when (transport) {
                        is StreamState.Connected -> LiveSessionState.Active
                        is StreamState.Connecting -> LiveSessionState.Connecting
                        is StreamState.Reconnecting -> LiveSessionState.Reconnecting(transport.attempt)
                        is StreamState.Disconnected -> transport.error
                            ?.let { LiveSessionState.Failed(it) }
                            ?: _live.value.state
                        is StreamState.Idle -> _live.value.state
                    },
                )
            }
        }

        streamJob = viewModelScope.launch {
            // Seed from REST so a late joiner sees history, then stream.
            when (val existing = ServiceLocator.sessions.listPackets(sessionId)) {
                is ViveResult.Success -> existing.data.forEach { packet ->
                    _live.value = _live.value.withPacket(packet, packet.seq ?: 0)
                }
                is ViveResult.Failure -> Unit // stream may still succeed
            }

            ServiceLocator.sessions.observeSession(sessionId).collect { event ->
                handle(event)
            }
        }
    }

    private suspend fun handle(event: ViveEvent) {
        when (event) {
            is ViveEvent.SessionState ->
                _live.value = _live.value.copy(
                    session = event.session,
                    state = LiveSessionState.Active,
                )

            is ViveEvent.PacketNew -> {
                if (_live.value.hasGap(event.seq)) backfill()
                _live.value = _live.value.withPacket(event.packet, event.seq)
            }

            is ViveEvent.RiskUpdate ->
                _live.value = _live.value.copy(
                    session = _live.value.session?.copy(
                        currentRisk = event.currentRisk,
                        overallRisk = event.overallRisk,
                        timings = event.timings,
                        packetsProcessed = _live.value.packets.size,
                    ),
                )

            is ViveEvent.TranscriptAppend ->
                _live.value = _live.value.copy(
                    transcript = _live.value.transcript + event.line,
                )

            is ViveEvent.AlertRaised ->
                _live.value = _live.value.copy(alertCount = _live.value.alertCount + 1)

            is ViveEvent.SessionEnded ->
                _live.value = _live.value.copy(
                    session = event.session,
                    state = LiveSessionState.Completed,
                )

            is ViveEvent.Failure ->
                _live.value = _live.value.copy(state = LiveSessionState.Failed(event.error))
        }
    }

    /** Fetches packets missed while the stream was down. */
    private suspend fun backfill() {
        val since = _live.value.lastSeq
        when (val missed = ServiceLocator.sessions.listPackets(sessionId, sinceSeq = since)) {
            is ViveResult.Success -> missed.data.forEach { packet ->
                _live.value = _live.value.withPacket(packet, packet.seq ?: since)
            }
            is ViveResult.Failure -> Unit
        }
    }

    /** Sends a scripted demo line so the backend produces a packet. */
    fun sendDemoLine(text: String, speaker: String = "Caller") {
        ServiceLocator.sendDemoTranscript(sessionId, text, speaker)
    }

    fun stop() {
        _live.value = _live.value.copy(state = LiveSessionState.Stopping)
        viewModelScope.launch {
            runCatching { ServiceLocator.closeStream(sessionId) }
            when (val ended = ServiceLocator.sessions.endSession(sessionId)) {
                is ViveResult.Success ->
                    _live.value = _live.value.copy(
                        session = ended.data,
                        state = LiveSessionState.Completed,
                    )
                is ViveResult.Failure ->
                    _live.value = _live.value.copy(state = LiveSessionState.Completed)
            }
            cancelStream()
        }
    }

    private fun cancelStream() {
        streamJob?.cancel()
        streamJob = null
        connectionJob?.cancel()
        connectionJob = null
    }

    /** Safe cancellation when the user leaves the session screen. */
    override fun onCleared() {
        cancelStream()
        super.onCleared()
    }
}
