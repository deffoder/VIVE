package com.vive.demo

import com.vive.data.demo.DemoData
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.AudioQuality
import com.vive.data.model.RiskLevel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Demo data must exercise the claims the product makes, not just fill screens.
 * These tests pin the scenario properties from docs/DEMO_SPEC.md.
 */
class DemoDataTest {

    @Test
    fun `packet windows overlap with a 2s window and 1s stride`() {
        val packets = DemoData.packets("VS-001")
        assertTrue(packets.size >= 2)
        packets.zipWithNext { a, b ->
            val wa = a.window!!
            val wb = b.window!!
            assertEquals(2.0, wa.endSec - wa.startSec, 1e-9)
            assertEquals(1.0, wb.startSec - wa.startSec, 1e-9)
            assertTrue("windows must overlap", wb.startSec < wa.endSec)
        }
    }

    @Test
    fun `S2 human social engineering escalates on semantics with low antispoof`() {
        val packets = DemoData.packets("VS-003")
        val peak = packets.maxOf { it.risk.score }
        assertTrue("risk must rise above LOW", peak >= 60)
        packets.forEach {
            val score = it.aasist.score
            assertNotNull(score)
            assertTrue(
                "anti-spoof evidence must stay low in S2, was $score",
                score!! < 0.2,
            )
        }
    }

    @Test
    fun `S4 poor audio lowers confidence without raising risk`() {
        val packets = DemoData.packets("VS-004")
        assertTrue(packets.isNotEmpty())
        packets.forEach {
            assertEquals(AudioQuality.POOR, it.quality)
            assertTrue("risk must stay low on unusable audio", it.risk.score < 25)
            assertTrue("confidence must fall", it.risk.confidence < 0.4)
        }
    }

    @Test
    fun `unavailable analyzers report status and omit values`() {
        val packet = DemoData.packets("VS-004").first()
        assertNull("no aasist score on unusable audio", packet.aasist.score)
        assertEquals(AnalyzerStatus.UNAVAILABLE, packet.aasist.status)
        assertNull("no transcript on unusable audio", packet.asr.transcript)
    }

    @Test
    fun `speaker consistency reports NO_REFERENCE rather than a zero`() {
        DemoData.packets("VS-001").forEach {
            assertEquals(AnalyzerStatus.NO_REFERENCE, it.ecapa.status)
            assertNull(it.ecapa.similarity)
        }
    }

    @Test
    fun `every adapter reports demo mode so the badge can never be missed`() {
        assertTrue(DemoData.models.isNotEmpty())
        DemoData.models.forEach {
            assertEquals(com.vive.data.model.AdapterMode.MOCK, it.mode)
        }
    }

    @Test
    fun `no model reports a plausible looking version number`() {
        DemoData.models.forEach {
            assertEquals("demo", it.version)
        }
    }

    @Test
    fun `S3 escalates to critical and carries reasons`() {
        val packets = DemoData.packets("VS-001")
        val critical = packets.filter { it.risk.level == RiskLevel.CRITICAL }
        assertTrue("S3 must reach CRITICAL", critical.isNotEmpty())
        critical.forEach { assertTrue(it.risk.reasons.isNotEmpty()) }
    }

    @Test
    fun `contributions are evidence strengths within 0 to 1`() {
        DemoData.packets("VS-001").forEach { p ->
            p.risk.contributions.values.forEach {
                assertTrue("contribution out of range: $it", it in 0.0..1.0)
            }
        }
    }
}
