package com.vive.ondevice.engine

import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.AudioQuality
import com.vive.data.model.Behavior
import com.vive.data.model.Intent
import com.vive.data.remote.dto.AasistDto
import com.vive.data.remote.dto.AlertDto
import com.vive.data.remote.dto.AsrDto
import com.vive.data.remote.dto.BehaviorDto
import com.vive.data.remote.dto.ContextDto
import com.vive.data.remote.dto.EcapaDto
import com.vive.data.remote.dto.EscalationTimingsDto
import com.vive.data.remote.dto.IntentDto
import com.vive.data.remote.dto.OodDto
import com.vive.data.remote.dto.PacketDto
import com.vive.data.remote.dto.PacketRiskDto
import com.vive.data.remote.dto.RiskSummaryDto
import com.vive.data.remote.dto.SessionDto
import com.vive.data.remote.dto.TranscriptLineDto
import com.vive.data.remote.dto.WindowDto
import com.vive.ondevice.risk.RiskFusion
import com.vive.ondevice.risk.RiskPolicy
import com.vive.ondevice.risk.SensitiveRequests
import com.vive.ondevice.risk.TemporalRisk

/**
 * What each analyzer returned for one window. Statuses use the app's
 * [AnalyzerStatus] vocabulary so a declined or failed model is visible as
 * exactly that, and never becomes a value.
 */
data class VadOut(val status: AnalyzerStatus, val hasSpeech: Boolean, val quality: AudioQuality, val ms: Long? = null)
data class ScoreOut(val status: AnalyzerStatus, val score: Double? = null, val version: String? = null, val ms: Long? = null)
data class AsrOut(val status: AnalyzerStatus, val text: String? = null, val confidence: Double? = null,
                  val version: String? = null, val ms: Long? = null)
data class IntentOut(val status: AnalyzerStatus, val label: Intent = Intent.UNKNOWN, val confidence: Double? = null,
                     val version: String? = null, val ms: Long? = null)
data class BehaviorOut(val status: AnalyzerStatus, val labels: List<Behavior> = emptyList(),
                       val confidence: Double? = null, val version: String? = null, val ms: Long? = null)

/**
 * The on-device model stack, behind one seam so the pipeline is testable on
 * the JVM with fakes and runs the real ONNX models on the phone
 * ([OnDeviceAnalyzers]). Nothing in the pipeline knows which it has.
 */
interface Analyzers {
    val vadVersion: String?
    fun vad(samples: FloatArray): VadOut
    /** Anti-spoofing. Implementations return a non-AVAILABLE status when the model is not validated for use. */
    fun antispoof(samples: FloatArray): ScoreOut
    /** Similarity to [reference], or NO_REFERENCE when none is enrolled. */
    fun speaker(samples: FloatArray, reference: FloatArray?): ScoreOut
    fun asr(samples: FloatArray, language: String): AsrOut
    fun intent(text: String?, language: String): IntentOut
    fun behavior(text: String?, language: String): BehaviorOut
    /** Loads everything a session in [language] will use, before its first window. */
    fun warmUp(language: String) {}
}

/** Mutable per-session analysis state. Held only while a session is live. */
class SessionRuntime(
    var session: SessionDto,
    val language: String,
    var nextSeq: Int = 1,
    val temporal: TemporalRisk = TemporalRisk(),
    var reference: FloatArray? = null,
    /** Previous window's transcript: context for the sensitive-request rules. */
    var lastTranscript: String? = null,
)

/** Everything one window produced, ready to persist and emit. */
data class WindowOutcome(
    val packet: PacketDto,
    val session: SessionDto,
    val transcript: TranscriptLineDto?,
    val alert: AlertDto?,
)

/**
 * One analysis window end to end - the on-device counterpart of the
 * backend's `SessionManager.process_window`, producing the SAME wire DTOs so
 * every screen renders on-device output exactly as it renders server output.
 *
 * One deliberate difference: a window Silero classifies as NO_SPEECH produces
 * NO packet ([process] returns null). The capture side already drops
 * windows below an energy gate for the same reason; Silero is the better
 * judge of the ones that pass it. Measured on the first live phone call,
 * 55 of 84 windows were room noise, each a score-15 / confidence-0.06
 * packet that buried the speech in the timeline and pulled the smoothed
 * call risk towards 15 between every sentence. Not analysing silence is
 * not evidence of safety, so no score is recorded for it at all.
 */
class AnalysisPipeline(
    private val analyzers: Analyzers,
    private val clock: () -> String,
    private val nextAlertId: () -> String,
    private val rules: SensitiveRequests? = null,
) {

    fun process(rt: SessionRuntime, samples: FloatArray, startSec: Double, endSec: Double): WindowOutcome? {
        val lang = rt.language
        val vad = analyzers.vad(samples)
        // A VAD that failed to load is not silence: analyse rather than drop,
        // so the failure shows on every packet instead of hiding the call.
        if (vad.status == AnalyzerStatus.AVAILABLE && !vad.hasSpeech) return null
        val seq = rt.nextSeq++
        val quality = if (vad.status == AnalyzerStatus.AVAILABLE) vad.quality else AudioQuality.DEGRADED

        val spoof = analyzers.antispoof(samples)
        val speaker = analyzers.speaker(samples, rt.reference)
        val asr = analyzers.asr(samples, lang)
        val text = asr.text.takeIf { asr.status == AnalyzerStatus.AVAILABLE }
        val intent = if (text != null) analyzers.intent(text, lang) else IntentOut(textStatus(asr.status))
        val behavior = if (text != null) analyzers.behavior(text, lang) else BehaviorOut(textStatus(asr.status))

        val rule = rules?.detectInContext(text, rt.lastTranscript)
        rt.lastTranscript = text

        val ctx = rt.session.context
        val fused = RiskFusion.fuse(
            RiskFusion.Input(
                quality = quality,
                synthetic = spoof.score.takeIf { spoof.status == AnalyzerStatus.AVAILABLE },
                speakerStatus = speaker.status,
                speakerSimilarity = speaker.score,
                asrStatus = asr.status,
                asrConfidence = asr.confidence,
                intentStatus = intent.status,
                intent = intent.label,
                behaviorStatus = behavior.status,
                behaviors = behavior.labels,
                callerVerified = ctx.callerVerified,
                sessionAuthenticated = ctx.sessionAuthenticated,
                sensitiveRequest = rule?.let { Intent.valueOf(it.label) },
            ),
        )

        val atSec = endSec.toInt()
        val (current, overall) = rt.temporal.update(fused.risk.score, fused.risk.confidence, atSec)
        val packetId = "P%03d".format(seq)
        val timestamp = "%02d:%02d".format(atSec / 60, atSec % 60)
        val now = clock()

        val packet = PacketDto(
            packetId = packetId,
            timestamp = timestamp,
            durationSec = (endSec - startSec).toInt(),
            language = lang,
            quality = fused.quality.name,
            aasist = AasistDto(spoof.score, spoof.status.name, spoof.version, spoof.ms),
            ecapa = EcapaDto(speaker.status.name, speaker.score, speaker.version, speaker.ms),
            asr = AsrDto(asr.text, asr.confidence, asr.status.name, asr.version, asr.ms),
            intent = IntentDto(intent.label.name, intent.confidence, intent.status.name, intent.version, intent.ms),
            behavior = BehaviorDto(behavior.labels.map { it.name }, behavior.confidence, behavior.status.name,
                behavior.version, behavior.ms),
            context = ContextDto(ctx.callerVerified, ctx.sessionAuthenticated, rt.session.sourceType,
                ctx.requestedAction, fused.contextRisk),
            risk = PacketRiskDto(fused.risk.score, fused.risk.level.name, fused.risk.confidence,
                fused.risk.contributions, fused.risk.reasons),
            sessionId = rt.session.sessionId,
            seq = seq,
            window = WindowDto(startSec, endSec),
            createdAt = now,
            ood = OodDto(fused.ood.name, fused.uncertainty),
            adapterMode = "real",
        )

        val t = rt.temporal.timings
        rt.session = rt.session.copy(
            status = "STREAMING",
            packetsProcessed = seq,
            durationSec = atSec,
            language = lang,
            currentRisk = RiskSummaryDto(current.score, current.level.name, current.confidence),
            overallRisk = RiskSummaryDto(overall.score, overall.level.name, overall.confidence),
            timings = EscalationTimingsDto(t.firstAnomalySec, t.firstWarningSec, t.firstHighSec, t.firstCriticalSec),
        )

        val line = text?.let {
            TranscriptLineDto(packetId, "Caller", it, lang, asr.confidence, timestamp)
        }

        // Per packet, as the backend does: policy reads the packet's own risk.
        val decision = RiskPolicy.evaluate(
            score = fused.risk.score,
            level = fused.risk.level,
            confidence = fused.risk.confidence,
            // The model's label when it names a sensitive request, else the
            // rule's finding (as the backend's _policy_intent). Otherwise an
            // alert raised by the rule said "HIGH risk" but not what the
            // caller asked for - seen on the phone.
            intent = intent.label.takeIf { intent.status == AnalyzerStatus.AVAILABLE }
                .let { model -> if (model != null && model in RiskPolicy.SENSITIVE) model
                    else rule?.let { Intent.valueOf(it.label) } ?: model },
            callerVerified = ctx.callerVerified,
        )
        val alert = if (!decision.shouldAlert) null else AlertDto(
            alertId = nextAlertId(),
            sessionId = rt.session.sessionId,
            level = fused.risk.level.name,
            raisedAt = now,
            reason = decision.reasons.joinToString("; "),
            packetId = packetId,
            intent = (rule?.label?.takeIf { intent.label !in RiskPolicy.SENSITIVE } ?: intent.label.name),
            recommendedAction = decision.action.name,
        )
        return WindowOutcome(packet, rt.session, line, alert)
    }

    /** Text heads never ran: say why, in the ASR's terms. */
    private fun textStatus(asr: AnalyzerStatus): AnalyzerStatus = when (asr) {
        AnalyzerStatus.AVAILABLE, AnalyzerStatus.INSUFFICIENT_AUDIO -> AnalyzerStatus.INSUFFICIENT_AUDIO
        AnalyzerStatus.UNSUPPORTED_LANGUAGE -> AnalyzerStatus.UNSUPPORTED_LANGUAGE
        else -> AnalyzerStatus.UNAVAILABLE
    }
}
