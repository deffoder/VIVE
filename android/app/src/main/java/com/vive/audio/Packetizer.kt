package com.vive.audio

/**
 * Sliding-window packetizer.
 *
 * 2.0 s windows advancing 1.0 s at a time, so consecutive windows OVERLAP by
 * one second (docs/ARCHITECTURE.md 4):
 *
 *   P001  00:00 - 00:02
 *   P002  00:01 - 00:03
 *   P003  00:02 - 00:04
 *
 * A packet is therefore not a partition of the call, and the UI says so.
 */
class Packetizer(
    private val windowSeconds: Double = WINDOW_SECONDS,
    private val strideSeconds: Double = STRIDE_SECONDS,
) {
    private val windowBytes = AudioFormat.bytesFor(windowSeconds)
    private val strideBytes = AudioFormat.bytesFor(strideSeconds)

    private val ring = RingBuffer(capacityBytes = windowBytes * 4)
    private var bytesSinceLastWindow = 0
    private var seq = 0

    val packetsEmitted: Int get() = seq

    /**
     * Feeds audio in and emits every window that completed.
     *
     * Emitting a list rather than one packet matters: a large chunk can
     * complete several windows, and dropping the extras would silently lose
     * analysis coverage.
     */
    fun feed(pcm: ByteArray): List<AudioPacket> {
        ring.write(pcm)
        bytesSinceLastWindow += pcm.size

        val out = mutableListOf<AudioPacket>()
        // The first window needs a full window's worth of audio; after that,
        // one stride is enough to advance.
        while (ring.available >= windowBytes && bytesSinceLastWindow >= strideBytes) {
            seq += 1
            val startSec = (seq - 1) * strideSeconds
            out += AudioPacket(
                seq = seq,
                packetId = "P%03d".format(seq),
                startSec = startSec,
                endSec = startSec + windowSeconds,
                pcm = ring.readLast(windowBytes),
            )
            bytesSinceLastWindow -= strideBytes
        }
        return out
    }

    fun reset() {
        ring.clear()
        bytesSinceLastWindow = 0
        seq = 0
    }

    companion object {
        const val WINDOW_SECONDS = 2.0
        const val STRIDE_SECONDS = 1.0
    }
}

/**
 * One analysis window ready to send upstream.
 *
 * Carries its own identity and timing so the backend event it produces stays
 * traceable: packet id, sequence, window bounds and duration.
 */
data class AudioPacket(
    val seq: Int,
    val packetId: String,
    val startSec: Double,
    val endSec: Double,
    val pcm: ByteArray,
) {
    val durationSec: Double get() = endSec - startSec

    /** Call-relative mm:ss at the window's end, matching the backend. */
    val timestamp: String
        get() = "%02d:%02d".format(endSec.toInt() / 60, endSec.toInt() % 60)

    // ByteArray needs explicit equals/hashCode for data-class semantics.
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is AudioPacket) return false
        return seq == other.seq && packetId == other.packetId &&
            startSec == other.startSec && endSec == other.endSec &&
            pcm.contentEquals(other.pcm)
    }

    override fun hashCode(): Int {
        var result = seq
        result = 31 * result + packetId.hashCode()
        result = 31 * result + startSec.hashCode()
        result = 31 * result + pcm.contentHashCode()
        return result
    }
}
