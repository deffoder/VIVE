package com.vive.ui.screens.alerts

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vive.data.model.RiskLevel
import com.vive.ui.components.AlertCard
import com.vive.ui.components.EmptyState
import com.vive.ui.components.FilterChipRow
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.screens.AlertsViewModel
import com.vive.ui.screens.StateHost
import com.vive.ui.theme.ViveThemeTokens

/**
 * Alerts (docs/UI_SPEC.md 4.15).
 * Each card carries risk, reason, session, intent and recommended action.
 * Tapping opens the originating packet, which is the fastest path to evidence.
 */
@Composable
fun AlertsScreen(
    onOpenPacket: (String, String) -> Unit,
    onOpenSession: (String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AlertsViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val filter by viewModel.filter.collectAsStateWithLifecycle()
    val filters = listOf("All", "Critical", "High", "Medium", "Low")

    ViveScreenScaffold(title = "Alerts", modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            FilterChipRow(filters, filter, viewModel::setFilter)

            StateHost(
                state = state,
                onRetry = viewModel::refresh,
                emptyTitle = "No alerts",
                emptyDescription = "Policy-raised alerts will appear here.",
            ) { alerts ->
                val visible = alerts.filter {
                    filter == "All" || it.level.name.equals(filter, ignoreCase = true)
                }
                if (visible.isEmpty()) {
                    EmptyState(
                        title = "No $filter alerts",
                        description = "Try a different filter.",
                    )
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md)) {
                        visible.forEach { alert ->
                            AlertCard(
                                alert = alert,
                                onClick = {
                                    val packetId = alert.packetId
                                    if (packetId != null) onOpenPacket(alert.sessionId, packetId)
                                    else onOpenSession(alert.sessionId)
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}
