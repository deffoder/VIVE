package com.vive.data.model

/**
 * A single analysis window.
 *
 * Mirrors the canonical packet in CLAUDE.md, as specified in docs/API_SPEC.md 4.
 * Core fields keep their exact backend names; fields marked (extension) are the
 * additive ones from API_SPEC 4.1 and are nullable because clients must
 * tolerate their absence.
 *
 * Windows OVERLAP (2s window, 1s stride) - a packet is not a partition of the
 * call (docs/ARCHITECTURE.md 4).
 */
data class Packet(
    val packetId: String,
    /** Call-relative "mm:ss", per CLAUDE.md - not a wall-clock time. */
    val timestamp: String,
    val durationSec: Int,
    /** ISO 639-1, e.g. "ta". */
    val language: String,
    val quality: AudioQuality,

    val aasist: AasistEvidence,
    val ecapa: EcapaEvidence,
    val asr: AsrEvidence,
    val intent: IntentEvidence,
    val behavior: BehaviorEvidence,
    val context: ContextEvidence,
    val risk: PacketRisk,

    // --- extensions (API_SPEC 4.1) ---
    val sessionId: String? = null,
    val seq: Int? = null,
    val window: AnalysisWindow? = null,
    val languageConfidence: Double? = null,
    val ood: OodEvidence? = null,
    /**
     * Whether REAL model adapters or the deterministic mocks produced this
     * packet. Carried per packet rather than read once at start-up, so the
     * "Demo data" badge follows the evidence on screen.
     */
    val adapterMode: AdapterMode? = null,
)

/** Absolute window bounds in seconds from call start. */
data class AnalysisWindow(
    val startSec: Double,
    val endSec: Double,
)

/** Anti-spoofing evidence. [score] is spoof likelihood, NOT probability of fraud. */
data class AasistEvidence(
    val score: Double? = null,
    val status: AnalyzerStatus = AnalyzerStatus.AVAILABLE,
    val modelVersion: String? = null,
    val inferenceMs: Long? = null,
)

/** Speaker consistency. Inert without an enrolled reference (NO_REFERENCE). */
data class EcapaEvidence(
    val status: AnalyzerStatus,
    val similarity: Double? = null,
    val modelVersion: String? = null,
    val inferenceMs: Long? = null,
)

/** Transcript for this window. Treated as sensitive; never logged. */
data class AsrEvidence(
    val transcript: String? = null,
    val confidence: Double? = null,
    val status: AnalyzerStatus = AnalyzerStatus.AVAILABLE,
    val modelVersion: String? = null,
    val inferenceMs: Long? = null,
)

data class IntentEvidence(
    val label: Intent,
    val confidence: Double? = null,
    val status: AnalyzerStatus = AnalyzerStatus.AVAILABLE,
    val modelVersion: String? = null,
    val inferenceMs: Long? = null,
)

/** Multi-label; may be empty. */
data class BehaviorEvidence(
    val labels: List<Behavior> = emptyList(),
    val confidence: Double? = null,
    val status: AnalyzerStatus = AnalyzerStatus.AVAILABLE,
    val modelVersion: String? = null,
    val inferenceMs: Long? = null,
)

data class ContextEvidence(
    val callerVerified: Boolean,
    val sessionAuthenticated: Boolean? = null,
    val sourceType: SourceType? = null,
    val requestedAction: String? = null,
    val contextRisk: Double? = null,
)

/** Uncertainty layer. High uncertainty lowers confidence, never raises risk. */
data class OodEvidence(
    val state: OodState,
    val uncertainty: Double? = null,
)

/**
 * Packet risk.
 *
 * [score] is 0-100. [confidence] is 0.0-1.0 and is a SEPARATE concept - it is
 * never presented as a fraud probability (CLAUDE.md, Risk Design).
 */
data class PacketRisk(
    val score: Int,
    val level: RiskLevel,
    val confidence: Double,
    /**
     * Evidence strengths 0.0-1.0 keyed by signal, for the packet-detail bars.
     * NOT a decomposition that sums to [score] (docs/API_SPEC.md 4.1).
     */
    val contributions: Map<String, Double> = emptyMap(),
    val reasons: List<String> = emptyList(),
)
