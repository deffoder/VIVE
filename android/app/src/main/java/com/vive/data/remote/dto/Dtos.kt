package com.vive.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Wire DTOs.
 *
 * Deliberately separate from the domain models in `data/model/`. The backend
 * speaks snake_case and may add fields; the domain layer should not carry
 * serialization annotations or tolerate unknown keys. Mappers in `Mappers.kt`
 * bridge the two.
 *
 * Every field the backend marks optional is nullable here, so a response that
 * omits an extension never fails to parse (docs/API_SPEC.md 4.1).
 */

@Serializable
data class CreateSessionRequestDto(
    @SerialName("source_type") val sourceType: String = "VOIP",
    val language: String = "auto",
    val context: SessionContextDto = SessionContextDto(),
)

@Serializable
data class SessionContextDto(
    @SerialName("caller_verified") val callerVerified: Boolean = false,
    @SerialName("session_authenticated") val sessionAuthenticated: Boolean = false,
    @SerialName("requested_action") val requestedAction: String? = null,
    @SerialName("source_type") val sourceType: String? = null,
)

@Serializable
data class CreateSessionResponseDto(
    @SerialName("session_id") val sessionId: String,
    val status: String,
    @SerialName("stream_path") val streamPath: String,
    @SerialName("expires_in") val expiresIn: Int = 3600,
)

@Serializable
data class RiskSummaryDto(
    val score: Int,
    val level: String,
    val confidence: Double,
)

@Serializable
data class EscalationTimingsDto(
    @SerialName("first_anomaly_sec") val firstAnomalySec: Int? = null,
    @SerialName("first_warning_sec") val firstWarningSec: Int? = null,
    @SerialName("first_high_sec") val firstHighSec: Int? = null,
    @SerialName("first_critical_sec") val firstCriticalSec: Int? = null,
)

@Serializable
data class SessionDto(
    @SerialName("session_id") val sessionId: String,
    val status: String,
    @SerialName("source_type") val sourceType: String,
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("ended_at") val endedAt: String? = null,
    @SerialName("duration_sec") val durationSec: Int = 0,
    @SerialName("packets_processed") val packetsProcessed: Int = 0,
    val language: String? = null,
    @SerialName("current_risk") val currentRisk: RiskSummaryDto? = null,
    @SerialName("overall_risk") val overallRisk: RiskSummaryDto? = null,
    val timings: EscalationTimingsDto = EscalationTimingsDto(),
    val context: SessionContextDto = SessionContextDto(),
)

@Serializable
data class AasistDto(
    val score: Double? = null,
    val status: String = "AVAILABLE",
    @SerialName("model_version") val modelVersion: String? = null,
    @SerialName("inference_ms") val inferenceMs: Long? = null,
)

@Serializable
data class EcapaDto(
    val status: String,
    val similarity: Double? = null,
    @SerialName("model_version") val modelVersion: String? = null,
    @SerialName("inference_ms") val inferenceMs: Long? = null,
)

@Serializable
data class AsrDto(
    val transcript: String? = null,
    val confidence: Double? = null,
    val status: String = "AVAILABLE",
    @SerialName("model_version") val modelVersion: String? = null,
    @SerialName("inference_ms") val inferenceMs: Long? = null,
)

@Serializable
data class IntentDto(
    val label: String,
    val confidence: Double? = null,
    val status: String = "AVAILABLE",
    @SerialName("model_version") val modelVersion: String? = null,
)

@Serializable
data class BehaviorDto(
    val labels: List<String> = emptyList(),
    val confidence: Double? = null,
    val status: String = "AVAILABLE",
    @SerialName("model_version") val modelVersion: String? = null,
)

@Serializable
data class ContextDto(
    @SerialName("caller_verified") val callerVerified: Boolean,
    @SerialName("session_authenticated") val sessionAuthenticated: Boolean? = null,
    @SerialName("source_type") val sourceType: String? = null,
    @SerialName("requested_action") val requestedAction: String? = null,
    @SerialName("context_risk") val contextRisk: Double? = null,
)

@Serializable
data class OodDto(
    val state: String,
    val uncertainty: Double? = null,
)

@Serializable
data class WindowDto(
    @SerialName("start_sec") val startSec: Double,
    @SerialName("end_sec") val endSec: Double,
)

@Serializable
data class PacketRiskDto(
    val score: Int,
    val level: String,
    val confidence: Double,
    val contributions: Map<String, Double> = emptyMap(),
    val reasons: List<String> = emptyList(),
)

@Serializable
data class PacketDto(
    @SerialName("packet_id") val packetId: String,
    val timestamp: String,
    @SerialName("duration_sec") val durationSec: Int,
    val language: String,
    val quality: String,
    val aasist: AasistDto,
    val ecapa: EcapaDto,
    val asr: AsrDto,
    val intent: IntentDto,
    val behavior: BehaviorDto,
    val context: ContextDto,
    val risk: PacketRiskDto,
    @SerialName("session_id") val sessionId: String? = null,
    val seq: Int? = null,
    val window: WindowDto? = null,
    @SerialName("language_confidence") val languageConfidence: Double? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val ood: OodDto? = null,
    @SerialName("adapter_mode") val adapterMode: String? = null,
)

@Serializable
data class TranscriptLineDto(
    @SerialName("packet_id") val packetId: String,
    val speaker: String,
    val text: String,
    val language: String? = null,
    val confidence: Double? = null,
    val timestamp: String? = null,
)

@Serializable
data class AlertDto(
    @SerialName("alert_id") val alertId: String,
    @SerialName("session_id") val sessionId: String,
    val level: String,
    @SerialName("raised_at") val raisedAt: String,
    val reason: String,
    @SerialName("packet_id") val packetId: String? = null,
    val intent: String? = null,
    @SerialName("recommended_action") val recommendedAction: String? = null,
    val acknowledged: Boolean = false,
)

@Serializable
data class AdapterStateDto(val status: String, val mode: String)

@Serializable
data class ReadyDto(
    val ready: Boolean,
    @SerialName("api_version") val apiVersion: String,
    val adapters: Map<String, AdapterStateDto> = emptyMap(),
)

@Serializable
data class ModelInfoDto(
    val id: String,
    @SerialName("display_name") val displayName: String,
    val purpose: String,
    val version: String,
    val mode: String,
    val status: String,
    @SerialName("last_updated") val lastUpdated: String? = null,
)

@Serializable
data class ErrorBodyDto(
    val code: String,
    val message: String,
    val detail: String? = null,
    @SerialName("request_id") val requestId: String? = null,
)

@Serializable
data class ErrorResponseDto(val error: ErrorBodyDto)

// ------------------------------------------------------------- WS envelopes

@Serializable
data class ServerFrameDto(
    val type: String,
    @SerialName("session_id") val sessionId: String,
    val seq: Int,
    val data: kotlinx.serialization.json.JsonObject? = null,
)

@Serializable
data class ClientAudioFrameDto(
    val type: String = "client.audio",
    val transcript: String? = null,
    val speaker: String? = null,
    @SerialName("audio_b64") val audioB64: String? = null,
)

@Serializable
data class ClientControlFrameDto(val type: String)

@Serializable
data class RiskUpdateDto(
    @SerialName("current_risk") val currentRisk: RiskSummaryDto? = null,
    @SerialName("overall_risk") val overallRisk: RiskSummaryDto? = null,
    val timings: EscalationTimingsDto = EscalationTimingsDto(),
    @SerialName("packets_processed") val packetsProcessed: Int = 0,
    @SerialName("duration_sec") val durationSec: Int = 0,
)
