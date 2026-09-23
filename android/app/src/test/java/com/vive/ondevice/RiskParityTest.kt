package com.vive.ondevice

import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.AudioQuality
import com.vive.data.model.Behavior
import com.vive.data.model.Intent
import com.vive.data.model.RiskLevel
import com.vive.ondevice.risk.RiskFusion
import com.vive.ondevice.risk.RiskPolicy
import com.vive.ondevice.risk.TemporalRisk
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The on-device risk engine must score exactly as the backend does.
 * `risk_golden.json` is produced by `scripts/mobile/make_risk_golden.py`
 * running the backend's own fusion, temporal and policy code.
 */
class RiskParityTest {

    private val golden: JsonObject by lazy {
        val text = javaClass.classLoader!!.getResource("risk_golden.json")!!.readText()
        Json.parseToJsonElement(text).jsonObject
    }

    private fun JsonElement.str() = jsonPrimitive.content
    private fun JsonElement.nullableDouble() = if (this is JsonNull) null else jsonPrimitive.doubleOrNull

    @Test
    fun `fusion matches the backend on every golden case`() {
        val cases = golden["fusion"]!!.jsonArray
        cases.forEachIndexed { i, c ->
            val input = c.jsonObject["in"]!!.jsonObject
            val want = c.jsonObject["out"]!!.jsonObject
            val got = RiskFusion.fuse(
                RiskFusion.Input(
                    quality = AudioQuality.valueOf(input["quality"]!!.str()),
                    synthetic = input["synthetic"]!!.nullableDouble(),
                    speakerStatus = AnalyzerStatus.valueOf(input["speaker_status"]!!.str()),
                    speakerSimilarity = input["speaker_similarity"]!!.nullableDouble(),
                    asrStatus = AnalyzerStatus.valueOf(input["asr_status"]!!.str()),
                    asrConfidence = input["asr_confidence"]!!.nullableDouble(),
                    intentStatus = AnalyzerStatus.valueOf(input["intent_status"]!!.str()),
                    intent = Intent.valueOf(input["intent"]!!.str()),
                    behaviorStatus = AnalyzerStatus.valueOf(input["behavior_status"]!!.str()),
                    behaviors = input["behaviors"]!!.jsonArray.map { Behavior.valueOf(it.str()) },
                    callerVerified = input["caller_verified"]!!.jsonPrimitive.boolean,
                    sessionAuthenticated = input["session_authenticated"]!!.jsonPrimitive.boolean,
                ),
            )
            val msg = "fusion case $i"
            assertEquals(msg, want["score"]!!.jsonPrimitive.int, got.risk.score)
            assertEquals(msg, want["level"]!!.str(), got.risk.level.name)
            assertEquals(msg, want["confidence"]!!.jsonPrimitive.double, got.risk.confidence, 0.0)
            assertEquals(msg, want["uncertainty"]!!.jsonPrimitive.double, got.uncertainty, 0.0)
            assertEquals(msg, want["context_risk"]!!.jsonPrimitive.double, got.contextRisk, 0.0)
            assertEquals(msg, want["ood"]!!.str(), got.ood.name)
            assertEquals(msg, want["reasons"]!!.jsonArray.map { it.str() }, got.risk.reasons)
            assertEquals(
                msg,
                want["contributions"]!!.jsonObject.mapValues { it.value.jsonPrimitive.double },
                got.risk.contributions,
            )
        }
    }

    @Test
    fun `temporal risk matches the backend step by step`() {
        golden["temporal"]!!.jsonArray.forEachIndexed { i, c ->
            val t = TemporalRisk()
            c.jsonObject["steps"]!!.jsonArray.forEachIndexed { j, s ->
                val o = s.jsonObject
                val (cur, ov) = t.update(
                    o["score"]!!.jsonPrimitive.int, o["confidence"]!!.jsonPrimitive.double, o["at"]!!.jsonPrimitive.int,
                )
                val msg = "temporal case $i step $j (${c.jsonObject["shape"]!!.str()})"
                assertEquals(msg, o["current_level"]!!.str(), cur.level.name)
                assertEquals(msg, o["overall_score"]!!.jsonPrimitive.int, ov.score)
                assertEquals(msg, o["overall_level"]!!.str(), ov.level.name)
                val tm = o["timings"]!!.jsonArray.map { it.jsonPrimitive.intOrNull }
                assertEquals(
                    msg, tm,
                    listOf(t.timings.firstAnomalySec, t.timings.firstWarningSec, t.timings.firstHighSec, t.timings.firstCriticalSec),
                )
            }
        }
    }

    @Test
    fun `policy matches the backend`() {
        golden["policy"]!!.jsonArray.forEachIndexed { i, c ->
            val input = c.jsonObject["in"]!!.jsonObject
            val want = c.jsonObject["out"]!!.jsonObject
            val d = RiskPolicy.evaluate(
                score = input["score"]!!.jsonPrimitive.int,
                level = (input["level"] as? JsonElement)?.takeIf { it !is JsonNull }?.let { RiskLevel.valueOf(it.str()) },
                confidence = input["confidence"]!!.jsonPrimitive.double,
                intent = input["intent"]!!.takeIf { it !is JsonNull }?.let { Intent.valueOf(it.str()) },
                callerVerified = input["caller_verified"]!!.jsonPrimitive.boolean,
            )
            val msg = "policy case $i"
            assertEquals(msg, want["action"]!!.str(), d.action.name)
            assertEquals(msg, want["alert"]!!.jsonPrimitive.boolean, d.shouldAlert)
            assertEquals(msg, want["reasons"]!!.jsonArray.map { it.str() }, d.reasons)
        }
    }
}
