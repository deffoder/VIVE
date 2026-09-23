package com.vive.ondevice

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.vive.audio.AudioAuthorization
import com.vive.audio.AudioFormat
import com.vive.audio.MicrophoneAudioSource
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Records the phone's microphone through the SAME source the app captures
 * with, for measurements that need handset-captured audio (anti-spoofing
 * transfer). Writes results/handset.wav (16 kHz mono PCM-16).
 *
 *   adb shell am instrument -w -e class com.vive.ondevice.HandsetRecordTest \
 *       -e seconds 400 com.vive.test/androidx.test.runner.AndroidJUnitRunner
 *
 * Requires RECORD_AUDIO already granted to the app; skipped otherwise.
 */
@RunWith(AndroidJUnit4::class)
class HandsetRecordTest {

    @Test
    fun record() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val seconds = InstrumentationRegistry.getArguments().getString("seconds")?.toDouble() ?: 30.0
        val source = MicrophoneAudioSource(context)
        assumeTrue("RECORD_AUDIO not granted", source.authorization() is AudioAuthorization.Granted)
        val target = AudioFormat.bytesFor(seconds)
        val pcm = ByteArrayOutputStream(target)
        source.start { chunk ->
            pcm.write(chunk)
            if (pcm.size() >= target) source.stop()
        }
        val out = File(context.getExternalFilesDir(null), "results/handset.wav")
        out.parentFile!!.mkdirs()
        val data = pcm.toByteArray()
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray()); putInt(36 + data.size); put("WAVE".toByteArray())
            put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1); putInt(16_000)
            putInt(32_000); putShort(2); putShort(16)
            put("data".toByteArray()); putInt(data.size)
        }
        out.outputStream().use { it.write(header.array()); it.write(data) }
    }
}
