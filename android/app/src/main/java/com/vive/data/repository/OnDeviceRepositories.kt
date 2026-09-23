package com.vive.data.repository

import com.vive.core.ViveError
import com.vive.core.ViveResult
import com.vive.data.local.SessionStore
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
import com.vive.data.remote.dto.toDomain
import com.vive.ondevice.engine.OnDeviceAnalyzers
import com.vive.ondevice.engine.OnDeviceEngine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.withContext

/**
 * Sessions analysed on the phone, persisted in [SessionStore].
 *
 * Same interface and the same events as the backend repository, so every
 * screen works unchanged. There is no network in this path at all.
 */
class OnDeviceSessionRepository(
    private val engine: OnDeviceEngine,
    private val store: SessionStore,
    private val defaultLanguage: () -> String,
) : SessionRepository {

    private suspend fun <T> io(block: () -> T): T = withContext(Dispatchers.IO) { block() }

    override suspend fun createSession(sourceType: SourceType, language: String?): ViveResult<Session> = io {
        val lang = language?.takeIf { it != "auto" } ?: defaultLanguage()
        ViveResult.Success(engine.createSession(sourceType.name, lang).toDomain())
    }

    override suspend fun getSession(sessionId: String): ViveResult<Session> = io {
        store.session(sessionId)?.let { ViveResult.Success(it.toDomain()) }
            ?: ViveResult.Failure(ViveError.NotFound("No session $sessionId on this phone"))
    }

    override suspend fun listSessions(limit: Int): ViveResult<List<Session>> = io {
        ViveResult.Success(store.sessions(limit).map { it.toDomain() })
    }

    override suspend fun endSession(sessionId: String): ViveResult<Session> =
        when (val r = engine.end(sessionId)) {
            is ViveResult.Success -> ViveResult.Success(r.data.toDomain())
            is ViveResult.Failure -> r
        }

    override suspend fun listPackets(sessionId: String, sinceSeq: Int?): ViveResult<List<Packet>> = io {
        ViveResult.Success(store.packets(sessionId, sinceSeq).map { it.toDomain() })
    }

    override suspend fun getPacket(sessionId: String, packetId: String): ViveResult<Packet> = io {
        store.packet(sessionId, packetId)?.let { ViveResult.Success(it.toDomain()) }
            ?: ViveResult.Failure(ViveError.NotFound("No packet $packetId"))
    }

    override suspend fun getTranscript(sessionId: String): ViveResult<List<TranscriptLine>> = io {
        ViveResult.Success(store.transcript(sessionId).map { it.toDomain() })
    }

    override fun observeSession(sessionId: String): Flow<ViveEvent> =
        engine.events.filter { it.sessionId == sessionId }

    /** Nothing to connect to: analysis is local, so the "stream" is always up. */
    override val connectionState: Flow<StreamState> = flowOf(StreamState.Connected)
}

class OnDeviceAlertRepository(private val store: SessionStore) : AlertRepository {

    override suspend fun listAlerts(sessionId: String?): ViveResult<List<Alert>> = withContext(Dispatchers.IO) {
        ViveResult.Success(store.alerts(sessionId).map { it.toDomain() })
    }

    override suspend fun acknowledge(alertId: String): ViveResult<Alert> = withContext(Dispatchers.IO) {
        store.acknowledge(alertId)?.let { ViveResult.Success(it.toDomain()) }
            ?: ViveResult.Failure(ViveError.NotFound("No alert $alertId"))
    }
}

/**
 * The phone's model inventory.
 *
 * [listModels] LOADS each model before reporting it AVAILABLE: this screen
 * exists to substantiate that claim, so a provisioned file that fails to
 * load must read LOAD_ERROR, not AVAILABLE. [ready] only checks
 * provisioning, because it runs at start-up and must stay cheap.
 */
class OnDeviceModelRepository(private val analyzers: OnDeviceAnalyzers) : ModelRepository {

    override suspend fun listModels(): ViveResult<List<ModelInfo>> = withContext(Dispatchers.IO) {
        val a = analyzers
        fun status(ok: Boolean) = if (ok) AnalyzerStatus.AVAILABLE else AnalyzerStatus.LOAD_ERROR
        val models = mutableListOf(
            ModelInfo("silero-vad", "Silero VAD", "Speech detection and audio quality",
                a.vadModel.version ?: "silero-vad-v5-onnx", AdapterMode.REAL, status(a.vadModel.load())),
        )
        for (lang in listOf("hi", "ta", "en")) {
            val spec = a.asrModel.spec(lang)
            val ok = a.asrModel.unavailableReason(lang) == null
            models += ModelInfo(
                "asr-$lang", "Speech recognition (${LANGUAGE_NAMES[lang]})",
                "wav2vec2 CTC transcription, ${spec?.license ?: "unprovisioned"}",
                spec?.let { com.vive.ondevice.OnDeviceAsr.version(it) } ?: "not provisioned",
                AdapterMode.REAL, if (spec == null) AnalyzerStatus.UNAVAILABLE else status(ok),
            )
        }
        val text = a.textModel.load() == com.vive.ondevice.OnDeviceText.Status.AVAILABLE
        models += ModelInfo("intent-classifier", "Intent classifier", "Request type in the transcript (en, hi, Hinglish)",
            a.textModel.intentVersion ?: "not provisioned", AdapterMode.REAL, status(text))
        models += ModelInfo("behavior-classifier", "Behaviour classifier", "Social-engineering cues (en, hi, Hinglish)",
            a.textModel.behaviorVersion ?: "not provisioned", AdapterMode.REAL, status(text))
        models += ModelInfo("ecapa-tdnn", "Speaker verification", "Consistency with an enrolled voice",
            a.speakerModel.version ?: "not provisioned", AdapterMode.REAL, status(a.speakerModel.load()))
        val spoofLoaded = a.spoofModel.load()
        models += ModelInfo(
            "antispoof", "Synthetic-voice indicators",
            if (a.spoofModel.validated) "wav2vec2 anti-spoofing, validated on handset audio"
            else "Not used: not validated on audio recorded through a phone",
            a.spoofModel.spec?.version ?: "not provisioned", AdapterMode.REAL,
            when {
                !spoofLoaded -> AnalyzerStatus.LOAD_ERROR
                !a.spoofModel.validated -> AnalyzerStatus.UNAVAILABLE
                else -> AnalyzerStatus.AVAILABLE
            },
        )
        ViveResult.Success(models)
    }

    override suspend fun ready(): ViveResult<ReadyState> = withContext(Dispatchers.IO) {
        val asr = listOf("hi", "ta", "en").associate { "asr-$it" to (analyzersAsrOk(it)) }
        val adapters = asr.mapValues { (_, ok) ->
            AdapterState(if (ok) AnalyzerStatus.AVAILABLE else AnalyzerStatus.UNAVAILABLE, AdapterMode.REAL)
        }
        ViveResult.Success(ReadyState(ready = asr.values.any { it }, apiVersion = "on-device", adapters = adapters))
    }

    private fun analyzersAsrOk(lang: String) = analyzers.asrModel.unavailableReason(lang) == null

    companion object {
        val LANGUAGE_NAMES = mapOf("hi" to "Hindi", "ta" to "Tamil", "en" to "English")
    }
}
