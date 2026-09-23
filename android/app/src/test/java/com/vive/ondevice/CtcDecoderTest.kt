package com.vive.ondevice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class CtcDecoderTest {

    // fairseq-style vocabulary: the CTC blank is <s> at id 0, not <pad>.
    private val vocab = listOf("<s>", "<pad>", "</s>", "<unk>", "|", "a", "b")

    private fun oneHot(vararg ids: Int): FloatArray {
        val out = FloatArray(ids.size * vocab.size) { -10f }
        ids.forEachIndexed { f, id -> out[f * vocab.size + id] = 10f }
        return out
    }

    @Test
    fun `collapses repeats, keeps repeats split by blank, maps delimiter`() {
        val d = CtcDecoder.decode(oneHot(5, 5, 0, 5, 4, 6, 1, 6), 8, vocab.size, vocab, 0, "|")
        // <pad> is a special token: dropped, but it still breaks the repeat.
        assertEquals("aa bb", d.text)
    }

    @Test
    fun `all blank frames give empty text and no confidence`() {
        val d = CtcDecoder.decode(oneHot(0, 0, 0), 3, vocab.size, vocab, 0, "|")
        assertEquals("", d.text)
        assertNull(d.confidence)
    }

    @Test
    fun `confidence is exp of mean max log-prob over emitted frames`() {
        val d = CtcDecoder.decode(oneHot(5, 0, 6), 3, vocab.size, vocab, 0, "|")
        // Winner 10 vs six at -10: p = 1 / (1 + 6 e^-20), essentially 1.
        assertTrue(abs(d.confidence!! - 1.0) < 1e-6)
    }

    @Test
    fun `normalise gives zero mean unit variance`() {
        val x = CtcDecoder.normalise(floatArrayOf(1f, 2f, 3f, 4f))
        assertTrue(abs(x.average()) < 1e-6)
        assertTrue(abs(x.map { it * it }.average() - 1.0) < 1e-4)
    }

    @Test
    fun `pcm decode is little-endian signed`() {
        val f = CtcDecoder.pcmToFloat(byteArrayOf(0x00, 0x80.toByte(), 0xFF.toByte(), 0x7F))
        assertEquals(-1f, f[0])
        assertEquals(32767f / 32768f, f[1])
    }
}
