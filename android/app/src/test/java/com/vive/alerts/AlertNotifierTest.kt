package com.vive.alerts

import com.vive.data.model.RiskLevel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * Alert notification decisions, at the seams a JVM test can reach.
 *
 * `NotificationManagerCompat` needs a device, so posting itself is verified
 * on-device. What is pinned here is the logic that decides *whether* and *how
 * loudly* to interrupt, because those are the parts that fail quietly: a
 * routing mistake produces either a silenced critical warning or a LOW
 * advisory that buzzes the user's phone, and neither throws.
 */
class AlertNotifierTest {

    @Test
    fun `high and critical share the interrupting channel`() {
        assertEquals(AlertNotifier.CHANNEL_HIGH, AlertNotifier.channelFor(RiskLevel.HIGH))
        assertEquals(AlertNotifier.CHANNEL_HIGH, AlertNotifier.channelFor(RiskLevel.CRITICAL))
    }

    @Test
    fun `medium is an advisory and does not use the warning channel`() {
        assertEquals(AlertNotifier.CHANNEL_INFO, AlertNotifier.channelFor(RiskLevel.MEDIUM))
        assertNotEquals(
            AlertNotifier.channelFor(RiskLevel.MEDIUM),
            AlertNotifier.channelFor(RiskLevel.CRITICAL),
        )
    }

    @Test
    fun `the two channels are distinct, so one can be silenced without the other`() {
        assertNotEquals(AlertNotifier.CHANNEL_HIGH, AlertNotifier.CHANNEL_INFO)
    }

    @Test
    fun `taxonomy constants are never shown raw`() {
        // A notification is read with no surrounding context, so OTP_REQUEST
        // must not reach the user as a screaming enum name.
        assertEquals("Otp request", AlertNotifier.humanise("OTP_REQUEST"))
        assertEquals("Critical", AlertNotifier.humanise("CRITICAL"))
        assertEquals(
            "Secondary verification",
            AlertNotifier.humanise("SECONDARY_VERIFICATION"),
        )
    }
}
