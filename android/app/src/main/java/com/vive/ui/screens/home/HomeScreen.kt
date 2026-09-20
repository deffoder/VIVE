package com.vive.ui.screens.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vive.core.UiState
import com.vive.data.model.Session
import com.vive.ui.components.EmptyState
import com.vive.ui.components.ErrorState
import com.vive.ui.components.LoadingState
import com.vive.ui.components.OfflineState
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.ViveCard
import com.vive.ui.theme.ViveThemeTokens

/**
 * Home dashboard (docs/UI_SPEC.md 4.5).
 *
 * Phase 1 wires the state architecture end to end against the stub repository.
 * The full dashboard - protected banner, metric row, session cards - is Phase 4.
 */
@Composable
fun HomeScreen(
    onOpenSession: (String) -> Unit,
    onViewAllSessions: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: HomeViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = ViveThemeTokens.spacing.gutter),
        verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.lg),
    ) {
        SectionHeader(
            title = "Recent Sessions",
            actionLabel = "View All",
            onActionClick = onViewAllSessions,
        )

        when (val s = state) {
            is UiState.Loading -> LoadingState()
            is UiState.Empty -> EmptyState(
                title = "No sessions yet",
                description = "Analysed calls will appear here.",
            )
            is UiState.Error -> ErrorState(s.error, onRetry = viewModel::refresh)
            is UiState.Offline -> OfflineState(onRetry = viewModel::refresh)
            is UiState.Unavailable -> EmptyState(title = "Unavailable")
            is UiState.InsufficientData -> EmptyState(title = "Insufficient data")
            is UiState.Success -> SessionList(s.data, onOpenSession)
        }
    }
}

@Composable
private fun SessionList(sessions: List<Session>, onOpenSession: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md)) {
        sessions.forEach { session ->
            ViveCard {
                Text(
                    text = session.sessionId,
                    style = MaterialTheme.typography.titleMedium,
                )
            }
        }
    }
}
