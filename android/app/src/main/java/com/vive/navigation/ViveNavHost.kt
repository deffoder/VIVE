package com.vive.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.vive.ui.screens.PlaceholderScreen
import com.vive.ui.screens.alerts.AlertsScreen
import com.vive.ui.screens.home.HomeScreen
import com.vive.ui.screens.more.MoreScreen
import com.vive.ui.screens.sessions.SessionsScreen

/**
 * Navigation graph.
 *
 * Phase 1 wires the four tabs and the full drill-down path so the structure is
 * verifiable end to end. Screens beyond the tabs render [PlaceholderScreen] -
 * their real content is Phase 4 (docs/IMPLEMENTATION_PLAN.md).
 *
 * The required evidence path (docs/UI_SPEC.md 3.2) is:
 *   Call -> Risk -> Evidence -> Packet -> Detailed evidence
 */
@Composable
fun ViveNavHost(
    navController: NavHostController,
    modifier: androidx.compose.ui.Modifier = androidx.compose.ui.Modifier,
) {
    NavHost(
        navController = navController,
        startDestination = ViveDestination.Home.route,
        modifier = modifier,
    ) {
        // --- bottom navigation ---
        composable(ViveDestination.Home.route) {
            HomeScreen(
                onOpenSession = { id ->
                    navController.navigate(ViveDestination.CallSummary.create(id))
                },
                onViewAllSessions = { navController.navigate(ViveDestination.Sessions.route) },
            )
        }
        composable(ViveDestination.Sessions.route) {
            SessionsScreen(
                onOpenSession = { id ->
                    navController.navigate(ViveDestination.CallSummary.create(id))
                },
            )
        }
        composable(ViveDestination.Alerts.route) {
            AlertsScreen(
                onOpenSession = { id ->
                    navController.navigate(ViveDestination.CallSummary.create(id))
                },
            )
        }
        composable(ViveDestination.More.route) {
            MoreScreen(onNavigate = { navController.navigate(it.route) })
        }

        // --- call flow ---
        composable(ViveDestination.IncomingCall.route) {
            PlaceholderScreen("Incoming call", "Phase 4")
        }

        composable(
            route = ViveDestination.ActiveCall.route,
            arguments = listOf(navArgument(ViveDestination.ARG_SESSION_ID) {
                type = NavType.StringType
            }),
        ) {
            PlaceholderScreen("Active call analysis", "Phase 4")
        }

        composable(
            route = ViveDestination.LiveTranscript.route,
            arguments = listOf(navArgument(ViveDestination.ARG_SESSION_ID) {
                type = NavType.StringType
            }),
        ) {
            PlaceholderScreen("Live transcript", "Phase 4")
        }

        composable(
            route = ViveDestination.RiskDetails.route,
            arguments = listOf(navArgument(ViveDestination.ARG_SESSION_ID) {
                type = NavType.StringType
            }),
        ) {
            PlaceholderScreen("Risk details", "Phase 4")
        }

        composable(
            route = ViveDestination.EvidenceDetails.route,
            arguments = listOf(navArgument(ViveDestination.ARG_SESSION_ID) {
                type = NavType.StringType
            }),
        ) {
            PlaceholderScreen("Evidence details", "Phase 4")
        }

        composable(
            route = ViveDestination.PacketTimeline.route,
            arguments = listOf(navArgument(ViveDestination.ARG_SESSION_ID) {
                type = NavType.StringType
            }),
        ) {
            PlaceholderScreen("Packet timeline", "Phase 4")
        }

        composable(
            route = ViveDestination.PacketDetail.route,
            arguments = listOf(
                navArgument(ViveDestination.ARG_SESSION_ID) { type = NavType.StringType },
                navArgument(ViveDestination.ARG_PACKET_ID) { type = NavType.StringType },
            ),
        ) {
            PlaceholderScreen("Packet detail", "Phase 4")
        }

        composable(
            route = ViveDestination.CallSummary.route,
            arguments = listOf(navArgument(ViveDestination.ARG_SESSION_ID) {
                type = NavType.StringType
            }),
        ) {
            PlaceholderScreen("Call summary", "Phase 4")
        }

        // --- More cluster ---
        composable(ViveDestination.Reports.route) { PlaceholderScreen("Reports", "Phase 4") }
        composable(ViveDestination.Settings.route) { PlaceholderScreen("Settings", "Phase 4") }
        composable(ViveDestination.ConnectedServices.route) {
            PlaceholderScreen("Connected services", "Phase 4")
        }
        composable(ViveDestination.ApiIntegrations.route) {
            PlaceholderScreen("API integrations", "Phase 4")
        }
        composable(ViveDestination.ModelInformation.route) {
            PlaceholderScreen("Model information", "Phase 4")
        }
        composable(ViveDestination.Profile.route) { PlaceholderScreen("Profile", "Phase 4") }
        composable(ViveDestination.Help.route) { PlaceholderScreen("Help & support", "Phase 4") }
        composable(ViveDestination.About.route) { PlaceholderScreen("About", "Phase 4") }
    }
}
