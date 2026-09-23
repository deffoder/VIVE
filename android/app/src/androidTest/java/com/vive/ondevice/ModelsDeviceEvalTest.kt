package com.vive.ondevice

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.vive.data.model.Behavior
import com.vive.data.model.Intent
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Runs the text heads, ECAPA and Silero VAD on the phone over fixtures whose
 * desktop outputs were computed from the same graphs, and records what the
 * phone produced plus timings and memory. `scripts/mobile/score_device_models.py`
 * compares; this test only measures. Skipped when fixtures are absent.
 */
@RunWith(AndroidJUnit4::class)
class ModelsDeviceEvalTest {

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val dir get() = OnDeviceRuntime.modelDir(context)

    private fun write(name: String, body: JsonObject) {
        val out = File(context.getExternalFilesDir(null), "results/$name")
        out.parentFile!!.mkdirs()
        out.writeText(body.toString())
    }

    private fun floats(a: FloatArray) = JsonArray(a.map { JsonPrimitive(it) })

    @Test
    fun textHeads() {
        val fixture = File(dir, "eval/text_eval.json")
        assumeTrue("text fixtures not provisioned", fixture.isFile)
        val text = OnDeviceText(dir, Intent.entries.map { it.name }, Behavior.entries.map { it.name })
        val rssBefore = MemoryProbe.rssKb()
        val status = text.load()
        org.junit.Assert.assertEquals("text load: ${text.loadError}", OnDeviceText.Status.AVAILABLE, status)
        val rssLoaded = MemoryProbe.rssKb()
        val items = Json.parseToJsonElement(fixture.readText()).jsonObject["items"]!!.jsonArray
        val times = mutableListOf<Long>()
        val rows = buildJsonArray {
            for (item in items) {
                val t = item.jsonObject["text"]!!.jsonPrimitive.content
                val began = System.nanoTime()
                val i = text.logits("intent", t)
                val b = text.logits("behavior", t)
                times += (System.nanoTime() - began) / 1_000_000
                add(buildJsonObject { put("intent", floats(i)); put("behavior", floats(b)) })
            }
        }
        write("text_device.json", buildJsonObject {
            put("load_status", status.name)
            text.loadMs?.let { put("load_ms", it) }
            text.loadError?.let { put("load_error", it) }
            put("rss_before_kb", rssBefore)
            put("rss_loaded_kb", rssLoaded)
            put("hwm_kb", MemoryProbe.hwmKb())
            put("both_heads_ms", JsonArray(times.map { JsonPrimitive(it) }))
            put("rows", rows)
        })
        text.close()
    }

    @Test
    fun speakerAndVad() {
        val fixture = File(dir, "eval/speaker_eval.json")
        assumeTrue("speaker fixtures not provisioned", fixture.isFile)
        val speaker = OnDeviceSpeaker(dir)
        val vad = OnDeviceVad(dir)
        val loaded = speaker.load() && vad.load()
        val items = Json.parseToJsonElement(fixture.readText()).jsonObject["items"]!!.jsonArray
        val rows = buildJsonArray {
            for (item in items) {
                val o = item.jsonObject
                val samples = Wav.read16kMono(File(dir, "eval/" + o["wav"]!!.jsonPrimitive.content))
                val began = System.nanoTime()
                val e = speaker.embed(samples)!!
                val embedMs = (System.nanoTime() - began) / 1_000_000
                val v = vad.analyze(samples.copyOfRange(0, minOf(samples.size, 32_000)))
                add(buildJsonObject {
                    put("wav", o["wav"]!!.jsonPrimitive.content)
                    put("embedding", floats(e))
                    put("embed_ms", embedMs)
                    put("samples", samples.size)
                    put("vad_ratio", v.speechRatio)
                    put("vad_quality", v.quality.name)
                    v.inferenceMs?.let { put("vad_ms", it) }
                })
            }
        }
        write("speaker_device.json", buildJsonObject {
            put("loaded", loaded)
            speaker.threshold?.let { put("threshold", it) }
            put("hwm_kb", MemoryProbe.hwmKb())
            put("rows", rows)
        })
    }
}
