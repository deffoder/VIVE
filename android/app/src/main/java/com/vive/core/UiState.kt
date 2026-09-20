package com.vive.core

/**
 * The seven states every VIVE screen must handle.
 *
 * Mandated by CLAUDE.md (State Design) and docs/UI_SPEC.md 8. Modelling them as
 * a sealed interface makes an unhandled state a compile error rather than a
 * blank screen.
 *
 * Distinctions that matter:
 *  - [Unavailable] means a model produced no output. Render "Unavailable",
 *    never 0 or a guess.
 *  - [InsufficientData] means the audio was unusable. Never inflate risk.
 *  - [Offline] is recoverable and may show cached data; [Error] is not.
 */
sealed interface UiState<out T> {
    data object Loading : UiState<Nothing>
    data class Success<out T>(val data: T) : UiState<T>
    data object Empty : UiState<Nothing>
    data class Error(val error: ViveError) : UiState<Nothing>
    data class Offline<out T>(val cached: T? = null) : UiState<T>
    data class Unavailable(val reason: String? = null) : UiState<Nothing>
    data class InsufficientData(val reason: String? = null) : UiState<Nothing>
}
