package com.vive.ui

import com.vive.core.Formatting
import com.vive.data.model.EscalationTimings
import com.vive.data.model.RiskLevel
import com.vive.data.model.Session
import com.vive.data.model.SessionStatus
import com.vive.data.model.SourceType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.ZoneId

class SummaryLogicTest {

    private fun session(t: EscalationTimings, packets: Int = 5) =
        Session("S-1", SessionStatus.ENDED, SourceType.IN_APP, packetsProcessed = packets, timings = t)

    @Test
    fun `peak level is the highest level any packet reached, not the average`() {
        assertEquals(RiskLevel.HIGH, session(EscalationTimings(13, 19, 19, null)).peakLevel)
        assertEquals(RiskLevel.CRITICAL, session(EscalationTimings(1, 2, 3, 4)).peakLevel)
        assertEquals(RiskLevel.LOW, session(EscalationTimings()).peakLevel)
        assertNull(session(EscalationTimings(), packets = 0).peakLevel)
    }

    @Test
    fun `times are shown in the phone's zone, and bad input is shown as is`() {
        assertEquals("24 Sep 2026, 01:33",
            Formatting.whenLocal("2026-09-23T20:03:14Z", ZoneId.of("Asia/Kolkata")))
        assertEquals("not a time", Formatting.whenLocal("not a time"))
        assertEquals("Tamil", Formatting.languageName("ta"))
    }
}
