package com.vive.core

import com.vive.BuildConfig
import com.vive.data.demo.DemoAlertRepository
import com.vive.data.demo.DemoModelRepository
import com.vive.data.demo.DemoSessionRepository
import com.vive.data.remote.NetworkModule
import com.vive.data.remote.OkHttpEventStream
import com.vive.data.remote.ViveService
import com.vive.data.repository.AlertRepository
import com.vive.data.repository.FallbackSessionRepository
import com.vive.data.repository.ModelRepository
import com.vive.data.repository.RemoteAlertRepository
import com.vive.data.repository.RemoteModelRepository
import com.vive.data.repository.RemoteSessionRepository
import com.vive.data.repository.SessionRepository

/**
 * Minimal dependency provider.
 *
 * A DI framework would be an unnecessary dependency at this stage
 * (CLAUDE.md: simplest architecture that satisfies the requirements). This is
 * the single place that decides which repository implementation the app uses.
 *
 * Default wiring is **backend-first with a demo fallback**: live data when the
 * backend answers, demo data when it is unreachable. The fallback is never
 * silent - [isDemo] drives the non-dismissable "Demo data" badge, so a viewer
 * always knows which source is on screen (docs/UI_SPEC.md 6).
 */
object ServiceLocator {

    private val service: ViveService by lazy {
        NetworkModule.service(BuildConfig.API_BASE_URL)
    }

    private val eventStream: OkHttpEventStream by lazy {
        OkHttpEventStream(BuildConfig.API_BASE_URL)
    }

    private val remoteSessions: RemoteSessionRepository by lazy {
        RemoteSessionRepository(service, eventStream)
    }

    private val fallbackSessions: FallbackSessionRepository by lazy {
        FallbackSessionRepository(remoteSessions, DemoSessionRepository())
    }

    var sessions: SessionRepository = fallbackSessions
        internal set

    var alerts: AlertRepository = DemoAlertRepository()
        internal set

    var models: ModelRepository = DemoModelRepository()
        internal set

    /**
     * True while demo data is on screen.
     *
     * In this build every backend adapter is also a mock, so this stays true
     * whether the data came from the demo repository or from the backend's mock
     * adapters. It only becomes false once real adapters report `mode: "real"`.
     */
    val isDemo: Boolean
        get() = true

    /** True specifically because the backend could not be reached. */
    val usingOfflineFallback: Boolean
        get() = (sessions as? FallbackSessionRepository)?.usingFallback ?: false

    /** Drives the scripted demo/replay path against a live backend. */
    fun sendDemoTranscript(sessionId: String, text: String, speaker: String = "Caller") {
        remoteSessions.sendTranscript(sessionId, text, speaker)
    }

    suspend fun closeStream(sessionId: String) {
        remoteSessions.closeStream(sessionId)
    }

    /** Test seam: swap implementations, then call [reset]. */
    fun override(
        sessions: SessionRepository = this.sessions,
        alerts: AlertRepository = this.alerts,
        models: ModelRepository = this.models,
    ) {
        this.sessions = sessions
        this.alerts = alerts
        this.models = models
    }

    fun reset() {
        sessions = fallbackSessions
        alerts = DemoAlertRepository()
        models = DemoModelRepository()
    }

    /** Uses demo data only, with no network attempt. Useful for offline demos. */
    fun useDemoOnly() {
        sessions = DemoSessionRepository()
        alerts = DemoAlertRepository()
        models = DemoModelRepository()
    }

    /** Uses the backend exclusively, with no demo fallback. */
    fun useBackendOnly() {
        sessions = remoteSessions
        alerts = RemoteAlertRepository(service)
        models = RemoteModelRepository(service)
    }
}
