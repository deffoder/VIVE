package com.vive.ondevice

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
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
 * Measures the on-device ASR on the phone itself.
 *
 * Decodes the clips written by `scripts/mobile/make_asr_eval.py` and records,
 * per clip, the transcript and decoder confidence the PHONE produced, plus
 * load time, 2 s window latency and process memory. Scoring (WER, agreement
 * with the desktop graph) is done by `scripts/mobile/score_device_asr.py`
 * with the same normaliser as every other VIVE ASR figure, so this test only
 * measures and never grades.
 *
 * Skipped, not failed, when the evaluation set is not provisioned.
 */
@RunWith(AndroidJUnit4::class)
class AsrDeviceEvalTest {

    @Test
    fun decodeEvaluationSet() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val dir = OnDeviceRuntime.modelDir(context)
        // Optional overrides, e.g. an fp32 graph to check the port without int8:
        //   -e manifest asr_fp32check.json -e eval eval_fp32check.json -e out asr_fp32check.json
        val args = InstrumentationRegistry.getArguments()
        val evalFile = File(dir, "eval/" + (args.getString("eval") ?: "eval.json"))
        assumeTrue("eval set not provisioned at ${evalFile.path}", evalFile.isFile)

        val clips = Json.parseToJsonElement(evalFile.readText()).jsonObject["clips"]!!.jsonArray
        val asr = OnDeviceAsr(dir, manifestName = args.getString("manifest") ?: OnDeviceAsr.MANIFEST)
        val rssBefore = MemoryProbe.rssKb()
        val results = buildJsonArray {
            for (lang in clips.map { it.jsonObject["lang"]!!.jsonPrimitive.content }.distinct()) {
                val loadStatus = asr.load(lang)
                val loadMs = asr.lastLoadMs
                val rssLoaded = MemoryProbe.rssKb()
                val mine = clips.filter { it.jsonObject["lang"]!!.jsonPrimitive.content == lang }
                val windowMs = mutableListOf<Long>()
                for (clip in mine) {
                    val o = clip.jsonObject
                    val samples = Wav.read16kMono(File(dir, "eval/" + o["wav"]!!.jsonPrimitive.content))
                    val full = asr.transcribe(samples, lang)
                    // Steady-state latency on VIVE's real window size.
                    val window = samples.copyOfRange(0, minOf(samples.size, 32_000))
                    val w = asr.transcribe(window, lang)
                    w.inferenceMs?.let { windowMs += it }
                    add(buildJsonObject {
                        put("lang", lang)
                        put("wav", o["wav"]!!.jsonPrimitive.content)
                        put("status", full.status.name)
                        put("device_hyp", full.text ?: "")
                        full.confidence?.let { put("device_conf", it) }
                        full.inferenceMs?.let { put("full_ms", it) }
                    })
                }
                add(buildJsonObject {
                    put("summary", lang)
                    put("load_status", loadStatus.name)
                    loadMs?.let { put("load_ms", it) }
                    put("rss_before_kb", rssBefore)
                    put("rss_loaded_kb", rssLoaded)
                    put("rss_after_kb", MemoryProbe.rssKb())
                    put("hwm_kb", MemoryProbe.hwmKb())
                    put("window_ms", JsonArray(windowMs.map { kotlinx.serialization.json.JsonPrimitive(it) }))
                    put("threads", OnDeviceRuntime.DEFAULT_THREADS)
                })
            }
        }
        asr.close()
        val out = File(context.getExternalFilesDir(null), "results/" + (args.getString("out") ?: "asr_device.json"))
        out.parentFile!!.mkdirs()
        out.writeText(JsonObject(mapOf("results" to results)).toString())
    }
}
