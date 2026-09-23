package com.vive.ui.screens.sessions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vive.data.model.RiskLevel
import com.vive.ui.components.EmptyState
import com.vive.ui.components.FilterChipRow
import com.vive.ui.components.SessionCard
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.screens.SessionListViewModel
import com.vive.ui.screens.StateHost
import com.vive.ui.theme.ViveThemeTokens

/**
 * Call history (docs/UI_SPEC.md 4.14).
 * Filter chips narrow by risk level; filtering to nothing shows an empty state
 * rather than a blank screen.
 */
@Composable
fun SessionsScreen(
    onOpenSession: (String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: SessionListViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var filter by remember { mutableStateOf("All") }
    val filters = listOf("All", "Low", "Medium", "High", "Critical")

    ViveScreenScaffold(title = "Sessions", modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            FilterChipRow(options = filters, selected = filter, onSelect = { filter = it })

            StateHost(
                state = state,
                onRetry = viewModel::refresh,
                emptyTitle = "No sessions yet",
                emptyDescription = "Analysed calls will appear here.",
            ) { sessions ->
                val visible = sessions.filter { s ->
                    filter == "All" || s.peakLevel?.matches(filter) == true
                }
                if (visible.isEmpty()) {
                    EmptyState(
                        title = "No $filter risk sessions",
                        description = "Try a different filter.",
                    )
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md)) {
                        visible.forEach { session ->
                            SessionCard(session = session, onClick = { onOpenSession(session.sessionId) })
                        }
                    }
                }
            }
        }
    }
}

private fun RiskLevel.matches(filter: String): Boolean = name.equals(filter, ignoreCase = true)
