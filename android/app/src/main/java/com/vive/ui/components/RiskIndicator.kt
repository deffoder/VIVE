package com.vive.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.vive.data.model.RiskLevel
import com.vive.ui.theme.RiskCritical
import com.vive.ui.theme.RiskCriticalContainer
import com.vive.ui.theme.RiskHigh
import com.vive.ui.theme.RiskHighContainer
import com.vive.ui.theme.RiskLow
import com.vive.ui.theme.RiskLowContainer
import com.vive.ui.theme.RiskMedium
import com.vive.ui.theme.RiskMediumContainer
import com.vive.ui.theme.RiskNeutral
import com.vive.ui.theme.RiskNeutralContainer
import com.vive.ui.theme.ViveTheme

/** Colour pair for a risk level. The single place risk colour is decided. */
data class RiskColors(val content: Color, val container: Color)

/** Neutral pair for states that carry no risk reading. */
val NeutralRiskColors = RiskColors(RiskNeutral, RiskNeutralContainer)

fun riskColorsFor(level: RiskLevel): RiskColors = when (level) {
    RiskLevel.LOW -> RiskColors(RiskLow, RiskLowContainer)
    RiskLevel.MEDIUM -> RiskColors(RiskMedium, RiskMediumContainer)
    RiskLevel.HIGH -> RiskColors(RiskHigh, RiskHighContainer)
    RiskLevel.CRITICAL -> RiskColors(RiskCritical, RiskCriticalContainer)
}

/** Human-readable label. Risk is never conveyed by colour alone (UI_SPEC 2.1). */
fun RiskLevel.label(): String = when (this) {
    RiskLevel.LOW -> "Low Risk"
    RiskLevel.MEDIUM -> "Medium Risk"
    RiskLevel.HIGH -> "High Risk"
    RiskLevel.CRITICAL -> "Critical Risk"
}

/**
 * Restrained inline severity marker.
 *
 * A filled, coloured pill is a strong visual claim, and the active-call screen
 * was making it six or seven times at once - once per evidence row, once per
 * packet in the timeline - beside a gauge that had already stated the risk.
 * Repeating it that often flattens the hierarchy: everything looks urgent, so
 * nothing does, and the screen reads like a status board rather than an
 * analysis.
 *
 * This renders the word in the level's colour with no filled container, so a
 * row's severity is legible without competing with the primary reading. LOW
 * and MEDIUM deliberately use the muted on-surface colour: only HIGH and
 * CRITICAL earn a colour, because only they are exceptional. The text is
 * always present, so nothing depends on colour alone (UI_SPEC 2.1).
 */
@Composable
fun RiskMarker(
    level: RiskLevel,
    modifier: Modifier = Modifier,
    text: String = level.shortLabel(),
) {
    val color = when (level) {
        RiskLevel.LOW, RiskLevel.MEDIUM -> MaterialTheme.colorScheme.onSurfaceVariant
        RiskLevel.HIGH -> RiskHigh
        RiskLevel.CRITICAL -> RiskCritical
    }
    Text(
        text = text,
        style = MaterialTheme.typography.labelLarge,
        color = color,
        modifier = modifier.semantics { contentDescription = text },
    )
}

/**
 * Compact risk pill.
 *
 * Always renders the level's text label alongside its colour, for accessibility
 * and because CLAUDE.md requires visual differentiation that survives colour
 * blindness.
 */
@Composable
fun RiskPill(
    level: RiskLevel,
    modifier: Modifier = Modifier,
    text: String = level.label(),
) {
    val colors = riskColorsFor(level)
    Text(
        text = text,
        style = MaterialTheme.typography.labelLarge,
        color = colors.content,
        modifier = modifier
            .background(colors.container, MaterialTheme.shapes.small)
            .padding(PaddingValues(horizontal = 10.dp, vertical = 4.dp))
            .semantics { contentDescription = text },
    )
}

@Preview(showBackground = true)
@Composable
private fun RiskPillPreview() {
    ViveTheme {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(8.dp),
        ) {
            RiskLevel.entries.forEach { RiskPill(it) }
        }
    }
}
