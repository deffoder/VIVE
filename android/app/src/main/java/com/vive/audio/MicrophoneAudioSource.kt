package com.vive.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat as AndroidAudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import com.vive.core.ViveLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlin.coroutines.coroutineContext

/**
 * The device microphone during an authorized in-app session — PATH B.
 *
 * This is the only source in the app that produces real speech. It records at
 * VIVE's canonical analysis format directly (16 kHz, mono, 16-bit PCM), so no
 * resampling or format conversion happens anywhere between the microphone and
 * the backend. Asking `AudioRecord` for the format we actually want is both
 * simpler and safer than converting afterwards: a resampler is one more place
 * for audio to be silently altered before a model sees it.
 *
 * ### What this is not
 *
 * This captures the **device microphone**, which in an in-app call carries the
 * local speaker and whatever the handset's mic picks up of the far end. It is
 * **not** cellular call audio. Android does not permit a third-party app to
 * capture both legs of an ordinary phone call, and `MediaRecorder.AudioSource`
 * offers no constant that would change that (docs/ARCHITECTURE.md 7,
 * docs/BLOCKERS.md P1). No input source grants call access; the choice below
 * only affects what the platform does to the microphone signal.
 *
 * ### Authorization
 *
 * [authorization] reports `PermissionMissing` until `RECORD_AUDIO` has actually
 * been granted, and [CaptureController] refuses to start without `Granted`. The
 * permission is checked here rather than assumed by the caller, so there is no
 * path that begins recording on an ungranted permission.
 */
class MicrophoneAudioSource(
    private val context: Context,
    private val chunkMillis: Int = DEFAULT_CHUNK_MILLIS,
    private val inputSource: Int = DEFAULT_INPUT_SOURCE,
) : AudioSource {

    override val kind = AudioSourceKind.MICROPHONE

    @Volatile
    private var record: AudioRecord? = null

    @Volatile
    private var stopped = false

    override fun authorization(): AudioAuthorization =
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED
        ) {
            AudioAuthorization.Granted
        } else {
            AudioAuthorization.PermissionMissing(Manifest.permission.RECORD_AUDIO)
        }

    override suspend fun start(onChunk: suspend (ByteArray) -> Unit): CaptureState =
        withContext(Dispatchers.IO) {
            if (authorization() !is AudioAuthorization.Granted) {
                return@withContext CaptureState.Failed("microphone permission not granted")
            }

            // The buffer must be at least the platform minimum or AudioRecord
            // refuses to initialise. Asking for several chunks' worth gives the
            // reader slack so a slow upload cannot drop samples on the floor.
            val minBuffer = AudioRecord.getMinBufferSize(
                AudioFormat.SAMPLE_RATE_HZ,
                AndroidAudioFormat.CHANNEL_IN_MONO,
                AndroidAudioFormat.ENCODING_PCM_16BIT,
            )
            if (minBuffer == AudioRecord.ERROR || minBuffer == AudioRecord.ERROR_BAD_VALUE) {
                return@withContext CaptureState.Failed(
                    "device does not support 16 kHz mono PCM capture",
                )
            }
            val chunkBytes = AudioFormat.bytesFor(chunkMillis / 1000.0)
            val bufferBytes = maxOf(minBuffer, chunkBytes * BUFFER_CHUNKS)

            val recorder = try {
                @Suppress("MissingPermission") // checked above via authorization()
                AudioRecord(
                    inputSource,
                    AudioFormat.SAMPLE_RATE_HZ,
                    AndroidAudioFormat.CHANNEL_IN_MONO,
                    AndroidAudioFormat.ENCODING_PCM_16BIT,
                    bufferBytes,
                )
            } catch (e: SecurityException) {
                return@withContext CaptureState.Failed("microphone permission denied")
            } catch (e: IllegalArgumentException) {
                return@withContext CaptureState.Failed("microphone unavailable")
            }

            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                recorder.release()
                return@withContext CaptureState.Failed("microphone could not be initialised")
            }

            record = recorder
            stopped = false

            try {
                recorder.startRecording()
                if (recorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                    return@withContext CaptureState.Failed("microphone did not start")
                }
                ViveLog.d(TAG) {
                    "capturing 16 kHz mono, buffer ${bufferBytes}B, " +
                        "inputSource=$inputSource"
                }

                val buffer = ByteArray(chunkBytes)
                while (!stopped) {
                    coroutineContext.ensureActive()
                    val read = recorder.read(buffer, 0, buffer.size)
                    when {
                        read > 0 -> onChunk(buffer.copyOf(read))
                        read == 0 -> Unit // nothing ready yet; loop
                        // A negative return is a real error, not an empty read.
                        else -> {
                            ViveLog.e(TAG, "microphone read error $read")
                            return@withContext CaptureState.Failed("microphone read failed")
                        }
                    }
                }
                CaptureState.Completed
            } finally {
                releaseRecorder()
            }
        }

    override suspend fun stop() {
        stopped = true
    }

    override suspend fun cancel() {
        stopped = true
    }

    /**
     * Stops and releases the recorder exactly once.
     *
     * An `AudioRecord` that is not released holds the microphone for the whole
     * process, so a later session would fail to initialise with no obvious
     * cause. This runs from the capture coroutine's `finally`, so it happens on
     * a normal stop, on cancellation and on a read error alike.
     */
    private fun releaseRecorder() {
        val recorder = record ?: return
        record = null
        runCatching {
            if (recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                recorder.stop()
            }
        }
        runCatching { recorder.release() }
        ViveLog.d(TAG) { "microphone released" }
    }

    private companion object {
        const val TAG = "MicrophoneAudioSource"

        /** 100 ms per read: small enough to keep latency low, large enough to
         *  avoid waking the reader thread constantly. */
        const val DEFAULT_CHUNK_MILLIS = 100

        const val BUFFER_CHUNKS = 8

        /**
         * Plain `MIC`, chosen on measured evidence rather than by default.
         *
         * `VOICE_COMMUNICATION` is the obvious pick for a call app and was
         * used first. It applies the platform's acoustic echo canceller,
         * whose job is to remove audio the device is PLAYING from what its
         * microphone hears - and that is precisely the far end of a call
         * played through the earpiece or speaker. For an app whose entire
         * purpose is analysing the other party's voice, the standard call
         * source removes the signal of interest.
         *
         * Measured on a OnePlus CPH2661 (Android 16), same build, same room,
         * same clip played from a nearby speaker:
         *
         *   VOICE_COMMUNICATION  0 packets - every window classified silent,
         *                        after the first two got through while the
         *                        canceller was still converging
         *   MIC                  packets produced, speech detected
         *                        (quality GOOD) and transcribed
         *
         * `MIC` captures what is acoustically present without that
         * subtraction. The cost is real and not hidden: no echo cancellation,
         * so in a speakerphone call the local side's own audio is captured
         * too, and the analysis cannot attribute a window to a speaker.
         * Speaker attribution needs diarisation or a separate far-end stream,
         * neither of which VIVE has (docs/BLOCKERS.md O3).
         */
        const val DEFAULT_INPUT_SOURCE = MediaRecorder.AudioSource.MIC
    }
}
