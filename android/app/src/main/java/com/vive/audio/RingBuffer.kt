package com.vive.audio

/**
 * Bounded PCM ring buffer.
 *
 * Holds only the most recent audio needed to form analysis windows. Bounded on
 * purpose: an unbounded buffer is both a memory risk on a long call and a
 * privacy problem, since audio would accumulate in process memory
 * (docs/SECURITY_SPEC.md 4). Older audio is overwritten, never archived.
 */
class RingBuffer(val capacityBytes: Int) {

    init {
        require(capacityBytes > 0) { "capacity must be positive" }
    }

    private val buffer = ByteArray(capacityBytes)
    private var writeIndex = 0
    private var filled = 0

    /** Total bytes ever written, used to derive absolute stream position. */
    var totalWritten: Long = 0
        private set

    val available: Int get() = filled

    val isFull: Boolean get() = filled == capacityBytes

    @Synchronized
    fun write(data: ByteArray, length: Int = data.size) {
        require(length <= data.size) { "length exceeds array" }
        var offset = 0
        var remaining = length

        // A chunk larger than the buffer can only leave its tail behind.
        if (remaining > capacityBytes) {
            offset = remaining - capacityBytes
            remaining = capacityBytes
        }

        while (remaining > 0) {
            val chunk = minOf(remaining, capacityBytes - writeIndex)
            System.arraycopy(data, offset, buffer, writeIndex, chunk)
            writeIndex = (writeIndex + chunk) % capacityBytes
            offset += chunk
            remaining -= chunk
        }

        filled = minOf(capacityBytes, filled + length)
        totalWritten += length
    }

    /** Copies the most recent [count] bytes in chronological order. */
    @Synchronized
    fun readLast(count: Int): ByteArray {
        val n = minOf(count, filled)
        val out = ByteArray(n)
        var start = writeIndex - n
        if (start < 0) start += capacityBytes
        for (i in 0 until n) {
            out[i] = buffer[(start + i) % capacityBytes]
        }
        return out
    }

    @Synchronized
    fun clear() {
        writeIndex = 0
        filled = 0
        totalWritten = 0
        buffer.fill(0)
    }
}
