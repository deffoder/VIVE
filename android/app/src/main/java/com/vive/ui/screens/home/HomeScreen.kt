package com.vive.ui.screens.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vive.data.model.RiskLevel
import com.vive.data.model.Session
import com.vive.data.model.SessionStatus
import com.vive.ui.components.IconChip
import com.vive.ui.components.MetricCard
import com.vive.ui.components.MetricRow
import com.vive.ui.components.PrimaryButton
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.SessionCard
import com.vive.ui.components.ViveCard
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.components.riskColorsFor
import com.vive.ui.screens.SessionListViewModel
import com.vive.ui.screens.StateHost
import com.vive.ui.theme.RiskLow
import com.vive.ui.theme.RiskLowContainer
import com.vive.ui.theme.ViveThemeTokens

/**
 * Home dashboard (docs/UI_SPEC.md 4.5).
 *
 * Protected state, real counters, recent sessions. When a session is live the
 * banner becomes a resume affordance into the active call, as the spec says.
 */
@Composable
fun HomeScreen(
    onOpenSession: (String) -> Unit,
    onResumeActiveCall: (String) -> Unit,
    onViewAllSessions: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: SessionListViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    ViveScreenScaffold(title = "VIVE", modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(
                state = state,
                onRetry = viewModel::refresh,
                emptyTitle = "No sessions yet",
                emptyDescription = "Analysed calls will appear here.",
            ) { sessions ->
                val active = sessions.firstOrNull { it.status == SessionStatus.STREAMING }

                if (active != null) {
                    ActiveCallBanner(active) { onResumeActiveCall(active.sessionId) }
                } else {
                    ProtectedBanner()
                }

                MetricRow {
                    MetricCard(
                        value = "${sessions.size}",
                        label = "Calls analysed",
                        modifier = Modifier.weight(1f),
                    )
                    MetricCard(
                        value = "${sessions.count { (it.overallRisk?.score ?: 0) >= 60 }}",
                        label = "High risk",
                        modifier = Modifier.weight(1f),
                    )
                    MetricCard(
                        value = "${sessions.count { it.status == SessionStatus.STREAMING }}",
                        label = "Active",
                        modifier = Modifier.weight(1f),
                    )
                }

                SectionHeader(
                    title = "Recent sessions",
                    actionLabel = "View all",
                    onActionClick = onViewAllSessions,
                )
                Column(verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md)) {
                    sessions.take(4).forEach { session ->
                        SessionCard(session = session, onClick = { onOpenSession(session.sessionId) })
                    }
                }
            }
        }
    }
}

@Composable
private fun ProtectedBanner() {
    ViveCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
        ) {
            IconChip(
                icon = Icons.Filled.CheckCircle,
                tint = RiskLow,
                container = RiskLowContainer,
            )
            Column {
                Text(
                    text = "No active call",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "VIVE analyses authorized calls while they are in progress.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ActiveCallBanner(session: Session, onResume: () -> Unit) {
    val level = session.currentRisk?.level ?: RiskLevel.LOW
    val colors = riskColorsFor(level)
    ViveCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
        ) {
            IconChip(
                icon = Icons.Filled.GraphicEq,
                tint = colors.content,
                container = colors.container,
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Call in progress",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "${session.sessionId} · ${session.packetsProcessed} packets analysed",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        PrimaryButton(
            text = "Resume analysis",
            onClick = onResume,
            modifier = Modifier.padding(top = ViveThemeTokens.spacing.md),
        )
    }
}
