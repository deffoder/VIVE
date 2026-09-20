package com.vive.data.demo

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
 * DEMO DATA - NOT MODEL OUTPUT.
 *
 * Every value in this file is hand-authored to exercise the UI. Nothing here
 * was produced by AASIST, ECAPA, an ASR model or a fusion engine, and none of
 * it may be cited as accuracy, performance or evidence of detection capability.
 *
 * This is the separation CLAUDE.md requires between demo and production data:
 * it lives in its own package, every adapter reports [AdapterMode.MOCK], and
 * the UI shows a non-dismissable "Demo data" badge whenever it is in use
 * (docs/UI_SPEC.md 6).
 *
 * Scenarios follow docs/DEMO_SPEC.md:
 *  - VS-001  S3  synthetic scam escalating to CRITICAL
 *  - VS-002  S1  normal conversation, stays LOW
 *  - VS-003  S2  human social engineering - risk rises on semantics alone,
 *                with anti-spoof evidence LOW throughout
 *  - VS-004  S4  poor audio - confidence falls, risk does NOT rise
 *
 * Replaced in the live-wiring phase by real backend responses.
 */
object DemoData {

    const val IS_DEMO = true

    // ---------------------------------------------------------------- sessions

    val sessions: List<Session> = listOf(
        Session(
            sessionId = "VS-001",
            status = SessionStatus.STREAMING,
            sourceType = SourceType.VOIP,
            startedAt = "Today, 04:21 PM",
            durationSec = 267,
            packetsProcessed = 11,
            language = "ta",
            // Matches the latest packet (P011) - "current" means the most
            // recent window, so these must not drift apart.
            currentRisk = RiskSummary(94, RiskLevel.CRITICAL, 0.86),
            overallRisk = RiskSummary(72, RiskLevel.HIGH, 0.89),
            timings = EscalationTimings(
                firstAnomalySec = 4,
                firstWarningSec = 6,
                firstHighSec = 8,
                firstCriticalSec = 10,
            ),
        ),
        Session(
            sessionId = "VS-002",
            status = SessionStatus.ENDED,
            sourceType = SourceType.VOIP,
            startedAt = "Today, 02:13 PM",
            durationSec = 142,
            packetsProcessed = 8,
            language = "en",
            currentRisk = RiskSummary(12, RiskLevel.LOW, 0.87),
            overallRisk = RiskSummary(12, RiskLevel.LOW, 0.87),
            timings = EscalationTimings(),
        ),
        Session(
            sessionId = "VS-003",
            status = SessionStatus.ENDED,
            sourceType = SourceType.VOIP,
            startedAt = "Today, 11:47 AM",
            durationSec = 198,
            packetsProcessed = 10,
            language = "hi",
            currentRisk = RiskSummary(64, RiskLevel.HIGH, 0.81),
            overallRisk = RiskSummary(58, RiskLevel.MEDIUM, 0.79),
            timings = EscalationTimings(
                firstAnomalySec = 12,
                firstWarningSec = 14,
                firstHighSec = 18,
            ),
        ),
        Session(
            sessionId = "VS-004",
            status = SessionStatus.ENDED,
            sourceType = SourceType.VOIP,
            startedAt = "Yesterday, 06:21 PM",
            durationSec = 63,
            packetsProcessed = 5,
            language = "hi",
            currentRisk = RiskSummary(9, RiskLevel.LOW, 0.21),
            overallRisk = RiskSummary(9, RiskLevel.LOW, 0.21),
            timings = EscalationTimings(),
        ),
    )

    fun session(id: String): Session? = sessions.firstOrNull { it.sessionId == id }

    /** The session the Home screen offers to resume. */
    val activeSession: Session get() = sessions.first()

    // ----------------------------------------------------------------- packets

    /**
     * Overlapping windows: 2s wide, 1s stride, so P00N covers [N-1, N+1].
     * A packet is not a partition of the call (docs/ARCHITECTURE.md 4).
     */
    private fun packet(
        seq: Int,
        sessionId: String,
        language: String,
        quality: AudioQuality,
        aasist: Double?,
        ecapaStatus: AnalyzerStatus,
        ecapa: Double?,
        transcript: String?,
        asrConfidence: Double?,
        intent: Intent,
        intentConfidence: Double?,
        behaviors: List<Behavior>,
        behaviorConfidence: Double?,
        callerVerified: Boolean,
        contextRisk: Double?,
        oodState: OodState,
        uncertainty: Double?,
        score: Int,
        level: RiskLevel,
        confidence: Double,
        reasons: List<String>,
    ): Packet {
        val start = (seq - 1).toDouble()
        val end = start + 2.0
        val contributions = buildMap {
            aasist?.let { put("synthetic", it) }
            intentConfidence?.let { put("intent", it) }
            contextRisk?.let { put("context", it) }
            ecapa?.let { put("speaker_consistency", it) }
            behaviorConfidence?.let { put("behavior", it) }
        }
        return Packet(
            packetId = "P%03d".format(seq),
            timestamp = "00:%02d".format(end.toInt()),
            durationSec = 2,
            language = language,
            quality = quality,
            aasist = AasistEvidence(
                score = aasist,
                status = if (aasist != null) AnalyzerStatus.AVAILABLE else AnalyzerStatus.UNAVAILABLE,
                modelVersion = if (aasist != null) DEMO_VERSION else null,
                inferenceMs = if (aasist != null) 182 else null,
            ),
            ecapa = EcapaEvidence(
                status = ecapaStatus,
                similarity = ecapa,
                modelVersion = if (ecapa != null) DEMO_VERSION else null,
                inferenceMs = if (ecapa != null) 41 else null,
            ),
            asr = AsrEvidence(
                transcript = transcript,
                confidence = asrConfidence,
                status = if (transcript != null) AnalyzerStatus.AVAILABLE
                else AnalyzerStatus.INSUFFICIENT_AUDIO,
                modelVersion = if (transcript != null) DEMO_VERSION else null,
                inferenceMs = if (transcript != null) 310 else null,
            ),
            intent = IntentEvidence(intent, intentConfidence, modelVersion = DEMO_VERSION),
            behavior = BehaviorEvidence(behaviors, behaviorConfidence, modelVersion = DEMO_VERSION),
            context = ContextEvidence(
                callerVerified = callerVerified,
                sessionAuthenticated = false,
                sourceType = SourceType.VOIP,
                requestedAction = if (contextRisk != null && contextRisk > 0.5) "SENSITIVE" else "ROUTINE",
                contextRisk = contextRisk,
            ),
            risk = PacketRisk(score, level, confidence, contributions, reasons),
            sessionId = sessionId,
            seq = seq,
            window = AnalysisWindow(start, end),
            languageConfidence = if (transcript != null) 0.88 else null,
            ood = OodEvidence(oodState, uncertainty),
        )
    }

    /** Version string for demo adapters. Deliberately says "demo", not a real version. */
    private const val DEMO_VERSION = "demo"

    /** VS-001 - S3 synthetic scam. Risk escalates LOW -> CRITICAL across 12 windows. */
    private val packetsVs001: List<Packet> = listOf(
        packet(1, "VS-001", "ta", AudioQuality.GOOD, 0.08, AnalyzerStatus.NO_REFERENCE, null,
            "Vanakkam, naan bank-la irundhu pesuren.", 0.93,
            Intent.NORMAL_CONVERSATION, 0.88, listOf(Behavior.NORMAL), 0.90,
            false, 0.20, OodState.IN_DISTRIBUTION, 0.08,
            8, RiskLevel.LOW, 0.86, listOf("Routine greeting", "No sensitive request")),
        packet(2, "VS-001", "ta", AudioQuality.GOOD, 0.11, AnalyzerStatus.NO_REFERENCE, null,
            "Unga account-la oru problem irukku.", 0.91,
            Intent.NORMAL_CONVERSATION, 0.74, listOf(Behavior.NORMAL), 0.71,
            false, 0.34, OodState.IN_DISTRIBUTION, 0.10,
            12, RiskLevel.LOW, 0.84, listOf("Caller not independently verified")),
        packet(3, "VS-001", "ta", AudioQuality.GOOD, 0.29, AnalyzerStatus.NO_REFERENCE, null,
            "Account block aagidum, seekiram pannanum.", 0.89,
            Intent.URGENT_ACTION, 0.81, listOf(Behavior.URGENCY), 0.77,
            false, 0.52, OodState.IN_DISTRIBUTION, 0.14,
            31, RiskLevel.MEDIUM, 0.82,
            listOf("Urgency in conversation", "Caller not independently verified")),
        packet(4, "VS-001", "ta", AudioQuality.GOOD, 0.44, AnalyzerStatus.NO_REFERENCE, null,
            "Naan than unga bank officer, nambunga.", 0.90,
            Intent.URGENT_ACTION, 0.85, listOf(Behavior.AUTHORITY_IMPERSONATION, Behavior.URGENCY), 0.83,
            false, 0.61, OodState.KNOWN_SYNTHETIC_LIKELY, 0.18,
            47, RiskLevel.MEDIUM, 0.83,
            listOf("Authority claim without verification", "Urgency in conversation")),
        packet(5, "VS-001", "ta", AudioQuality.GOOD, 0.63, AnalyzerStatus.NO_REFERENCE, null,
            "Verification-kaaga oru number varum.", 0.92,
            Intent.CONFIDENTIAL_INFORMATION, 0.79, listOf(Behavior.PRESSURE), 0.80,
            false, 0.68, OodState.KNOWN_SYNTHETIC_LIKELY, 0.19,
            58, RiskLevel.MEDIUM, 0.84,
            listOf("Elevated synthetic-voice indicators", "Preparing a credential request")),
        packet(6, "VS-001", "ta", AudioQuality.GOOD, 0.71, AnalyzerStatus.NO_REFERENCE, null,
            "Antha OTP number-a enakku sollunga.", 0.90,
            Intent.OTP_REQUEST, 0.88, listOf(Behavior.PRESSURE, Behavior.URGENCY), 0.85,
            false, 0.74, OodState.KNOWN_SYNTHETIC_LIKELY, 0.20,
            68, RiskLevel.HIGH, 0.85,
            listOf("OTP request detected", "Elevated synthetic-voice indicators")),
        packet(7, "VS-001", "ta", AudioQuality.GOOD, 0.87, AnalyzerStatus.NO_REFERENCE, null,
            "OTP sollunga, illa account close aagidum.", 0.91,
            Intent.OTP_REQUEST, 0.94, listOf(Behavior.URGENCY, Behavior.THREAT), 0.89,
            false, 0.82, OodState.KNOWN_SYNTHETIC_LIKELY, 0.16,
            91, RiskLevel.CRITICAL, 0.84,
            listOf(
                "Elevated synthetic-voice indicators",
                "OTP request detected",
                "Urgency in conversation",
                "Caller not independently verified",
            )),
        packet(8, "VS-001", "ta", AudioQuality.GOOD, 0.84, AnalyzerStatus.NO_REFERENCE, null,
            "Yaarukkum sollaadheenga, idhu confidential.", 0.88,
            Intent.CONFIDENTIAL_INFORMATION, 0.90, listOf(Behavior.SECRECY, Behavior.PRESSURE), 0.87,
            false, 0.80, OodState.KNOWN_SYNTHETIC_LIKELY, 0.17,
            88, RiskLevel.CRITICAL, 0.85,
            listOf("Secrecy request", "Elevated synthetic-voice indicators")),
        packet(9, "VS-001", "ta", AudioQuality.DEGRADED, 0.79, AnalyzerStatus.NO_REFERENCE, null,
            "Seekiram, time illa.", 0.72,
            Intent.URGENT_ACTION, 0.83, listOf(Behavior.URGENCY), 0.84,
            false, 0.77, OodState.KNOWN_SYNTHETIC_LIKELY, 0.24,
            81, RiskLevel.HIGH, 0.71,
            listOf("Urgency in conversation", "Audio quality degraded")),
        packet(10, "VS-001", "ta", AudioQuality.GOOD, 0.86, AnalyzerStatus.NO_REFERENCE, null,
            "Card number kooda venum.", 0.89,
            Intent.CARD_DETAILS_REQUEST, 0.92, listOf(Behavior.PRESSURE), 0.86,
            false, 0.85, OodState.KNOWN_SYNTHETIC_LIKELY, 0.15,
            93, RiskLevel.CRITICAL, 0.86,
            listOf("Card details requested", "Elevated synthetic-voice indicators")),
        packet(11, "VS-001", "ta", AudioQuality.GOOD, 0.83, AnalyzerStatus.NO_REFERENCE, null,
            "Transfer pannunga, naan help pannuren.", 0.90,
            Intent.MONEY_TRANSFER_REQUEST, 0.91, listOf(Behavior.PRESSURE, Behavior.URGENCY), 0.88,
            false, 0.86, OodState.KNOWN_SYNTHETIC_LIKELY, 0.16,
            94, RiskLevel.CRITICAL, 0.86,
            listOf("Money transfer requested", "Caller not independently verified")),
    )

    /** VS-002 - S1 normal conversation. Stays LOW. */
    private val packetsVs002: List<Packet> = (1..8).map { i ->
        packet(i, "VS-002", "en", AudioQuality.GOOD, 0.05 + i * 0.004,
            AnalyzerStatus.NO_REFERENCE, null,
            "Just calling to confirm the appointment time.", 0.94,
            Intent.NORMAL_CONVERSATION, 0.93, listOf(Behavior.NORMAL), 0.92,
            true, 0.10, OodState.IN_DISTRIBUTION, 0.06,
            8 + i / 2, RiskLevel.LOW, 0.87, listOf("Routine conversation"))
    }

    /**
     * VS-003 - S2 human social engineering. The important scenario: anti-spoof
     * evidence stays LOW while intent and behaviour drive risk upward, proving
     * a genuine human voice is not automatically safe.
     */
    private val packetsVs003: List<Packet> = listOf(
        packet(1, "VS-003", "hi", AudioQuality.GOOD, 0.06, AnalyzerStatus.NO_REFERENCE, null,
            "Namaste, main aapke bank se bol raha hoon.", 0.92,
            Intent.NORMAL_CONVERSATION, 0.86, listOf(Behavior.NORMAL), 0.88,
            false, 0.22, OodState.IN_DISTRIBUTION, 0.07,
            9, RiskLevel.LOW, 0.85, listOf("Routine greeting")),
        packet(2, "VS-003", "hi", AudioQuality.GOOD, 0.07, AnalyzerStatus.NO_REFERENCE, null,
            "Aapke account mein suspicious transaction hua hai.", 0.91,
            Intent.NORMAL_CONVERSATION, 0.71, listOf(Behavior.FEAR), 0.74,
            false, 0.41, OodState.IN_DISTRIBUTION, 0.09,
            22, RiskLevel.LOW, 0.84, listOf("Fear-inducing framing")),
        packet(3, "VS-003", "hi", AudioQuality.GOOD, 0.05, AnalyzerStatus.NO_REFERENCE, null,
            "Turant verify karna hoga, warna account band.", 0.90,
            Intent.URGENT_ACTION, 0.84, listOf(Behavior.URGENCY, Behavior.THREAT), 0.86,
            false, 0.63, OodState.IN_DISTRIBUTION, 0.11,
            44, RiskLevel.MEDIUM, 0.82,
            listOf("Urgency in conversation", "Consequence threatened")),
        packet(4, "VS-003", "hi", AudioQuality.GOOD, 0.06, AnalyzerStatus.NO_REFERENCE, null,
            "Aapka OTP bataiye, verification ke liye.", 0.92,
            Intent.OTP_REQUEST, 0.93, listOf(Behavior.PRESSURE, Behavior.URGENCY), 0.87,
            false, 0.79, OodState.IN_DISTRIBUTION, 0.10,
            64, RiskLevel.HIGH, 0.81,
            listOf(
                "OTP request detected",
                "Urgency in conversation",
                "Caller not independently verified",
                "Anti-spoof evidence is low - risk is driven by intent and behaviour",
            )),
        packet(5, "VS-003", "hi", AudioQuality.GOOD, 0.07, AnalyzerStatus.NO_REFERENCE, null,
            "Kisi ko mat bataiyega, yeh confidential hai.", 0.89,
            Intent.CONFIDENTIAL_INFORMATION, 0.88, listOf(Behavior.SECRECY), 0.85,
            false, 0.75, OodState.IN_DISTRIBUTION, 0.12,
            61, RiskLevel.HIGH, 0.80, listOf("Secrecy request")),
    ) + (6..10).map { i ->
        packet(i, "VS-003", "hi", AudioQuality.GOOD, 0.06,
            AnalyzerStatus.NO_REFERENCE, null,
            "Jaldi kijiye, time nahi hai.", 0.88,
            Intent.URGENT_ACTION, 0.82, listOf(Behavior.PRESSURE), 0.83,
            false, 0.72, OodState.IN_DISTRIBUTION, 0.11,
            57, RiskLevel.MEDIUM, 0.79, listOf("Sustained pressure"))
    }

    /** VS-004 - S4 poor audio. Confidence collapses; risk stays LOW. */
    private val packetsVs004: List<Packet> = (1..5).map { i ->
        packet(i, "VS-004", "hi", AudioQuality.POOR, null,
            AnalyzerStatus.NO_REFERENCE, null,
            null, null,
            Intent.UNKNOWN, null, emptyList(), null,
            false, null, OodState.UNAVAILABLE, 0.79,
            9, RiskLevel.LOW, 0.21,
            listOf("Insufficient clear speech to assess", "Audio quality poor"))
    }

    private val packetsBySession: Map<String, List<Packet>> = mapOf(
        "VS-001" to packetsVs001,
        "VS-002" to packetsVs002,
        "VS-003" to packetsVs003,
        "VS-004" to packetsVs004,
    )

    fun packets(sessionId: String): List<Packet> = packetsBySession[sessionId].orEmpty()

    fun packet(sessionId: String, packetId: String): Packet? =
        packets(sessionId).firstOrNull { it.packetId == packetId }

    // -------------------------------------------------------------- transcript

    fun transcript(sessionId: String): List<TranscriptLine> =
        packets(sessionId).mapNotNull { p ->
            p.asr.transcript?.let {
                TranscriptLine(
                    packetId = p.packetId,
                    speaker = if (p.seq!! % 3 == 0) "You" else "Caller",
                    text = it,
                    language = p.language,
                    confidence = p.asr.confidence,
                    timestamp = p.timestamp,
                )
            }
        }

    // ------------------------------------------------------------------ alerts

    val alerts: List<Alert> = listOf(
        Alert("AL-014", "VS-001", RiskLevel.CRITICAL, "Today, 04:25 PM",
            "OTP request with elevated synthetic indicators from unverified caller",
            "P007", Intent.OTP_REQUEST, RecommendedAction.SECONDARY_VERIFICATION, false),
        Alert("AL-013", "VS-001", RiskLevel.HIGH, "Today, 04:24 PM",
            "Money transfer requested by an unverified caller",
            "P011", Intent.MONEY_TRANSFER_REQUEST, RecommendedAction.ESCALATE, false),
        Alert("AL-012", "VS-003", RiskLevel.HIGH, "Today, 11:49 AM",
            "OTP request under time pressure; anti-spoof evidence low",
            "P004", Intent.OTP_REQUEST, RecommendedAction.SECONDARY_VERIFICATION, true),
        Alert("AL-011", "VS-003", RiskLevel.MEDIUM, "Today, 11:48 AM",
            "Consequence threatened to create urgency",
            "P003", Intent.URGENT_ACTION, RecommendedAction.WARN_USER, true),
    )

    fun alert(id: String): Alert? = alerts.firstOrNull { it.alertId == id }

    // ------------------------------------------------------------------ models

    /**
     * Inventory with every adapter in MOCK mode and no accuracy reported.
     * Versions read "demo" rather than a plausible-looking semantic version.
     */
    val models: List<ModelInfo> = listOf(
        ModelInfo("silero-vad", "Silero VAD", "Speech activity detection",
            DEMO_VERSION, AdapterMode.MOCK, AnalyzerStatus.AVAILABLE),
        ModelInfo("aasist", "AASIST", "Synthetic-voice evidence",
            DEMO_VERSION, AdapterMode.MOCK, AnalyzerStatus.AVAILABLE),
        ModelInfo("ecapa-tdnn", "ECAPA-TDNN", "Speaker consistency",
            DEMO_VERSION, AdapterMode.MOCK, AnalyzerStatus.NO_REFERENCE),
        ModelInfo("indicconformer", "IndicConformer", "Multilingual speech recognition",
            DEMO_VERSION, AdapterMode.MOCK, AnalyzerStatus.AVAILABLE),
        ModelInfo("intent-classifier", "Intent Classifier", "Caller intent",
            DEMO_VERSION, AdapterMode.MOCK, AnalyzerStatus.AVAILABLE),
        ModelInfo("behavior-classifier", "Behaviour Classifier", "Social-engineering behaviour",
            DEMO_VERSION, AdapterMode.MOCK, AnalyzerStatus.AVAILABLE),
        ModelInfo("risk-fusion", "Risk Fusion", "Calibrated risk from evidence",
            DEMO_VERSION, AdapterMode.MOCK, AnalyzerStatus.AVAILABLE),
    )
}
