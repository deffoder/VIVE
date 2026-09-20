package com.vive.data.model

/**
 * One entry in the model inventory (docs/API_SPEC.md 5, UI_SPEC 4.20).
 *
 * [mode] MUST be surfaced in the UI so demo output is never mistaken for real
 * inference. Accuracy is deliberately absent: no metric is displayed that was
 * not measured (docs/ML_SPEC.md 8.5).
 */
data class ModelInfo(
    val id: String,
    val displayName: String,
    val purpose: String,
    val version: String,
    val mode: AdapterMode,
    val status: AnalyzerStatus,
    val lastUpdated: String? = null,
)

/** Backend readiness, including per-adapter load state (docs/API_SPEC.md 2). */
data class ReadyState(
    val ready: Boolean,
    val apiVersion: String,
    val adapters: Map<String, AdapterState>,
) {
    /** True when ANY adapter is mock - drives the persistent Demo data badge. */
    val hasMockAdapter: Boolean get() = adapters.values.any { it.mode == AdapterMode.MOCK }
}

data class AdapterState(
    val status: AnalyzerStatus,
    val mode: AdapterMode,
)
