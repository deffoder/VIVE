package com.vive.ui.screens.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.vive.navigation.ViveDestination
import com.vive.ui.components.ViveCard
import com.vive.ui.theme.ViveThemeTokens

/**
 * More menu (docs/UI_SPEC.md 3.1).
 *
 * Everything outside the four tabs is reached from here. Rows navigate to real
 * destinations already, so the navigation graph is verifiable in Phase 1 even
 * though the destinations render placeholders.
 */
@Composable
fun MoreScreen(
    onNavigate: (ViveDestination) -> Unit,
    modifier: Modifier = Modifier,
) {
    val entries = listOf(
        ViveDestination.Reports to "Reports & insights",
        ViveDestination.ModelInformation to "Model information",
        ViveDestination.ConnectedServices to "Connected services",
        ViveDestination.ApiIntegrations to "API integrations",
        ViveDestination.Settings to "Settings",
        ViveDestination.Profile to "Profile",
        ViveDestination.Help to "Help & support",
        ViveDestination.About to "About",
    )

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(ViveThemeTokens.spacing.gutter),
        verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
    ) {
        entries.forEach { (destination, label) ->
            ViveCard(modifier = Modifier.clickable { onNavigate(destination) }) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.heightIn(min = ViveThemeTokens.spacing.touchTarget),
                )
            }
        }
    }
}
