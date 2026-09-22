package com.vive.remote

import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.Intent
import com.vive.data.model.RiskLevel
import com.vive.data.remote.NetworkModule
import com.vive.data.remote.dto.PacketDto
import com.vive.data.remote.dto.SessionDto
import com.vive.data.remote.dto.isDemo
import com.vive.data.remote.dto.toDomain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Wire-contract tests.
 *
 * These parse the exact JSON the backend emits, so a schema drift on either
 * side fails here rather than at runtime on a phone.
 */
class SerializationTest {

    private val json = NetworkModule.json

    /** The canonical CLAUDE.md packet, as the backend serialises it. */
    private val canonicalPacket = """
    {
      "packet_id": "P007",
      "timestamp": "00:08",
      "duration_sec": 2,
      "language": "ta",
      "quality": "GOOD",
      "aasist": {"score": 0.87, "status": "AVAILABLE", "model_version": "demo", "inference_ms": 12},
      "ecapa": {"status": "NO_REFERENCE", "similarity": null},
      "asr": {"transcript": "OTP sollunga...", "confidence": 0.91, "status": "AVAILABLE"},
      "intent": {"label": "OTP_REQUEST", "confidence": 0.94, "status": "AVAILABLE"},
      "behavior": {"labels": ["URGENCY"], "confidence": 0.89, "status": "AVAILABLE"},
      "context": {"caller_verified": false, "context_risk": 0.82},
      "risk": {"score": 91, "level": "CRITICAL", "confidence": 0.84,
               "contributions": {"synthetic": 0.87, "intent": 0.94},
               "reasons": ["OTP request detected"]},
      "session_id": "VS-001",
      "seq": 7,
      "window": {"start_sec": 6.0, "end_sec": 8.0},
      "ood": {"state": "KNOWN_SYNTHETIC_LIKELY", "uncertainty": 0.16},
      "adapter_mode": "mock"
    }
    """.trimIndent()

    @Test
    fun `canonical packet parses and maps to domain`() {
        val dto = json.decodeFromString<PacketDto>(canonicalPacket)
        val packet = dto.toDomain()

        assertEquals("P007", packet.packetId)
        assertEquals("00:08", packet.timestamp)
        assertEquals("ta", packet.language)
        assertEquals(0.87, packet.aasist.score!!, 1e-9)
        assertEquals(Intent.OTP_REQUEST, packet.intent.label)
        assertEquals(RiskLevel.CRITICAL, packet.risk.level)
        assertEquals(91, packet.risk.score)
        assertEquals(0.84, packet.risk.confidence, 1e-9)
        assertEquals(6.0, packet.window!!.startSec, 1e-9)
    }

    @Test
    fun `absent analyzer output maps to null not zero`() {
        val packet = json.decodeFromString<PacketDto>(canonicalPacket).toDomain()
        assertEquals(AnalyzerStatus.NO_REFERENCE, packet.ecapa.status)
        assertNull("similarity must be null, never 0.0", packet.ecapa.similarity)
    }

    @Test
    fun `adapter mode mock is detected so the demo badge can be shown`() {
        assertTrue(json.decodeFromString<PacketDto>(canonicalPacket).isDemo())
    }

    @Test
    fun `unknown fields are ignored so a newer backend does not break the client`() {
        val withExtra = canonicalPacket.replace(
            """"adapter_mode": "mock"""",
            """"adapter_mode": "mock", "a_field_from_the_future": 42""",
        )
        val packet = json.decodeFromString<PacketDto>(withExtra).toDomain()
        assertEquals("P007", packet.packetId)
    }

    @Test
    fun `unknown enum values degrade instead of throwing`() {
        val withNewIntent = canonicalPacket.replace(
            """"label": "OTP_REQUEST"""",
            """"label": "SOME_NEW_INTENT_WE_DO_NOT_KNOW"""",
        )
        val packet = json.decodeFromString<PacketDto>(withNewIntent).toDomain()
        assertEquals(Intent.UNKNOWN, packet.intent.label)
    }

    @Test
    fun `minimal packet without extensions still parses`() {
        val minimal = """
        {
          "packet_id": "P001", "timestamp": "00:02", "duration_sec": 2,
          "language": "en", "quality": "GOOD",
          "aasist": {"score": 0.1}, "ecapa": {"status": "NO_REFERENCE"},
          "asr": {}, "intent": {"label": "NORMAL_CONVERSATION"},
          "behavior": {}, "context": {"caller_verified": true},
          "risk": {"score": 8, "level": "LOW", "confidence": 0.9}
        }
        """.trimIndent()
        val packet = json.decodeFromString<PacketDto>(minimal).toDomain()
        assertEquals("P001", packet.packetId)
        assertNull(packet.seq)
        assertNull(packet.window)
        assertNull(packet.ood)
    }

    @Test
    fun `session with null timings parses and null means not reached`() {
        val body = """
        {
          "session_id": "VS-001", "status": "STREAMING", "source_type": "VOIP",
          "duration_sec": 12, "packets_processed": 6,
          "current_risk": {"score": 72, "level": "HIGH", "confidence": 0.89},
          "timings": {"first_warning_sec": 8, "first_critical_sec": null}
        }
        """.trimIndent()
        val session = json.decodeFromString<SessionDto>(body).toDomain()
        assertEquals(8, session.timings.firstWarningSec)
        assertNull("null means not reached", session.timings.firstCriticalSec)
        assertEquals(RiskLevel.HIGH, session.currentRisk!!.level)
    }
}

/**
 * Analyzer status must never fail open.
 *
 * `AVAILABLE` is a positive claim that a model ran and produced a value.
 * These pin the two ways that claim could be fabricated: a status this client
 * does not recognise, and a status the backend genuinely emits that the client
 * was never taught.
 */
class AnalyzerStatusContractTest {

    private val json = NetworkModule.json

    private fun packetWithIntentStatus(status: String): String = """
    {
      "packet_id": "P001",
      "timestamp": "00:02",
      "duration_sec": 2,
      "language": "ta",
      "quality": "GOOD",
      "aasist": {"status": "INSUFFICIENT_AUDIO", "score": null},
      "ecapa": {"status": "NO_REFERENCE", "similarity": null},
      "asr": {"transcript": "vanakkam", "confidence": 0.9, "status": "AVAILABLE"},
      "intent": {"label": "UNKNOWN", "status": "$status"},
      "behavior": {"labels": [], "status": "$status"},
      "context": {"caller_verified": false},
      "risk": {"score": 12, "level": "LOW", "confidence": 0.5,
               "contributions": {}, "reasons": []}
    }
    """.trimIndent()

    @Test
    fun `unsupported language is preserved, not reported as available`() {
        val packet = json.decodeFromString<PacketDto>(
            packetWithIntentStatus("UNSUPPORTED_LANGUAGE"),
        ).toDomain()

        assertEquals(AnalyzerStatus.UNSUPPORTED_LANGUAGE, packet.intent.status)
        assertEquals(AnalyzerStatus.UNSUPPORTED_LANGUAGE, packet.behavior.status)
        assertFalse(
            "an analyzer that declined to run must not claim a value",
            packet.intent.status.producedAValue,
        )
    }

    @Test
    fun `an unrecognised status degrades to unavailable, never available`() {
        val packet = json.decodeFromString<PacketDto>(
            packetWithIntentStatus("SOME_FUTURE_STATUS"),
        ).toDomain()

        assertEquals(AnalyzerStatus.UNAVAILABLE, packet.intent.status)
        assertFalse(packet.intent.status.producedAValue)
    }

    @Test
    fun `only AVAILABLE claims a value was produced`() {
        AnalyzerStatus.entries.forEach { status ->
            assertEquals(
                "$status must not claim a value unless it is AVAILABLE",
                status == AnalyzerStatus.AVAILABLE,
                status.producedAValue,
            )
        }
    }

    @Test
    fun `every status the backend can emit is known to this client`() {
        // Mirrors backend/app/schemas/models.py::AnalyzerStatus. If the
        // backend gains a member, add it here AND to the Kotlin enum - the
        // mapper's fallback is safe but it collapses meaning, and a whole
        // language once rendered as a successful analysis that way.
        val backendEmits = listOf(
            "AVAILABLE", "UNAVAILABLE", "NO_REFERENCE", "INSUFFICIENT_AUDIO",
            "LOAD_ERROR", "INFERENCE_ERROR", "UNSUPPORTED_LANGUAGE", "ERROR",
        )
        val known = AnalyzerStatus.entries.map { it.name }.toSet()
        backendEmits.forEach {
            assertTrue("client cannot represent backend status $it", it in known)
        }
    }

    @Test
    fun `every non-available status explains itself`() {
        AnalyzerStatus.entries
            .filterNot { it.producedAValue }
            .forEach { status ->
                assertTrue("$status has no label", status.absenceLabel().isNotBlank())
                assertTrue(
                    "$status has no explanation",
                    status.absenceExplanation().isNotBlank(),
                )
            }
    }
}
