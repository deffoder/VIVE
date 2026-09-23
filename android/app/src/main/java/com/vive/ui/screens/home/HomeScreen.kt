package com.vive.ui.screens.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vive.core.UiState
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.ReadyState
import com.vive.data.model.RiskLevel
import com.vive.data.model.Session
import com.vive.data.model.SessionStatus
import com.vive.ui.components.IconChip
import com.vive.ui.components.PrimaryButton
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.SessionCard
import com.vive.ui.components.ViveCard
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.components.riskColorsFor
import com.vive.ui.screens.SessionListViewModel
import com.vive.ui.screens.SystemStatusViewModel
import com.vive.ui.theme.RiskHigh
import com.vive.ui.theme.RiskHighContainer
import com.vive.ui.theme.RiskLow
import com.vive.ui.theme.RiskLowContainer
import com.vive.ui.theme.RiskNeutral
import com.vive.ui.theme.RiskNeutralContainer
import com.vive.ui.theme.ViveThemeTokens

/**
 * Home (docs/UI_SPEC.md 4.5): protection state, the primary action, system
 * status, recent sessions.
 *
 * The whole screen used to sit inside the session-list state, including the
 * button that starts a session. With no sessions the list rendered its empty
 * state and replaced everything - so the only way to reach live analysis was
 * to already have analysed a call. On a fresh install Home was a dead end
 * reading "No sessions yet", and device acceptance failed at "live analysis
 * entry point is reachable" because there genuinely was none.
 *
 * Only the RECENT SESSIONS list depends on that state now. Protection state,
 * the primary action and system status render unconditionally, because none
 * of them is a fact about the session list.
 */
@Composable
fun HomeScreen(
    onOpenSession: (String) -> Unit,
    onResumeActiveCall: (String) -> Unit,
    onViewAllSessions: () -> Unit,
    modifier: Modifier = Modifier,
    onStartLiveSession: ((String) -> Unit)? = null,
    viewModel: SessionListViewModel = viewModel(),
    statusViewModel: SystemStatusViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val starting by viewModel.starting.collectAsStateWithLifecycle()
    val status by statusViewModel.state.collectAsStateWithLifecycle()
    var startError by remember { mutableStateOf<String?>(null) }

    val sessions = (state as? UiState.Success)?.data.orEmpty()
    val active = sessions.firstOrNull { it.status == SessionStatus.STREAMING }

    ViveScreenScaffold(title = "VIVE", modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            if (active != null) {
                ActiveCallBanner(active) { onResumeActiveCall(active.sessionId) }
            } else {
                IdleBanner()
            }

            onStartLiveSession?.let { navigate ->
                StartAnalysisCard(
                    starting = starting,
                    error = startError,
                    onStart = {
                        startError = null
                        viewModel.startLiveSession(
                            onCreated = navigate,
                            onError = { startError = it.message },
                        )
                    },
                )
            }

            SystemStatusCard(status) { statusViewModel.refresh() }

            SectionHeader(
                title = "Recent sessions",
                actionLabel = if (sessions.isEmpty()) null else "View all",
                onActionClick = onViewAllSessions,
            )
            when {
                state is UiState.Loading ->
                    StatusLine("Loading sessions…")
                state is UiState.Error ->
                    StatusLine("Sessions could not be loaded.", error = true)
                sessions.isEmpty() ->
                    StatusLine("No calls analysed yet. Start live analysis above.")
                else -> Column(
                    verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
                ) {
                    sessions.take(4).forEach { session ->
                        SessionCard(
                            session = session,
                            onClick = { onOpenSession(session.sessionId) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun StatusLine(text: String, error: Boolean = false) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = if (error) MaterialTheme.colorScheme.error
        else MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun StartAnalysisCard(
    starting: Boolean,
    error: String?,
    onStart: () -> Unit,
) {
    ViveCard {
        SectionHeader(title = "Live analysis")
        Text(
            // The platform limit stated plainly, on the screen where someone
            // decides to use this. Android gives no third-party app the audio
            // of an ordinary cellular call, and implying otherwise here would
            // be the most consequential place to overstate the product.
            text = "Analyses audio from this device's microphone during an " +
                "authorized in-app session. Ordinary cellular call audio is " +
                "not available to any third-party Android app.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        error?.let { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
            )
        }
        PrimaryButton(
            text = if (starting) "Starting…" else "Start live analysis",
            onClick = onStart,
            modifier = Modifier.padding(top = ViveThemeTokens.spacing.md),
        )
    }
}

/**
 * One line on whether analysis can run at all, and what is missing if not.
 *
 * Deliberately not a grid of per-model chips: on Home the only actionable
 * question is whether starting a call would work. The model inventory answers
 * the detailed version and is one tap away.
 */
@Composable
private fun SystemStatusCard(status: UiState<ReadyState>, onRetry: () -> Unit) {
    ViveCard {
        SectionHeader(title = "System status")
        when (status) {
            is UiState.Loading -> StatusLine("Checking the analysis engine…")
            // Every non-success state means the same thing here: the engine
            // did not answer, so live analysis will not produce results.
            // Distinguishing offline from unavailable would give the user two
            // words for one situation and no extra action.
            is UiState.Success -> {
                val ready = status.data
                // NO_REFERENCE is the speaker adapter working correctly with
                // nothing enrolled, so it is not counted as a fault. Calling
                // it one would send the user to fix the one thing behaving as
                // designed.
                val working = ready.adapters.values.count {
                    it.status == AnalyzerStatus.AVAILABLE ||
                        it.status == AnalyzerStatus.NO_REFERENCE
                }
                val total = ready.adapters.size
                val healthy = working == total && total > 0
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
                ) {
                    IconChip(
                        icon = if (healthy) Icons.Filled.CheckCircle else Icons.Filled.CloudOff,
                        tint = if (healthy) RiskLow else RiskNeutral,
                        container = if (healthy) RiskLowContainer else RiskNeutralContainer,
                    )
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = if (healthy) "Analysis engine ready"
                            else "$working of $total models ready",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        StatusLine(
                            if (ready.hasMockAdapter) {
                                "Some results are demonstration output, not " +
                                    "model inference."
                            } else {
                                "All results come from model inference."
                            },
                        )
                    }
                }
                if (!healthy) {
                    val missing = ready.adapters
                        .filterValues {
                            it.status != AnalyzerStatus.AVAILABLE &&
                                it.status != AnalyzerStatus.NO_REFERENCE
                        }
                        .keys.sorted().joinToString(", ")
                    Text(
                        text = "Unavailable: $missing. Analysis will run " +
                            "without these signals and say so per packet.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
                    )
                }
            }            else -> {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
                ) {
                    IconChip(
                        icon = Icons.Filled.CloudOff,
                        tint = RiskHigh,
                        container = RiskHighContainer,
                    )
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "Analysis engine unreachable",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        StatusLine("Live analysis will not produce results " +
                            "until the engine responds.")
                    }
                }
                PrimaryButton(
                    text = "Retry",
                    onClick = onRetry,
                    modifier = Modifier.padding(top = ViveThemeTokens.spacing.md),
                )
            }

        }
    }
}

@Composable
private fun IdleBanner() {
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
                    // "Monitoring in the background" would be a claim VIVE
                    // does not implement: nothing is analysed until a session
                    // is started here.
                    text = "Analysis runs only while a session is in progress.",
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
                    text = "${session.packetsProcessed} analysis windows processed",
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
