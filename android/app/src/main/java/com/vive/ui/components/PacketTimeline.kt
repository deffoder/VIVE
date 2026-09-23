package com.vive.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.vive.data.model.Packet
import com.vive.data.model.RiskLevel
import com.vive.ui.theme.ViveOutline
import com.vive.ui.theme.ViveTheme
import com.vive.ui.theme.ViveThemeTokens

/**
 * One packet on the vertical timeline rail (docs/UI_SPEC.md 4.11).
 *
 * The whole row is the touch target - tapping opens packet detail, which is the
 * required path from a call to its evidence.
 */
@Composable
fun PacketRow(
    packet: Packet,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    isFirst: Boolean = false,
    isLast: Boolean = false,
) {
    val colors = riskColorsFor(packet.risk.level)
    val window = packet.window
    val windowText = if (window != null) {
        "%02d:%02d – %02d:%02d".format(
            window.startSec.toInt() / 60, window.startSec.toInt() % 60,
            window.endSec.toInt() / 60, window.endSec.toInt() % 60,
        )
    } else {
        packet.timestamp
    }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .heightIn(min = ViveThemeTokens.spacing.touchTarget)
            .clearAndSetSemantics {
                contentDescription =
                    "Packet ${packet.packetId}, $windowText, ${packet.risk.level.label()}, " +
                        "score ${packet.risk.score}. Opens packet detail."
            },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Rail: connector above/below the dot, so the column reads as one thread.
        Box(
            modifier = Modifier
                .width(32.dp)
                .height(64.dp),
            contentAlignment = Alignment.Center,
        ) {
            Canvas(modifier = Modifier.fillMaxWidth().height(64.dp)) {
                val cx = size.width / 2
                if (!isFirst) {
                    drawLine(ViveOutline, Offset(cx, 0f), Offset(cx, size.height / 2 - 10.dp.toPx()), 2.dp.toPx())
                }
                if (!isLast) {
                    drawLine(ViveOutline, Offset(cx, size.height / 2 + 10.dp.toPx()), Offset(cx, size.height), 2.dp.toPx())
                }
            }
            Box(
                modifier = Modifier
                    .size(14.dp)
                    .background(colors.content, CircleShape),
            )
        }

        Column(
            modifier = Modifier
                .weight(1f)
                .padding(vertical = ViveThemeTokens.spacing.sm),
        ) {
            Text(
                text = packet.packetId,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = windowText,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        // Score first, level second. In a list of packets the number is what
        // the reader is comparing; a column of identical coloured pills is
        // noise that hides the one packet that differs.
        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = packet.risk.score.toString(),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            RiskMarker(level = packet.risk.level)
        }
    }
}

/**
 * Overall risk progression across the call (docs/UI_SPEC.md 4.7).
 *
 * A lightweight line chart drawn on Canvas rather than a charting library -
 * one dependency avoided, and it redraws cheaply as packets stream in.
 * The line is coloured by the CURRENT level so the trend and the present state
 * read together.
 */
@Composable
fun RiskTimeline(
    scores: List<Int>,
    modifier: Modifier = Modifier,
    level: RiskLevel = RiskLevel.LOW,
    height: androidx.compose.ui.unit.Dp = 72.dp,
) {
    val colors = riskColorsFor(level)

    if (scores.isEmpty()) {
        Box(
            modifier = modifier.fillMaxWidth().height(height),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "No risk history yet",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        return
    }

    Canvas(
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .clearAndSetSemantics {
                contentDescription =
                    "Risk progression across ${scores.size} packets, " +
                        "currently ${scores.last()} out of 100."
            },
    ) {
        val maxScore = 100f
        val stepX = if (scores.size > 1) size.width / (scores.size - 1) else size.width
        val points = scores.mapIndexed { i, s ->
            Offset(i * stepX, size.height - (s / maxScore) * size.height)
        }

        // Baseline
        drawLine(
            ViveOutline,
            Offset(0f, size.height),
            Offset(size.width, size.height),
            1.dp.toPx(),
        )

        // Fill under the curve, very light.
        val fill = Path().apply {
            moveTo(0f, size.height)
            points.forEach { lineTo(it.x, it.y) }
            lineTo(size.width, size.height)
            close()
        }
        drawPath(fill, colors.container)

        // The line itself
        val line = Path().apply {
            moveTo(points.first().x, points.first().y)
            points.drop(1).forEach { lineTo(it.x, it.y) }
        }
        drawPath(line, colors.content, style = Stroke(width = 2.5.dp.toPx(), cap = StrokeCap.Round))

        // Current value marker
        drawCircle(colors.content, radius = 4.dp.toPx(), center = points.last())
    }
}

/**
 * One explainability bar on the packet-detail screen (docs/UI_SPEC.md 4.12).
 *
 * These are evidence STRENGTHS, not a decomposition of the risk score. The
 * screen that hosts them says so; this component just renders one honestly.
 */
@Composable
fun ContributionBar(
    label: String,
    value: Double,
    modifier: Modifier = Modifier,
    level: RiskLevel? = null,
) {
    val colors = level?.let { riskColorsFor(it) } ?: NeutralRiskColors
    val pct = (value.coerceIn(0.0, 1.0) * 100).toInt()

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = ViveThemeTokens.spacing.sm)
            .clearAndSetSemantics { contentDescription = "$label, $pct percent" },
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "$pct%",
                style = MaterialTheme.typography.labelLarge,
                color = colors.content,
            )
        }
        Box(
            modifier = Modifier
                .padding(top = ViveThemeTokens.spacing.xs)
                .fillMaxWidth()
                .height(6.dp)
                .background(ViveOutline, MaterialTheme.shapes.small),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(value.coerceIn(0.0, 1.0).toFloat())
                    .height(6.dp)
                    .background(colors.content, MaterialTheme.shapes.small),
            )
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun TimelinePreview() {
    ViveTheme {
        Column(modifier = Modifier.padding(16.dp)) {
            RiskTimeline(listOf(8, 12, 31, 47, 58, 68, 91), level = RiskLevel.CRITICAL)
            ContributionBar("Synthetic indicators", 0.87, level = RiskLevel.HIGH)
            ContributionBar("Speaker consistency", 0.43, level = RiskLevel.MEDIUM)
        }
    }
}
