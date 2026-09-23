package com.vive.ondevice

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtSession
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.nio.FloatBuffer
import kotlin.math.exp

@Serializable
data class AntiSpoofManifest(val models: Map<String, AntiSpoofSpec>)

@Serializable
data class AntiSpoofSpec(
    val file: String,
    val bytes: Long,
    val source: String,
    val license: String,
    val version: String,
    val labels: List<String>,
    val spoof_index: Int,
    val window_samples: Int = 32_000,
    val do_normalize: Boolean = true,
    /** Set only by `scripts/mobile/handset_antispoof.py` after measuring handset-captured audio. */
    val validated: Boolean = false,
    val validation_note: String? = null,
)

/**
 * wav2vec2 anti-spoofing on the device (Phase J2's selection).
 *
 * The score is P(synthetic) for this window. It is NOT a probability of
 * fraud: synthetic speech is not fraud and human speech is not safety
 * (docs/BLOCKERS.md P3).
 *
 * Unless the manifest records that the model was validated on audio captured
 * through a handset microphone, [score] returns [State.NOT_VALIDATED] and
 * nothing is computed. AASIST was correct on its benchmark and returned
 * 0.9998 "spoof" for genuine speech through this phone, so a benchmark
 * result is not permission to put a number in front of a user.
 */
class OnDeviceAntiSpoof(private val modelDir: File) {

    enum class State { AVAILABLE, NOT_VALIDATED, UNAVAILABLE, INSUFFICIENT_AUDIO, INFERENCE_ERROR }

    data class Result(val state: State, val score: Double? = null, val ms: Long? = null)

    private var session: OrtSession? = null
    var spec: AntiSpoofSpec? = null; private set
    var loadError: String? = "not loaded"; private set

    @Synchronized
    fun load(): Boolean {
        if (spec != null) return true
        val f = File(modelDir, MANIFEST)
        if (!f.isFile) { loadError = "anti-spoof manifest missing"; return false }
        val s = runCatching { json.decodeFromString(AntiSpoofManifest.serializer(), f.readText()) }
            .getOrElse { loadError = "anti-spoof manifest unreadable"; return false }
            .models["antispoof"] ?: run { loadError = "manifest has no antispoof model"; return false }
        val model = File(modelDir, s.file)
        if (!model.isFile || model.length() != s.bytes) { loadError = "${s.file} missing or truncated"; return false }
        spec = s
        if (!s.validated) { loadError = null; return true }   // known, deliberately not run
        return runCatching {
            session = OnDeviceRuntime.session(model)
            loadError = null
            true
        }.getOrElse { spec = null; loadError = it::class.simpleName; false }
    }

    val validated: Boolean get() = spec?.validated == true

    @Synchronized
    fun score(samples: FloatArray): Result {
        if (!load()) return Result(State.UNAVAILABLE)
        val s = spec!!
        if (!s.validated) return Result(State.NOT_VALIDATED)
        if (samples.size < MIN_SAMPLES) return Result(State.INSUFFICIENT_AUDIO)
        val x = if (s.do_normalize) CtcDecoder.normalise(samples) else samples
        val began = System.nanoTime()
        return try {
            OnnxTensor.createTensor(OnDeviceRuntime.env, FloatBuffer.wrap(x), longArrayOf(1, x.size.toLong())).use { t ->
                session!!.run(mapOf("input_values" to t)).use { out ->
                    val b = (out[0] as OnnxTensor).floatBuffer
                    val logits = FloatArray(b.remaining()).also { b.get(it) }
                    val m = logits.max()
                    val e = logits.map { exp((it - m).toDouble()) }
                    Result(State.AVAILABLE, RiskRound.round4(e[s.spoof_index] / e.sum()),
                        (System.nanoTime() - began) / 1_000_000)
                }
            }
        } catch (e: Exception) {
            Result(State.INFERENCE_ERROR)
        }
    }

    companion object {
        const val MANIFEST = "antispoof_manifest.json"
        /** Half a second, as the backend adapter. */
        const val MIN_SAMPLES = 8_000
        private val json = Json { ignoreUnknownKeys = true }
    }
}
