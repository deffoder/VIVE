package com.vive.data.remote.dto

import com.vive.data.model.AasistEvidence
import com.vive.data.model.AdapterMode
import com.vive.data.model.Alert
import com.vive.data.model.AnalysisWindow
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.AsrEvidence
import com.vive.data.model.AudioQuality
import com.vive.data.model.Behavior
import com.vive.data.model.BehaviorEvidence
import com.vive.data.model.ContextEvidence
import com.vive.data.model.EcapaEvidence
import com.vive.data.model.EscalationTimings
import com.vive.data.model.Intent
import com.vive.data.model.IntentEvidence
import com.vive.data.model.ModelInfo
import com.vive.data.model.OodEvidence
import com.vive.data.model.OodState
import com.vive.data.model.Packet
import com.vive.data.model.PacketRisk
import com.vive.data.model.RecommendedAction
import com.vive.data.model.RiskLevel
import com.vive.data.model.RiskSummary
import com.vive.data.model.Session
import com.vive.data.model.SessionStatus
import com.vive.data.model.SourceType
import com.vive.data.model.TranscriptLine

/**
 * DTO to domain mapping.
 *
 * Unknown enum values degrade to a documented fallback rather than throwing, so
 * a newer backend that adds a label cannot crash an older client. That is the
 * reason the domain enums each carry an UNKNOWN-style member.
 */

private inline fun <reified T : Enum<T>> String?.toEnumOr(fallback: T): T =
    this?.let { raw -> enumValues<T>().firstOrNull { it.name.equals(raw, ignoreCase = true) } }
        ?: fallback

fun RiskSummaryDto.toDomain() = RiskSummary(
    score = score,
    level = level.toEnumOr(RiskLevel.LOW),
    confidence = confidence,
)

fun EscalationTimingsDto.toDomain() = EscalationTimings(
    firstAnomalySec = firstAnomalySec,
    firstWarningSec = firstWarningSec,
    firstHighSec = firstHighSec,
    firstCriticalSec = firstCriticalSec,
)

fun SessionDto.toDomain() = Session(
    sessionId = sessionId,
    status = status.toEnumOr(SessionStatus.READY),
    sourceType = sourceType.toEnumOr(SourceType.VOIP),
    startedAt = startedAt,
    durationSec = durationSec,
    packetsProcessed = packetsProcessed,
    language = language,
    currentRisk = currentRisk?.toDomain(),
    overallRisk = overallRisk?.toDomain(),
    timings = timings.toDomain(),
)

fun PacketDto.toDomain() = Packet(
    packetId = packetId,
    timestamp = timestamp,
    durationSec = durationSec,
    language = language,
    quality = quality.toEnumOr(AudioQuality.GOOD),
    aasist = AasistEvidence(
        score = aasist.score,
        status = aasist.status.toEnumOr(AnalyzerStatus.AVAILABLE),
        modelVersion = aasist.modelVersion,
        inferenceMs = aasist.inferenceMs,
    ),
    ecapa = EcapaEvidence(
        status = ecapa.status.toEnumOr(AnalyzerStatus.UNAVAILABLE),
        similarity = ecapa.similarity,
        modelVersion = ecapa.modelVersion,
        inferenceMs = ecapa.inferenceMs,
    ),
    asr = AsrEvidence(
        transcript = asr.transcript,
        confidence = asr.confidence,
        status = asr.status.toEnumOr(AnalyzerStatus.AVAILABLE),
        modelVersion = asr.modelVersion,
        inferenceMs = asr.inferenceMs,
    ),
    intent = IntentEvidence(
        label = intent.label.toEnumOr(Intent.UNKNOWN),
        confidence = intent.confidence,
        status = intent.status.toEnumOr(AnalyzerStatus.AVAILABLE),
        modelVersion = intent.modelVersion,
    ),
    behavior = BehaviorEvidence(
        labels = behavior.labels.mapNotNull { raw ->
            Behavior.entries.firstOrNull { it.name.equals(raw, ignoreCase = true) }
        },
        confidence = behavior.confidence,
        status = behavior.status.toEnumOr(AnalyzerStatus.AVAILABLE),
        modelVersion = behavior.modelVersion,
    ),
    context = ContextEvidence(
        callerVerified = context.callerVerified,
        sessionAuthenticated = context.sessionAuthenticated,
        sourceType = context.sourceType.toEnumOr(SourceType.VOIP),
        requestedAction = context.requestedAction,
        contextRisk = context.contextRisk,
    ),
    risk = PacketRisk(
        score = risk.score,
        level = risk.level.toEnumOr(RiskLevel.LOW),
        confidence = risk.confidence,
        contributions = risk.contributions,
        reasons = risk.reasons,
    ),
    sessionId = sessionId,
    seq = seq,
    window = window?.let { AnalysisWindow(it.startSec, it.endSec) },
    languageConfidence = languageConfidence,
    ood = ood?.let {
        OodEvidence(it.state.toEnumOr(OodState.UNAVAILABLE), it.uncertainty)
    },
)

/** True when the backend produced this packet with demo adapters. */
fun PacketDto.isDemo(): Boolean = adapterMode?.equals("mock", ignoreCase = true) == true

fun TranscriptLineDto.toDomain() = TranscriptLine(
    packetId = packetId,
    speaker = speaker,
    text = text,
    language = language,
    confidence = confidence,
    timestamp = timestamp,
)

fun AlertDto.toDomain() = Alert(
    alertId = alertId,
    sessionId = sessionId,
    level = level.toEnumOr(RiskLevel.LOW),
    raisedAt = raisedAt,
    reason = reason,
    packetId = packetId,
    intent = intent?.toEnumOr(Intent.UNKNOWN),
    recommendedAction = recommendedAction?.toEnumOr(RecommendedAction.MONITOR),
    acknowledged = acknowledged,
)

fun ModelInfoDto.toDomain() = ModelInfo(
    id = id,
    displayName = displayName,
    purpose = purpose,
    version = version,
    mode = if (mode.equals("real", ignoreCase = true)) AdapterMode.REAL else AdapterMode.MOCK,
    status = status.toEnumOr(AnalyzerStatus.UNAVAILABLE),
    lastUpdated = lastUpdated,
)

fun ReadyDto.hasMockAdapter(): Boolean =
    adapters.values.any { it.mode.equals("mock", ignoreCase = true) }
