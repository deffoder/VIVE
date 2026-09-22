package com.vive.navigation

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.vive.ui.screens.PacketDetailViewModel
import com.vive.ui.screens.SessionDetailViewModel
import com.vive.ui.screens.alerts.AlertsScreen
import com.vive.ui.screens.call.ActiveCallScreen
import com.vive.ui.screens.call.CallSummaryScreen
import com.vive.ui.screens.call.EvidenceDetailsScreen
import com.vive.ui.screens.call.IncomingCallScreen
import com.vive.ui.screens.call.LiveTranscriptScreen
import com.vive.ui.screens.call.PacketDetailScreen
import com.vive.ui.screens.call.PacketTimelineScreen
import com.vive.ui.screens.call.RiskDetailsScreen
import com.vive.ui.screens.home.HomeScreen
import com.vive.ui.screens.more.AboutScreen
import com.vive.ui.screens.more.ApiIntegrationsScreen
import com.vive.ui.screens.more.ConnectedServicesScreen
import com.vive.ui.screens.more.HelpScreen
import com.vive.ui.screens.more.LogoutScreen
import com.vive.ui.screens.more.ModelInformationScreen
import com.vive.ui.screens.more.MoreScreen
import com.vive.ui.screens.more.ProfileScreen
import com.vive.ui.screens.more.ReportsScreen
import com.vive.ui.screens.more.SettingsScreen
import com.vive.ui.screens.onboarding.LoginScreen
import com.vive.ui.screens.onboarding.OnboardingScreen
import com.vive.ui.screens.onboarding.PermissionsScreen
import com.vive.ui.screens.onboarding.SplashScreen
import com.vive.ui.screens.sessions.SessionsScreen

/**
 * Navigation graph (docs/UI_SPEC.md 3).
 *
 * Every one of the 24 flows is reachable. The required evidence path
 *   Call -> Risk -> Evidence -> Packet -> Detailed evidence
 * is wired so packet evidence is at most two taps from an active call.
 */
@Composable
fun ViveNavHost(
    navController: NavHostController,
    modifier: Modifier = Modifier,
    startDestination: String = ViveDestination.Home.route,
) {
    NavHost(
        navController = navController,
        startDestination = startDestination,
        modifier = modifier,
    ) {
        // ---------------------------------------------------------- onboarding
        composable(ViveDestination.Splash.route) {
            SplashScreen(onContinue = { navController.navigate(ViveDestination.Onboarding.route) })
        }
        composable(ViveDestination.Onboarding.route) {
            OnboardingScreen(onFinish = { navController.navigate(ViveDestination.Permissions.route) })
        }
        composable(ViveDestination.Permissions.route) {
            PermissionsScreen(onContinue = { navController.navigate(ViveDestination.Login.route) })
        }
        composable(ViveDestination.Login.route) {
            LoginScreen(onSignedIn = {
                navController.navigate(ViveDestination.Home.route) {
                    popUpTo(ViveDestination.Splash.route) { inclusive = true }
                }
            })
        }

        // ------------------------------------------------------ bottom nav tabs
        composable(ViveDestination.Home.route) {
            HomeScreen(
                onOpenSession = { navController.navigate(ViveDestination.CallSummary.create(it)) },
                onResumeActiveCall = { navController.navigate(ViveDestination.ActiveCall.create(it)) },
                onViewAllSessions = { navController.navigate(ViveDestination.Sessions.route) },
                // Navigates with the REAL session id the backend returned, so
                // the analysis screen observes the session that was actually
                // created rather than a placeholder.
                onStartLiveSession = {
                    navController.navigate(ViveDestination.ActiveCall.create(it))
                },
            )
        }
        composable(ViveDestination.Sessions.route) {
            SessionsScreen(
                onOpenSession = { navController.navigate(ViveDestination.CallSummary.create(it)) },
            )
        }
        composable(ViveDestination.Alerts.route) {
            AlertsScreen(
                onOpenPacket = { sessionId, packetId ->
                    navController.navigate(ViveDestination.PacketDetail.create(sessionId, packetId))
                },
                onOpenSession = { navController.navigate(ViveDestination.CallSummary.create(it)) },
            )
        }
        composable(ViveDestination.More.route) {
            MoreScreen(onNavigate = { navController.navigate(it.route) })
        }

        // ----------------------------------------------------------- call flow
        composable(ViveDestination.IncomingCall.route) {
            IncomingCallScreen(
                onAccept = { navController.navigate(ViveDestination.ActiveCall.create("VS-001")) },
                onDecline = { navController.popBackStack() },
            )
        }

        sessionScreen(ViveDestination.ActiveCall.route) { sessionId, vm ->
            ActiveCallScreen(
                sessionId = sessionId,
                viewModel = vm,
                onBack = { navController.popBackStack() },
                onOpenTranscript = {
                    navController.navigate(ViveDestination.LiveTranscript.create(sessionId))
                },
                onOpenRiskDetails = {
                    navController.navigate(ViveDestination.RiskDetails.create(sessionId))
                },
                onOpenPacketTimeline = {
                    navController.navigate(ViveDestination.PacketTimeline.create(sessionId))
                },
                // Ends the session for real - stops the microphone and tells
                // the backend - then opens the summary. Navigating alone left
                // the mic recording and the session STREAMING forever.
                onEndCall = {
                    vm.endSession {
                        navController.navigate(ViveDestination.CallSummary.create(sessionId))
                    }
                },
            )
        }

        sessionScreen(ViveDestination.RiskDetails.route) { sessionId, vm ->
            RiskDetailsScreen(
                viewModel = vm,
                onBack = { navController.popBackStack() },
                onOpenEvidence = {
                    navController.navigate(ViveDestination.EvidenceDetails.create(sessionId))
                },
            )
        }

        sessionScreen(ViveDestination.EvidenceDetails.route) { sessionId, vm ->
            EvidenceDetailsScreen(
                viewModel = vm,
                onBack = { navController.popBackStack() },
                onOpenPacketTimeline = {
                    navController.navigate(ViveDestination.PacketTimeline.create(sessionId))
                },
            )
        }

        sessionScreen(ViveDestination.PacketTimeline.route) { sessionId, vm ->
            PacketTimelineScreen(
                viewModel = vm,
                onBack = { navController.popBackStack() },
                onOpenPacket = { packetId ->
                    navController.navigate(
                        ViveDestination.PacketDetail.create(sessionId, packetId),
                    )
                },
            )
        }

        sessionScreen(ViveDestination.LiveTranscript.route) { sessionId, vm ->
            LiveTranscriptScreen(
                viewModel = vm,
                onBack = { navController.popBackStack() },
                onOpenPacket = { packetId ->
                    navController.navigate(
                        ViveDestination.PacketDetail.create(sessionId, packetId),
                    )
                },
            )
        }

        sessionScreen(ViveDestination.CallSummary.route) { sessionId, vm ->
            CallSummaryScreen(
                viewModel = vm,
                onBack = { navController.popBackStack() },
                onOpenTranscript = {
                    navController.navigate(ViveDestination.LiveTranscript.create(sessionId))
                },
                onOpenPacketTimeline = {
                    navController.navigate(ViveDestination.PacketTimeline.create(sessionId))
                },
                onOpenRiskDetails = {
                    navController.navigate(ViveDestination.RiskDetails.create(sessionId))
                },
            )
        }

        composable(
            route = ViveDestination.PacketDetail.route,
            arguments = listOf(
                navArgument(ViveDestination.ARG_SESSION_ID) { type = NavType.StringType },
                navArgument(ViveDestination.ARG_PACKET_ID) { type = NavType.StringType },
            ),
        ) { entry ->
            val sessionId = entry.arguments?.getString(ViveDestination.ARG_SESSION_ID).orEmpty()
            val packetId = entry.arguments?.getString(ViveDestination.ARG_PACKET_ID).orEmpty()
            val vm: PacketDetailViewModel = viewModel(
                key = "$sessionId/$packetId",
                factory = factory { PacketDetailViewModel(sessionId, packetId) },
            )
            PacketDetailScreen(viewModel = vm, onBack = { navController.popBackStack() })
        }

        // --------------------------------------------------------- More cluster
        composable(ViveDestination.Reports.route) {
            ReportsScreen(onBack = { navController.popBackStack() })
        }
        composable(ViveDestination.Settings.route) {
            SettingsScreen(
                onBack = { navController.popBackStack() },
                onNavigate = { navController.navigate(it.route) },
            )
        }
        composable(ViveDestination.ConnectedServices.route) {
            ConnectedServicesScreen(onBack = { navController.popBackStack() })
        }
        composable(ViveDestination.ApiIntegrations.route) {
            ApiIntegrationsScreen(onBack = { navController.popBackStack() })
        }
        composable(ViveDestination.ModelInformation.route) {
            ModelInformationScreen(onBack = { navController.popBackStack() })
        }
        composable(ViveDestination.Profile.route) {
            ProfileScreen(onBack = { navController.popBackStack() })
        }
        composable(ViveDestination.Help.route) {
            HelpScreen(onBack = { navController.popBackStack() })
        }
        composable(ViveDestination.About.route) {
            AboutScreen(onBack = { navController.popBackStack() })
        }
        composable(ViveDestination.Logout.route) {
            LogoutScreen(
                onBack = { navController.popBackStack() },
                onConfirm = {
                    navController.navigate(ViveDestination.Splash.route) {
                        popUpTo(ViveDestination.Home.route) { inclusive = true }
                    }
                },
            )
        }
    }
}

/**
 * Registers a route that needs a [SessionDetailViewModel] keyed to its session,
 * so the six session screens share one loaded copy per session rather than
 * refetching on every navigation.
 */
private fun androidx.navigation.NavGraphBuilder.sessionScreen(
    route: String,
    content: @Composable (String, SessionDetailViewModel) -> Unit,
) {
    composable(
        route = route,
        arguments = listOf(navArgument(ViveDestination.ARG_SESSION_ID) {
            type = NavType.StringType
        }),
    ) { entry ->
        val sessionId = entry.arguments?.getString(ViveDestination.ARG_SESSION_ID).orEmpty()
        val vm: SessionDetailViewModel = viewModel(
            key = sessionId,
            factory = factory { SessionDetailViewModel(sessionId) },
        )
        content(sessionId, vm)
    }
}

/** Tiny factory helper so view models can take constructor arguments. */
private inline fun <reified VM : ViewModel> factory(
    crossinline create: () -> VM,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = create() as T
}
