package com.vive.navigation

/**
 * Navigation destinations.
 *
 * Structure follows docs/UI_SPEC.md 3. The bottom bar has exactly four
 * destinations (CLAUDE.md, Primary Navigation) - everything else is reached by
 * drill-down or from More. Do not add tabs.
 *
 * Route strings are stable identifiers; parameterised routes build their path
 * through [create] so call sites never concatenate strings by hand.
 */
sealed class ViveDestination(val route: String) {

    // --- bottom navigation ---
    data object Home : ViveDestination("home")
    data object Sessions : ViveDestination("sessions")
    data object Alerts : ViveDestination("alerts")
    data object More : ViveDestination("more")

    // --- call flow ---
    data object IncomingCall : ViveDestination("call/incoming")

    data object ActiveCall : ViveDestination("call/{sessionId}/active") {
        fun create(sessionId: String) = "call/$sessionId/active"
    }

    data object LiveTranscript : ViveDestination("call/{sessionId}/transcript") {
        fun create(sessionId: String) = "call/$sessionId/transcript"
    }

    data object RiskDetails : ViveDestination("call/{sessionId}/risk") {
        fun create(sessionId: String) = "call/$sessionId/risk"
    }

    data object EvidenceDetails : ViveDestination("call/{sessionId}/evidence") {
        fun create(sessionId: String) = "call/$sessionId/evidence"
    }

    data object PacketTimeline : ViveDestination("call/{sessionId}/packets") {
        fun create(sessionId: String) = "call/$sessionId/packets"
    }

    data object PacketDetail : ViveDestination("call/{sessionId}/packets/{packetId}") {
        fun create(sessionId: String, packetId: String) = "call/$sessionId/packets/$packetId"
    }

    data object CallSummary : ViveDestination("call/{sessionId}/summary") {
        fun create(sessionId: String) = "call/$sessionId/summary"
    }

    // --- More cluster ---
    data object Reports : ViveDestination("more/reports")
    data object Settings : ViveDestination("more/settings")
    data object ConnectedServices : ViveDestination("more/services")
    data object ApiIntegrations : ViveDestination("more/integrations")
    data object ModelInformation : ViveDestination("more/models")
    data object Profile : ViveDestination("more/profile")
    data object Help : ViveDestination("more/help")
    data object About : ViveDestination("more/about")

    companion object {
        const val ARG_SESSION_ID = "sessionId"
        const val ARG_PACKET_ID = "packetId"
    }
}
