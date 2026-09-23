package com.vive.ondevice

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtSession
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.nio.LongBuffer
import kotlin.math.exp

@Serializable
data class TextManifest(
    val tokenizer: TokenizerSpec,
    val languages: List<String>,
    val models: Map<String, TextHeadSpec>,
)

@Serializable
data class TokenizerSpec(val file: String, val bytes: Long, val max_length: Int)

@Serializable
data class TextHeadSpec(
    val file: String,
    val bytes: Long,
    val precision: String,
    val kind: String,
    val labels: List<String>,
    val threshold: Double? = null,
    val version: String,
)

/**
 * On-device intent (softmax, 12 labels) and behaviour (multi-label sigmoid,
 * 8 labels) heads. Decoding mirrors `backend/app/adapters/real/text_classifiers.py`
 * exactly: argmax + its probability for intent; every label at or above the
 * threshold, confidence = mean probability of the labels that fired, for
 * behaviour.
 *
 * Label order comes from the manifest, which the export script copied from
 * the checkpoint's own id2label. [load] refuses to run if that order differs
 * from the app's taxonomy: a reordered head gives confident wrong labels.
 *
 * Tamil is declined with UNSUPPORTED_LANGUAGE: the heads saw no Tamil in
 * training (docs/BLOCKERS.md O11), so a prediction would be a guess.
 */
class OnDeviceText(
    private val modelDir: File,
    private val intentTaxonomy: List<String>,
    private val behaviorTaxonomy: List<String>,
    private val threads: Int = 2,
) {
    enum class Status { AVAILABLE, INSUFFICIENT_AUDIO, UNSUPPORTED_LANGUAGE, LOAD_ERROR, INFERENCE_ERROR }

    data class IntentOut(val status: Status, val label: String = "UNKNOWN", val confidence: Double? = null,
                         val inferenceMs: Long? = null, val version: String? = null)

    data class BehaviorOut(val status: Status, val labels: List<String> = emptyList(), val confidence: Double? = null,
                           val inferenceMs: Long? = null, val version: String? = null)

    private var manifest: TextManifest? = null
    private var tokenizer: WordPieceTokenizer? = null
    private var intent: OrtSession? = null
    private var behavior: OrtSession? = null
    var loadError: String? = "not loaded"
        private set
    var loadMs: Long? = null
        private set

    val status: Status get() = if (intent != null && behavior != null) Status.AVAILABLE else Status.LOAD_ERROR
    val intentVersion: String? get() = manifest?.models?.get("intent")?.version
    val behaviorVersion: String? get() = manifest?.models?.get("behavior")?.version

    @Synchronized
    fun load(): Status {
        if (status == Status.AVAILABLE) return Status.AVAILABLE
        val began = System.nanoTime()
        try {
            val f = File(modelDir, MANIFEST)
            if (!f.isFile) return fail("text manifest missing under ${modelDir.path}")
            val m = json.decodeFromString(TextManifest.serializer(), f.readText())
            val i = m.models["intent"] ?: return fail("manifest has no intent head")
            val b = m.models["behavior"] ?: return fail("manifest has no behaviour head")
            if (i.labels != intentTaxonomy) return fail("intent label order differs from the taxonomy")
            if (b.labels != behaviorTaxonomy) return fail("behaviour label order differs from the taxonomy")
            for (spec in listOf(i.file to i.bytes, b.file to b.bytes, m.tokenizer.file to m.tokenizer.bytes)) {
                val file = File(modelDir, spec.first)
                if (!file.isFile || file.length() != spec.second) return fail("${spec.first} missing or truncated")
            }
            tokenizer = WordPieceTokenizer(File(modelDir, m.tokenizer.file).readLines(), m.tokenizer.max_length)
            intent = OnDeviceRuntime.session(File(modelDir, i.file), threads)
            behavior = OnDeviceRuntime.session(File(modelDir, b.file), threads)
            manifest = m
            loadError = null
            loadMs = (System.nanoTime() - began) / 1_000_000
            return Status.AVAILABLE
        } catch (e: Exception) {
            close()
            return fail("${e::class.simpleName}: ${e.message?.take(120)}")
        }
    }

    private fun fail(reason: String): Status { loadError = reason; return Status.LOAD_ERROR }

    private fun guard(text: String?, language: String?): Status? {
        if (load() != Status.AVAILABLE) return Status.LOAD_ERROR
        if (language != null && language !in manifest!!.languages) return Status.UNSUPPORTED_LANGUAGE
        if (text.isNullOrBlank()) return Status.INSUFFICIENT_AUDIO
        return null
    }

    /** Raw logits, exposed for the parity check against the desktop graph. */
    @Synchronized
    fun logits(head: String, text: String): FloatArray {
        val ids = tokenizer!!.encode(text)
        val shape = longArrayOf(1, ids.size.toLong())
        val env = OnDeviceRuntime.env
        val session = if (head == "intent") intent!! else behavior!!
        OnnxTensor.createTensor(env, LongBuffer.wrap(LongArray(ids.size) { ids[it].toLong() }), shape).use { idT ->
            OnnxTensor.createTensor(env, LongBuffer.wrap(LongArray(ids.size) { 1L }), shape).use { maskT ->
                session.run(mapOf("input_ids" to idT, "attention_mask" to maskT)).use { out ->
                    val buf = (out[0] as OnnxTensor).floatBuffer
                    return FloatArray(buf.remaining()).also { buf.get(it) }
                }
            }
        }
    }

    fun intent(text: String?, language: String?): IntentOut {
        guard(text, language)?.let { return IntentOut(it, version = intentVersion) }
        val began = System.nanoTime()
        return try {
            val probs = softmax(logits("intent", text!!))
            val best = probs.indices.maxBy { probs[it] }
            IntentOut(Status.AVAILABLE, intentTaxonomy[best], round4(probs[best]),
                (System.nanoTime() - began) / 1_000_000, intentVersion)
        } catch (e: Exception) {
            IntentOut(Status.INFERENCE_ERROR, version = intentVersion)
        }
    }

    fun behavior(text: String?, language: String?): BehaviorOut {
        guard(text, language)?.let { return BehaviorOut(it, version = behaviorVersion) }
        val began = System.nanoTime()
        return try {
            val threshold = manifest!!.models.getValue("behavior").threshold ?: 0.5
            val probs = logits("behavior", text!!).map { 1.0 / (1.0 + exp(-it.toDouble())) }
            val fired = probs.withIndex().filter { it.value >= threshold }
            BehaviorOut(
                Status.AVAILABLE, fired.map { behaviorTaxonomy[it.index] },
                if (fired.isEmpty()) null else round4(fired.sumOf { it.value } / fired.size),
                (System.nanoTime() - began) / 1_000_000, behaviorVersion,
            )
        } catch (e: Exception) {
            BehaviorOut(Status.INFERENCE_ERROR, version = behaviorVersion)
        }
    }

    @Synchronized
    fun close() {
        runCatching { intent?.close() }
        runCatching { behavior?.close() }
        intent = null
        behavior = null
    }

    companion object {
        const val MANIFEST = "text_manifest.json"
        private val json = Json { ignoreUnknownKeys = true }

        fun softmax(x: FloatArray): DoubleArray {
            val m = x.max()
            val e = DoubleArray(x.size) { exp((x[it] - m).toDouble()) }
            val s = e.sum()
            return DoubleArray(x.size) { e[it] / s }
        }

        fun round4(v: Double): Double = Math.round(v * 10_000) / 10_000.0
    }
}
