package com.vive.ondevice.engine

import com.vive.audio.AudioPacket
import com.vive.core.ViveError
import com.vive.core.ViveLog
import com.vive.core.ViveResult
import com.vive.data.local.SessionStore
import com.vive.data.remote.ViveEvent
import com.vive.data.remote.dto.SessionContextDto
import com.vive.data.remote.dto.SessionDto
import com.vive.data.remote.dto.toDomain
import com.vive.ondevice.CtcDecoder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/**
 * Runs VIVE's analysis on the phone.
 *
 *   microphone window -> queue -> [AnalysisPipeline] on one inference thread
 *     -> SQLite (atomic per window) -> ViveEvents to the UI
 *
 * One inference thread for all sessions: ONNX Runtime already spreads each
 * model over the big cores, and the backend measured that running analyzers
 * concurrently makes every stage slower (session_manager.py). The queue per
 * session is small and bounded; when analysis falls behind real time the
 * newest window is refused and the caller counts it as dropped, rather than
 * a backlog growing until results describe audio from minutes ago.
 *
 * Events are emitted only AFTER the window is persisted, so a screen that
 * backfills from the store after a gap can never miss what it was told about.
 */
class OnDeviceEngine(
    private val store: SessionStore,
    private val analyzers: Analyzers,
) {
    private val inference = Executors.newSingleThreadExecutor { r -> Thread(r, "vive-inference") }
        .asCoroutineDispatcher()
    private val scope = CoroutineScope(SupervisorJob() + inference)

    private val pipeline = AnalysisPipeline(analyzers, clock = ::now, nextAlertId = {
        "AL-%03d".format(store.next("alert"))
    })

    private class Live(val runtime: SessionRuntime, val queue: Channel<AudioPacket>, var worker: Job? = null)

    private val live = ConcurrentHashMap<String, Live>()

    private val _events = MutableSharedFlow<ViveEvent>(extraBufferCapacity = 256)
    val events: SharedFlow<ViveEvent> = _events.asSharedFlow()

    init {
        // A session still STREAMING at start-up belonged to a process that
        // died mid-call. Its audio is gone, so it cannot resume; it is closed
        // as it stands rather than left looking live forever.
        runCatching {
            store.unfinishedSessions().forEach {
                store.upsertSession(it.copy(status = "ENDED", endedAt = it.endedAt ?: now()))
            }
        }
    }

    fun createSession(sourceType: String, language: String): SessionDto {
        val id = "S-%04d".format(store.next("session"))
        val session = SessionDto(
            sessionId = id, status = "READY", sourceType = sourceType, startedAt = now(),
            language = language, context = SessionContextDto(sourceType = sourceType),
        )
        store.upsertSession(session)
        val entry = Live(SessionRuntime(session, language), Channel(QUEUE))
        live[id] = entry
        entry.worker = scope.launch {
            for (window in entry.queue) process(entry, window)
        }
        return session
    }

    private suspend fun process(entry: Live, window: AudioPacket) {
        val outcome = try {
            pipeline.process(entry.runtime, CtcDecoder.pcmToFloat(window.pcm), window.startSec, window.endSec)
        } catch (e: Exception) {
            ViveLog.e(TAG, "window failed: ${e::class.simpleName}")
            return
        }
        store.appendWindow(outcome.packet, outcome.session, outcome.transcript, outcome.alert)
        val id = outcome.session.sessionId
        _events.emit(ViveEvent.PacketNew(id, outcome.packet.seq ?: 0, outcome.packet.toDomain()))
        val s = outcome.session.toDomain()
        _events.emit(ViveEvent.RiskUpdate(id, s.currentRisk!!, s.overallRisk!!, s.timings))
        outcome.transcript?.let { _events.emit(ViveEvent.TranscriptAppend(id, it.toDomain())) }
        outcome.alert?.let { _events.emit(ViveEvent.AlertRaised(id, it.toDomain())) }
    }

    /**
     * Queues one captured window. False means it was NOT analysed - the
     * session is not live, or analysis is behind real time - and the caller
     * must not count it as processed.
     */
    fun submit(sessionId: String, window: AudioPacket): Boolean =
        live[sessionId]?.queue?.trySend(window)?.isSuccess ?: false

    fun isLive(sessionId: String) = live.containsKey(sessionId)

    /** Ends a session after analysing every window already queued. */
    suspend fun end(sessionId: String): ViveResult<SessionDto> {
        val entry = live.remove(sessionId)
        if (entry != null) {
            entry.queue.close()
            entry.worker?.join()
            entry.runtime.reference = null
        }
        val stored = store.session(sessionId) ?: return ViveResult.Failure(ViveError.NotFound("session $sessionId"))
        if (stored.status == "ENDED") return ViveResult.Success(stored)
        val ended = stored.copy(status = "ENDED", endedAt = now())
        store.upsertSession(ended)
        _events.emit(ViveEvent.SessionEnded(sessionId, ended.toDomain()))
        return ViveResult.Success(ended)
    }

    /**
     * Embeds a reference voice for this session and keeps only the embedding,
     * in memory. The audio is discarded here and the voiceprint is never
     * written to disk (docs/SECURITY_SPEC.md 4).
     */
    suspend fun enrol(sessionId: String, pcm: ByteArray, embed: (FloatArray) -> FloatArray?): ViveResult<String> {
        val entry = live[sessionId] ?: return ViveResult.Failure(ViveError.NotFound("live session $sessionId"))
        val embedding = withContext(inference) { embed(CtcDecoder.pcmToFloat(pcm)) }
            ?: return ViveResult.Failure(
                ViveError.Validation("Enrolment needs at least 3 seconds of clear speech."),
            )
        withContext(inference) { entry.runtime.reference = embedding }
        return ViveResult.Success("Reference voice enrolled for this session.")
    }

    suspend fun clearEnrolment(sessionId: String): ViveResult<String> {
        val entry = live[sessionId] ?: return ViveResult.Failure(ViveError.NotFound("live session $sessionId"))
        withContext(inference) { entry.runtime.reference = null }
        return ViveResult.Success("Reference voice removed.")
    }

    fun isEnrolled(sessionId: String): Boolean = live[sessionId]?.runtime?.reference != null

    companion object {
        private const val TAG = "OnDeviceEngine"
        /** Windows allowed to wait. Two seconds of backlog at the 1 s stride. */
        const val QUEUE = 2

        fun now(): String = Instant.now().truncatedTo(ChronoUnit.SECONDS).toString()
    }
}
