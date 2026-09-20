package com.vive.audio

import com.vive.data.model.AudioQuality
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * PATH B tests: ring buffer, packetisation, timing, quality and the
 * deterministic demo source.
 */
class AudioPipelineTest {

    private fun silence(seconds: Double) = ByteArray(AudioFormat.bytesFor(seconds))

    private fun tone(seconds: Double, amplitude: Int = 6000): ByteArray {
        val bytes = AudioFormat.bytesFor(seconds)
        val out = ByteArray(bytes)
        var i = 0
        var n = 0
        while (i + 1 < bytes) {
            val t = n.toDouble() / AudioFormat.SAMPLE_RATE_HZ
            val v = (amplitude * kotlin.math.sin(2 * Math.PI * 220 * t)).toInt()
            out[i] = (v and 0xFF).toByte()
            out[i + 1] = ((v shr 8) and 0xFF).toByte()
            i += 2; n++
        }
        return out
    }

    // ------------------------------------------------------------ ring buffer

    @Test
    fun `ring buffer is bounded and never exceeds capacity`() {
        val ring = RingBuffer(1024)
        ring.write(ByteArray(4096))
        assertEquals(1024, ring.available)
        assertTrue(ring.isFull)
    }

    @Test
    fun `ring buffer keeps the most recent bytes`() {
        val ring = RingBuffer(4)
        ring.write(byteArrayOf(1, 2, 3, 4, 5, 6))
        assertArrayEquals(byteArrayOf(3, 4, 5, 6), ring.readLast(4))
    }

    @Test
    fun `ring buffer wraps correctly across writes`() {
        val ring = RingBuffer(4)
        ring.write(byteArrayOf(1, 2, 3))
        ring.write(byteArrayOf(4, 5))
        assertArrayEquals(byteArrayOf(2, 3, 4, 5), ring.readLast(4))
    }

    @Test
    fun `clear discards buffered audio`() {
        val ring = RingBuffer(64)
        ring.write(ByteArray(32))
        ring.clear()
        assertEquals(0, ring.available)
    }

    private fun assertArrayEquals(expected: ByteArray, actual: ByteArray) {
        org.junit.Assert.assertArrayEquals(expected, actual)
    }

    // ----------------------------------------------------------- packetizer

    @Test
    fun `windows are 2 seconds wide with a 1 second stride and overlap`() {
        val packetizer = Packetizer()
        val packets = mutableListOf<AudioPacket>()
        repeat(6) { packets += packetizer.feed(tone(1.0)) }

        assertTrue("expected several windows", packets.size >= 4)
        packets.forEach {
            assertEquals(2.0, it.durationSec, 1e-9)
        }
        packets.zipWithNext { a, b ->
            assertEquals(1.0, b.startSec - a.startSec, 1e-9)
            assertTrue("windows must overlap", b.startSec < a.endSec)
        }
    }

    @Test
    fun `packet ids are sequential and zero padded`() {
        val packetizer = Packetizer()
        val packets = mutableListOf<AudioPacket>()
        repeat(5) { packets += packetizer.feed(tone(1.0)) }
        assertEquals(listOf("P001", "P002", "P003", "P004"), packets.take(4).map { it.packetId })
    }

    @Test
    fun `timestamps are call relative mm ss at the window end`() {
        val packetizer = Packetizer()
        val packets = mutableListOf<AudioPacket>()
        repeat(4) { packets += packetizer.feed(tone(1.0)) }
        assertEquals("00:02", packets.first().timestamp)
        assertEquals("00:03", packets[1].timestamp)
    }

    @Test
    fun `no window is emitted before a full window of audio arrives`() {
        val packetizer = Packetizer()
        assertTrue(packetizer.feed(tone(0.5)).isEmpty())
        assertTrue(packetizer.feed(tone(0.9)).isEmpty())
    }

    @Test
    fun `a large chunk emits every window it completes`() {
        val packetizer = Packetizer()
        val packets = packetizer.feed(tone(5.0))
        assertTrue("a 5s chunk must complete multiple windows", packets.size >= 3)
    }

    @Test
    fun `reset clears sequence state`() {
        val packetizer = Packetizer()
        repeat(4) { packetizer.feed(tone(1.0)) }
        packetizer.reset()
        val after = mutableListOf<AudioPacket>()
        repeat(3) { after += packetizer.feed(tone(1.0)) }
        assertEquals("P001", after.first().packetId)
    }

    @Test
    fun `window pcm is exactly two seconds of canonical audio`() {
        val packetizer = Packetizer()
        val packets = mutableListOf<AudioPacket>()
        repeat(3) { packets += packetizer.feed(tone(1.0)) }
        assertEquals(AudioFormat.bytesFor(2.0), packets.first().pcm.size)
    }

    // --------------------------------------------------------- vad + quality

    @Test
    fun `energy gate distinguishes silence from tone`() {
        val vad = EnergyGateVad()
        assertTrue(!vad.hasSpeech(silence(1.0)))
        assertTrue(vad.hasSpeech(tone(1.0)))
    }

    @Test
    fun `quality reports NO_SPEECH for silence`() {
        assertEquals(AudioQuality.NO_SPEECH, AudioQualityMeter.assess(silence(1.0)))
    }

    @Test
    fun `quality reports POOR when the signal is clipping`() {
        val clipped = ByteArray(AudioFormat.bytesFor(0.5))
        var i = 0
        while (i + 1 < clipped.size) {
            clipped[i] = 0xFF.toByte()
            clipped[i + 1] = 0x7F // Short.MAX_VALUE
            i += 2
        }
        assertEquals(AudioQuality.POOR, AudioQualityMeter.assess(clipped))
    }

    @Test
    fun `quality reports GOOD for a healthy tone`() {
        assertEquals(AudioQuality.GOOD, AudioQualityMeter.assess(tone(1.0, amplitude = 9000)))
    }

    @Test
    fun `measurements are real and not invented`() {
        val m = AudioQualityMeter.measurements(tone(1.0))
        assertTrue("rms must be measured", m.rms > 0)
        assertEquals(1.0, m.durationSec, 0.01)
        assertEquals(0.0, m.clippingRatio, 1e-9)
    }

    // ------------------------------------------------------------ demo source

    @Test
    fun `demo source is deterministic across runs`() = runTest {
        suspend fun capture(): List<ByteArray> {
            val chunks = mutableListOf<ByteArray>()
            DemoAudioSource(durationSeconds = 1, chunkMillis = 200)
                .start { chunks += it.copyOf() }
            return chunks
        }
        val first = capture()
        val second = capture()
        assertEquals(first.size, second.size)
        first.zip(second).forEach { (a, b) ->
            assertTrue("same input must give the same bytes", a.contentEquals(b))
        }
    }

    @Test
    fun `demo source emits canonical format chunks`() = runTest {
        val chunks = mutableListOf<ByteArray>()
        val outcome = DemoAudioSource(durationSeconds = 1, chunkMillis = 200)
            .start { chunks += it }
        assertEquals(CaptureState.Completed, outcome)
        assertEquals(5, chunks.size)
        assertEquals(AudioFormat.bytesFor(0.2), chunks.first().size)
    }

    @Test
    fun `unauthorized source refuses to start`() = runTest {
        val source = DemoAudioSource(durationSeconds = 1, authorized = false)
        val outcome = source.start { }
        assertTrue(outcome is CaptureState.Failed)
    }

    @Test
    fun `different chunks of the demo source differ`() = runTest {
        val chunks = mutableListOf<ByteArray>()
        DemoAudioSource(durationSeconds = 2, chunkMillis = 200).start { chunks += it.copyOf() }
        assertNotEquals(
            "a constant stream would not exercise packetisation",
            chunks[0].toList(),
            chunks[5].toList(),
        )
    }
}
