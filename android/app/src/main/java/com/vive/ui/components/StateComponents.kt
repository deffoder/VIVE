package com.vive.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.vive.core.ViveError
import com.vive.ui.theme.ViveTheme
import com.vive.ui.theme.ViveThemeTokens

/**
 * The seven screen states as reusable components.
 *
 * Required by CLAUDE.md (State Design) and docs/UI_SPEC.md 8. Having one
 * implementation each keeps wording and spacing consistent everywhere, and
 * means a screen can never invent its own phrasing for "no data".
 *
 * Wording discipline: [UnavailableState] and [InsufficientDataState] explain
 * WHY there is no value. Neither ever shows 0, a dash, or a guess.
 */

@Composable
fun LoadingState(modifier: Modifier = Modifier, label: String = "Loading") {
    StateContainer(modifier) {
        CircularProgressIndicator(strokeWidth = 2.dp)
        StateText(label)
    }
}

@Composable
fun EmptyState(
    title: String = "Nothing here yet",
    description: String? = null,
    modifier: Modifier = Modifier,
) {
    StateContainer(modifier) {
        StateTitle(title)
        description?.let { StateText(it) }
    }
}

@Composable
fun ErrorState(
    error: ViveError,
    modifier: Modifier = Modifier,
    onRetry: (() -> Unit)? = null,
) {
    StateContainer(modifier) {
        StateTitle("Something went wrong")
        StateText(error.message)
        if (onRetry != null) {
            TextButton(onClick = onRetry) { Text("Retry") }
        }
    }
}

/**
 * Offline is distinct from error: it is recoverable and cached data may still
 * be shown alongside it (docs/UI_SPEC.md 8).
 */
@Composable
fun OfflineState(modifier: Modifier = Modifier, onRetry: (() -> Unit)? = null) {
    StateContainer(modifier) {
        StateTitle("You are offline")
        StateText("Showing the last data received. Live analysis resumes when the connection returns.")
        if (onRetry != null) {
            TextButton(onClick = onRetry) { Text("Retry") }
        }
    }
}

/**
 * A model produced no output. Never render 0 or a placeholder number here -
 * absence of evidence is not evidence of safety, nor of risk.
 */
@Composable
fun UnavailableState(
    modifier: Modifier = Modifier,
    reason: String? = null,
) {
    StateContainer(modifier) {
        StateTitle("Unavailable")
        StateText(reason ?: "This analysis is not available for the current session.")
    }
}

/**
 * The audio was unusable. Confidence falls; risk must NOT rise
 * (docs/PROJECT_SPEC.md 3, DEMO_SPEC S4).
 */
@Composable
fun InsufficientDataState(
    modifier: Modifier = Modifier,
    reason: String? = null,
) {
    StateContainer(modifier) {
        StateTitle("Insufficient data")
        StateText(reason ?: "There is not enough clear audio to assess this reliably.")
    }
}

// --- shared building blocks ---

@Composable
private fun StateContainer(
    modifier: Modifier = Modifier,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(ViveThemeTokens.spacing.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.sm),
        content = content,
    )
}

@Composable
private fun StateTitle(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.onSurface,
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun StateText(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
    )
}

@Preview(showBackground = true)
@Composable
private fun StatesPreview() {
    ViveTheme {
        Column {
            LoadingState()
            EmptyState()
            UnavailableState()
            InsufficientDataState()
            OfflineState()
            ErrorState(ViveError.Unexpected())
        }
    }
}
