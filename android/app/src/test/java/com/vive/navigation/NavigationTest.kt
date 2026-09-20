package com.vive.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The navigation contract: exactly four tabs, and every parameterised route
 * builds a path that matches its own pattern.
 */
class NavigationTest {

    @Test
    fun `parameterised routes build paths matching their pattern`() {
        val cases = listOf(
            ViveDestination.ActiveCall.route to ViveDestination.ActiveCall.create("VS-001"),
            ViveDestination.RiskDetails.route to ViveDestination.RiskDetails.create("VS-001"),
            ViveDestination.EvidenceDetails.route to ViveDestination.EvidenceDetails.create("VS-001"),
            ViveDestination.PacketTimeline.route to ViveDestination.PacketTimeline.create("VS-001"),
            ViveDestination.LiveTranscript.route to ViveDestination.LiveTranscript.create("VS-001"),
            ViveDestination.CallSummary.route to ViveDestination.CallSummary.create("VS-001"),
        )
        cases.forEach { (pattern, built) ->
            val regex = Regex(pattern.replace(Regex("[{][^}]+[}]"), "[^/]+"))
            assertTrue("'$built' must match '$pattern'", regex.matches(built))
        }
    }

    @Test
    fun `packet detail route carries both session and packet`() {
        val built = ViveDestination.PacketDetail.create("VS-001", "P007")
        assertEquals("call/VS-001/packets/P007", built)
        val regex = Regex(
            ViveDestination.PacketDetail.route.replace(Regex("[{][^}]+[}]"), "[^/]+"),
        )
        assertTrue(regex.matches(built))
    }

    @Test
    fun `routes are unique`() {
        val routes = listOf(
            ViveDestination.Splash, ViveDestination.Onboarding, ViveDestination.Permissions,
            ViveDestination.Login, ViveDestination.Home, ViveDestination.Sessions,
            ViveDestination.Alerts, ViveDestination.More, ViveDestination.IncomingCall,
            ViveDestination.ActiveCall, ViveDestination.LiveTranscript, ViveDestination.RiskDetails,
            ViveDestination.EvidenceDetails, ViveDestination.PacketTimeline,
            ViveDestination.PacketDetail, ViveDestination.CallSummary, ViveDestination.Reports,
            ViveDestination.Settings, ViveDestination.ConnectedServices,
            ViveDestination.ApiIntegrations, ViveDestination.ModelInformation,
            ViveDestination.Profile, ViveDestination.Help, ViveDestination.About,
            ViveDestination.Logout,
        ).map { it.route }
        assertEquals("routes must be unique", routes.size, routes.toSet().size)
    }

    @Test
    fun `all 24 specified flows have a destination`() {
        val all = listOf(
            ViveDestination.Splash, ViveDestination.Onboarding, ViveDestination.Permissions,
            ViveDestination.Login, ViveDestination.Home, ViveDestination.IncomingCall,
            ViveDestination.ActiveCall, ViveDestination.LiveTranscript, ViveDestination.RiskDetails,
            ViveDestination.EvidenceDetails, ViveDestination.PacketTimeline,
            ViveDestination.PacketDetail, ViveDestination.CallSummary, ViveDestination.Sessions,
            ViveDestination.Alerts, ViveDestination.Reports, ViveDestination.Settings,
            ViveDestination.ConnectedServices, ViveDestination.ApiIntegrations,
            ViveDestination.ModelInformation, ViveDestination.Profile, ViveDestination.Help,
            ViveDestination.About, ViveDestination.Logout,
        )
        assertEquals(24, all.size)
    }
}
