package com.vive.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Packetization arithmetic, at every duration that matters.
 *
 * This is the one piece of client-side signal handling that can silently
 * corrupt an entire session: a window mislabelled by one stride is analysed
 * against audio it does not contain, and nothing downstream can detect that.
 * The backend trusts the client's window bounds.
 *
 * Window 2.0 s, stride 1.0 s, so window `k` (zero-based) covers
 * `[k, k+2]` seconds and closes once `2 + k` seconds have been fed.
 */
class PacketizerMathTest {

    private fun seconds(n: Double) = ByteArray(AudioFormat.bytesFor(n))

    private fun windowsFor(vararg chunkSeconds: Double): List<AudioPacket> {
        val packetizer = Packetizer()
        val out = mutableListOf<AudioPacket>()
        chunkSeconds.forEach { out += packetizer.feed(seconds(it)) }
        return out
    }

    @Test
    fun `half a second yields nothing`() {
        assertTrue(windowsFor(0.5).isEmpty())
    }

    @Test
    fun `one second yields nothing`() {
        assertTrue("a window needs a full 2 s", windowsFor(1.0).isEmpty())
    }

    @Test
    fun `two seconds yields exactly one window`() {
        val windows = windowsFor(2.0)
        assertEquals(1, windows.size)
        assertEquals(0.0, windows[0].startSec, 1e-9)
        assertEquals(2.0, windows[0].endSec, 1e-9)
    }

    @Test
    fun `three seconds yields two windows`() {
        val windows = windowsFor(3.0)
        assertEquals(2, windows.size)
        assertEquals(listOf(0.0, 1.0), windows.map { it.startSec })
        assertEquals(listOf(2.0, 3.0), windows.map { it.endSec })
    }

    @Test
    fun `five seconds yields four windows`() {
        val windows = windowsFor(5.0)
        assertEquals(4, windows.size)
        assertEquals(listOf(0.0, 1.0, 2.0, 3.0), windows.map { it.startSec })
        assertEquals(listOf(2.0, 3.0, 4.0, 5.0), windows.map { it.endSec })
    }

    @Test
    fun `chunking does not change the result`() {
        // The same 5 s delivered as one chunk, as 1 s chunks and as 100 ms
        // chunks must produce identical windows. A real microphone delivers
        // small chunks; a test that only ever feeds whole seconds would miss
        // an accounting bug that only shows up at other chunk sizes.
        val whole = windowsFor(5.0)
        val perSecond = windowsFor(1.0, 1.0, 1.0, 1.0, 1.0)
        val realistic = Packetizer().let { p ->
            val out = mutableListOf<AudioPacket>()
            repeat(50) { out += p.feed(seconds(0.1)) }
            out
        }

        assertEquals(whole.map { it.startSec }, perSecond.map { it.startSec })
        assertEquals(whole.map { it.startSec }, realistic.map { it.startSec })
        assertEquals(whole.map { it.endSec }, realistic.map { it.endSec })
        assertEquals(whole.size, realistic.size)
    }

    @Test
    fun `sequence numbers are contiguous from one`() {
        val windows = windowsFor(10.0)
        assertEquals((1..9).toList(), windows.map { it.seq })
        assertEquals(
            (1..9).map { "P%03d".format(it) },
            windows.map { it.packetId },
        )
    }

    @Test
    fun `every window carries exactly two seconds of audio`() {
        val expected = AudioFormat.bytesFor(2.0)
        windowsFor(1.0, 1.0, 1.0, 1.0, 1.0, 1.0).forEach {
            assertEquals("window ${it.packetId} is the wrong length", expected, it.pcm.size)
        }
    }

    @Test
    fun `duration is always the window length, never the stride`() {
        windowsFor(6.0).forEach { assertEquals(2.0, it.durationSec, 1e-9) }
    }

    @Test
    fun `a partial trailing buffer emits nothing until its window closes`() {
        val packetizer = Packetizer()
        packetizer.feed(seconds(2.0))          // window 1 closes
        assertTrue(
            "0.9 s is not enough to close the next window",
            packetizer.feed(seconds(0.9)).isEmpty(),
        )
        val next = packetizer.feed(seconds(0.1))   // now exactly 3.0 s fed
        assertEquals(1, next.size)
        assertEquals(1.0, next[0].startSec, 1e-9)
        assertEquals(3.0, next[0].endSec, 1e-9)
    }

    @Test
    fun `continuous streaming stays aligned over a long session`() {
        // 5 minutes at 100 ms per read. Drift here would be invisible in a
        // short test and catastrophic in a real call.
        val packetizer = Packetizer()
        var count = 0
        var last: AudioPacket? = null
        repeat(3_000) {
            packetizer.feed(seconds(0.1)).forEach { packet ->
                count += 1
                assertEquals("seq must not skip", count, packet.seq)
                assertEquals(
                    "window $count is misaligned",
                    (count - 1).toDouble(),
                    packet.startSec,
                    1e-9,
                )
                last = packet
            }
        }
        assertEquals("300 s at 1 s stride, first window at 2 s", 299, count)
        assertEquals(300.0, last!!.endSec, 1e-9)
    }

    @Test
    fun `reset returns the packetizer to a clean state`() {
        val packetizer = Packetizer()
        packetizer.feed(seconds(5.0))
        packetizer.reset()

        assertEquals(0, packetizer.packetsEmitted)
        assertTrue(packetizer.feed(seconds(1.0)).isEmpty())
        val first = packetizer.feed(seconds(1.0))
        assertEquals(1, first.size)
        assertEquals("numbering restarts", 1, first[0].seq)
        assertEquals(0.0, first[0].startSec, 1e-9)
    }

    @Test
    fun `no audio is skipped between consecutive windows`() {
        // Consecutive windows overlap by one stride, so window k+1 must begin
        // exactly one stride after window k - never leaving a gap that no
        // window covers.
        val windows = windowsFor(12.0)
        windows.zipWithNext().forEach { (a, b) ->
            assertEquals(a.startSec + 1.0, b.startSec, 1e-9)
            assertTrue("windows must overlap, not partition", b.startSec < a.endSec)
        }
    }
}
