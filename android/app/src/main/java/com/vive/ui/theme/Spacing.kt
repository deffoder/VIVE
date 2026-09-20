package com.vive.ui.theme

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * VIVE spacing scale. Source of truth: docs/UI_SPEC.md 2.3.
 *
 * 4dp base scale. Exposed through a CompositionLocal so components never
 * hard-code padding values.
 */
data class ViveSpacing(
    val xs: Dp = 4.dp,
    val sm: Dp = 8.dp,
    val md: Dp = 12.dp,
    val lg: Dp = 16.dp,
    val xl: Dp = 24.dp,
    val xxl: Dp = 32.dp,
    /** Screen side gutter. */
    val gutter: Dp = 16.dp,
    /** Internal card padding. */
    val cardPadding: Dp = 16.dp,
    /** Minimum accessible touch target (UI_SPEC 9). */
    val touchTarget: Dp = 48.dp,
)

val LocalViveSpacing = staticCompositionLocalOf { ViveSpacing() }
