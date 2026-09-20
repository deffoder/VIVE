package com.vive.data

import com.vive.data.model.Behavior
import com.vive.data.model.Intent
import com.vive.data.model.RiskLevel
import com.vive.data.model.AudioQuality
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Taxonomy sizes are fixed by CLAUDE.md and docs/PROJECT_SPEC.md 7. If someone
 * adds or removes a label without updating the backend, these fail first.
 */
class TaxonomyTest {

    @Test
    fun `intent taxonomy has the 12 specified labels`() {
        assertEquals(12, Intent.entries.size)
        assertTrue(Intent.entries.contains(Intent.OTP_REQUEST))
        assertTrue(Intent.entries.contains(Intent.UNKNOWN))
    }

    @Test
    fun `behavior taxonomy has the 8 specified labels`() {
        assertEquals(8, Behavior.entries.size)
        assertTrue(Behavior.entries.contains(Behavior.URGENCY))
        assertTrue(Behavior.entries.contains(Behavior.NORMAL))
    }

    @Test
    fun `risk levels are ordered low to critical`() {
        assertEquals(
            listOf(RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL),
            RiskLevel.entries.toList(),
        )
    }

    @Test
    fun `audio quality includes the unusable states`() {
        assertEquals(4, AudioQuality.entries.size)
        assertTrue(AudioQuality.entries.contains(AudioQuality.POOR))
        assertTrue(AudioQuality.entries.contains(AudioQuality.NO_SPEECH))
    }
}
