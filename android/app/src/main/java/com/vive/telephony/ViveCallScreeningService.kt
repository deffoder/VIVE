package com.vive.telephony

import android.telecom.Call
import android.telecom.CallScreeningService
import com.vive.core.ViveLog

/**
 * VIVE's CallScreeningService — PATH A.
 *
 * The platform binds this on an incoming cellular call and expects a prompt
 * `respondToCall`. Everything here is therefore synchronous and local: no
 * network, no model, no disk.
 *
 * This service NEVER receives audio. See [CallScreening] for the full boundary.
 *
 * Only available when the user grants the call-screening role; see
 * [CallScreeningRole].
 */
class ViveCallScreeningService : CallScreeningService() {

    private val policy: ScreeningPolicy = MetadataScreeningPolicy()

    override fun onScreenCall(callDetails: Call.Details) {
        val decision = try {
            policy.evaluate(callDetails.toMetadata())
        } catch (e: Exception) {
            // Never leave the platform waiting: fall back to allowing the call.
            ViveLog.e(TAG, "screening failed: ${e::class.simpleName}")
            ScreeningDecision(ScreeningVerdict.UNKNOWN, "Screening unavailable")
        }

        // Metadata only - never the number, which is personal data
        // (docs/SECURITY_SPEC.md 5).
        ViveLog.i(TAG, "screened call: ${decision.verdict}")

        respondToCall(callDetails, decision.toResponse())
    }

    private companion object {
        const val TAG = "ViveCallScreening"
    }
}

/** Maps platform call details onto the metadata the policy understands. */
fun Call.Details.toMetadata(): CallMetadata {
    val withheld = handlePresentation != android.telecom.TelecomManager.PRESENTATION_ALLOWED
    return CallMetadata(
        phoneNumber = handle?.schemeSpecificPart,
        isIncoming = callDirection == Call.Details.DIRECTION_INCOMING,
        numberWithheld = withheld,
        inContacts = null,
    )
}

/**
 * Maps a decision onto a platform response.
 *
 * Note what is NOT set: `setDisallowCall`. VIVE does not reject calls. A
 * flagged call still rings, and the user decides
 * (docs/PROJECT_SPEC.md 2).
 */
fun ScreeningDecision.toResponse(): CallScreeningService.CallResponse =
    CallScreeningService.CallResponse.Builder()
        .setDisallowCall(false)
        .setRejectCall(false)
        .setSkipCallLog(false)
        .setSkipNotification(verdict == ScreeningVerdict.SILENCE)
        .setSilenceCall(verdict == ScreeningVerdict.SILENCE)
        .build()
