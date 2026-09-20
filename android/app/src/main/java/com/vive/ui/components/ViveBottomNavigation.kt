package com.vive.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.navigation.NavDestination
import androidx.navigation.NavDestination.Companion.hierarchy
import com.vive.navigation.ViveDestination

/**
 * The four primary destinations. Exactly four, per CLAUDE.md.
 *
 * Adding a fifth is a specification change, not a UI tweak.
 */
enum class ViveTab(
    val destination: ViveDestination,
    val label: String,
    val icon: ImageVector,
) {
    HOME(ViveDestination.Home, "Home", Icons.Filled.Home),
    SESSIONS(ViveDestination.Sessions, "Sessions", Icons.Filled.List),
    ALERTS(ViveDestination.Alerts, "Alerts", Icons.Filled.Notifications),
    MORE(ViveDestination.More, "More", Icons.Filled.Menu),
}

@Composable
fun ViveBottomNavigation(
    currentDestination: NavDestination?,
    onTabSelected: (ViveTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    NavigationBar(
        modifier = modifier,
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
    ) {
        ViveTab.entries.forEach { tab ->
            val selected = currentDestination
                ?.hierarchy
                ?.any { it.route == tab.destination.route } == true

            NavigationBarItem(
                selected = selected,
                onClick = { onTabSelected(tab) },
                icon = { Icon(tab.icon, contentDescription = tab.label) },
                label = { Text(tab.label, style = MaterialTheme.typography.labelSmall) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = MaterialTheme.colorScheme.primary,
                    selectedTextColor = MaterialTheme.colorScheme.primary,
                    indicatorColor = MaterialTheme.colorScheme.primaryContainer,
                    unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                ),
            )
        }
    }
}
