package com.vive.ondevice

import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.sqrt

/**
 * Greedy CTC decoding and the waveform normalisation the wav2vec2 models
 * expect. Pure Kotlin, no runtime dependency, so it is unit-tested on the JVM
 * against strings produced by `scripts/mobile/export_asr.py`.
 *
 * This is a line-for-line port of `ctc_greedy` and `normalise_wave` in that
 * script. The WER published in the manifest was measured through exactly this
 * arithmetic, which is the only reason it may be quoted for the phone.
 */
object CtcDecoder {

    data class Decoded(
        val text: String,
        /**
         * exp(mean over emitted frames of the max log-probability) - the same
         * decoder confidence the server ASR reports. NOT a probability that
         * the transcript is correct and NOT a fraud probability. Null when
         * every frame was blank.
         */
        val confidence: Double?,
    )

    /**
     * @param logits row-major `[frames][vocab]`.
     */
    fun decode(
        logits: FloatArray,
        frames: Int,
        vocabSize: Int,
        vocab: List<String>,
        blank: Int,
        delimiter: String,
    ): Decoded {
        require(logits.size == frames * vocabSize) { "logits shape mismatch" }
        val sb = StringBuilder()
        var previous = -1
        var keptLogProb = 0.0
        var kept = 0
        for (f in 0 until frames) {
            val base = f * vocabSize
            var best = 0
            var bestValue = logits[base]
            for (v in 1 until vocabSize) {
                val x = logits[base + v]
                if (x > bestValue) { bestValue = x; best = v }
            }
            if (best != blank) {
                // log-softmax of the winning class: x_max - logsumexp(x).
                var sum = 0.0
                for (v in 0 until vocabSize) sum += exp((logits[base + v] - bestValue).toDouble())
                keptLogProb += -ln(sum)
                kept += 1
                if (best != previous && !isSpecial(vocab[best])) sb.append(vocab[best])
            }
            previous = best
        }
        val text = sb.toString().replace(delimiter, " ").trim().split(Regex("\\s+"))
            .filter { it.isNotEmpty() }.joinToString(" ")
        return Decoded(text, if (kept > 0) exp(keptLogProb / kept) else null)
    }

    /** `<s>`, `<pad>`, `</s>`, `<unk>`: never part of a transcript. */
    fun isSpecial(token: String): Boolean =
        token.length > 2 && token.startsWith("<") && token.endsWith(">")

    /** Zero mean, unit variance; the 1e-7 matches Wav2Vec2FeatureExtractor. */
    fun normalise(samples: FloatArray): FloatArray {
        if (samples.isEmpty()) return samples
        var mean = 0.0
        for (s in samples) mean += s
        mean /= samples.size
        var variance = 0.0
        for (s in samples) { val d = s - mean; variance += d * d }
        variance /= samples.size
        val scale = 1.0 / sqrt(variance + 1e-7)
        return FloatArray(samples.size) { ((samples[it] - mean) * scale).toFloat() }
    }

    /** 16-bit little-endian PCM to [-1, 1) floats, as the backend does. */
    fun pcmToFloat(pcm: ByteArray): FloatArray {
        val n = pcm.size / 2
        return FloatArray(n) {
            val lo = pcm[2 * it].toInt() and 0xFF
            val hi = pcm[2 * it + 1].toInt()
            ((hi shl 8) or lo).toShort() / 32768f
        }
    }
}
