package com.vive.ui.screens.call

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.Packet
import com.vive.ui.components.ConfidenceIndicator
import com.vive.ui.components.ContributionBar
import com.vive.ui.components.InfoRow
import com.vive.ui.components.MetricCard
import com.vive.ui.components.MetricRow
import com.vive.ui.components.PacketRow
import com.vive.ui.components.RiskPill
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.StatusBadge
import com.vive.ui.components.ViveCard
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.components.shortLabel
import com.vive.ui.screens.PacketDetailViewModel
import com.vive.ui.screens.SessionDetailViewModel
import com.vive.ui.screens.StateHost
import com.vive.ui.theme.ViveThemeTokens

/**
 * Packet timeline (docs/UI_SPEC.md 4.11).
 *
 * Every analysis window in sequence. Windows OVERLAP - the note below the
 * header says so, because a reader who assumes they partition the call will
 * misread the evidence.
 *
 * Tapping a row opens packet detail. This is the required interaction.
 */
@Composable
fun PacketTimelineScreen(
    viewModel: SessionDetailViewModel,
    onBack: () -> Unit,
    onOpenPacket: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val packetState by viewModel.packets.collectAsStateWithLifecycle()

    ViveScreenScaffold(title = "Packet timeline", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(
                state = packetState,
                onRetry = viewModel::refresh,
                emptyTitle = "No packets yet",
                emptyDescription = "Analysis windows appear here as the call is processed.",
            ) { packets ->
                Text(
                    text = "Windows overlap: each packet covers 2 seconds, advancing 1 second " +
                        "at a time. They do not partition the call.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                ViveCard {
                    packets.forEachIndexed { index, packet ->
                        PacketRow(
                            packet = packet,
                            onClick = { onOpenPacket(packet.packetId) },
                            isFirst = index == 0,
                            isLast = index == packets.lastIndex,
                        )
                    }
                }
            }
        }
    }
}

/**
 * Packet detail (docs/UI_SPEC.md 4.12).
 *
 * Shows every required field, then the contribution visualization. Absent
 * analyzer output renders as its status, never as a number.
 */
@Composable
fun PacketDetailScreen(
    viewModel: PacketDetailViewModel,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    ViveScreenScaffold(title = "Packet detail", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(state, onRetry = viewModel::refresh) { packet ->
                PacketDetailContent(packet)
            }
        }
    }
}

@Composable
private fun PacketDetailContent(packet: Packet) {
    // Header: identity and verdict together.
    ViveCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text(
                    text = packet.packetId,
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = windowLabel(packet),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            RiskPill(level = packet.risk.level)
        }
    }

    MetricRow {
        MetricCard(
            value = "${packet.risk.score}",
            label = "Packet risk",
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            value = "${(packet.risk.confidence * 100).toInt()}%",
            label = "Confidence",
            modifier = Modifier.weight(1f),
        )
    }

    // Transcript. Sensitive content - shown here, never logged or webhooked.
    ViveCard {
        SectionHeader(title = "Transcript")
        Text(
            text = packet.asr.transcript ?: "No usable speech in this window.",
            style = MaterialTheme.typography.bodyLarge,
            color = if (packet.asr.transcript != null) MaterialTheme.colorScheme.onSurface
            else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = ViveThemeTokens.spacing.xs),
        )
        packet.asr.confidence?.let {
            Text(
                text = "ASR confidence ${(it * 100).toInt()}%",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.xs),
            )
        }
    }

    // Every field docs/UI_SPEC.md 4.12 requires.
    ViveCard {
        SectionHeader(title = "Analysis")
        InfoRow("Timestamp", packet.timestamp)
        InfoRow("Window", windowLabel(packet))
        InfoRow("Duration", "${packet.durationSec}s")
        InfoRow("Language", packet.language.uppercase())
        InfoRow("Audio quality", packet.quality.name.replace('_', ' '))
        InfoRow("Intent", packet.intent.label.name.replace('_', ' '))
        InfoRow(
            "Behaviour",
            packet.behavior.labels.takeIf { it.isNotEmpty() }
                ?.joinToString(", ") { it.name.replace('_', ' ') },
        )
        InfoRow(
            "Synthetic voice evidence",
            packet.aasist.score?.let { describeSynthetic(it) },
        )
        InfoRow(
            "Speaker consistency",
            when (packet.ecapa.status) {
                AnalyzerStatus.NO_REFERENCE -> "No enrolled reference"
                else -> packet.ecapa.similarity?.let { "${(it * 100).toInt()}%" }
            },
        )
        InfoRow(
            "Context",
            if (packet.context.callerVerified) "Caller verified" else "Caller not verified",
        )
        packet.ood?.let {
            InfoRow("Uncertainty", it.uncertainty?.let { u -> "${(u * 100).toInt()}%" })
        }
    }

    // The explainability graph.
    ViveCard {
        SectionHeader(title = "Evidence contributions")
        Text(
            text = "Strength of each signal in this window. These are evidence " +
                "strengths, not a breakdown that adds up to the packet risk.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (packet.risk.contributions.isEmpty()) {
            Text(
                text = "No contributing evidence available for this window.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
            )
        } else {
            packet.risk.contributions.forEach { (key, value) ->
                ContributionBar(
                    label = contributionLabel(key),
                    value = value,
                    level = severityFor(value),
                )
            }
        }
    }

    if (packet.risk.reasons.isNotEmpty()) {
        ViveCard {
            SectionHeader(title = "Reasons")
            packet.risk.reasons.forEach { reason ->
                Text(
                    text = "• $reason",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.padding(vertical = 2.dp),
                )
            }
        }
    }

    // Model provenance belongs here, not on the primary screens.
    ViveCard {
        SectionHeader(title = "Provenance")
        InfoRow("Anti-spoof model", packet.aasist.modelVersion)
        InfoRow("ASR model", packet.asr.modelVersion)
        InfoRow("Inference time", packet.aasist.inferenceMs?.let { "${it} ms" })
        Row(modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm)) {
            StatusBadge("DEMO DATA — NOT MODEL OUTPUT")
        }
    }
}

private fun windowLabel(packet: Packet): String {
    val w = packet.window ?: return packet.timestamp
    return "%02d:%02d – %02d:%02d".format(
        w.startSec.toInt() / 60, w.startSec.toInt() % 60,
        w.endSec.toInt() / 60, w.endSec.toInt() % 60,
    )
}

private fun contributionLabel(key: String): String = when (key) {
    "synthetic" -> "Synthetic indicators"
    "intent" -> "Intent risk"
    "context" -> "Context risk"
    "speaker_consistency" -> "Speaker consistency"
    "behavior" -> "Behaviour risk"
    else -> key.replace('_', ' ').replaceFirstChar { it.uppercase() }
}
