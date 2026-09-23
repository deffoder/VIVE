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

    private val remoteAlerts: RemoteAlertRepository by lazy {
        RemoteAlertRepository(service)
    }

    private val remoteModels: RemoteModelRepository by lazy {
        RemoteModelRepository(service)
    }

    var sessions: SessionRepository = fallbackSessions
        internal set

    /**
     * Alerts come from the backend's policy engine, never from a demo list.
     *
     * This was wired to `DemoAlertRepository`, so the Alerts screen showed
     * invented alerts naming sessions that never happened - indistinguishable
     * on screen from real policy output. An unreachable backend now yields an
     * honest error or empty state instead.
     */
    var alerts: AlertRepository = remoteAlerts
        internal set

    /**
     * Model status comes from `/api/v1/ready` and `/api/v1/models`.
     *
     * Also previously a demo repository, which meant the Model Information
     * screen reported adapters as AVAILABLE without anything having loaded -
     * the exact claim that screen exists to substantiate.
     */
    var models: ModelRepository = remoteModels
        internal set

    /**
     * True while demo data is on screen.
     *
     * Was hard-coded `true`, which was correct while every backend adapter was
     * also a mock. It is no longer correct: with the backend in real mode the
     * badge claimed real inference was demo data, which is the same class of
     * error as the reverse and just as misleading to a viewer.
     *
     * It now reports what was actually observed. [observeAdapterMode] is fed
     * from each packet's `adapter_mode`, so the badge follows the evidence on
     * screen rather than a build-time assumption. It stays `true` until a real
     * packet proves otherwise: defaulting to "this is demo data" is the safe
     * direction, because the failure mode is understating the product rather
     * than overstating it.
     */
    val isDemo: Boolean
        get() = usingOfflineFallback || lastAdapterModeWasMock

    @Volatile
    private var lastAdapterModeWasMock: Boolean = true

    /**
     * Records the adapter mode carried by a packet that reached the UI.
     *
     * Called from the mapper as packets arrive, so it reflects the pipeline
     * that actually produced what is on screen.
     */
    fun observeAdapterMode(isMock: Boolean) {
        lastAdapterModeWasMock = isMock
    }

    /** True specifically because the backend could not be reached. */
    val usingOfflineFallback: Boolean
        get() = (sessions as? FallbackSessionRepository)?.usingFallback ?: false

    /** Drives the scripted demo/replay path against a live backend. */
    fun sendDemoTranscript(sessionId: String, text: String, speaker: String = "Caller") {
        remoteSessions.sendTranscript(sessionId, text, speaker)
    }

    /**
     * Sends one captured analysis window to the backend.
     *
     * Deliberately routed through [remoteSessions] rather than [sessions]: the
     * live capture path must reach the real backend or fail visibly. Sending
     * real microphone audio into a demo repository would produce scripted
     * results that look like analysis of what the user just said, which is the
     * one outcome this project must never produce.
     */
    suspend fun sendAudio(sessionId: String, pcm: ByteArray): Boolean =
        remoteSessions.sendAudio(sessionId, pcm)

    /** Enrols a reference voice so speaker comparison can run at all (O3). */
    suspend fun enrolSpeaker(sessionId: String, pcm: ByteArray, label: String? = null) =
        remoteSessions.enrolSpeaker(sessionId, pcm, label)

    suspend fun clearEnrolment(sessionId: String) =
        remoteSessions.clearEnrolment(sessionId)

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
        alerts = remoteAlerts
        models = remoteModels
    }

    /**
     * Demo data only, with no network attempt.
     *
     * NOT the production path and never selected automatically: it exists for
     * rehearsing a demo with no backend present, and anything it serves is
     * badged as demo data. Nothing in the app calls it.
     */
    fun useDemoOnly() {
        sessions = DemoSessionRepository()
        alerts = DemoAlertRepository()
        models = DemoModelRepository()
    }

    /** Uses the backend exclusively, with no demo fallback. */
    fun useBackendOnly() {
        sessions = remoteSessions
        alerts = remoteAlerts
        models = remoteModels
    }
}
