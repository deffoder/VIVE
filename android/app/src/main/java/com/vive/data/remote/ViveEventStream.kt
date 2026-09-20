package com.vive.data.remote

import kotlinx.coroutines.flow.Flow

/**
 * Live session stream. Mirrors WS /api/v1/sessions/{id}/stream
 * (docs/API_SPEC.md 6).
 *
 * Interface only in Phase 1; an OkHttp-backed implementation lands in Phase 5.
 *
 * Implementations are responsible for reconnect with backoff and for reporting
 * [connectionState] so the UI can distinguish Offline from Error. They must NOT
 * silently drop events - a sequence gap is surfaced so the caller can backfill.
 */
interface ViveEventStream {

    /** Emits typed events for the session until the flow is cancelled. */
    fun observe(sessionId: String): Flow<ViveEvent>

    /** Transport state, independent of event content. */
    val connectionState: Flow<StreamState>

    /**
     * Sends a captured audio chunk upstream.
     * Expected format: 16 kHz mono pcm_s16le (docs/ML_SPEC.md 5).
     */
    suspend fun sendAudio(sessionId: String, pcm: ByteArray)

    suspend fun pause(sessionId: String)

    suspend fun resume(sessionId: String)

    suspend fun close(sessionId: String)
}
