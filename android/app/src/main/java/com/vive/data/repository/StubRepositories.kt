package com.vive.data.repository

import com.vive.core.ViveError
import com.vive.core.ViveResult
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
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow

/**
 * Phase 1 stand-ins.
 *
 * DELIBERATELY EMPTY. These report "no data" and "unavailable" - they do NOT
 * fabricate risk scores, transcripts or model outputs. CLAUDE.md forbids
 * creating fake model logic to populate the UI, and docs/ML_SPEC.md 4 places
 * scenario-driven demo adapters in Phase 2, backed by DEMO_SPEC scenarios.
 *
 * Their job here is to exercise the Empty / Unavailable / Error state paths so
 * the state architecture is proven before any real or mock data exists.
 *
 * Superseded in Phase 4 by DemoRepositories and RemoteRepositories. Retained
 * as the no-data reference implementation; not wired into ServiceLocator.
 */

class StubSessionRepository : SessionRepository {

    override suspend fun createSession(sourceType: SourceType): ViveResult<Session> =
        ViveResult.Failure(ViveError.AdapterUnavailable(adapter = "backend"))

    override suspend fun getSession(sessionId: String): ViveResult<Session> =
        ViveResult.Failure(ViveError.NotFound())

    override suspend fun listSessions(limit: Int): ViveResult<List<Session>> =
        ViveResult.Success(emptyList())

    override suspend fun endSession(sessionId: String): ViveResult<Session> =
        ViveResult.Failure(ViveError.NotFound())

    override suspend fun listPackets(sessionId: String, sinceSeq: Int?): ViveResult<List<Packet>> =
        ViveResult.Success(emptyList())

    override suspend fun getPacket(sessionId: String, packetId: String): ViveResult<Packet> =
        ViveResult.Failure(ViveError.NotFound())

    override suspend fun getTranscript(sessionId: String): ViveResult<List<TranscriptLine>> =
        ViveResult.Success(emptyList())

    override fun observeSession(sessionId: String): Flow<ViveEvent> = emptyFlow()

    override val connectionState: Flow<StreamState> = MutableStateFlow(StreamState.Idle)
}

class StubAlertRepository : AlertRepository {

    override suspend fun listAlerts(sessionId: String?): ViveResult<List<Alert>> =
        ViveResult.Success(emptyList())

    override suspend fun acknowledge(alertId: String): ViveResult<Alert> =
        ViveResult.Failure(ViveError.NotFound())
}

class StubModelRepository : ModelRepository {

    /**
     * Reports the model inventory with every adapter UNAVAILABLE. Versions are
     * empty strings rather than invented values, and no accuracy is reported -
     * nothing here was measured (docs/ML_SPEC.md 8.5).
     */
    override suspend fun listModels(): ViveResult<List<ModelInfo>> = ViveResult.Success(
        ModelCatalog.ALL.map { (id, displayName, purpose) ->
            ModelInfo(
                id = id,
                displayName = displayName,
                purpose = purpose,
                version = "",
                mode = com.vive.data.model.AdapterMode.MOCK,
                status = AnalyzerStatus.UNAVAILABLE,
            )
        },
    )

    override suspend fun ready(): ViveResult<ReadyState> =
        ViveResult.Failure(ViveError.AdapterUnavailable(adapter = "backend"))
}

/**
 * Canonical model identifiers, matching docs/ML_SPEC.md 2 exactly.
 * Names only - no versions, no metrics.
 */
object ModelCatalog {
    val ALL: List<Triple<String, String, String>> = listOf(
        Triple("silero-vad", "Silero VAD", "Speech activity detection"),
        Triple("aasist", "AASIST", "Synthetic-voice evidence"),
        Triple("ecapa-tdnn", "ECAPA-TDNN", "Speaker consistency"),
        Triple("indic-conformer-600m", "IndicConformer-600M (CTC)",
            "Multilingual speech recognition, IN-22"),
        Triple("intent-classifier", "Intent Classifier", "Caller intent"),
        Triple("behavior-classifier", "Behaviour Classifier", "Social-engineering behaviour"),
        Triple("risk-fusion", "Risk Fusion", "Calibrated risk from evidence"),
    )
}
