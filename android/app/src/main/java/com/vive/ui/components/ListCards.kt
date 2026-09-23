package com.vive.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.vive.data.model.Alert
import com.vive.data.model.RiskLevel
import com.vive.data.model.Session
import com.vive.data.model.TranscriptLine
import com.vive.ui.theme.ViveTheme
import com.vive.ui.theme.ViveThemeTokens

/** A past or active call in a list (docs/UI_SPEC.md 4.14). */
@Composable
fun SessionCard(
    session: Session,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // The highest level the call reached, not its smoothed average: a list
    // entry reading "Low" for a call that raised a HIGH alert is wrong.
    val peak = session.peakLevel
    ViveCard(modifier = modifier.clickable(onClick = onClick)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
        ) {
            IconChip(
                icon = Icons.Filled.Call,
                tint = peak?.let { riskColorsFor(it).content }
                    ?: MaterialTheme.colorScheme.primary,
                container = peak?.let { riskColorsFor(it).container }
                    ?: MaterialTheme.colorScheme.primaryContainer,
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = session.sessionId,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = listOfNotNull(
                        com.vive.core.Formatting.whenLocal(session.startedAt),
                        com.vive.core.Formatting.languageName(session.language),
                        "${session.packetsProcessed} speech windows",
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            peak?.let { RiskPill(level = it) }
        }
    }
}

/** A policy-raised alert (docs/UI_SPEC.md 4.15). */
@Composable
fun AlertCard(
    alert: Alert,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = riskColorsFor(alert.level)
    ViveCard(modifier = modifier.clickable(onClick = onClick)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
        ) {
            IconChip(
                icon = Icons.Filled.Warning,
                tint = colors.content,
                container = colors.container,
            )
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.Top,
                ) {
                    Text(
                        text = alertHeadline(alert),
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f),
                    )
                    if (!alert.acknowledged) {
                        Box(
                            modifier = Modifier
                                .padding(top = 6.dp)
                                .background(colors.content, androidx.compose.foundation.shape.CircleShape)
                                .widthIn(min = 8.dp)
                                .padding(4.dp),
                        )
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RiskPill(level = alert.level)
                }
                Text(
                    text = listOfNotNull(
                        com.vive.core.Formatting.whenLocal(alert.raisedAt),
                        alert.sessionId,
                        alert.packetId,
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                alert.recommendedAction?.let {
                    Text(
                        text = actionAdvice(it),
                        style = MaterialTheme.typography.labelSmall,
                        color = colors.content,
                        modifier = Modifier.padding(top = ViveThemeTokens.spacing.xs),
                    )
                }
            }
        }
    }
}

/** What the caller did, in words; the level alone says nothing actionable. */
internal fun alertHeadline(alert: Alert): String = when (alert.intent) {
    com.vive.data.model.Intent.OTP_REQUEST -> "Caller asked for an OTP"
    com.vive.data.model.Intent.PASSWORD_REQUEST -> "Caller asked for a password or PIN"
    com.vive.data.model.Intent.CARD_DETAILS_REQUEST -> "Caller asked for card details"
    com.vive.data.model.Intent.BANKING_CREDENTIAL_REQUEST -> "Caller asked for banking credentials"
    com.vive.data.model.Intent.MONEY_TRANSFER_REQUEST -> "Caller asked for a money transfer"
    com.vive.data.model.Intent.REMOTE_ACCESS_REQUEST -> "Caller asked for remote access"
    com.vive.data.model.Intent.THREAT_OR_INTIMIDATION -> "Threatening language"
    else -> "${alert.level.label()} on this call"
}

/** Advisory only: VIVE never acts on an account (docs/PROJECT_SPEC.md 2). */
internal fun actionAdvice(action: com.vive.data.model.RecommendedAction): String = when (action) {
    com.vive.data.model.RecommendedAction.MONITOR -> "Keep listening"
    com.vive.data.model.RecommendedAction.WARN_USER -> "Be cautious on this call"
    com.vive.data.model.RecommendedAction.SECONDARY_VERIFICATION ->
        "Verify the caller through a number you already trust before sharing anything"
    com.vive.data.model.RecommendedAction.ESCALATE -> "Treat this call as suspicious"
    com.vive.data.model.RecommendedAction.HOLD_SENSITIVE_ACTION ->
        "Do not share codes or move money on this call"
}

/**
 * One transcript utterance (docs/UI_SPEC.md 4.8).
 *
 * Caller and local speaker are distinguished by alignment and surface, not by
 * colour alone. Indic script renders as-is; no transliteration.
 */
@Composable
fun TranscriptBubble(
    line: TranscriptLine,
    modifier: Modifier = Modifier,
    isLocal: Boolean = false,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = if (isLocal) Alignment.End else Alignment.Start,
    ) {
        Text(
            text = listOfNotNull(line.speaker, line.timestamp).joinToString("  "),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = ViveThemeTokens.spacing.sm),
        )
        Box(
            modifier = Modifier
                .padding(top = 2.dp)
                .background(
                    if (isLocal) MaterialTheme.colorScheme.primaryContainer
                    else MaterialTheme.colorScheme.surface,
                    MaterialTheme.shapes.large,
                )
                .padding(ViveThemeTokens.spacing.md),
        ) {
            Text(
                text = line.text,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
        line.confidence?.let {
            Text(
                text = "ASR confidence ${(it * 100).toInt()}%",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(
                    horizontal = ViveThemeTokens.spacing.sm,
                    vertical = 2.dp,
                ),
            )
        }
    }
}

/** Neutral status chip for connection/adapter states. */
@Composable
fun StatusBadge(
    text: String,
    modifier: Modifier = Modifier,
    level: RiskLevel? = null,
) {
    val colors = level?.let { riskColorsFor(it) } ?: NeutralRiskColors
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = colors.content,
        modifier = modifier
            .background(colors.container, MaterialTheme.shapes.small)
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@Preview(showBackground = true)
@Composable
private fun ListCardsPreview() {
    ViveTheme {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            StatusBadge("NO REFERENCE")
            TranscriptBubble(
                TranscriptLine("P001", "Caller", "OTP sollunga...", "ta", 0.91, "00:08"),
            )
        }
    }
}
