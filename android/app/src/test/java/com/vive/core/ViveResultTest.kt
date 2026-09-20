package com.vive.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ViveResultTest {

    @Test
    fun `map transforms success and preserves failure`() {
        val success: ViveResult<Int> = ViveResult.Success(2)
        assertEquals(ViveResult.Success(4), success.map { it * 2 })

        val failure: ViveResult<Int> = ViveResult.Failure(ViveError.NotFound())
        assertTrue(failure.map { it * 2 } is ViveResult.Failure)
    }

    @Test
    fun `getOrNull returns null on failure`() {
        val failure: ViveResult<Int> = ViveResult.Failure(ViveError.Offline())
        assertNull(failure.getOrNull())
        assertEquals(7, ViveResult.Success(7).getOrNull())
    }

    @Test
    fun `adapter unavailable names the adapter so the UI can explain itself`() {
        val error = ViveError.AdapterUnavailable(adapter = "aasist")
        assertEquals("aasist", error.adapter)
    }
}
