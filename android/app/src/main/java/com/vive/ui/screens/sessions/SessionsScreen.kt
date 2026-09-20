package com.vive.ui.screens.sessions

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.vive.ui.components.EmptyState

/**
 * Call history (docs/UI_SPEC.md 4.14).
 * Search, filter chips and day grouping arrive in Phase 4.
 */
@Composable
fun SessionsScreen(
    onOpenSession: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    EmptyState(
        title = "No sessions yet",
        description = "Analysed calls will appear here.",
        modifier = modifier.fillMaxSize(),
    )
}
