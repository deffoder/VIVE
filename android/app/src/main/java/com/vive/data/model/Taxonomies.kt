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

/** Per-analyzer availability. Drives the Unavailable UI state. */
enum class AnalyzerStatus {
    AVAILABLE,
    UNAVAILABLE,
    NO_REFERENCE,
    INSUFFICIENT_AUDIO,
    ERROR,
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
