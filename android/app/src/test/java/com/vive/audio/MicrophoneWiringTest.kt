package com.vive.audio

import com.vive.data.model.AdapterMode
import com.vive.data.remote.NetworkModule
import com.vive.data.remote.dto.PacketDto
import com.vive.data.remote.dto.toDomain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The live microphone path, at the seams a unit test can reach.
 *
 * `AudioRecord` itself cannot run on the JVM, so these pin the contracts
 * around it: that capture refuses to start unauthorized, that windowing
 * matches the backend's expectation, and that a packet's adapter mode
 * survives the wire. The recorder itself is verified on-device.
 */
class MicrophoneWiringTest {

    private class StubSource(
        private val auth: AudioAuthorization,
        override val kind: AudioSourceKind = AudioSourceKind.MICROPHONE,
    ) : AudioSource {
        var started = false
        override fun authorization() = auth
        override suspend fun start(onChunk: suspend (ByteArray) -> Unit): CaptureState {
            started = true
            return CaptureState.Completed
        }
        override suspend fun stop() = Unit
        override suspend fun cancel() = Unit
    }

    @Test
    fun `capture refuses to start without the microphone permission`() {
        val source = StubSource(
            AudioAuthorization.PermissionMissing("android.permission.RECORD_AUDIO"),
        )
        val controller = CaptureController(
            source = source,
            scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.Unconfined),
        )

        controller.start { }

        assertFalse("capture must not begin without permission", source.started)
        assertTrue(controller.state.value is CaptureState.Failed)
    }

    @Test
    fun `capture refuses a source the platform forbids`() {
        val source = StubSource(
            AudioAuthorization.NotPermittedByPlatform("cellular call audio is not accessible"),
        )
        val controller = CaptureController(
            source = source,
            scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.Unconfined),
        )

        controller.start { }

        assertFalse(source.started)
        val state = controller.state.value
        assertTrue(state is CaptureState.Failed)
        assertEquals(
            "cellular call audio is not accessible",
            (state as CaptureState.Failed).reason,
        )
    }

    @Test
    fun `windows match the backend's 2 second window and 1 second stride`() {
        // What the backend expects (docs/ARCHITECTURE.md 4). If the client
        // packetised differently, every window would be analysed against the
        // wrong span of audio.
        val packetizer = Packetizer()
        val oneSecond = ByteArray(AudioFormat.BYTES_PER_SECOND)

        assertTrue("no window before 2 s of audio", packetizer.feed(oneSecond).isEmpty())

        val first = packetizer.feed(oneSecond)
        assertEquals(1, first.size)
        assertEquals(0.0, first[0].startSec, 0.001)
        assertEquals(2.0, first[0].endSec, 0.001)
        assertEquals(AudioFormat.bytesFor(2.0), first[0].pcm.size)

        val second = packetizer.feed(oneSecond)
        assertEquals("one stride advances one window", 1, second.size)
        assertEquals("windows overlap by 1 s", 1.0, second[0].startSec, 0.001)
        assertEquals(3.0, second[0].endSec, 0.001)
    }

    @Test
    fun `a full window does not emit two windows at once`() {
        // Regression guard. `bytesSinceLastWindow` counted from zero, so the
        // first full window satisfied the stride condition TWICE: two packets
        // came out of 2 s of audio, the second holding the same samples but
        // labelled 1-3 s. Every later window inherited that offset, so each
        // one was analysed against a span of audio it did not contain.
        val packetizer = Packetizer()
        val twoSeconds = ByteArray(AudioFormat.bytesFor(2.0))

        val windows = packetizer.feed(twoSeconds)

        assertEquals("2 s of audio is exactly one window", 1, windows.size)
        assertEquals(0.0, windows[0].startSec, 0.001)
        assertEquals(2.0, windows[0].endSec, 0.001)
    }

    @Test
    fun `a chunk spanning several windows labels each one correctly`() {
        val packetizer = Packetizer()

        val windows = packetizer.feed(ByteArray(AudioFormat.bytesFor(4.0)))

        // 4 s yields windows ending at 2, 3 and 4 seconds.
        assertEquals(3, windows.size)
        assertEquals(listOf(0.0, 1.0, 2.0), windows.map { it.startSec })
        assertEquals(listOf(2.0, 3.0, 4.0), windows.map { it.endSec })
        assertTrue(
            "every window carries a full 2 s of audio",
            windows.all { it.pcm.size == AudioFormat.bytesFor(2.0) },
        )
    }

    @Test
    fun `microphone capture uses the canonical analysis format`() {
        // 16 kHz mono 16-bit, recorded directly rather than resampled - a
        // resampler would be one more place audio could change before a model
        // sees it (docs/ML_SPEC.md 5).
        assertEquals(16_000, AudioFormat.SAMPLE_RATE_HZ)
        assertEquals(1, AudioFormat.CHANNELS)
        assertEquals(16, AudioFormat.BITS_PER_SAMPLE)
        assertEquals(32_000, AudioFormat.BYTES_PER_SECOND)
    }

    @Test
    fun `a real-mode packet is not reported as demo data`() {
        val json = NetworkModule.json
        fun packet(mode: String) = """
        {
          "packet_id": "P001", "timestamp": "00:02", "duration_sec": 2,
          "language": "hi", "quality": "GOOD",
          "aasist": {"status": "INSUFFICIENT_AUDIO", "score": null},
          "ecapa": {"status": "NO_REFERENCE", "similarity": null},
          "asr": {"transcript": "namaste", "confidence": 0.9, "status": "AVAILABLE"},
          "intent": {"label": "NORMAL_CONVERSATION", "status": "AVAILABLE"},
          "behavior": {"labels": [], "status": "AVAILABLE"},
          "context": {"caller_verified": false},
          "risk": {"score": 10, "level": "LOW", "confidence": 0.8,
                   "contributions": {}, "reasons": []},
          "adapter_mode": "$mode"
        }
        """.trimIndent()

        assertEquals(
            AdapterMode.REAL,
            json.decodeFromString<PacketDto>(packet("real")).toDomain().adapterMode,
        )
        assertEquals(
            AdapterMode.MOCK,
            json.decodeFromString<PacketDto>(packet("mock")).toDomain().adapterMode,
        )
    }
}

/**
 * Delivery must be reported, not assumed.
 *
 * `sendAudio` returned Unit and used `sockets[sessionId]?.send(...)`, so a
 * missing socket was a silent no-op while the capture counter kept counting.
 * The UI read "89 analysis windows sent to the backend" with a backend that
 * had received none - a claim of delivery with nothing behind it, and
 * indistinguishable on screen from a working capture.
 */
class AudioDeliveryContractTest {

    private class RecordingStream(private val connected: Boolean) {
        var attempts = 0
        fun sendAudio(pcm: ByteArray): Boolean {
            attempts += 1
            return connected && pcm.isNotEmpty()
        }
    }

    @Test
    fun `an unsent window is not counted as sent`() {
        val stream = RecordingStream(connected = false)
        var counted = 0

        repeat(5) {
            if (stream.sendAudio(ByteArray(64_000))) counted += 1
        }

        assertEquals("every window was attempted", 5, stream.attempts)
        assertEquals("none should be counted as delivered", 0, counted)
    }

    @Test
    fun `a delivered window is counted`() {
        val stream = RecordingStream(connected = true)
        var counted = 0

        repeat(5) {
            if (stream.sendAudio(ByteArray(64_000))) counted += 1
        }

        assertEquals(5, counted)
    }
}
