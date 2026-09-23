package com.vive.data.model

/**
 * A monitored call. Mirrors docs/API_SPEC.md 3.2.
 *
 * [currentRisk] is the latest packet's reading; [overallRisk] is the aggregate
 * for the call so far. Both are shown (CLAUDE.md, Overall Call Analysis).
 */
data class Session(
    val sessionId: String,
    val status: SessionStatus,
    val sourceType: SourceType,
    val startedAt: String? = null,
    val durationSec: Int = 0,
    val packetsProcessed: Int = 0,
    val language: String? = null,
    val currentRisk: RiskSummary? = null,
    val overallRisk: RiskSummary? = null,
    val timings: EscalationTimings = EscalationTimings(),
) {
    /**
     * Highest level any packet reached, from the escalation timings (packet
     * score thresholds 35 / 65 / 85). [overallRisk] is a smoothed average and
     * is the wrong headline for a finished call: a call where the caller asked
     * for a password once scored 74 HIGH on that packet and averaged 23 LOW.
     * Null when nothing was analysed.
     */
    val peakLevel: RiskLevel?
        get() = when {
            timings.firstCriticalSec != null -> RiskLevel.CRITICAL
            timings.firstHighSec != null -> RiskLevel.HIGH
            timings.firstWarningSec != null -> RiskLevel.MEDIUM
            packetsProcessed > 0 -> RiskLevel.LOW
            else -> null
        }
}

/** Risk score, level and confidence as a unit. Score and confidence stay distinct. */
data class RiskSummary(
    val score: Int,
    val level: RiskLevel,
    val confidence: Double,
)

/**
 * When the call first crossed each threshold, in seconds from start.
 * Null means "not reached" - which is information, not a missing value.
 */
data class EscalationTimings(
    val firstAnomalySec: Int? = null,
    val firstWarningSec: Int? = null,
    val firstHighSec: Int? = null,
    val firstCriticalSec: Int? = null,
)

/** One line of transcript. Sensitive; never logged, never sent in webhooks. */
data class TranscriptLine(
    val packetId: String,
    val speaker: String,
    val text: String,
    val language: String? = null,
    val confidence: Double? = null,
    val timestamp: String? = null,
)
