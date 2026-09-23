package com.vive.data.repository

import com.vive.core.ViveResult
import com.vive.data.model.Packet
import com.vive.data.model.Session
import com.vive.data.model.SourceType
import com.vive.data.model.TranscriptLine
import com.vive.data.remote.StreamState
import com.vive.data.remote.ViveEvent
import kotlinx.coroutines.flow.Flow

/**
 * Sessions, packets and the live stream.
 *
 * The UI layer talks only to repositories - never to ViveApi or ViveEventStream
 * directly (docs/ARCHITECTURE.md 6, clean separation of UI/business/data).
 */
interface SessionRepository {

    /**
     * @param language ISO 639-1 the caller will speak, or null for "auto".
     * The on-device ASR has one model per language and no language ID, so
     * on-device sessions require it; the backend accepts "auto".
     */
    suspend fun createSession(sourceType: SourceType, language: String? = null): ViveResult<Session>

    suspend fun getSession(sessionId: String): ViveResult<Session>

    suspend fun listSessions(limit: Int = 20): ViveResult<List<Session>>

    suspend fun endSession(sessionId: String): ViveResult<Session>

    suspend fun listPackets(sessionId: String, sinceSeq: Int? = null): ViveResult<List<Packet>>

    suspend fun getPacket(sessionId: String, packetId: String): ViveResult<Packet>

    suspend fun getTranscript(sessionId: String): ViveResult<List<TranscriptLine>>

    /** Live events for an active session. */
    fun observeSession(sessionId: String): Flow<ViveEvent>

    val connectionState: Flow<StreamState>
}
