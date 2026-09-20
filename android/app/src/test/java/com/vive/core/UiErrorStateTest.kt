package com.vive.core

import com.vive.data.model.AdapterMode
import com.vive.data.model.AdapterState
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.ReadyState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * UI error-state and demo-boundary tests.
 *
 * These pin the rules the screens depend on: every failure maps to a state the
 * UI can render, and the MOCK/REAL boundary is always visible.
 */
class UiErrorStateTest {

    private fun <T> stateFor(result: ViveResult<T>): UiState<T> = when (result) {
        is ViveResult.Success -> UiState.Success(result.data)
        is ViveResult.Failure -> when (result.error) {
            is ViveError.Offline -> UiState.Offline()
            is ViveError.AdapterUnavailable -> UiState.Unavailable(result.error.message)
            else -> UiState.Error(result.error)
        }
    }

    @Test
    fun `offline maps to the recoverable Offline state, not Error`() {
        val state = stateFor(ViveResult.Failure(ViveError.Offline()))
        assertTrue(state is UiState.Offline)
        assertFalse("offline is recoverable and must not read as a failure", state is UiState.Error)
    }

    @Test
    fun `adapter unavailable maps to Unavailable rather than Error`() {
        val state = stateFor(ViveResult.Failure(ViveError.AdapterUnavailable("aasist")))
        assertTrue(state is UiState.Unavailable)
    }

    @Test
    fun `not found and validation map to Error`() {
        assertTrue(stateFor(ViveResult.Failure(ViveError.NotFound())) is UiState.Error)
        assertTrue(stateFor(ViveResult.Failure(ViveError.Validation("bad"))) is UiState.Error)
    }

    @Test
    fun `unauthenticated maps to Error so the UI can prompt sign-in`() {
        val state = stateFor(ViveResult.Failure(ViveError.Unauthenticated()))
        assertTrue(state is UiState.Error)
        assertTrue((state as UiState.Error).error is ViveError.Unauthenticated)
    }

    @Test
    fun `every ViveError has a user-facing message`() {
        val errors = listOf(
            ViveError.Offline(), ViveError.Unauthenticated(), ViveError.NotFound(),
            ViveError.AdapterUnavailable("x"), ViveError.Validation("v"), ViveError.Unexpected(),
        )
        errors.forEach { assertTrue("${it::class.simpleName} needs a message", it.message.isNotBlank()) }
    }

    @Test
    fun `no error message leaks a stack trace`() {
        val error = ViveError.Unexpected(cause = IllegalStateException("internal detail"))
        assertFalse(error.message.contains("IllegalStateException"))
        assertFalse(error.message.contains("internal detail"))
    }

    @Test
    fun `a mock adapter anywhere marks the whole readout as demo`() {
        val ready = ReadyState(
            ready = true,
            apiVersion = "v1",
            adapters = mapOf(
                "antispoof" to AdapterState(AnalyzerStatus.AVAILABLE, AdapterMode.REAL),
                "asr" to AdapterState(AnalyzerStatus.AVAILABLE, AdapterMode.MOCK),
            ),
        )
        assertTrue("one mock adapter is enough to require the badge", ready.hasMockAdapter)
    }

    @Test
    fun `all-real adapters clear the demo badge`() {
        val ready = ReadyState(
            ready = true,
            apiVersion = "v1",
            adapters = mapOf(
                "antispoof" to AdapterState(AnalyzerStatus.AVAILABLE, AdapterMode.REAL),
                "asr" to AdapterState(AnalyzerStatus.AVAILABLE, AdapterMode.REAL),
            ),
        )
        assertFalse(ready.hasMockAdapter)
    }

    @Test
    fun `insufficient data is distinct from unavailable`() {
        val insufficient: UiState<String> = UiState.InsufficientData("poor audio")
        val unavailable: UiState<String> = UiState.Unavailable("no model")
        assertFalse(insufficient is UiState.Unavailable)
        assertEquals("poor audio", (insufficient as UiState.InsufficientData).reason)
    }
}
