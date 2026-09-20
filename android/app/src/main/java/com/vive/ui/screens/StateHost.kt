package com.vive.ui.screens

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.vive.core.UiState
import com.vive.ui.components.EmptyState
import com.vive.ui.components.ErrorState
import com.vive.ui.components.InsufficientDataState
import com.vive.ui.components.LoadingState
import com.vive.ui.components.OfflineState
import com.vive.ui.components.UnavailableState

/**
 * Renders the six non-success states consistently and hands [content] the data
 * on success.
 *
 * Every screen routes through this, which is what guarantees the seven-state
 * requirement (CLAUDE.md, State Design) is actually met everywhere rather than
 * screen by screen at the author's discretion.
 */
@Composable
fun <T> StateHost(
    state: UiState<T>,
    modifier: Modifier = Modifier,
    onRetry: (() -> Unit)? = null,
    emptyTitle: String = "Nothing here yet",
    emptyDescription: String? = null,
    content: @Composable (T) -> Unit,
) {
    when (state) {
        is UiState.Loading -> LoadingState(modifier)
        is UiState.Empty -> EmptyState(emptyTitle, emptyDescription, modifier)
        is UiState.Error -> ErrorState(state.error, modifier, onRetry)
        is UiState.Offline -> OfflineState(modifier, onRetry)
        is UiState.Unavailable -> UnavailableState(modifier, state.reason)
        is UiState.InsufficientData -> InsufficientDataState(modifier, state.reason)
        is UiState.Success -> content(state.data)
    }
}
