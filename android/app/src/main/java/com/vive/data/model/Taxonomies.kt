package com.vive.data.model

/**
 * Canonical VIVE taxonomies.
 *
 * Source of truth: docs/PROJECT_SPEC.md 7, mirroring CLAUDE.md. These must stay
 * identical to the backend Pydantic enums; they are the typed contract between
 * the two (docs/IMPLEMENTATION_PLAN.md, Phase 1).
 *
 * Every enum carries an UNKNOWN-style fallback so an unrecognised value from a
 * newer backend degrades gracefully instead of crashing the client.
 */

/** Risk level. Always rendered with a text label, never colour alone. */
enum class RiskLevel { LOW, MEDIUM, HIGH, CRITICAL }

/** Audio quality of an analysis window. POOR/NO_SPEECH must never raise risk. */
enum class AudioQuality { GOOD, DEGRADED, POOR, NO_SPEECH }

/**
 * Why an analyzer did or did not produce a value. Drives every "this did not
 * run" state in the UI.
 *
 * Must mirror `backend/app/schemas/models.py::AnalyzerStatus` exactly. It did
 * not: the backend gained `LOAD_ERROR`, `INFERENCE_ERROR` and
 * `UNSUPPORTED_LANGUAGE` in Phase 8, and this enum was never extended. Because
 * the mapper fell back to AVAILABLE for anything it did not recognise, an
 * analyzer that never ran arrived in the UI looking like one that had
 * succeeded - and every Tamil packet reports `UNSUPPORTED_LANGUAGE` on both
 * text heads, so that was the normal case for a whole language, not an edge
 * case (docs/BLOCKERS.md O11).
 *
 * Only AVAILABLE means a value was produced. Everything else means there is no
 * value, and the UI must say which kind of nothing it is.
 */
enum class AnalyzerStatus {
    /** The model ran and produced a value. */
    AVAILABLE,

    /** Not configured or not running in this deployment. */
    UNAVAILABLE,

    /** Speaker only: nothing enrolled to compare against. NOT a mismatch. */
    NO_REFERENCE,

    /** Not enough audio yet. Anti-spoofing needs ~4 s of real audio. */
    INSUFFICIENT_AUDIO,

    /** The model could not be loaded - missing weights or runtime. */
    LOAD_ERROR,

    /** The model loaded but failed on this window. */
    INFERENCE_ERROR,

    /** The model does not support this language and declined to guess. */
    UNSUPPORTED_LANGUAGE,

    /** Generic failure, retained for backward compatibility. */
    ERROR;

    /** True only when a value actually exists. */
    val producedAValue: Boolean get() = this == AVAILABLE

    /** Short phrase for a UI row that has no value to show. */
    fun absenceLabel(): String = when (this) {
        AVAILABLE -> ""
        UNAVAILABLE -> "Unavailable"
        NO_REFERENCE -> "No reference"
        INSUFFICIENT_AUDIO -> "Not enough audio yet"
        LOAD_ERROR -> "Model unavailable"
        INFERENCE_ERROR -> "Analysis failed"
        UNSUPPORTED_LANGUAGE -> "Language not supported"
        ERROR -> "Analysis failed"
    }

    /** One line explaining what the absence means, for detail views. */
    fun absenceExplanation(): String = when (this) {
        AVAILABLE -> ""
        UNAVAILABLE -> "This analyzer is not running in this deployment."
        NO_REFERENCE ->
            "No enrolled voice to compare against, so no similarity was " +
                "computed. This is not a speaker mismatch."
        INSUFFICIENT_AUDIO ->
            "Not enough genuine audio has accumulated yet. VIVE waits rather " +
                "than padding the window."
        LOAD_ERROR ->
            "The model could not be loaded, so no result exists for this " +
                "window. A missing model does not raise risk."
        INFERENCE_ERROR ->
            "The model failed on this window. A failure does not raise risk."
        UNSUPPORTED_LANGUAGE ->
            "This analyzer does not support the detected language and " +
                "declined to guess rather than produce an untrained result."
        ERROR -> "This analyzer failed. A failure does not raise risk."
    }
}

/** Whether an adapter is a demo stand-in or a real model. Surfaced in the UI. */
enum class AdapterMode { MOCK, REAL }

/** Session lifecycle. */
enum class SessionStatus { READY, STREAMING, ENDED, ERROR }

/** Where a session's audio comes from. */
enum class SourceType { VOIP, IN_APP, CELLULAR_SCREENING, REPLAY }

/** What the caller is asking for. 12 values, per CLAUDE.md. */
enum class Intent {
    NORMAL_CONVERSATION,
    OTP_REQUEST,
    PASSWORD_REQUEST,
    CARD_DETAILS_REQUEST,
    BANKING_CREDENTIAL_REQUEST,
    MONEY_TRANSFER_REQUEST,
    ACCOUNT_CHANGE_REQUEST,
    REMOTE_ACCESS_REQUEST,
    URGENT_ACTION,
    THREAT_OR_INTIMIDATION,
    CONFIDENTIAL_INFORMATION,
    UNKNOWN,
}

/** Persuasion behaviour. 8 values, multi-label; NORMAL is exclusive. */
enum class Behavior {
    AUTHORITY_IMPERSONATION,
    URGENCY,
    THREAT,
    FEAR,
    SECRECY,
    PRESSURE,
    REWARD_PROMISE,
    NORMAL,
}

/**
 * Uncertainty / unknown-generator state (docs/API_SPEC.md 4.1).
 * High uncertainty lowers confidence; it does not raise risk.
 */
enum class OodState {
    IN_DISTRIBUTION,
    KNOWN_SYNTHETIC_LIKELY,
    UNKNOWN_GENERATOR_SUSPECTED,
    OUT_OF_DISTRIBUTION,
    UNAVAILABLE,
}

/** Advisory action. VIVE never acts on these itself (docs/PROJECT_SPEC.md 2). */
enum class RecommendedAction {
    MONITOR,
    WARN_USER,
    SECONDARY_VERIFICATION,
    ESCALATE,
    HOLD_SENSITIVE_ACTION,
}
