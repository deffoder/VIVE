package com.vive.data.demo

import com.vive.core.ViveError
import com.vive.core.ViveResult
import com.vive.data.model.AdapterMode
import com.vive.data.model.AdapterState
import com.vive.data.model.Alert
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.ModelInfo
import com.vive.data.model.Packet
import com.vive.data.model.ReadyState
import com.vive.data.model.Session
import com.vive.data.model.SourceType
import com.vive.data.model.TranscriptLine
import com.vive.data.remote.StreamState
import com.vive.data.remote.ViveEvent
import com.vive.data.repository.AlertRepository
import com.vive.data.repository.ModelRepository
import com.vive.data.repository.SessionRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flow

/**
 * Demo-backed repository implementations.
 *
 * These serve [DemoData] through the same interfaces the real implementations
 * will use, so swapping to a live backend touches nothing above the data layer.
 *
 * They report [AdapterMode.MOCK] so the UI shows the "Demo data" badge. They do
 * not run inference and must never be presented as detection capability.
 */

/** Small delay so Loading states are actually observable in the UI. */
private const val LATENCY_MS = 220L

class DemoSessionRepository : SessionRepository {

    private val acknowledged = mutableSetOf<String>()

    override suspend fun createSession(sourceType: SourceType): ViveResult<Session> {
        delay(LATENCY_MS)
        return ViveResult.Success(DemoData.activeSession)
    }

    override suspend fun getSession(sessionId: String): ViveResult<Session> {
        delay(LATENCY_MS)
        return DemoData.session(sessionId)
            ?.let { ViveResult.Success(it) }
            ?: ViveResult.Failure(ViveError.NotFound("No session $sessionId"))
    }

    override suspend fun listSessions(limit: Int): ViveResult<List<Session>> {
        delay(LATENCY_MS)
        return ViveResult.Success(DemoData.sessions.take(limit))
    }

    override suspend fun endSession(sessionId: String): ViveResult<Session> =
        getSession(sessionId)

    override suspend fun listPackets(sessionId: String, sinceSeq: Int?): ViveResult<List<Packet>> {
        delay(LATENCY_MS)
        val all = DemoData.packets(sessionId)
        val filtered = if (sinceSeq == null) all else all.filter { (it.seq ?: 0) > sinceSeq }
        return ViveResult.Success(filtered)
    }

    override suspend fun getPacket(sessionId: String, packetId: String): ViveResult<Packet> {
        delay(LATENCY_MS)
        return DemoData.packet(sessionId, packetId)
            ?.let { ViveResult.Success(it) }
            ?: ViveResult.Failure(ViveError.NotFound("No packet $packetId"))
    }

    override suspend fun getTranscript(sessionId: String): ViveResult<List<TranscriptLine>> {
        delay(LATENCY_MS)
        return ViveResult.Success(DemoData.transcript(sessionId))
    }

    /**
     * Replays the session's packets on a timer so the live screens animate.
     * This is a scripted replay, not a model producing results in real time.
     */
    override fun observeSession(sessionId: String): Flow<ViveEvent> = flow {
        val packets = DemoData.packets(sessionId)
        val session = DemoData.session(sessionId) ?: return@flow
        emit(ViveEvent.SessionState(sessionId, session))
        packets.forEach { packet ->
            delay(1_400)
            emit(ViveEvent.PacketNew(sessionId, packet.seq ?: 0, packet))
        }
    }

    override val connectionState: Flow<StreamState> = MutableStateFlow(StreamState.Connected)
}

class DemoAlertRepository : AlertRepository {

    private val acknowledged = mutableSetOf<String>()

    override suspend fun listAlerts(sessionId: String?): ViveResult<List<Alert>> {
        delay(LATENCY_MS)
        val list = DemoData.alerts
            .filter { sessionId == null || it.sessionId == sessionId }
            .map { if (it.alertId in acknowledged) it.copy(acknowledged = true) else it }
        return ViveResult.Success(list)
    }

    override suspend fun acknowledge(alertId: String): ViveResult<Alert> {
        delay(LATENCY_MS)
        acknowledged += alertId
        return DemoData.alert(alertId)
            ?.let { ViveResult.Success(it.copy(acknowledged = true)) }
            ?: ViveResult.Failure(ViveError.NotFound("No alert $alertId"))
    }
}

class DemoModelRepository : ModelRepository {

    override suspend fun listModels(): ViveResult<List<ModelInfo>> {
        delay(LATENCY_MS)
        return ViveResult.Success(DemoData.models)
    }

    override suspend fun ready(): ViveResult<ReadyState> {
        delay(LATENCY_MS)
        return ViveResult.Success(
            ReadyState(
                ready = true,
                apiVersion = "v1",
                adapters = DemoData.models.associate { model ->
                    adapterKey(model.id) to AdapterState(model.status, AdapterMode.MOCK)
                },
            ),
        )
    }

    /** Maps model IDs to the adapter keys used by /ready (docs/ML_SPEC.md 2). */
    private fun adapterKey(modelId: String): String = when (modelId) {
        "silero-vad" -> "vad"
        "aasist" -> "antispoof"
        "ecapa-tdnn" -> "speaker"
        "indic-conformer-600m" -> "asr"
        "intent-classifier" -> "intent"
        "behavior-classifier" -> "behavior"
        else -> modelId
    }
}
