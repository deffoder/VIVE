package com.vive.audio

import com.vive.data.model.AudioQuality

/**
 * Voice activity detection boundary.
 *
 * INTERFACE ONLY. Real Silero VAD is the ML phase (docs/ML_SPEC.md 9); nothing
 * here runs a model.
 *
 * On-device VAD exists to avoid shipping silence upstream, not to assess risk.
 * Every risk judgement stays in the backend.
 */
interface VoiceActivityDetector {
    fun hasSpeech(pcm: ByteArray): Boolean
}

/**
 * Energy-gate stand-in for a real VAD.
 *
 * This measures signal energy, which is a genuine property of the samples - it
 * is not a fabricated model output. It is deliberately crude and is only used
 * to skip obvious silence.
 */
class EnergyGateVad(private val thresholdRms: Double = 350.0) : VoiceActivityDetector {

    override fun hasSpeech(pcm: ByteArray): Boolean = rms(pcm) >= thresholdRms

    companion object {
        /**
         * Root-mean-square amplitude of 16-bit little-endian samples.
         * A measurement, not an inference.
         */
        fun rms(pcm: ByteArray): Double {
            if (pcm.size < 2) return 0.0
            var sumSquares = 0.0
            var count = 0
            var i = 0
            while (i + 1 < pcm.size) {
                val sample = ((pcm[i + 1].toInt() shl 8) or (pcm[i].toInt() and 0xFF)).toShort()
                sumSquares += sample.toDouble() * sample.toDouble()
                count++
                i += 2
            }
            return if (count == 0) 0.0 else kotlin.math.sqrt(sumSquares / count)
        }

        /** Fraction of samples at or beyond full scale - real clipping detection. */
        fun clippingRatio(pcm: ByteArray): Double {
            if (pcm.size < 2) return 0.0
            var clipped = 0
            var count = 0
            var i = 0
            while (i + 1 < pcm.size) {
                val sample = ((pcm[i + 1].toInt() shl 8) or (pcm[i].toInt() and 0xFF)).toShort()
                if (sample >= Short.MAX_VALUE - 1 || sample <= Short.MIN_VALUE + 1) clipped++
                count++
                i += 2
            }
            return if (count == 0) 0.0 else clipped.toDouble() / count
        }
    }
}

/**
 * Local audio-quality assessment.
 *
 * Reports ONLY what can be measured from the samples: signal level, clipping
 * and whether any speech was gated through. It does not estimate SNR, MOS or
 * anything requiring a model or a reference signal - inventing those would be
 * fabricating a measurement.
 *
 * The backend makes the authoritative quality call; this is a client-side hint
 * so obviously unusable audio can be flagged before it is sent.
 */
object AudioQualityMeter {

    fun assess(pcm: ByteArray, vad: VoiceActivityDetector = EnergyGateVad()): AudioQuality {
        if (pcm.size < 2) return AudioQuality.NO_SPEECH
        val rms = EnergyGateVad.rms(pcm)
        val clipping = EnergyGateVad.clippingRatio(pcm)

        return when {
            !vad.hasSpeech(pcm) -> AudioQuality.NO_SPEECH
            clipping > 0.05 -> AudioQuality.POOR
            rms < 600 -> AudioQuality.DEGRADED
            else -> AudioQuality.GOOD
        }
    }

    /** The raw measurements, for display or logging without interpretation. */
    fun measurements(pcm: ByteArray): AudioMeasurements = AudioMeasurements(
        rms = EnergyGateVad.rms(pcm),
        clippingRatio = EnergyGateVad.clippingRatio(pcm),
        durationSec = AudioFormat.secondsFor(pcm.size),
    )
}

/** Measured signal properties. Nothing here is inferred. */
data class AudioMeasurements(
    val rms: Double,
    val clippingRatio: Double,
    val durationSec: Double,
)
