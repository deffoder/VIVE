package com.vive.audio

/**
 * Authorized audio sources — PATH B.
 *
 * This is the ONLY path that yields audio for full analysis. It is deliberately
 * separate from the cellular screening path in `com.vive.telephony`, which
 * never produces audio (docs/ARCHITECTURE.md 7).
 *
 * Android does not permit a third-party app to capture two-way cellular call
 * audio. Every source here is one the user or operator has explicitly
 * authorized: in-app VoIP, a collaboration stream, the device microphone for an
 * in-app call, or a prerecorded demo file.
 */
enum class AudioSourceKind {
    /** In-app VoIP call; both legs are ours to analyse. */
    IN_APP_VOIP,

    /** Authorized collaboration/conference audio. */
    COLLABORATION,

    /** Device microphone during an authorized in-app session. */
    MICROPHONE,

    /** Prerecorded file. Deterministic; used for demos and tests. */
    PRERECORDED_DEMO,
}

/** Why an audio source is or is not permitted to run. */
sealed interface AudioAuthorization {
    /** The user granted the permission and the source is authorized. */
    data object Granted : AudioAuthorization

    /** A runtime permission is missing. */
    data class PermissionMissing(val permission: String) : AudioAuthorization

    /** The user has explicitly declined; do not prompt again this session. */
    data object Denied : AudioAuthorization

    /**
     * The platform forbids this source outright.
     * Cellular call audio is the case this exists for.
     */
    data class NotPermittedByPlatform(val reason: String) : AudioAuthorization
}

/** Lifecycle of a capture session. */
sealed interface CaptureState {
    data object Idle : CaptureState
    data object Starting : CaptureState
    data object Capturing : CaptureState
    data object Stopping : CaptureState
    data object Completed : CaptureState
    data class Failed(val reason: String) : CaptureState
}

/**
 * The canonical analysis format (docs/ML_SPEC.md 5).
 *
 * 16 kHz, mono, 16-bit little-endian PCM. Sources that natively differ are
 * normalised to this before packetisation, so every analyzer sees one format.
 */
object AudioFormat {
    const val SAMPLE_RATE_HZ = 16_000
    const val CHANNELS = 1
    const val BITS_PER_SAMPLE = 16
    const val BYTES_PER_SAMPLE = BITS_PER_SAMPLE / 8

    /** Bytes in one second of canonical audio. */
    const val BYTES_PER_SECOND = SAMPLE_RATE_HZ * CHANNELS * BYTES_PER_SAMPLE

    fun bytesFor(seconds: Double): Int = (BYTES_PER_SECOND * seconds).toInt()

    fun secondsFor(bytes: Int): Double = bytes.toDouble() / BYTES_PER_SECOND
}

/**
 * A source of authorized audio.
 *
 * Implementations push canonical PCM into a [RingBuffer]; they do not analyse
 * it. Analysis happens in the backend (docs/ARCHITECTURE.md 1, decision 8).
 */
interface AudioSource {
    val kind: AudioSourceKind

    /** Checked before [start]; capture must not begin without [AudioAuthorization.Granted]. */
    fun authorization(): AudioAuthorization

    /**
     * Begins capture, invoking [onChunk] with canonical 16 kHz mono PCM.
     * Returns the state the source settled into.
     */
    suspend fun start(onChunk: suspend (ByteArray) -> Unit): CaptureState

    suspend fun stop()

    /** Abandons capture without completing; used when the user leaves. */
    suspend fun cancel()
}
