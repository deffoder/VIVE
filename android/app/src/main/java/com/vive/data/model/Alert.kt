package com.vive.data.model

/**
 * A policy-raised alert. Mirrors docs/API_SPEC.md 5.
 *
 * [recommendedAction] is advisory only - VIVE never acts on it
 * (docs/PROJECT_SPEC.md 2).
 */
data class Alert(
    val alertId: String,
    val sessionId: String,
    val level: RiskLevel,
    val raisedAt: String,
    val reason: String,
    val packetId: String? = null,
    val intent: Intent? = null,
    val recommendedAction: RecommendedAction? = null,
    val acknowledged: Boolean = false,
)
