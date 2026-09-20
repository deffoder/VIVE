package com.vive.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.vive.navigation.ViveDestination
import com.vive.navigation.ViveNavHost
import com.vive.ui.components.ViveBottomNavigation
import com.vive.ui.components.ViveTab

/**
 * App shell: bottom navigation plus the nav host.
 *
 * Each tab keeps an independent back stack and re-selecting a tab returns to
 * its root, which is the behaviour docs/UI_SPEC.md 3.1 describes. The bar is
 * hidden on drill-down screens so evidence detail gets the full viewport.
 */
@Composable
fun ViveApp(modifier: Modifier = Modifier) {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = backStackEntry?.destination

    val tabRoutes = ViveTab.entries.map { it.destination.route }.toSet()
    val showBottomBar = currentDestination?.route in tabRoutes

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            if (showBottomBar) {
                ViveBottomNavigation(
                    currentDestination = currentDestination,
                    onTabSelected = { tab -> navController.navigateToTab(tab.destination) },
                )
            }
        },
    ) { innerPadding ->
        ViveNavHost(
            navController = navController,
            modifier = Modifier.padding(innerPadding),
        )
    }
}

/**
 * Tab switching that avoids stacking duplicates and restores the tab's own
 * back stack, per the Compose navigation guidance.
 */
private fun androidx.navigation.NavHostController.navigateToTab(destination: ViveDestination) {
    navigate(destination.route) {
        popUpTo(graph.startDestinationId) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
