package com.vive.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * VIVE colour tokens.
 *
 * Source of truth: docs/UI_SPEC.md 2.1, extracted from design/02_vive_ui_reference.png.
 * Do not introduce colours outside this file.
 */

// Brand / surfaces
val VivePrimary = Color(0xFF1B6FE8)
val VivePrimaryContainer = Color(0xFFEAF2FE)
val ViveOnPrimary = Color(0xFFFFFFFF)
val ViveSurface = Color(0xFFFFFFFF)
val ViveBackground = Color(0xFFF5F8FD)
val ViveOnSurface = Color(0xFF0F1B33)
val ViveOnSurfaceVariant = Color(0xFF5A6B85)
val ViveOutline = Color(0xFFE2E9F3)

// Risk palette. The only other saturated colours in the product.
val RiskLow = Color(0xFF16A34A)
val RiskLowContainer = Color(0xFFE8F6EE)
val RiskMedium = Color(0xFFF59E0B)
val RiskMediumContainer = Color(0xFFFEF3E2)
val RiskHigh = Color(0xFFEF4444)
val RiskHighContainer = Color(0xFFFEECEC)
val RiskCritical = Color(0xFFDC2626)
val RiskCriticalContainer = Color(0xFFFDE4E4)

/** Neutral pair for states that carry no risk reading (unavailable, insufficient data). */
val RiskNeutral = Color(0xFF5A6B85)
val RiskNeutralContainer = Color(0xFFEEF2F8)
