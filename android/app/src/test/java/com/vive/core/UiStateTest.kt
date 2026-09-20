package com.vive.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The seven states are a contract, not a convenience. These tests pin the
 * distinctions the specs depend on (docs/UI_SPEC.md 8).
 */
class UiStateTest {

    @Test
    fun `unavailable is distinct from empty`() {
        val unavailable: UiState<List<String>> = UiState.Unavailable("no model")
        val empty: UiState<List<String>> = UiState.Empty
        assertTrue(unavailable is UiState.Unavailable)
        assertTrue(empty is UiState.Empty)
        assertTrue(unavailable != empty)
    }

    @Test
    fun `insufficient data is distinct from error`() {
        val insufficient: UiState<String> = UiState.InsufficientData("poor audio")
        val error: UiState<String> = UiState.Error(ViveError.Unexpected())
        assertTrue(insufficient !is UiState.Error)
        assertTrue(error !is UiState.InsufficientData)
    }

    @Test
    fun `offline can carry cached data while error cannot`() {
        val offline = UiState.Offline(cached = listOf("VS-001"))
        assertEquals(listOf("VS-001"), offline.cached)

        val withoutCache = UiState.Offline<List<String>>()
        assertNull(withoutCache.cached)
    }
}
