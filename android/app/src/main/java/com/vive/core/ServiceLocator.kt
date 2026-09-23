package com.vive.core

import android.content.Context
import com.vive.BuildConfig
import com.vive.alerts.AlertNotifier
import com.vive.data.demo.DemoAlertRepository
import com.vive.data.model.Alert
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
import com.vive.audio.AudioPacket
import com.vive.data.local.SessionStore
import com.vive.data.repository.OnDeviceAlertRepository
import com.vive.data.repository.OnDeviceModelRepository
import com.vive.data.repository.OnDeviceSessionRepository
import com.vive.ondevice.OnDeviceRuntime
import com.vive.ondevice.engine.OnDeviceAnalyzers
import com.vive.ondevice.engine.OnDeviceEngine

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

    /** True when every model runs on the phone and no network is used. */
    val onDevice: Boolean get() = BuildConfig.ANALYSIS_MODE == "on-device"

    private var engine: OnDeviceEngine? = null
    var analyzers: OnDeviceAnalyzers? = null
        private set
    private var onDeviceSessions: SessionRepository? = null
    private var onDeviceAlerts: AlertRepository? = null
    private var onDeviceModels: ModelRepository? = null
    private var prefs: android.content.SharedPreferences? = null

    /**
     * Builds the on-device stack. Called once from the Application. Model
     * files are not loaded here - each loads on first use - so start-up
     * stays fast and a missing model is reported where it is used.
     */
    fun initOnDevice(context: Context) {
        if (!onDevice || engine != null) return
        val app = context.applicationContext
        prefs = app.getSharedPreferences("vive", Context.MODE_PRIVATE)
        val store = SessionStore(app)
        val a = OnDeviceAnalyzers(OnDeviceRuntime.modelDir(app))
        val e = OnDeviceEngine(store, a)
        analyzers = a
        engine = e
        onDeviceSessions = OnDeviceSessionRepository(e, store) { analysisLanguage }
        onDeviceAlerts = OnDeviceAlertRepository(store)
        onDeviceModels = OnDeviceModelRepository(a)
        sessions = onDeviceSessions!!
        alerts = onDeviceAlerts!!
        models = onDeviceModels!!
        // Every packet on this path comes from real models on the phone.
        observeAdapterMode(false)
    }

    /**
     * The language the caller will speak. The phone runs one ASR model per
     * language and has no language identification, so this is declared.
     */
    var analysisLanguage: String
        get() = prefs?.getString("analysis_language", "hi") ?: "hi"
        set(value) { prefs?.edit()?.putString("analysis_language", value)?.apply() }

    fun speakerThreshold(): Double? = analyzers?.speakerModel?.let { it.load(); it.threshold }

    fun isEnrolled(sessionId: String): Boolean = engine?.isEnrolled(sessionId) ?: false

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

    // --- alert delivery -------------------------------------------------

    private var appContext: Context? = null

    /**
     * Supplies the application context used to post alert notifications.
     *
     * Held as the APPLICATION context, never an Activity: an alert has to
     * survive the user leaving the app, which is the situation that makes a
     * notification worth posting at all. An Activity reference here would
     * both leak and be gone exactly when it is needed.
     */
    fun attachAlertDelivery(context: Context) {
        appContext = context.applicationContext
    }

    /**
     * Posts [alert] to the system, returning whether it was actually
     * delivered.
     *
     * False is a real answer, not an error: LOW alerts never interrupt, and
     * the user may have denied notifications. A caller that assumed delivery
     * would be claiming the user was warned when they were not.
     */
    fun deliverAlert(alert: Alert): Boolean {
        val context = appContext ?: return false
        return AlertNotifier.notify(context, alert)
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

    /**
     * Hands one captured window to analysis: the on-device engine, or the
     * backend. False means the window was not analysed and must not be
     * counted as if it were.
     */
    suspend fun submitWindow(sessionId: String, packet: AudioPacket): Boolean =
        engine?.submit(sessionId, packet) ?: sendAudio(sessionId, packet.pcm)

    /** Enrols a reference voice so speaker comparison can run at all (O3). */
    suspend fun enrolSpeaker(sessionId: String, pcm: ByteArray, label: String? = null): ViveResult<String> {
        val e = engine ?: return remoteSessions.enrolSpeaker(sessionId, pcm, label)
        val speaker = analyzers!!.speakerModel
        return e.enrol(sessionId, pcm) { speaker.enrol(it) }
    }

    suspend fun clearEnrolment(sessionId: String): ViveResult<String> =
        engine?.clearEnrolment(sessionId) ?: remoteSessions.clearEnrolment(sessionId)

    suspend fun closeStream(sessionId: String) {
        if (engine == null) remoteSessions.closeStream(sessionId)
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
        sessions = onDeviceSessions ?: fallbackSessions
        alerts = onDeviceAlerts ?: remoteAlerts
        models = onDeviceModels ?: remoteModels
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
