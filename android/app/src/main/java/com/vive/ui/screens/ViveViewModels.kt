package com.vive.ui.screens

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vive.audio.AudioAuthorization
import com.vive.audio.AudioFormat
import com.vive.audio.CaptureController
import com.vive.audio.CaptureState
import com.vive.audio.MicrophoneAudioSource
import com.vive.core.ServiceLocator
import com.vive.core.UiState
import com.vive.core.ViveError
import com.vive.core.ViveLog
import com.vive.core.ViveResult
import com.vive.data.model.AdapterMode
import com.vive.data.model.Alert
import com.vive.data.model.ModelInfo
import com.vive.data.model.Packet
import com.vive.data.model.Session
import com.vive.data.model.SourceType
import com.vive.data.model.TranscriptLine
import com.vive.data.remote.StreamState
import com.vive.data.remote.ViveEvent
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Shared state holders.
 *
 * Four view models cover every data-backed screen, so the app has ONE
 * state-management approach (the `UiState` sealed interface from Phase 1)
 * rather than a second architecture layered on top.
 *
 * Repositories come from [ServiceLocator], which currently serves demo data.
 */

/** Loads a list, mapping an empty result to [UiState.Empty]. */
private fun <T> ViveResult<List<T>>.toListState(): UiState<List<T>> = when (this) {
    is ViveResult.Success -> if (data.isEmpty()) UiState.Empty else UiState.Success(data)
    is ViveResult.Failure -> UiState.Error(error)
}

private fun <T> ViveResult<T>.toState(): UiState<T> = when (this) {
    is ViveResult.Success -> UiState.Success(data)
    is ViveResult.Failure -> UiState.Error(error)
}

/** Home and Call History. */
class SessionListViewModel : ViewModel() {

    private val _state = MutableStateFlow<UiState<List<Session>>>(UiState.Loading)
    val state: StateFlow<UiState<List<Session>>> = _state.asStateFlow()

    private val _starting = MutableStateFlow(false)
    val starting: StateFlow<Boolean> = _starting.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.sessions.listSessions().toListState()
    }

    /**
     * Creates a real backend session for authorized in-app microphone capture.
     *
     * [onCreated] fires only on success, with the real session id from the
     * backend. A failure reports itself and navigates nowhere: opening an
     * analysis screen for a session the backend never created would show an
     * empty call that looks like a system fault rather than a connection one.
     *
     * `IN_APP` is the source type because that is what this is - audio the
     * user authorized inside the app. It is not `CELLULAR_SCREENING`, which
     * carries no audio at all (docs/ARCHITECTURE.md 7).
     */
    fun startLiveSession(onCreated: (String) -> Unit, onError: (ViveError) -> Unit) {
        if (_starting.value) return
        _starting.value = true
        viewModelScope.launch {
            when (val created = ServiceLocator.sessions.createSession(SourceType.IN_APP)) {
                is ViveResult.Success -> {
                    refresh()
                    onCreated(created.data.sessionId)
                }
                is ViveResult.Failure -> onError(created.error)
            }
            _starting.value = false
        }
    }
}

/**
 * Backs the active-call, summary, risk, evidence, timeline and transcript
 * screens. One view model per session keeps packet history in a single place
 * so the risk graph and the timeline never disagree.
 */
class SessionDetailViewModel(private val sessionId: String) : ViewModel() {

    private val _session = MutableStateFlow<UiState<Session>>(UiState.Loading)
    val session: StateFlow<UiState<Session>> = _session.asStateFlow()

    private val _packets = MutableStateFlow<UiState<List<Packet>>>(UiState.Loading)
    val packets: StateFlow<UiState<List<Packet>>> = _packets.asStateFlow()

    private val _transcript = MutableStateFlow<UiState<List<TranscriptLine>>>(UiState.Loading)
    val transcript: StateFlow<UiState<List<TranscriptLine>>> = _transcript.asStateFlow()

    private val _connection = MutableStateFlow<StreamState>(StreamState.Idle)
    val connection: StateFlow<StreamState> = _connection.asStateFlow()

    private var streamJob: Job? = null
    private var lastSeq: Int = 0

    /**
     * Microphone capture for this session.
     *
     * Null until the user explicitly starts live analysis. A session that is
     * only being reviewed - a past call, or one driven from elsewhere - must
     * never open the microphone, so this is created on demand rather than in
     * `init`.
     */
    private var capture: CaptureController? = null

    private val _captureState = MutableStateFlow<CaptureState>(CaptureState.Idle)
    val captureState: StateFlow<CaptureState> = _captureState.asStateFlow()

    /** Analysis windows the backend actually accepted. Drives the UI counter. */
    private val _windowsSent = MutableStateFlow(0)
    val windowsSent: StateFlow<Int> = _windowsSent.asStateFlow()

    /**
     * Consecutive windows that did NOT leave the device.
     *
     * Surfaced rather than swallowed: capture running while nothing reaches
     * the backend looks identical to capture working, and that is precisely
     * the state a user must be able to see.
     */
    private val _windowsDropped = MutableStateFlow(0)
    val windowsDropped: StateFlow<Int> = _windowsDropped.asStateFlow()

    init {
        refresh()
        observeStream()
    }

    /**
     * Subscribes to live backend events.
     *
     * Applying them here means every session screen - active call, timeline,
     * transcript, summary - updates from the backend with no UI change. Packets
     * are APPENDED, never re-fetched wholesale, so the list is not rebuilt for
     * each event (docs/ARCHITECTURE.md 8).
     */
    private fun observeStream() {
        streamJob = viewModelScope.launch {
            launch {
                ServiceLocator.sessions.connectionState.collect { _connection.value = it }
            }
            ServiceLocator.sessions.observeSession(sessionId).collect { event ->
                when (event) {
                    is ViveEvent.SessionState -> _session.value = UiState.Success(event.session)

                    is ViveEvent.PacketNew -> {
                        // A sequence gap means packets were missed: backfill
                        // rather than silently losing them.
                        if (lastSeq != 0 && event.seq > lastSeq + 1) backfill()
                        lastSeq = maxOf(lastSeq, event.seq)
                        appendPacket(event.packet)
                    }

                    is ViveEvent.RiskUpdate -> {
                        val current = (_session.value as? UiState.Success)?.data ?: return@collect
                        _session.value = UiState.Success(
                            current.copy(
                                currentRisk = event.currentRisk,
                                overallRisk = event.overallRisk,
                                timings = event.timings,
                                packetsProcessed =
                                    (_packets.value as? UiState.Success)?.data?.size
                                        ?: current.packetsProcessed,
                            ),
                        )
                    }

                    is ViveEvent.TranscriptAppend -> {
                        val existing = (_transcript.value as? UiState.Success)?.data.orEmpty()
                        _transcript.value = UiState.Success(existing + event.line)
                    }

                    is ViveEvent.SessionEnded -> _session.value = UiState.Success(event.session)

                    is ViveEvent.AlertRaised -> Unit

                    is ViveEvent.Failure -> _session.value = UiState.Error(event.error)
                }
            }
        }
    }

    private fun appendPacket(packet: Packet) {
        val existing = (_packets.value as? UiState.Success)?.data.orEmpty()
        if (existing.any { it.packetId == packet.packetId }) return
        // The badge follows the packets actually on screen, so it can never
        // claim real inference is demo data or the reverse.
        ServiceLocator.observeAdapterMode(packet.adapterMode == AdapterMode.MOCK)
        _packets.value = UiState.Success(existing + packet)
    }

    private suspend fun backfill() {
        when (val missed = ServiceLocator.sessions.listPackets(sessionId, sinceSeq = lastSeq)) {
            is ViveResult.Success -> missed.data.forEach { appendPacket(it) }
            is ViveResult.Failure -> Unit
        }
    }

    /**
     * Starts capturing the device microphone and streaming it to the backend.
     *
     * [CaptureController] does the buffering, 2 s/1 s windowing and silence
     * skipping; this only forwards each completed window. No analysis happens
     * on the device, so what the screen renders afterwards is the backend's
     * verdict on audio the user actually spoke - never a local guess
     * (docs/ARCHITECTURE.md 1, decision 8).
     *
     * This is the device MICROPHONE during an authorized in-app session. It is
     * not cellular call audio, which Android does not permit a third-party app
     * to capture (docs/BLOCKERS.md P1).
     */
    fun startCapture(context: Context) {
        if (capture != null) return

        val controller = CaptureController(
            source = MicrophoneAudioSource(context.applicationContext),
            scope = viewModelScope,
        )
        capture = controller

        viewModelScope.launch { controller.state.collect { _captureState.value = it } }

        controller.start { packet ->
            // A failed send must not kill capture. The stream reconnects on
            // its own, and a window lost in the gap is recovered by the same
            // `since_seq` backfill that covers any other disconnect.
            //
            // But it must not be COUNTED as sent either. The counter used to
            // track windows the packetizer emitted, which is not the same
            // thing: with no open socket the UI read "89 analysis windows
            // sent to the backend" while the backend had received none.
            val delivered = runCatching {
                ServiceLocator.sendAudio(sessionId, packet.pcm)
            }.getOrDefault(false)

            if (delivered) {
                _windowsSent.value = _windowsSent.value + 1
                _windowsDropped.value = 0
            } else {
                _windowsDropped.value = _windowsDropped.value + 1
                ViveLog.e(TAG, "window ${packet.packetId} did not leave the device")
            }
        }
    }

    private val _enrolment = MutableStateFlow<String?>(null)
    /** Last enrolment outcome, for the UI. Null means nothing attempted yet. */
    val enrolment: StateFlow<String?> = _enrolment.asStateFlow()

    /**
     * Records a reference voice and enrols it.
     *
     * Captures [ENROLMENT_SECONDS] of audio through the same microphone source
     * the live path uses, sends it once, and keeps nothing locally. The
     * backend stores the embedding and discards the audio, so neither side
     * retains a recording of the speaker's voice.
     *
     * Until a voice is enrolled the speaker channel reports NO_REFERENCE on
     * every packet, which is not a mismatch and is not a failure - it is the
     * honest state of a comparison with nothing to compare against
     * (docs/BLOCKERS.md O3).
     */
    fun enrolSpeaker(context: Context, label: String? = null) {
        if (_enrolment.value == ENROLLING) return
        _enrolment.value = ENROLLING
        viewModelScope.launch {
            val source = MicrophoneAudioSource(context.applicationContext)
            if (source.authorization() !is AudioAuthorization.Granted) {
                _enrolment.value = "Microphone permission is required to enrol."
                return@launch
            }
            val collected = java.io.ByteArrayOutputStream()
            val target = AudioFormat.bytesFor(ENROLMENT_SECONDS)
            val outcome = withTimeoutOrNull(ENROLMENT_TIMEOUT_MS) {
                source.start { chunk ->
                    collected.write(chunk)
                    if (collected.size() >= target) source.stop()
                }
            }
            if (outcome == null) source.stop()

            val pcm = collected.toByteArray()
            if (pcm.size < target) {
                _enrolment.value =
                    "Not enough audio captured. Speak for a few seconds and retry."
                return@launch
            }
            _enrolment.value = when (val result =
                ServiceLocator.enrolSpeaker(sessionId, pcm, label)) {
                is ViveResult.Success -> result.data
                is ViveResult.Failure -> result.error.message
            }
            refresh()
        }
    }

    fun clearEnrolment() {
        viewModelScope.launch {
            _enrolment.value = when (val result = ServiceLocator.clearEnrolment(sessionId)) {
                is ViveResult.Success -> result.data
                is ViveResult.Failure -> result.error.message
            }
        }
    }

    /** Stops the microphone without ending the backend session. */
    fun stopCapture() {
        capture?.stop()
        capture = null
    }

    /**
     * Ends the analysis session for real.
     *
     * "End call" used to only navigate to the summary screen. The microphone
     * kept recording and the backend session stayed STREAMING indefinitely -
     * a control that changed the screen without performing the operation it
     * named. [onEnded] fires once the backend has confirmed, so the summary
     * opens on a session that is actually finished.
     *
     * Order matters: release the microphone BEFORE ending the session, or the
     * recorder keeps running with nowhere to send.
     */
    fun endSession(onEnded: () -> Unit = {}) {
        stopCapture()
        viewModelScope.launch {
            when (val ended = ServiceLocator.sessions.endSession(sessionId)) {
                is ViveResult.Success -> _session.value = UiState.Success(ended.data)
                // A failed end is reported, not hidden, but the user is still
                // taken to the summary: the local session is over either way.
                is ViveResult.Failure -> ViveLog.e(TAG, "endSession failed")
            }
            runCatching { ServiceLocator.closeStream(sessionId) }
            streamJob?.cancel()
            streamJob = null
            onEnded()
        }
    }

    /** Safe cancellation when the user leaves the session. */
    override fun onCleared() {
        // Cancel rather than stop: the user has left, so buffered audio is
        // discarded instead of uploaded. An AudioRecord that is never released
        // holds the microphone for the lifetime of the process, and the next
        // session would fail to initialise with no obvious cause.
        capture?.cancel()
        capture = null
        streamJob?.cancel()
        streamJob = null
        super.onCleared()
    }

    private companion object {
        const val TAG = "SessionDetailViewModel"
        const val ENROLLING = "Recording reference voice..."

        /** The backend refuses anything shorter than 3 s, so capture 4 s. */
        const val ENROLMENT_SECONDS = 4.0
        const val ENROLMENT_TIMEOUT_MS = 15_000L
    }

    fun refresh() = viewModelScope.launch {
        _session.value = UiState.Loading
        _packets.value = UiState.Loading
        _transcript.value = UiState.Loading
        _session.value = ServiceLocator.sessions.getSession(sessionId).toState()
        val packetResult = ServiceLocator.sessions.listPackets(sessionId)
        (packetResult as? ViveResult.Success)?.data?.lastOrNull()?.seq?.let { lastSeq = it }
        _packets.value = packetResult.toListState()
        _transcript.value = ServiceLocator.sessions.getTranscript(sessionId).toListState()
    }

    /** Risk score per packet, in order - the series behind the overall graph. */
    fun riskSeries(): List<Int> =
        (_packets.value as? UiState.Success)?.data?.map { it.risk.score }.orEmpty()

    fun latestPacket(): Packet? =
        (_packets.value as? UiState.Success)?.data?.lastOrNull()
}

/** Single packet detail. */
class PacketDetailViewModel(
    private val sessionId: String,
    private val packetId: String,
) : ViewModel() {

    private val _state = MutableStateFlow<UiState<Packet>>(UiState.Loading)
    val state: StateFlow<UiState<Packet>> = _state.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.sessions.getPacket(sessionId, packetId).toState()
    }
}

/** Alerts list, with acknowledgement. */
class AlertsViewModel : ViewModel() {

    private val _state = MutableStateFlow<UiState<List<Alert>>>(UiState.Loading)
    val state: StateFlow<UiState<List<Alert>>> = _state.asStateFlow()

    private val _filter = MutableStateFlow<String>("All")
    val filter: StateFlow<String> = _filter.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.alerts.listAlerts().toListState()
    }

    fun setFilter(value: String) { _filter.value = value }

    fun acknowledge(alertId: String) = viewModelScope.launch {
        ServiceLocator.alerts.acknowledge(alertId)
        refresh()
    }
}

/** Model Information screen. */
class ModelsViewModel : ViewModel() {

    private val _state = MutableStateFlow<UiState<List<ModelInfo>>>(UiState.Loading)
    val state: StateFlow<UiState<List<ModelInfo>>> = _state.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.models.listModels().toListState()
    }
}
