package com.vive.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.vive.core.ServiceLocator
import com.vive.ui.theme.ViveThemeTokens

/**
 * Shared screen scaffold.
 *
 * Gives every screen the same app bar, gutter and background so spacing never
 * drifts between screens. The Demo data badge is attached here rather than per
 * screen, so it cannot be forgotten (docs/UI_SPEC.md 6).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ViveScreenScaffold(
    title: String,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    actions: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit = {},
    showDemoBadge: Boolean = ServiceLocator.isDemo,
    content: @Composable (PaddingValues) -> Unit,
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(text = title, style = MaterialTheme.typography.titleLarge)
                        if (showDemoBadge) {
                            DemoDataBadge()
                        }
                    }
                },
                navigationIcon = {
                    if (onBack != null) {
                        IconButton(onClick = onBack) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back",
                            )
                        }
                    }
                },
                actions = actions,
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                    navigationIconContentColor = MaterialTheme.colorScheme.onSurface,
                ),
            )
        },
        content = content,
    )
}

/**
 * Standard scrollable body: screen gutter, consistent vertical rhythm.
 * Screens that need a lazy list use their own LazyColumn instead.
 */
@Composable
fun ViveScreenBody(
    padding: PaddingValues,
    modifier: Modifier = Modifier,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(padding)
            .verticalScroll(rememberScrollState())
            .padding(
                start = ViveThemeTokens.spacing.gutter,
                end = ViveThemeTokens.spacing.gutter,
                top = ViveThemeTokens.spacing.sm,
                bottom = ViveThemeTokens.spacing.xxl,
            ),
        verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.lg),
        content = content,
    )
}
