package com.vive.telephony

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * PATH A tests.
 *
 * The important ones assert what screening must NOT do: claim audio access,
 * or reject a call on a provisional signal.
 */
class ScreeningTest {

    private val policy = MetadataScreeningPolicy(watchlist = setOf("919876543210"))

    @Test
    fun `withheld number is flagged not rejected`() {
        val decision = policy.evaluate(
            CallMetadata(phoneNumber = null, isIncoming = true, numberWithheld = true),
        )
        assertEquals(ScreeningVerdict.FLAG, decision.verdict)
    }

    @Test
    fun `watchlisted number is flagged`() {
        val decision = policy.evaluate(
            CallMetadata(phoneNumber = "+91 98765 43210", isIncoming = true),
        )
        assertEquals(ScreeningVerdict.FLAG, decision.verdict)
    }

    @Test
    fun `contact is allowed`() {
        val decision = policy.evaluate(
            CallMetadata(phoneNumber = "+91 99999 11111", isIncoming = true, inContacts = true),
        )
        assertEquals(ScreeningVerdict.ALLOW, decision.verdict)
    }

    @Test
    fun `absent metadata yields UNKNOWN rather than a guess`() {
        val decision = policy.evaluate(CallMetadata(phoneNumber = null, isIncoming = true))
        assertEquals(ScreeningVerdict.UNKNOWN, decision.verdict)
    }

    @Test
    fun `unknown number with no signal is allowed`() {
        val decision = policy.evaluate(
            CallMetadata(phoneNumber = "+91 91234 56789", isIncoming = true),
        )
        assertEquals(ScreeningVerdict.ALLOW, decision.verdict)
    }

    @Test
    fun `no screening decision ever claims the call is analysable`() {
        val cases = listOf(
            CallMetadata(phoneNumber = null, isIncoming = true, numberWithheld = true),
            CallMetadata(phoneNumber = "+91 98765 43210", isIncoming = true),
            CallMetadata(phoneNumber = "+91 91234 56789", isIncoming = true, inContacts = true),
            CallMetadata(phoneNumber = null, isIncoming = true),
        )
        cases.forEach { metadata ->
            assertFalse(
                "cellular screening must never claim audio analysis",
                policy.evaluate(metadata).analysable,
            )
        }
    }

    @Test
    fun `the no-audio notice states the platform limitation`() {
        val notice = ScreeningDecision.NO_AUDIO_NOTICE.lowercase()
        assertTrue(notice.contains("not accessible"))
        assertTrue(notice.contains("metadata"))
    }

    @Test
    fun `screening verdicts never include a reject option`() {
        // The enum itself is the guarantee: there is no REJECT or BLOCK.
        val names = ScreeningVerdict.entries.map { it.name }
        assertFalse(names.any { it.contains("REJECT") || it.contains("BLOCK") })
        assertEquals(setOf("ALLOW", "FLAG", "SILENCE", "UNKNOWN"), names.toSet())
    }

    @Test
    fun `every decision carries a human readable reason`() {
        val decision = policy.evaluate(CallMetadata(phoneNumber = "+91 98765 43210", isIncoming = true))
        assertTrue(decision.reason.isNotBlank())
    }
}
