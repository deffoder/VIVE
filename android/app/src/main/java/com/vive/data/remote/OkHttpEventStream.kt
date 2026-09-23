package com.vive.data.remote

import com.vive.core.ViveError
import com.vive.core.ViveLog
import com.vive.data.remote.dto.AlertDto
import com.vive.data.remote.dto.PacketDto
import com.vive.data.remote.dto.RiskUpdateDto
import com.vive.data.remote.dto.ServerFrameDto
import com.vive.data.remote.dto.SessionDto
import com.vive.data.remote.dto.TranscriptLineDto
import com.vive.data.remote.dto.toDomain
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.retryWhen
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.io.IOException
import kotlin.math.min
import kotlin.math.pow

/**
 * OkHttp-backed live session stream.
 *
 * Reconnect strategy: exponential backoff with a cap. The sequence counter
 * lives on the SERVER session, not this socket, so after a reconnect the
 * repository backfills anything missed with `since_seq` rather than assuming
 * continuity (docs/API_SPEC.md 6).
 *
 * The flow never throws into the UI: transport failures surface as
 * [ViveEvent.Failure] and as [StreamState.Reconnecting] / [StreamState.Disconnected].
 */
class OkHttpEventStream(
    private val baseUrl: String,
    private val client: OkHttpClient = NetworkModule.okHttp(),
    private val maxReconnectAttempts: Int = 5,
) : ViveEventStream {

    private val _connectionState = MutableStateFlow<StreamState>(StreamState.Idle)
    override val connectionState: Flow<StreamState> = _connectionState.asStateFlow()

    private val sockets = mutableMapOf<String, WebSocket>()

    override fun observe(sessionId: String): Flow<ViveEvent> = callbackFlow {
        _connectionState.value = StreamState.Connecting

        val url = baseUrl.trimEnd('/')
            .replaceFirst("http://", "ws://")
            .replaceFirst("https://", "wss://") +
            "/api/v1/sessions/$sessionId/stream"

        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _connectionState.value = StreamState.Connected
                ViveLog.d(TAG) { "stream open for $sessionId" }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                parseFrame(sessionId, text)?.let { trySend(it) }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                _connectionState.value = StreamState.Disconnected(ViveError.Offline(cause = t))
                // Close the flow with an IOException so retryWhen can back off.
                close(IOException("websocket failure", t))
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(NORMAL_CLOSE, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                _connectionState.value = StreamState.Disconnected(null)
                close()
            }
        }

        val socket = client.newWebSocket(Request.Builder().url(url).build(), listener)
        sockets[sessionId] = socket

        awaitClose {
            socket.close(NORMAL_CLOSE, "client closed")
            sockets.remove(sessionId)
            _connectionState.value = StreamState.Idle
        }
    }.retryWhen { cause, attempt ->
        if (cause !is IOException || attempt >= maxReconnectAttempts) {
            _connectionState.value = StreamState.Disconnected(ViveError.Offline())
            false
        } else {
            val backoffMs = min(MAX_BACKOFF_MS, (BASE_BACKOFF_MS * 2.0.pow(attempt.toInt())).toLong())
            _connectionState.value = StreamState.Reconnecting(attempt.toInt() + 1)
            ViveLog.d(TAG) { "reconnect attempt ${attempt + 1} in ${backoffMs}ms" }
            delay(backoffMs)
            true
        }
    }

    private fun parseFrame(sessionId: String, text: String): ViveEvent? = try {
        val frame = NetworkModule.json.decodeFromString<ServerFrameDto>(text)
        val data: JsonObject? = frame.data
        when (frame.type) {
            "session.state" -> data?.let {
                ViveEvent.SessionState(
                    sessionId,
                    NetworkModule.json.decodeFromJsonElement<SessionDto>(it).toDomain(),
                )
            }

            "packet.new" -> data?.let {
                val dto = NetworkModule.json.decodeFromJsonElement<PacketDto>(it)
                ViveEvent.PacketNew(sessionId, frame.seq, dto.toDomain())
            }

            "risk.update" -> data?.let {
                val dto = NetworkModule.json.decodeFromJsonElement<RiskUpdateDto>(it)
                val current = dto.currentRisk?.toDomain()
                val overall = dto.overallRisk?.toDomain()
                if (current != null && overall != null) {
                    ViveEvent.RiskUpdate(sessionId, current, overall, dto.timings.toDomain())
                } else null
            }

            "transcript.append" -> data?.let {
                ViveEvent.TranscriptAppend(
                    sessionId,
                    NetworkModule.json.decodeFromJsonElement<TranscriptLineDto>(it).toDomain(),
                )
            }

            "alert.raised" -> data?.let {
                ViveEvent.AlertRaised(
                    sessionId,
                    NetworkModule.json.decodeFromJsonElement<AlertDto>(it).toDomain(),
                )
            }

            "session.ended" -> data?.let {
                ViveEvent.SessionEnded(
                    sessionId,
                    NetworkModule.json.decodeFromJsonElement<SessionDto>(it).toDomain(),
                )
            }

            "error" -> ViveEvent.Failure(
                sessionId,
                ViveError.Unexpected(
                    data?.get("message")?.toString()?.trim('"') ?: "Stream error",
                ),
            )

            // heartbeat and any future frame type: ignored, not an error.
            else -> null
        }
    } catch (e: Exception) {
        // A malformed frame must not tear down the stream.
        ViveLog.w(TAG, "dropping unparseable frame", e)
        null
    }

    /**
     * Sends one window, reporting whether it actually left the device.
     *
     * This returned Unit and used `sockets[sessionId]?.send(...)`, so a
     * missing socket was a silent no-op. The capture counter incremented
     * regardless, and the UI read "89 analysis windows sent to the backend"
     * while the backend had received none - a claim of delivery with nothing
     * behind it. `WebSocket.send` also returns false when the outgoing buffer
     * is full, which was discarded the same way.
     */
    override suspend fun sendAudio(sessionId: String, pcm: ByteArray): Boolean {
        val socket = sockets[sessionId] ?: return false
        return socket.send(pcm.toByteString(0, pcm.size))
    }

    /** Demo/replay: drives the pipeline with a scripted line instead of audio. */
    fun sendTranscript(sessionId: String, transcript: String, speaker: String = "Caller") {
        val frame = NetworkModule.json.encodeToString(
            com.vive.data.remote.dto.ClientAudioFrameDto(
                transcript = transcript,
                speaker = speaker,
            ),
        )
        sockets[sessionId]?.send(frame)
    }

    override suspend fun pause(sessionId: String) = sendControl(sessionId, "client.pause")

    override suspend fun resume(sessionId: String) = sendControl(sessionId, "client.resume")

    override suspend fun close(sessionId: String) {
        sendControl(sessionId, "client.end")
        sockets.remove(sessionId)?.close(NORMAL_CLOSE, "client end")
    }

    private fun sendControl(sessionId: String, type: String) {
        val frame = NetworkModule.json.encodeToString(
            com.vive.data.remote.dto.ClientControlFrameDto(type),
        )
        sockets[sessionId]?.send(frame)
    }

    private companion object {
        const val TAG = "ViveEventStream"
        const val NORMAL_CLOSE = 1000
        const val BASE_BACKOFF_MS = 500L
        const val MAX_BACKOFF_MS = 8_000L
    }
}
