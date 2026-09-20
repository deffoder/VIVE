package com.vive.data.remote

import com.vive.core.ViveResult
import com.vive.data.model.Alert
import com.vive.data.model.ModelInfo
import com.vive.data.model.Packet
import com.vive.data.model.ReadyState
import com.vive.data.model.RiskSummary
import com.vive.data.model.Session
import com.vive.data.model.SourceType
import com.vive.data.model.TranscriptLine

/**
 * REST surface. Mirrors docs/API_SPEC.md 2, 3 and 5 exactly.
 *
 * Declared as an interface with no networking dependency so Phase 1 stays free
 * of transport concerns. A Retrofit-backed implementation arrives in Phase 5
 * (docs/IMPLEMENTATION_PLAN.md); until then FakeViveApi serves the same contract.
 *
 * All methods return ViveResult rather than throwing, so callers must handle
 * failure and the UI cannot crash on missing output.
 */
interface ViveApi {

    // --- operational ---

    suspend fun health(): ViveResult<Boolean>

    /** Includes per-adapter mock/real mode, which the UI must surface. */
    suspend fun ready(): ViveResult<ReadyState>

    // --- sessions ---

    suspend fun createSession(
        sourceType: SourceType,
        language: String = "auto",
    ): ViveResult<Session>

    suspend fun listSessions(limit: Int = 20, offset: Int = 0): ViveResult<List<Session>>

    suspend fun getSession(sessionId: String): ViveResult<Session>

    suspend fun endSession(sessionId: String): ViveResult<Session>

    suspend fun getRisk(sessionId: String): ViveResult<RiskSummary>

    /** [sinceSeq] backfills packets missed while the stream was down. */
    suspend fun listPackets(
        sessionId: String,
        sinceSeq: Int? = null,
        limit: Int = 50,
    ): ViveResult<List<Packet>>

    suspend fun getPacket(sessionId: String, packetId: String): ViveResult<Packet>

    suspend fun getTranscript(sessionId: String): ViveResult<List<TranscriptLine>>

    // --- alerts ---

    suspend fun listAlerts(sessionId: String? = null): ViveResult<List<Alert>>

    suspend fun acknowledgeAlert(alertId: String): ViveResult<Alert>

    // --- models ---

    suspend fun listModels(): ViveResult<List<ModelInfo>>
}
