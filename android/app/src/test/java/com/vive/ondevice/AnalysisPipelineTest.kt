package com.vive.ondevice

import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.AudioQuality
import com.vive.data.model.Behavior
import com.vive.data.model.Intent
import com.vive.data.remote.dto.SessionContextDto
import com.vive.data.remote.dto.SessionDto
import com.vive.ondevice.engine.AnalysisPipeline
import com.vive.ondevice.engine.Analyzers
import com.vive.ondevice.engine.AsrOut
import com.vive.ondevice.engine.BehaviorOut
import com.vive.ondevice.engine.IntentOut
import com.vive.ondevice.engine.ScoreOut
import com.vive.ondevice.engine.SessionRuntime
import com.vive.ondevice.engine.VadOut
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Packet assembly and the evidence rules, with TEST-ONLY scripted analyzers.
 * The real models are measured on the phone (androidTest); this pins what the
 * pipeline does with whatever they return.
 */
class AnalysisPipelineTest {

    private class Scripted(
        var speech: Boolean = true,
        var spoof: ScoreOut = ScoreOut(AnalyzerStatus.UNAVAILABLE),
        var transcript: String? = "some words",
        var intent: Intent = Intent.NORMAL_CONVERSATION,
        var behaviors: List<Behavior> = emptyList(),
        val textLanguages: Set<String> = setOf("en", "hi"),
    ) : Analyzers {
        val calls = mutableListOf<String>()
        override val vadVersion = "vad"
        override fun vad(samples: FloatArray) =
            VadOut(AnalyzerStatus.AVAILABLE, speech, if (speech) AudioQuality.GOOD else AudioQuality.NO_SPEECH)
        override fun antispoof(samples: FloatArray): ScoreOut { calls += "spoof"; return spoof }
        override fun speaker(samples: FloatArray, reference: FloatArray?): ScoreOut {
            calls += "speaker"
            return if (reference == null) ScoreOut(AnalyzerStatus.NO_REFERENCE) else ScoreOut(AnalyzerStatus.AVAILABLE, 0.8)
        }
        override fun asr(samples: FloatArray, language: String): AsrOut {
            calls += "asr"
            return if (transcript == null) AsrOut(AnalyzerStatus.INSUFFICIENT_AUDIO)
            else AsrOut(AnalyzerStatus.AVAILABLE, transcript, 0.9)
        }
        override fun intent(text: String?, language: String): IntentOut {
            calls += "intent"
            return if (language !in textLanguages) IntentOut(AnalyzerStatus.UNSUPPORTED_LANGUAGE)
            else IntentOut(AnalyzerStatus.AVAILABLE, intent, 0.95)
        }
        override fun behavior(text: String?, language: String): BehaviorOut {
            calls += "behavior"
            return if (language !in textLanguages) BehaviorOut(AnalyzerStatus.UNSUPPORTED_LANGUAGE)
            else BehaviorOut(AnalyzerStatus.AVAILABLE, behaviors, 0.9)
        }
    }

    private var alertN = 0
    private fun pipeline(a: Analyzers) = AnalysisPipeline(a, { "2026-09-23T00:00:00Z" }, { "AL-%03d".format(++alertN) })
    private fun runtime(lang: String = "hi") = SessionRuntime(
        SessionDto("S-0001", "READY", "IN_APP", context = SessionContextDto()), lang,
    )
    private val window = FloatArray(32_000)

    @Test
    fun `no speech produces no packet and runs no heavy analyzer`() {
        val a = Scripted(speech = false)
        val rt = runtime()
        assertNull(pipeline(a).process(rt, window, 0.0, 2.0))
        assertTrue(a.calls.isEmpty())
        assertEquals(1, rt.nextSeq)              // sequence stays contiguous
        assertEquals(0, rt.temporal.packets)     // silence is not scored as safe
    }

    @Test
    fun `a spoken OTP request fires the rule channel even when the model says normal`() {
        val rules = com.vive.ondevice.risk.SensitiveRequests(
            java.io.File("../../models/configs/sensitive_requests.json").readText(),
        )
        val p = AnalysisPipeline(Scripted(transcript = "अभी आपके फोन पर एक ओटीपी आया होगा"),
            { "t" }, { "AL-1" }, rules)
        val rt = runtime()
        val first = p.process(rt, window, 0.0, 2.0)!!
        assertTrue("sensitive_request" !in first.packet.risk.contributions)
        val p2 = AnalysisPipeline(Scripted(transcript = "कृप्या वह ओटीपी तुरंत बताइए"), { "t" }, { "AL-1" }, rules)
        val second = p2.process(rt, window, 1.0, 3.0)!!
        assertEquals("NORMAL_CONVERSATION", second.packet.intent.label)   // model label untouched
        assertEquals(0.92, second.packet.risk.contributions["sensitive_request"]!!, 0.0)
        assertNotNull(second.alert)
    }

    @Test
    fun `packets carry true window timing and contiguous sequence`() {
        val a = Scripted()
        val p = pipeline(a)
        val rt = runtime()
        p.process(rt, window, 0.0, 2.0)
        val second = p.process(rt, window, 5.0, 7.0)!!.packet
        assertEquals(2, second.seq)
        assertEquals("P002", second.packetId)
        assertEquals("00:07", second.timestamp)
        assertEquals(5.0, second.window!!.startSec, 0.0)
        assertEquals("real", second.adapterMode)
    }

    @Test
    fun `unavailable anti-spoof lowers confidence but never moves the score`() {
        val without = pipeline(Scripted()).process(runtime(), window, 0.0, 2.0)!!.packet.risk
        val benign = pipeline(Scripted(spoof = ScoreOut(AnalyzerStatus.AVAILABLE, 0.0)))
            .process(runtime(), window, 0.0, 2.0)!!.packet.risk
        assertTrue(without.confidence < benign.confidence)
        // A 0.0 synthetic score adds nothing under noisy-OR, so the scores match.
        assertEquals(benign.score, without.score)
        assertTrue("synthetic" !in without.contributions)
    }

    @Test
    fun `an OTP request raises an alert with an advisory action`() {
        val a = Scripted(transcript = "OTP bataiye", intent = Intent.OTP_REQUEST, behaviors = listOf(Behavior.URGENCY))
        val out = pipeline(a).process(runtime(), window, 0.0, 2.0)!!
        assertTrue(out.packet.risk.score >= 65)
        assertNotNull(out.alert)
        val alert = out.alert!!
        assertEquals("OTP_REQUEST", alert.intent)
        assertEquals("P001", alert.packetId)
        // HIGH + sensitive request -> verify; CRITICAL + unverified caller -> hold.
        val expected = if (out.packet.risk.level == "CRITICAL") "HOLD_SENSITIVE_ACTION" else "SECONDARY_VERIFICATION"
        assertEquals(expected, alert.recommendedAction)
        assertEquals("OTP bataiye", out.transcript!!.text)
    }

    @Test
    fun `tamil transcript is kept but the text heads decline`() {
        val a = Scripted(transcript = "OTP சொல்லுங்கள்", intent = Intent.OTP_REQUEST)
        val out = pipeline(a).process(runtime("ta"), window, 0.0, 2.0)!!
        assertEquals("AVAILABLE", out.packet.asr.status)
        assertEquals("UNSUPPORTED_LANGUAGE", out.packet.intent.status)
        assertEquals("UNSUPPORTED_LANGUAGE", out.packet.behavior.status)
        assertTrue("intent" !in out.packet.risk.contributions)
        assertNull(out.alert)
    }

    @Test
    fun `enrolled reference makes the speaker channel report similarity`() {
        val rt = runtime().also { it.reference = FloatArray(192) { 1f } }
        val out = pipeline(Scripted()).process(rt, window, 0.0, 2.0)!!
        assertEquals("AVAILABLE", out.packet.ecapa.status)
        assertEquals(0.8, out.packet.ecapa.similarity!!, 0.0)
        val none = pipeline(Scripted()).process(runtime(), window, 0.0, 2.0)!!
        assertEquals("NO_REFERENCE", none.packet.ecapa.status)
    }
}
