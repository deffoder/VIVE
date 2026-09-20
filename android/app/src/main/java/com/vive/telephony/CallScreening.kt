package com.vive.telephony

/**
 * Cellular screening — PATH A.
 *
 * ## What this path can and cannot do
 *
 * `CallScreeningService` is the only supported way for a third-party Android
 * app to see an incoming cellular call before it is answered. It receives
 * `Call.Details`: the handle (number when available), presentation and
 * direction.
 *
 * **It provides no audio.** Android does not permit a third-party app to
 * capture either leg of an ordinary cellular call, let alone both. Nothing in
 * this package attempts it, and no part of the product may claim otherwise
 * (docs/BLOCKERS.md P1).
 *
 * Deepfake and speech analysis therefore cannot run on a cellular call. Full
 * analysis requires the authorized audio path in `com.vive.audio` — a separate
 * package, deliberately, so the two cannot be confused in code.
 *
 * ## Response deadline
 *
 * The platform expects `respondToCall` promptly; the system may treat a slow
 * service as unresponsive. Screening must therefore stay LIGHTWEIGHT: a local
 * lookup, never a network round trip and never a model.
 *
 * ## Blocking policy
 *
 * VIVE does not reject calls on an unvalidated score. A screening decision may
 * flag or silence, and the user decides. Auto-rejecting on a provisional model
 * output would be acting on the user's behalf, which the product forbids
 * (docs/PROJECT_SPEC.md 2).
 */

/** Metadata the platform actually exposes to a screening service. No audio. */
data class CallMetadata(
    val phoneNumber: String?,
    val isIncoming: Boolean,
    /** True when the caller withheld their number. */
    val numberWithheld: Boolean = false,
    /** True when the number is in the user's contacts, if that is known. */
    val inContacts: Boolean? = null,
)

/** What screening concluded, from metadata alone. */
enum class ScreeningVerdict {
    /** Nothing known against this caller. */
    ALLOW,

    /** Surfaced to the user with a caution. The call still rings. */
    FLAG,

    /** Silenced, not rejected. The user still sees it. */
    SILENCE,

    /** Not enough metadata to say anything. */
    UNKNOWN,
}

/**
 * A screening decision.
 *
 * [analysable] records the platform boundary explicitly, so any UI rendering
 * this result states plainly that the call's audio is not being analysed.
 */
data class ScreeningDecision(
    val verdict: ScreeningVerdict,
    val reason: String,
    val analysable: Boolean = false,
) {
    companion object {
        /** Cellular screening never yields audio, so this is always the case. */
        const val NO_AUDIO_NOTICE =
            "Cellular call audio is not accessible to VIVE. This decision uses " +
                "call metadata only. Full analysis requires an authorized in-app call."
    }
}

/**
 * Local, synchronous screening policy.
 *
 * Deliberately trivial and offline: the platform deadline makes a network call
 * unsafe here, and a heavier check would risk the service being killed.
 */
interface ScreeningPolicy {
    fun evaluate(metadata: CallMetadata): ScreeningDecision
}

/**
 * Default policy.
 *
 * Flags only what metadata can genuinely support: a withheld number, or a
 * number on a locally held watchlist. It does not guess, and it never rejects.
 */
class MetadataScreeningPolicy(
    private val watchlist: Set<String> = emptySet(),
) : ScreeningPolicy {

    override fun evaluate(metadata: CallMetadata): ScreeningDecision {
        val number = metadata.phoneNumber?.filter { it.isDigit() }

        return when {
            metadata.numberWithheld -> ScreeningDecision(
                verdict = ScreeningVerdict.FLAG,
                reason = "Caller withheld their number",
            )

            number != null && number in watchlist -> ScreeningDecision(
                verdict = ScreeningVerdict.FLAG,
                reason = "Number is on your watchlist",
            )

            metadata.inContacts == true -> ScreeningDecision(
                verdict = ScreeningVerdict.ALLOW,
                reason = "Caller is in your contacts",
            )

            number == null -> ScreeningDecision(
                verdict = ScreeningVerdict.UNKNOWN,
                reason = "No caller metadata available",
            )

            else -> ScreeningDecision(
                verdict = ScreeningVerdict.ALLOW,
                reason = "No known risk signal for this number",
            )
        }
    }
}
