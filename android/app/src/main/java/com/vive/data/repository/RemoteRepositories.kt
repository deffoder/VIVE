package com.vive.data.repository

import com.vive.core.ViveError
import com.vive.core.ViveResult
import com.vive.core.map
import com.vive.data.model.Alert
import com.vive.data.model.ModelInfo
import com.vive.data.model.Packet
import com.vive.data.model.ReadyState
import com.vive.data.model.AdapterMode
import com.vive.data.model.AdapterState
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.Session
import com.vive.data.model.SourceType
import com.vive.data.model.TranscriptLine
import com.vive.data.remote.OkHttpEventStream
import com.vive.data.remote.StreamState
import com.vive.data.remote.ViveEvent
import com.vive.data.remote.ViveService
import com.vive.data.remote.apiCall
import com.vive.data.remote.dto.CreateSessionRequestDto
import com.vive.data.remote.dto.toDomain
import kotlinx.coroutines.flow.Flow

/**
 * Backend-backed repositories.
 *
 * The UI layer is unchanged: it still talks to [SessionRepository] and never
 * sees Retrofit, OkHttp or a DTO. Swapping demo for backend is a
 * ServiceLocator change (docs/ARCHITECTURE.md 6).
 */
class RemoteSessionRepository(
    private val service: ViveService,
    private val stream: OkHttpEventStream,
) : SessionRepository {

    override suspend fun createSession(sourceType: SourceType): ViveResult<Session> {
        val created = apiCall {
            service.createSession(CreateSessionRequestDto(sourceType = sourceType.name))
        }
        return when (created) {
            is ViveResult.Failure -> created
            is ViveResult.Success -> getSession(created.data.sessionId)
        }
    }

    override suspend fun getSession(sessionId: String): ViveResult<Session> =
        apiCall { service.getSession(sessionId) }.map { it.toDomain() }

    override suspend fun listSessions(limit: Int): ViveResult<List<Session>> =
        apiCall { service.listSessions(limit = limit) }.map { list -> list.map { it.toDomain() } }

    override suspend fun endSession(sessionId: String): ViveResult<Session> =
        apiCall { service.endSession(sessionId) }.map { it.toDomain() }

    /**
     * [sinceSeq] is what makes reconnection lossless: after a dropped stream
     * the caller asks for everything past the last sequence it saw.
     */
    override suspend fun listPackets(sessionId: String, sinceSeq: Int?): ViveResult<List<Packet>> =
        apiCall { service.listPackets(sessionId, sinceSeq) }
            .map { list -> list.map { it.toDomain() } }

    override suspend fun getPacket(sessionId: String, packetId: String): ViveResult<Packet> =
        apiCall { service.getPacket(sessionId, packetId) }.map { it.toDomain() }

    override suspend fun getTranscript(sessionId: String): ViveResult<List<TranscriptLine>> =
        apiCall { service.getTranscript(sessionId) }.map { list -> list.map { it.toDomain() } }

    override fun observeSession(sessionId: String): Flow<ViveEvent> = stream.observe(sessionId)

    override val connectionState: Flow<StreamState> = stream.connectionState

    /** Demo/replay driver: sends a scripted line so the backend produces a packet. */
    fun sendTranscript(sessionId: String, text: String, speaker: String = "Caller") =
        stream.sendTranscript(sessionId, text, speaker)

    /**
     * Sends one captured analysis window upstream.
     *
     * Canonical 16 kHz mono pcm_s16le (docs/ML_SPEC.md 5). This is the live
     * path: real microphone audio, analysed by the backend's real adapters.
     * Nothing about the packet is decided here - the client captures and
     * transports, the backend analyses (docs/ARCHITECTURE.md 1, decision 8).
     */
    suspend fun sendAudio(sessionId: String, pcm: ByteArray) =
        stream.sendAudio(sessionId, pcm)

    suspend fun closeStream(sessionId: String) = stream.close(sessionId)
}

class RemoteAlertRepository(private val service: ViveService) : AlertRepository {

    override suspend fun listAlerts(sessionId: String?): ViveResult<List<Alert>> =
        apiCall { service.listAlerts(sessionId) }.map { list -> list.map { it.toDomain() } }

    override suspend fun acknowledge(alertId: String): ViveResult<Alert> =
        apiCall { service.acknowledgeAlert(alertId) }.map { it.toDomain() }
}

class RemoteModelRepository(private val service: ViveService) : ModelRepository {

    override suspend fun listModels(): ViveResult<List<ModelInfo>> =
        apiCall { service.listModels() }.map { list -> list.map { it.toDomain() } }

    override suspend fun ready(): ViveResult<ReadyState> =
        apiCall { service.ready() }.map { dto ->
            ReadyState(
                ready = dto.ready,
                apiVersion = dto.apiVersion,
                adapters = dto.adapters.mapValues { (_, state) ->
                    AdapterState(
                        status = AnalyzerStatus.entries
                            .firstOrNull { it.name.equals(state.status, ignoreCase = true) }
                            ?: AnalyzerStatus.UNAVAILABLE,
                        mode = if (state.mode.equals("real", ignoreCase = true)) {
                            AdapterMode.REAL
                        } else {
                            AdapterMode.MOCK
                        },
                    )
                },
            )
        }
}

/**
 * Falls back to a secondary repository when the primary is unreachable.
 *
 * This is what lets the app stay usable with no backend running: live data when
 * the backend answers, demo data when it does not. The fallback is NOT silent -
 * [usingFallback] drives the UI's demo indicator, so a viewer always knows
 * which source they are looking at.
 */
class FallbackSessionRepository(
    private val primary: SessionRepository,
    private val fallback: SessionRepository,
) : SessionRepository {

    @Volatile
    var usingFallback: Boolean = false
        private set

    private inline fun <T> pick(
        primaryCall: () -> ViveResult<T>,
        fallbackCall: () -> ViveResult<T>,
    ): ViveResult<T> {
        val result = primaryCall()
        val unreachable = result is ViveResult.Failure && result.error is ViveError.Offline
        usingFallback = unreachable
        return if (unreachable) fallbackCall() else result
    }

    override suspend fun createSession(sourceType: SourceType): ViveResult<Session> {
        val result = primary.createSession(sourceType)
        val unreachable = result is ViveResult.Failure && result.error is ViveError.Offline
        usingFallback = unreachable
        return if (unreachable) fallback.createSession(sourceType) else result
    }

    override suspend fun getSession(sessionId: String): ViveResult<Session> {
        val result = primary.getSession(sessionId)
        val unreachable = result is ViveResult.Failure && result.error is ViveError.Offline
        usingFallback = unreachable
        return if (unreachable) fallback.getSession(sessionId) else result
    }

    override suspend fun listSessions(limit: Int): ViveResult<List<Session>> {
        val result = primary.listSessions(limit)
        val unreachable = result is ViveResult.Failure && result.error is ViveError.Offline
        usingFallback = unreachable
        return if (unreachable) fallback.listSessions(limit) else result
    }

    override suspend fun endSession(sessionId: String): ViveResult<Session> {
        val result = primary.endSession(sessionId)
        return if (result is ViveResult.Failure && result.error is ViveError.Offline) {
            fallback.endSession(sessionId)
        } else {
            result
        }
    }

    override suspend fun listPackets(sessionId: String, sinceSeq: Int?): ViveResult<List<Packet>> {
        val result = primary.listPackets(sessionId, sinceSeq)
        return if (result is ViveResult.Failure && result.error is ViveError.Offline) {
            fallback.listPackets(sessionId, sinceSeq)
        } else {
            result
        }
    }

    override suspend fun getPacket(sessionId: String, packetId: String): ViveResult<Packet> {
        val result = primary.getPacket(sessionId, packetId)
        return if (result is ViveResult.Failure && result.error is ViveError.Offline) {
            fallback.getPacket(sessionId, packetId)
        } else {
            result
        }
    }

    override suspend fun getTranscript(sessionId: String): ViveResult<List<TranscriptLine>> {
        val result = primary.getTranscript(sessionId)
        return if (result is ViveResult.Failure && result.error is ViveError.Offline) {
            fallback.getTranscript(sessionId)
        } else {
            result
        }
    }

    override fun observeSession(sessionId: String): Flow<ViveEvent> =
        if (usingFallback) fallback.observeSession(sessionId) else primary.observeSession(sessionId)

    override val connectionState: Flow<StreamState> = primary.connectionState
}
