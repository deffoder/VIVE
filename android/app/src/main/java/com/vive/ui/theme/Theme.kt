package com.vive.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider

/**
 * VIVE theme.
 *
 * Light only for now. Dark is deferred (docs/BLOCKERS.md D8) but every colour is
 * a token here, so adding it later needs no component changes.
 *
 * Dynamic colour is deliberately NOT used: risk colours must be stable and
 * legible across devices, and wallpaper-derived palettes would undermine that.
 */
private val ViveLightColorScheme = lightColorScheme(
    primary = VivePrimary,
    onPrimary = ViveOnPrimary,
    primaryContainer = VivePrimaryContainer,
    onPrimaryContainer = ViveOnSurface,
    background = ViveBackground,
    onBackground = ViveOnSurface,
    surface = ViveSurface,
    onSurface = ViveOnSurface,
    surfaceVariant = VivePrimaryContainer,
    onSurfaceVariant = ViveOnSurfaceVariant,
    outline = ViveOutline,
    outlineVariant = ViveOutline,
    error = RiskHigh,
    onError = ViveOnPrimary,
    errorContainer = RiskHighContainer,
    onErrorContainer = ViveOnSurface,
)

@Composable
fun ViveTheme(
    content: @Composable () -> Unit,
) {
    CompositionLocalProvider(LocalViveSpacing provides ViveSpacing()) {
        MaterialTheme(
            colorScheme = ViveLightColorScheme,
            typography = ViveTypography,
            shapes = ViveShapes,
            content = content,
        )
    }
}

/** Convenience accessor so components read spacing as `ViveTheme.spacing.lg`. */
object ViveThemeTokens {
    val spacing: ViveSpacing
        @Composable get() = LocalViveSpacing.current
}
