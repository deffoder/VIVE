package com.vive.data

import com.vive.data.model.AasistEvidence
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.AsrEvidence
import com.vive.data.model.AudioQuality
import com.vive.data.model.Behavior
import com.vive.data.model.BehaviorEvidence
import com.vive.data.model.ContextEvidence
import com.vive.data.model.EcapaEvidence
import com.vive.data.model.Intent
import com.vive.data.model.IntentEvidence
import com.vive.data.model.Packet
import com.vive.data.model.PacketRisk
import com.vive.data.model.RiskLevel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Pins the canonical packet from CLAUDE.md (Backend/UI Contract).
 *
 * This is the Phase 1 exit criterion in docs/IMPLEMENTATION_PLAN.md: the
 * example packet must model without a field being renamed or dropped. The
 * literal values below come from that example and are a SCHEMA fixture, not
 * model output.
 */
class PacketContractTest {

    private fun canonicalPacket() = Packet(
        packetId = "P007",
        timestamp = "00:08",
        durationSec = 2,
        language = "ta",
        quality = AudioQuality.GOOD,
        aasist = AasistEvidence(score = 0.87),
        ecapa = EcapaEvidence(status = AnalyzerStatus.AVAILABLE, similarity = 0.43),
        asr = AsrEvidence(transcript = "OTP sollunga...", confidence = 0.91),
        intent = IntentEvidence(label = Intent.OTP_REQUEST, confidence = 0.94),
        behavior = BehaviorEvidence(labels = listOf(Behavior.URGENCY), confidence = 0.89),
        context = ContextEvidence(callerVerified = false),
        risk = PacketRisk(score = 91, level = RiskLevel.CRITICAL, confidence = 0.84),
    )

    @Test
    fun `canonical packet models every required field`() {
        val p = canonicalPacket()
        assertEquals("P007", p.packetId)
        assertEquals("00:08", p.timestamp)
        assertEquals("ta", p.language)
        assertEquals(AudioQuality.GOOD, p.quality)
        assertEquals(0.87, p.aasist.score!!, 1e-9)
        assertEquals(0.43, p.ecapa.similarity!!, 1e-9)
        assertEquals(0.91, p.asr.confidence!!, 1e-9)
        assertEquals(Intent.OTP_REQUEST, p.intent.label)
        assertEquals(listOf(Behavior.URGENCY), p.behavior.labels)
        assertEquals(false, p.context.callerVerified)
    }

    @Test
    fun `risk score and confidence stay separate concepts`() {
        val p = canonicalPacket()
        assertEquals(91, p.risk.score)
        assertEquals(RiskLevel.CRITICAL, p.risk.level)
        assertEquals(0.84, p.risk.confidence, 1e-9)
    }

    @Test
    fun `extension fields are optional`() {
        val p = canonicalPacket()
        assertNull(p.seq)
        assertNull(p.window)
        assertNull(p.ood)
        assertNull(p.sessionId)
    }

    @Test
    fun `missing analyzer output is absent rather than zero`() {
        val p = canonicalPacket().copy(
            ecapa = EcapaEvidence(status = AnalyzerStatus.NO_REFERENCE),
        )
        assertEquals(AnalyzerStatus.NO_REFERENCE, p.ecapa.status)
        assertNull("similarity must be null, never 0.0", p.ecapa.similarity)
    }
}
