package com.vive.remote

import com.vive.core.ViveError
import com.vive.core.ViveResult
import com.vive.data.demo.DemoSessionRepository
import com.vive.data.model.SourceType
import com.vive.data.remote.NetworkModule
import com.vive.data.remote.OkHttpEventStream
import com.vive.data.repository.FallbackSessionRepository
import com.vive.data.repository.RemoteAlertRepository
import com.vive.data.repository.RemoteModelRepository
import com.vive.data.repository.RemoteSessionRepository
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Repository tests against a MockWebServer.
 *
 * These prove the HTTP-to-[ViveError] mapping and the offline fallback without
 * needing a running backend.
 */
class RepositoryTest {

    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun repo(): RemoteSessionRepository {
        val base = server.url("/").toString()
        return RemoteSessionRepository(
            NetworkModule.service(base),
            OkHttpEventStream(base),
        )
    }

    private fun jsonResponse(code: Int, body: String) = MockResponse()
        .setResponseCode(code)
        .setHeader("Content-Type", "application/json")
        .setBody(body)

    @Test
    fun `list sessions maps the backend payload`() = runTest {
        server.enqueue(
            jsonResponse(
                200,
                """[{"session_id":"VS-001","status":"ENDED","source_type":"VOIP",
                     "duration_sec":42,"packets_processed":7}]""",
            ),
        )
        val result = repo().listSessions()
        assertTrue(result is ViveResult.Success)
        val sessions = (result as ViveResult.Success).data
        assertEquals(1, sessions.size)
        assertEquals("VS-001", sessions.first().sessionId)
        assertEquals(7, sessions.first().packetsProcessed)
    }

    @Test
    fun `structured 404 maps to NotFound`() = runTest {
        server.enqueue(
            jsonResponse(
                404,
                """{"error":{"code":"SESSION_NOT_FOUND","message":"No session with id VS-9."}}""",
            ),
        )
        val result = repo().getSession("VS-9")
        assertTrue(result is ViveResult.Failure)
        assertTrue((result as ViveResult.Failure).error is ViveError.NotFound)
    }

    @Test
    fun `401 maps to Unauthenticated`() = runTest {
        server.enqueue(
            jsonResponse(401, """{"error":{"code":"UNAUTHENTICATED","message":"Token required."}}"""),
        )
        val result = repo().getSession("VS-1")
        assertTrue((result as ViveResult.Failure).error is ViveError.Unauthenticated)
    }

    @Test
    fun `validation error maps to Validation`() = runTest {
        server.enqueue(
            jsonResponse(400, """{"error":{"code":"VALIDATION_ERROR","message":"bad request"}}"""),
        )
        val result = repo().createSession(SourceType.VOIP)
        assertTrue((result as ViveResult.Failure).error is ViveError.Validation)
    }

    @Test
    fun `unreachable backend maps to Offline rather than throwing`() = runTest {
        server.shutdown() // nothing is listening now
        val result = repo().listSessions()
        assertTrue(result is ViveResult.Failure)
        assertTrue((result as ViveResult.Failure).error is ViveError.Offline)
    }

    @Test
    fun `since_seq is sent so a reconnecting client can backfill`() = runTest {
        server.enqueue(jsonResponse(200, "[]"))
        repo().listPackets("VS-001", sinceSeq = 4)
        val request = server.takeRequest()
        assertTrue(
            "request must carry since_seq: ${request.path}",
            request.path!!.contains("since_seq=4"),
        )
    }

    @Test
    fun `fallback serves demo data when the backend is unreachable`() = runTest {
        server.shutdown()
        val fallback = FallbackSessionRepository(repo(), DemoSessionRepository())

        val result = fallback.listSessions()
        assertTrue(result is ViveResult.Success)
        assertTrue(
            "demo data must be served when offline",
            (result as ViveResult.Success).data.isNotEmpty(),
        )
        assertTrue("fallback must be visible, never silent", fallback.usingFallback)
    }

    @Test
    fun `fallback prefers the backend when it answers`() = runTest {
        server.enqueue(jsonResponse(200, """[{"session_id":"VS-042","status":"ENDED","source_type":"VOIP"}]"""))
        val fallback = FallbackSessionRepository(repo(), DemoSessionRepository())

        val sessions = (fallback.listSessions() as ViveResult.Success).data
        assertEquals("VS-042", sessions.single().sessionId)
        assertTrue("backend answered, so no fallback", !fallback.usingFallback)
    }

    @Test
    fun `ready reports adapter mode so the demo badge can be driven`() = runTest {
        server.enqueue(
            jsonResponse(
                200,
                """{"ready":true,"api_version":"v1",
                    "adapters":{"antispoof":{"status":"AVAILABLE","mode":"mock"}}}""",
            ),
        )
        val result = RemoteModelRepository(NetworkModule.service(server.url("/").toString())).ready()
        val ready = (result as ViveResult.Success).data
        assertTrue(ready.hasMockAdapter)
    }

    @Test
    fun `alerts map including recommended action`() = runTest {
        server.enqueue(
            jsonResponse(
                200,
                """[{"alert_id":"AL-001","session_id":"VS-001","level":"CRITICAL",
                     "raised_at":"now","reason":"OTP request",
                     "recommended_action":"SECONDARY_VERIFICATION"}]""",
            ),
        )
        val result = RemoteAlertRepository(NetworkModule.service(server.url("/").toString()))
            .listAlerts()
        val alerts = (result as ViveResult.Success).data
        assertEquals("AL-001", alerts.single().alertId)
        assertEquals(
            com.vive.data.model.RecommendedAction.SECONDARY_VERIFICATION,
            alerts.single().recommendedAction,
        )
    }
}
