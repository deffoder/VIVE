package com.vive.ondevice

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Minimal 16 kHz mono PCM-16 WAV reader, for evaluation fixtures only. */
object Wav {
    fun read16kMono(file: File): FloatArray {
        val bytes = file.readBytes()
        val bb = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        require(String(bytes, 0, 4) == "RIFF" && String(bytes, 8, 4) == "WAVE") { "not a WAV: ${file.name}" }
        var pos = 12
        var channels = 0
        var rate = 0
        var bits = 0
        while (pos + 8 <= bytes.size) {
            val id = String(bytes, pos, 4)
            val size = bb.getInt(pos + 4)
            val body = pos + 8
            when (id) {
                "fmt " -> {
                    channels = bb.getShort(body + 2).toInt()
                    rate = bb.getInt(body + 4)
                    bits = bb.getShort(body + 14).toInt()
                }
                "data" -> {
                    require(channels == 1 && rate == 16_000 && bits == 16) {
                        "expected 16 kHz mono 16-bit, got $rate Hz x$channels ${bits}bit"
                    }
                    val end = minOf(body + size, bytes.size)
                    return CtcDecoder.pcmToFloat(bytes.copyOfRange(body, end))
                }
            }
            pos = body + size + (size and 1)
        }
        error("no data chunk in ${file.name}")
    }
}

/** Process memory from /proc, which is what the OS weighs when it kills apps. */
object MemoryProbe {
    private fun field(name: String): Long =
        File("/proc/self/status").readLines().firstOrNull { it.startsWith(name) }
            ?.split(Regex("\\s+"))?.getOrNull(1)?.toLongOrNull() ?: -1

    fun rssKb(): Long = field("VmRSS:")
    fun hwmKb(): Long = field("VmHWM:")
}
