package com.vive.ondevice.risk

import com.vive.data.model.EscalationTimings
import com.vive.data.model.Intent
import com.vive.data.model.RecommendedAction
import com.vive.data.model.RiskLevel
import com.vive.data.model.RiskSummary

/**
 * On-device port of `backend/app/risk/temporal.py`: EMA smoothing, a
 * minimum-evidence gate, hysteresis, and recurrence counting so intermittent
 * evidence escalates (O14). Constants are the backend's; see that file for
 * why each has the value it has.
 */
class TemporalRisk {

    var ema = 0.0; private set
    var packets = 0; private set
    var level = RiskLevel.LOW; private set
    var timings = EscalationTimings(); private set
    var peakScore = 0; private set
    var reason = ""; private set
    private val recent = ArrayDeque<Int>()

    private val elevated: Int get() = recent.count { it >= PERSISTENCE_SCORE }

    private val recurrenceLive: Boolean
        get() = elevated >= PERSISTENCE_COUNT &&
            recent.takeLast(PERSISTENCE_RECENCY).any { it >= PERSISTENCE_SCORE }

    /** Feeds one packet; returns (current, overall). */
    fun update(score: Int, confidence: Double, atSec: Int): Pair<RiskSummary, RiskSummary> {
        packets += 1
        ema = if (packets == 1) score.toDouble() else EMA_ALPHA * score + (1 - EMA_ALPHA) * ema
        peakScore = maxOf(peakScore, score)
        recent.addLast(score)
        if (recent.size > PERSISTENCE_WINDOW) recent.removeFirst()

        val smoothed = RiskFusion.pyRound(ema)
        var candidate = RiskFusion.levelFor(smoothed)
        var why = "smoothed score"
        val live = recurrenceLive
        if (live && candidate.ordinal < RiskLevel.HIGH.ordinal) {
            candidate = RiskLevel.HIGH
            why = "$elevated elevated windows in the last ${recent.size}"
        }
        if (packets < MIN_PACKETS_BEFORE_ESCALATION) {
            candidate = RiskLevel.LOW
            why = "insufficient evidence"
        } else if (candidate.ordinal < level.ordinal) {
            if (smoothed > lowerBound(level) - HYSTERESIS || live) {
                candidate = level
                why = "held by hysteresis"
            }
        }
        level = candidate
        reason = why
        recordTimings(score, atSec)
        return RiskSummary(score, RiskFusion.levelFor(score), confidence) to
            RiskSummary(smoothed, level, confidence)
    }

    private fun recordTimings(score: Int, at: Int) {
        val t = timings
        timings = t.copy(
            firstAnomalySec = t.firstAnomalySec ?: at.takeIf { score >= 20 },
            firstWarningSec = t.firstWarningSec ?: at.takeIf { score >= 35 },
            firstHighSec = t.firstHighSec ?: at.takeIf { score >= 65 },
            firstCriticalSec = t.firstCriticalSec ?: at.takeIf { score >= 85 },
        )
    }

    private fun lowerBound(l: RiskLevel) = when (l) {
        RiskLevel.LOW -> 0; RiskLevel.MEDIUM -> 35; RiskLevel.HIGH -> 65; RiskLevel.CRITICAL -> 85
    }

    companion object {
        const val EMA_ALPHA = 0.4
        const val MIN_PACKETS_BEFORE_ESCALATION = 2
        const val HYSTERESIS = 5
        const val PERSISTENCE_WINDOW = 12
        const val PERSISTENCE_SCORE = 65
        const val PERSISTENCE_COUNT = 3
        const val PERSISTENCE_RECENCY = 4
    }
}

/**
 * On-device port of `backend/app/risk/policy.py`. Every action is advisory:
 * VIVE never acts on an account. Confidence gates escalation, so a high score
 * from thin evidence recommends verification, and raises no alert.
 */
object RiskPolicy {

    const val VERSION = "policy-demo-1"
    const val MIN_CONFIDENCE_FOR_ESCALATION = 0.5

    private val SENSITIVE = setOf(
        Intent.OTP_REQUEST, Intent.PASSWORD_REQUEST, Intent.CARD_DETAILS_REQUEST,
        Intent.BANKING_CREDENTIAL_REQUEST, Intent.MONEY_TRANSFER_REQUEST, Intent.REMOTE_ACCESS_REQUEST,
    )

    data class Decision(val action: RecommendedAction, val shouldAlert: Boolean, val reasons: List<String>)

    fun evaluate(score: Int, level: RiskLevel?, confidence: Double, intent: Intent?, callerVerified: Boolean): Decision {
        val lvl = level ?: RiskFusion.levelFor(score)
        val reasons = mutableListOf<String>()
        if (confidence < MIN_CONFIDENCE_FOR_ESCALATION) {
            reasons += "Confidence is low; evidence is insufficient to escalate"
            val action = if (lvl == RiskLevel.HIGH || lvl == RiskLevel.CRITICAL) {
                RecommendedAction.SECONDARY_VERIFICATION
            } else {
                RecommendedAction.MONITOR
            }
            return Decision(action, false, reasons)
        }
        val sensitive = intent in SENSITIVE
        if (sensitive) reasons += "Sensitive request: ${intent!!.name.replace('_', ' ').lowercase()}"
        if (!callerVerified) reasons += "Caller not independently verified"
        val action = when (lvl) {
            RiskLevel.CRITICAL -> if (sensitive && !callerVerified) RecommendedAction.HOLD_SENSITIVE_ACTION else RecommendedAction.ESCALATE
            RiskLevel.HIGH -> if (sensitive) RecommendedAction.SECONDARY_VERIFICATION else RecommendedAction.ESCALATE
            RiskLevel.MEDIUM -> RecommendedAction.WARN_USER
            RiskLevel.LOW -> RecommendedAction.MONITOR
        }
        val alert = lvl == RiskLevel.HIGH || lvl == RiskLevel.CRITICAL
        if (alert) reasons += "${lvl.name} risk with sufficient confidence"
        return Decision(action, alert, reasons.ifEmpty { listOf("No policy condition met") })
    }
}
