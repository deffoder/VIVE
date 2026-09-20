package com.vive.audio

import kotlinx.coroutines.delay

/**
 * Deterministic prerecorded-audio stand-in — PATH B fallback.
 *
 * Generates a fixed PCM tone pattern rather than reading a WAV, so the repo
 * carries no audio asset and every run produces byte-identical output. That is
 * what makes a demo rehearsable.
 *
 * The samples are synthetic and carry no speech: they exercise capture,
 * buffering, packetisation and transport. Semantic analysis in a demo is driven
 * by scripted transcripts through the backend, not by pretending this audio
 * contains words.
 */
class DemoAudioSource(
    private val durationSeconds: Int = 10,
    private val chunkMillis: Int = 200,
    private val authorized: Boolean = true,
) : AudioSource {

    override val kind = AudioSourceKind.PRERECORDED_DEMO

    override fun authorization(): AudioAuthorization =
        if (authorized) AudioAuthorization.Granted else AudioAuthorization.Denied

    @Volatile
    private var cancelled = false

    override suspend fun start(onChunk: suspend (ByteArray) -> Unit): CaptureState {
        if (authorization() !is AudioAuthorization.Granted) {
            return CaptureState.Failed("not authorized")
        }
        cancelled = false

        val chunkBytes = AudioFormat.bytesFor(chunkMillis / 1000.0)
        val totalChunks = (durationSeconds * 1000) / chunkMillis

        for (index in 0 until totalChunks) {
            if (cancelled) return CaptureState.Idle
            onChunk(generateChunk(index, chunkBytes))
            delay(chunkMillis.toLong())
        }
        return CaptureState.Completed
    }

    override suspend fun stop() { cancelled = true }

    override suspend fun cancel() { cancelled = true }

    /**
     * Deterministic sample generation: a low-amplitude sine whose frequency
     * steps per chunk. Same index, same bytes, every run.
     */
    private fun generateChunk(index: Int, bytes: Int): ByteArray {
        val out = ByteArray(bytes)
        // A short modulo cycle (index % 5) made chunk 0 and chunk 5 identical:
        // the frequency repeated AND the phase realigned, because 180 Hz over a
        // 1 s cycle is a whole number of periods. A coprime step avoids both.
        val frequency = 180.0 + ((index * 61) % 240)
        val amplitude = 4_000.0 + ((index * 13) % 800)
        var i = 0
        var sampleIndex = index * (bytes / AudioFormat.BYTES_PER_SAMPLE)
        while (i + 1 < bytes) {
            val t = sampleIndex.toDouble() / AudioFormat.SAMPLE_RATE_HZ
            val value = (amplitude * kotlin.math.sin(2.0 * Math.PI * frequency * t)).toInt()
            out[i] = (value and 0xFF).toByte()
            out[i + 1] = ((value shr 8) and 0xFF).toByte()
            i += 2
            sampleIndex++
        }
        return out
    }
}
