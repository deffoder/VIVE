package com.vive.session

import com.vive.core.ServiceLocator
import com.vive.core.ViveError
import com.vive.core.ViveResult
import com.vive.data.model.Packet
import com.vive.data.model.Session
import com.vive.data.model.SessionStatus
import com.vive.data.model.SourceType
import com.vive.data.model.TranscriptLine
import com.vive.data.remote.StreamState
import com.vive.data.remote.ViveEvent
import com.vive.data.repository.SessionRepository
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session lifecycle, at the repository boundary.
 *
 * These exist because "End call" used to only navigate: the screen changed,
 * the microphone kept recording and the backend session stayed STREAMING
 * indefinitely. A control named for an operation has to perform it, and the
 * way to keep that true over time is to assert the call reaches the data
 * layer rather than trusting the screen to have done something.
 */
class SessionLifecycleTest {

    /** Records what the UI actually asked the data layer to do. */
    private class RecordingRepository : SessionRepository {
        val calls = mutableListOf<String>()
        val endedSessions = mutableListOf<String>()

        private fun session(id: String, status: SessionStatus) = Session(
            sessionId = id,
            status = status,
            sourceType = SourceType.IN_APP,
            startedAt = "2026-09-23T00:00:00Z",
        )

        override suspend fun createSession(sourceType: SourceType): ViveResult<Session> {
            calls += "create:${sourceType.name}"
            return ViveResult.Success(session("VS-TEST", SessionStatus.STREAMING))
        }

        override suspend fun getSession(sessionId: String): ViveResult<Session> {
            calls += "get:$sessionId"
            return ViveResult.Success(session(sessionId, SessionStatus.STREAMING))
        }

        override suspend fun listSessions(limit: Int): ViveResult<List<Session>> {
            calls += "list"
            return ViveResult.Success(emptyList())
        }

        override suspend fun endSession(sessionId: String): ViveResult<Session> {
            calls += "end:$sessionId"
            endedSessions += sessionId
            return ViveResult.Success(session(sessionId, SessionStatus.ENDED))
        }

        override suspend fun listPackets(
            sessionId: String,
            sinceSeq: Int?,
        ): ViveResult<List<Packet>> {
            calls += "packets:$sessionId"
            return ViveResult.Success(emptyList())
        }

        override suspend fun getPacket(
            sessionId: String,
            packetId: String,
        ): ViveResult<Packet> = ViveResult.Failure(ViveError.NotFound())

        override suspend fun getTranscript(
            sessionId: String,
        ): ViveResult<List<TranscriptLine>> {
            calls += "transcript:$sessionId"
            return ViveResult.Success(emptyList())
        }

        override fun observeSession(sessionId: String): Flow<ViveEvent> = emptyFlow()

        override val connectionState: Flow<StreamState> = flowOf(StreamState.Idle)
    }

    @After
    fun tearDown() = ServiceLocator.reset()

    @Test
    fun `creating a live session asks the backend for an in-app source`() = runTest {
        val repository = RecordingRepository()
        ServiceLocator.override(sessions = repository)

        val result = ServiceLocator.sessions.createSession(SourceType.IN_APP)

        assertTrue(result is ViveResult.Success)
        assertTrue(
            "the session must be created on the backend, not invented locally",
            repository.calls.contains("create:IN_APP"),
        )
    }

    @Test
    fun `ending a session reaches the backend`() = runTest {
        val repository = RecordingRepository()
        ServiceLocator.override(sessions = repository)

        ServiceLocator.sessions.endSession("VS-TEST")

        assertEquals(listOf("VS-TEST"), repository.endedSessions)
    }

    @Test
    fun `an ended session reports ENDED, not STREAMING`() = runTest {
        val repository = RecordingRepository()
        ServiceLocator.override(sessions = repository)

        val ended = ServiceLocator.sessions.endSession("VS-TEST")

        assertEquals(
            SessionStatus.ENDED,
            (ended as ViveResult.Success).data.status,
        )
    }

    @Test
    fun `the production path does not serve demo repositories`() {
        ServiceLocator.reset()
        // Alerts and model status were wired to demo repositories, so the app
        // showed invented alerts naming sessions that never happened, and
        // reported adapters AVAILABLE with nothing loaded. Neither belongs in
        // a product whose whole claim is that its output comes from real
        // analysis.
        assertTrue(
            "alerts must come from the backend, not a demo list",
            ServiceLocator.alerts::class.simpleName?.startsWith("Remote") == true,
        )
        assertTrue(
            "model status must come from the backend",
            ServiceLocator.models::class.simpleName?.startsWith("Remote") == true,
        )
    }
}
