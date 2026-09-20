package com.vive.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * Transcript text must never reach logs (docs/SECURITY_SPEC.md 5).
 * redact is the supported way to reference sensitive content.
 */
class ViveLogTest {

    @Test
    fun `redact never leaks the original content`() {
        val transcript = "OTP sollunga, account verify pannanum"
        val redacted = ViveLog.redact(transcript)
        assertFalse(redacted.contains("OTP"))
        assertFalse(redacted.contains("account"))
        assertEquals("<redacted:${transcript.length}>", redacted)
    }

    @Test
    fun `redact handles null and empty`() {
        assertEquals("<empty>", ViveLog.redact(null))
        assertEquals("<empty>", ViveLog.redact(""))
    }
}
