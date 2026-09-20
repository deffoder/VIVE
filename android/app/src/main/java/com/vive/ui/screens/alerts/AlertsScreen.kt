package com.vive.ui.screens.alerts

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.vive.ui.components.EmptyState

/**
 * Alerts (docs/UI_SPEC.md 4.15).
 * Severity filter chips and acknowledgement arrive in Phase 4.
 */
@Composable
fun AlertsScreen(
    onOpenSession: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    EmptyState(
        title = "No alerts",
        description = "Policy-raised alerts will appear here.",
        modifier = modifier.fillMaxSize(),
    )
}
