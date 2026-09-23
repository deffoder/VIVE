package com.vive.ondevice

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtSession
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.nio.FloatBuffer

/**
 * `asr_manifest.json`, written by `scripts/mobile/export_asr.py`. Only the
 * fields the phone needs; the measured WER blocks are ignored here.
 */
@Serializable
data class AsrManifest(val models: Map<String, AsrModelSpec> = emptyMap())

@Serializable
data class AsrModelSpec(
    val file: String,
    val bytes: Long,
    val precision: String,
    val source: String,
    val license: String,
    val sample_rate: Int = 16_000,
    val do_normalize: Boolean = true,
    val blank_id: Int,
    val delimiter: String,
    val vocab: List<String>,
)

/**
 * On-device speech recognition: one wav2vec2-CTC model per language.
 *
 * Only one language is resident at a time. A session declares its language,
 * so holding all three would triple memory for no benefit; switching
 * language closes the old session before opening the new one.
 *
 * There is deliberately no fallback between languages. A Tamil window given
 * to the Hindi model yields a confident Devanagari transcript of the wrong
 * words, and a wrong transcript becomes intent, behaviour and risk.
 */
class OnDeviceAsr(
    private val modelDir: File,
    private val threads: Int = OnDeviceRuntime.DEFAULT_THREADS,
    private val manifestName: String = MANIFEST,
) {

    data class Result(
        val status: Status,
        val text: String? = null,
        val confidence: Double? = null,
        val language: String? = null,
        val inferenceMs: Long? = null,
        val modelVersion: String? = null,
        val detail: String? = null,
    )

    enum class Status { AVAILABLE, INSUFFICIENT_AUDIO, UNSUPPORTED_LANGUAGE, LOAD_ERROR, INFERENCE_ERROR }

    private val manifest: AsrManifest? by lazy {
        val f = File(modelDir, manifestName)
        if (!f.isFile) null else runCatching {
            json.decodeFromString(AsrManifest.serializer(), f.readText())
        }.getOrNull()
    }

    private var loadedLang: String? = null
    private var session: OrtSession? = null
    private var spec: AsrModelSpec? = null
    var lastLoadMs: Long? = null
        private set

    val languages: Set<String> get() = manifest?.models?.keys ?: emptySet()

    fun spec(language: String): AsrModelSpec? = manifest?.models?.get(language)

    /** Why [language] cannot run, or null when it can. */
    fun unavailableReason(language: String): String? {
        val m = manifest ?: return "asr manifest missing under ${modelDir.path}"
        val s = m.models[language] ?: return "no on-device ASR for '$language'"
        val f = File(modelDir, s.file)
        if (!f.isFile) return "model file ${s.file} not provisioned"
        if (f.length() != s.bytes) return "model file ${s.file} is ${f.length()} bytes, manifest says ${s.bytes}"
        return null
    }

    @Synchronized
    fun load(language: String): Status {
        if (loadedLang == language && session != null) return Status.AVAILABLE
        if (manifest?.models?.containsKey(language) == false) return Status.UNSUPPORTED_LANGUAGE
        unavailableReason(language)?.let { return Status.LOAD_ERROR }
        close()
        val s = manifest!!.models.getValue(language)
        val began = System.nanoTime()
        return try {
            session = OnDeviceRuntime.session(File(modelDir, s.file), threads)
            spec = s
            loadedLang = language
            lastLoadMs = (System.nanoTime() - began) / 1_000_000
            Status.AVAILABLE
        } catch (e: Exception) {
            close()
            Status.LOAD_ERROR
        }
    }

    /** Transcribes 16 kHz mono float samples in [language]. */
    @Synchronized
    fun transcribe(samples: FloatArray, language: String): Result {
        val loaded = load(language)
        if (loaded != Status.AVAILABLE) {
            return Result(loaded, language = language, detail = unavailableReason(language))
        }
        if (samples.size < MIN_SAMPLES) return Result(Status.INSUFFICIENT_AUDIO, language = language)
        val s = spec!!
        val input = if (s.do_normalize) CtcDecoder.normalise(samples) else samples
        val began = System.nanoTime()
        return try {
            OnnxTensor.createTensor(
                OnDeviceRuntime.env, FloatBuffer.wrap(input), longArrayOf(1, input.size.toLong()),
            ).use { tensor ->
                session!!.run(mapOf(INPUT to tensor)).use { out ->
                    val logits = out[0] as OnnxTensor
                    val shape = logits.info.shape // [1, frames, vocab]
                    val frames = shape[1].toInt()
                    val vocab = shape[2].toInt()
                    val buf = logits.floatBuffer
                    val flat = FloatArray(buf.remaining()).also { buf.get(it) }
                    val decoded = CtcDecoder.decode(flat, frames, vocab, s.vocab, s.blank_id, s.delimiter)
                    val ms = (System.nanoTime() - began) / 1_000_000
                    if (decoded.text.isEmpty()) {
                        Result(Status.INSUFFICIENT_AUDIO, language = language, inferenceMs = ms, modelVersion = version(s))
                    } else {
                        Result(Status.AVAILABLE, decoded.text, decoded.confidence, language, ms, version(s))
                    }
                }
            }
        } catch (e: Exception) {
            Result(Status.INFERENCE_ERROR, language = language, detail = e::class.simpleName)
        }
    }

    @Synchronized
    fun close() {
        runCatching { session?.close() }
        session = null
        spec = null
        loadedLang = null
    }

    companion object {
        const val MANIFEST = "asr_manifest.json"
        const val INPUT = "input_values"
        /** Below ~25 ms the conv feature encoder emits no frames. */
        const val MIN_SAMPLES = 400
        private val json = Json { ignoreUnknownKeys = true }

        fun version(s: AsrModelSpec): String = "${s.source.substringAfter('/')}-${s.precision}"
    }
}
