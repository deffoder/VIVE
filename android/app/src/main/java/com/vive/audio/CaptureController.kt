package com.vive.audio

import com.vive.core.ViveLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Drives one authorized capture session — PATH B.
 *
 *   audio source -> ring buffer -> sliding windows -> upstream
 *
 * The controller performs NO analysis. It normalises, buffers, packetises and
 * hands each window to [onPacket], which sends it to the backend. Risk is
 * decided there (docs/ARCHITECTURE.md 1, decision 8).
 *
 * Silence is skipped locally so unusable audio is not shipped, which is a
 * bandwidth and privacy decision, not a risk judgement.
 */
class CaptureController(
    private val source: AudioSource,
    private val scope: CoroutineScope,
    private val vad: VoiceActivityDetector = EnergyGateVad(),
    private val packetizer: Packetizer = Packetizer(),
    private val skipSilence: Boolean = true,
) {

    private val _state = MutableStateFlow<CaptureState>(CaptureState.Idle)
    val state: StateFlow<CaptureState> = _state.asStateFlow()

    private val _packetsSent = MutableStateFlow(0)
    val packetsSent: StateFlow<Int> = _packetsSent.asStateFlow()

    private var job: Job? = null

    /**
     * Starts capture. Refuses to begin unless the source is authorized, so an
     * unauthorized source can never be processed.
     */
    fun start(onPacket: suspend (AudioPacket) -> Unit) {
        if (job != null) return

        when (val auth = source.authorization()) {
            is AudioAuthorization.Granted -> Unit
            is AudioAuthorization.PermissionMissing -> {
                _state.value = CaptureState.Failed("permission required: ${auth.permission}")
                return
            }
            is AudioAuthorization.Denied -> {
                _state.value = CaptureState.Failed("audio access declined")
                return
            }
            is AudioAuthorization.NotPermittedByPlatform -> {
                _state.value = CaptureState.Failed(auth.reason)
                return
            }
        }

        _state.value = CaptureState.Starting
        packetizer.reset()
        _packetsSent.value = 0

        job = scope.launch {
            try {
                _state.value = CaptureState.Capturing
                val outcome = source.start { chunk ->
                    packetizer.feed(chunk).forEach { packet ->
                        if (skipSilence && !vad.hasSpeech(packet.pcm)) {
                            ViveLog.d(TAG) { "skipping silent window ${packet.packetId}" }
                            return@forEach
                        }
                        onPacket(packet)
                        _packetsSent.value = _packetsSent.value + 1
                    }
                }
                _state.value = outcome
            } catch (e: Exception) {
                // Message only - never a stack trace into logs.
                ViveLog.e(TAG, "capture failed: ${e::class.simpleName}")
                _state.value = CaptureState.Failed("capture failed")
            } finally {
                job = null
            }
        }
    }

    fun stop() {
        _state.value = CaptureState.Stopping
        scope.launch {
            source.stop()
            job?.cancel()
            job = null
            _state.value = CaptureState.Completed
        }
    }

    /** Abandons capture and discards buffered audio. */
    fun cancel() {
        scope.launch {
            source.cancel()
            job?.cancel()
            job = null
            packetizer.reset()
            _state.value = CaptureState.Idle
        }
    }

    private companion object {
        const val TAG = "CaptureController"
    }
}
