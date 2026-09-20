package com.vive.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.vive.data.model.RiskLevel
import com.vive.ui.theme.ViveOutline
import com.vive.ui.theme.ViveTheme

/**
 * The signature VIVE risk gauge (docs/UI_SPEC.md 4.7).
 *
 * A circular arc with the score numeral and risk level inside. Confidence is
 * NOT drawn here - it is a separate concept and is rendered beneath the gauge
 * by [ConfidenceIndicator]. Merging them would imply the score is a
 * probability, which CLAUDE.md explicitly forbids.
 *
 * The whole gauge is one accessibility node so a screen reader announces
 * "Risk score 72 out of 100, High Risk" rather than reading fragments.
 */
@Composable
fun RiskGauge(
    score: Int,
    level: RiskLevel,
    modifier: Modifier = Modifier,
    size: Dp = 180.dp,
    strokeWidth: Dp = 14.dp,
) {
    val colors = riskColorsFor(level)
    val sweep by animateFloatAsState(
        targetValue = score.coerceIn(0, 100) / 100f,
        animationSpec = tween(durationMillis = 300),
        label = "riskSweep",
    )

    Box(
        modifier = modifier
            .size(size)
            .clearAndSetSemantics {
                contentDescription = "Risk score $score out of 100. ${level.label()}."
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(size)) {
            val stroke = strokeWidth.toPx()
            val inset = stroke / 2
            val arcSize = Size(this.size.width - stroke, this.size.height - stroke)
            val topLeft = Offset(inset, inset)

            // Track
            drawArc(
                color = ViveOutline,
                startAngle = 135f,
                sweepAngle = 270f,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(width = stroke, cap = StrokeCap.Round),
            )
            // Value
            drawArc(
                color = colors.content,
                startAngle = 135f,
                sweepAngle = 270f * sweep,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(width = stroke, cap = StrokeCap.Round),
            )
        }

        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = "$score",
                style = MaterialTheme.typography.displayMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = level.label().uppercase(),
                style = MaterialTheme.typography.labelLarge,
                color = colors.content,
            )
        }
    }
}

/**
 * Confidence, shown as its own labelled value.
 *
 * Deliberately plain text rather than a second gauge: confidence describes how
 * much evidence supports the score, and giving it equal visual weight to the
 * score invites the two to be confused.
 */
@Composable
fun ConfidenceIndicator(
    confidence: Double?,
    modifier: Modifier = Modifier,
) {
    val text = when (confidence) {
        null -> "Confidence unavailable"
        else -> "Confidence ${(confidence * 100).toInt()}%"
    }
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

@Preview(showBackground = true)
@Composable
private fun RiskGaugePreview() {
    ViveTheme {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            RiskGauge(score = 72, level = RiskLevel.HIGH)
            ConfidenceIndicator(0.89)
        }
    }
}
