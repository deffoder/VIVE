package com.vive.ondevice

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtSession
import com.vive.data.model.AudioQuality
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.nio.FloatBuffer
import java.nio.LongBuffer
import kotlin.math.abs
import kotlin.math.sqrt

@Serializable
data class AudioManifest(val models: Map<String, AudioModelSpec>)

@Serializable
data class AudioModelSpec(
    val file: String,
    val bytes: Long,
    val source: String,
    val license: String,
    val version: String,
    val match_threshold: Double? = null,
    val threshold_source: String? = null,
    val min_enrol_samples: Int? = null,
)

internal object AudioManifestLoader {
    private val json = Json { ignoreUnknownKeys = true }
    const val FILE = "audio_manifest.json"

    fun spec(dir: File, key: String): Pair<AudioModelSpec?, String?> {
        val f = File(dir, FILE)
        if (!f.isFile) return null to "audio manifest missing under ${dir.path}"
        val m = runCatching { json.decodeFromString(AudioManifest.serializer(), f.readText()) }
            .getOrElse { return null to "audio manifest unreadable" }
        val s = m.models[key] ?: return null to "manifest has no $key model"
        val model = File(dir, s.file)
        if (!model.isFile || model.length() != s.bytes) return null to "${s.file} missing or truncated"
        return s to null
    }
}

/**
 * Silero VAD v5 on the device, deciding speech vs silence and audio quality
 * for each window with the backend's exact rules (`SileroVadAdapter`): frame
 * threshold 0.5, >= 10% speech frames, and quality from measured signal
 * properties only - quality never encodes suspicion.
 */
class OnDeviceVad(private val modelDir: File) {

    data class Result(val available: Boolean, val hasSpeech: Boolean, val quality: AudioQuality,
                      val speechRatio: Double = 0.0, val inferenceMs: Long? = null)

    private var session: OrtSession? = null
    var version: String? = null; private set
    var loadError: String? = "not loaded"; private set

    @Synchronized
    fun load(): Boolean {
        if (session != null) return true
        val (spec, err) = AudioManifestLoader.spec(modelDir, "vad")
        if (spec == null) { loadError = err; return false }
        return runCatching {
            session = OnDeviceRuntime.session(File(modelDir, spec.file), threads = 1)
            version = spec.version
            loadError = null
            true
        }.getOrElse { loadError = it::class.simpleName; false }
    }

    @Synchronized
    fun analyze(samples: FloatArray): Result {
        if (!load()) return Result(false, false, AudioQuality.NO_SPEECH)
        if (samples.size < FRAME) return Result(true, false, AudioQuality.NO_SPEECH)
        val began = System.nanoTime()
        val env = OnDeviceRuntime.env
        var state = FloatArray(2 * 1 * 128)
        val context = FloatArray(CONTEXT)
        val frames = samples.size / FRAME
        var speech = 0
        OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(SR.toLong())), LongArray(0)).use { sr ->
            for (i in 0 until frames) {
                val input = FloatArray(CONTEXT + FRAME)
                System.arraycopy(context, 0, input, 0, CONTEXT)
                System.arraycopy(samples, i * FRAME, input, CONTEXT, FRAME)
                System.arraycopy(input, FRAME, context, 0, CONTEXT)
                OnnxTensor.createTensor(env, FloatBuffer.wrap(input), longArrayOf(1, (CONTEXT + FRAME).toLong())).use { x ->
                    OnnxTensor.createTensor(env, FloatBuffer.wrap(state), longArrayOf(2, 1, 128)).use { st ->
                        session!!.run(mapOf("input" to x, "state" to st, "sr" to sr)).use { out ->
                            val p = (out[0] as OnnxTensor).floatBuffer.get(0)
                            val sb = (out[1] as OnnxTensor).floatBuffer
                            state = FloatArray(sb.remaining()).also { sb.get(it) }
                            if (p >= SPEECH_THRESHOLD) speech += 1
                        }
                    }
                }
            }
        }
        val ratio = speech.toDouble() / maxOf(frames, 1)
        val has = ratio >= MIN_SPEECH_RATIO
        var peak = 0f
        var clippedCount = 0
        for (s in samples) { val a = abs(s); if (a > peak) peak = a; if (a >= 0.999f) clippedCount++ }
        val q = quality(has, ratio, peak.toDouble(), clippedCount.toDouble() / samples.size)
        return Result(true, has, q, ratio, (System.nanoTime() - began) / 1_000_000)
    }

    companion object {
        const val SR = 16_000
        const val FRAME = 512
        const val CONTEXT = 64
        const val SPEECH_THRESHOLD = 0.5f
        const val MIN_SPEECH_RATIO = 0.10

        fun quality(hasSpeech: Boolean, ratio: Double, peak: Double, clipped: Double): AudioQuality = when {
            !hasSpeech -> AudioQuality.NO_SPEECH
            clipped > 0.01 || peak < 0.02 -> AudioQuality.POOR
            ratio < 0.35 || peak < 0.08 -> AudioQuality.DEGRADED
            else -> AudioQuality.GOOD
        }
    }
}

/**
 * ECAPA-TDNN speaker verification on the device.
 *
 * Enrolment keeps only the 192-d embedding; the audio is dropped
 * (docs/SECURITY_SPEC.md 4). Without an enrolment the result is NO_REFERENCE,
 * which is never a mismatch. MATCH / MISMATCH use the threshold measured by
 * `scripts/mobile/export_audio.py` for exactly this protocol (>= 3 s
 * enrolment vs a 2 s window), carried in the manifest with its provenance.
 */
class OnDeviceSpeaker(private val modelDir: File) {

    enum class State { NO_REFERENCE, ENROLLED, MATCH, MISMATCH, INSUFFICIENT_AUDIO, UNAVAILABLE }

    data class Result(val state: State, val similarity: Double? = null, val inferenceMs: Long? = null)

    private var session: OrtSession? = null
    private var spec: AudioModelSpec? = null
    var loadError: String? = "not loaded"; private set
    val version: String? get() = spec?.version
    val threshold: Double? get() = spec?.match_threshold
    val thresholdSource: String? get() = spec?.threshold_source
    val minEnrolSamples: Int get() = spec?.min_enrol_samples ?: 48_000

    @Synchronized
    fun load(): Boolean {
        if (session != null) return true
        val (s, err) = AudioManifestLoader.spec(modelDir, "ecapa")
        if (s == null) { loadError = err; return false }
        return runCatching {
            session = OnDeviceRuntime.session(File(modelDir, s.file))
            spec = s
            loadError = null
            true
        }.getOrElse { loadError = it::class.simpleName; false }
    }

    @Synchronized
    fun embed(samples: FloatArray): FloatArray? {
        if (!load()) return null
        return OnnxTensor.createTensor(OnDeviceRuntime.env, FloatBuffer.wrap(samples), longArrayOf(1, samples.size.toLong())).use { x ->
            session!!.run(mapOf("wav" to x)).use { out ->
                val b = (out[0] as OnnxTensor).floatBuffer
                FloatArray(b.remaining()).also { b.get(it) }
            }
        }
    }

    /** Returns the reference embedding, or null when the audio is too short. */
    fun enrol(samples: FloatArray): FloatArray? {
        if (!load() || samples.size < minEnrolSamples) return null
        return embed(samples)
    }

    fun compare(samples: FloatArray, reference: FloatArray?): Result {
        if (!load()) return Result(State.UNAVAILABLE)
        if (reference == null) return Result(State.NO_REFERENCE)
        if (samples.size < OnDeviceVad.FRAME) return Result(State.INSUFFICIENT_AUDIO)
        val began = System.nanoTime()
        val e = embed(samples) ?: return Result(State.UNAVAILABLE)
        val sim = RiskRound.round4(cosine(e, reference))
        val t = threshold ?: return Result(State.UNAVAILABLE)
        return Result(if (sim >= t) State.MATCH else State.MISMATCH, sim, (System.nanoTime() - began) / 1_000_000)
    }

    companion object {
        fun cosine(a: FloatArray, b: FloatArray): Double {
            var dot = 0.0; var na = 0.0; var nb = 0.0
            for (i in a.indices) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i] }
            return dot / (sqrt(na) * sqrt(nb))
        }
    }
}

internal object RiskRound {
    fun round4(v: Double) = com.vive.ondevice.risk.RiskFusion.round4(v)
}
