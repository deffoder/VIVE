package com.vive.ui.screens.call

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vive.core.UiState
import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.Packet
import com.vive.data.model.RiskLevel
import com.vive.data.model.Session
import com.vive.ui.components.ConfidenceIndicator
import com.vive.ui.components.ContributionBar
import com.vive.ui.components.FilterChipRow
import com.vive.ui.components.InfoRow
import com.vive.ui.components.MetricCard
import com.vive.ui.components.MetricRow
import com.vive.ui.components.PrimaryButton
import com.vive.ui.components.RiskGauge
import com.vive.ui.components.RiskTimeline
import com.vive.ui.components.SecondaryButton
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.TranscriptBubble
import com.vive.ui.components.ViveCard
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.screens.SessionDetailViewModel
import com.vive.ui.screens.StateHost
import com.vive.ui.theme.ViveThemeTokens

/**
 * Risk details (docs/UI_SPEC.md 4.9) - the current score decomposed by signal.
 */
@Composable
fun RiskDetailsScreen(
    viewModel: SessionDetailViewModel,
    onBack: () -> Unit,
    onOpenEvidence: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val sessionState by viewModel.session.collectAsStateWithLifecycle()
    val packetState by viewModel.packets.collectAsStateWithLifecycle()

    ViveScreenScaffold(title = "Risk details", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(sessionState, onRetry = viewModel::refresh) { session ->
                val latest = (packetState as? UiState.Success)?.data?.lastOrNull()
                val risk = session.currentRisk

                ViveCard {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        RiskGauge(
                            score = risk?.score ?: 0,
                            level = risk?.level ?: RiskLevel.LOW,
                            size = 150.dp,
                        )
                        ConfidenceIndicator(risk?.confidence)
                    }
                }

                ViveCard {
                    SectionHeader(title = "Signal breakdown")
                    if (latest == null || latest.risk.contributions.isEmpty()) {
                        Text(
                            text = "No signal breakdown available yet.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        latest.risk.contributions.forEach { (key, value) ->
                            ContributionBar(
                                label = key.replace('_', ' ').replaceFirstChar { it.uppercase() },
                                value = value,
                                level = severityFor(value),
                            )
                        }
                    }
                }

                ViveCard {
                    SectionHeader(title = "What this means")
                    Text(
                        text = "A high risk score reflects the combined evidence, not a " +
                            "verdict. Synthetic speech is not proof of fraud, and a genuine " +
                            "human voice is not proof of safety.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }

                SecondaryButton("View detailed evidence", onOpenEvidence)
            }
        }
    }
}

/**
 * Evidence details (docs/UI_SPEC.md 4.10), grouped by signal family.
 * Model versions and inference times live here, off the primary screens.
 */
@Composable
fun EvidenceDetailsScreen(
    viewModel: SessionDetailViewModel,
    onBack: () -> Unit,
    onOpenPacketTimeline: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val packetState by viewModel.packets.collectAsStateWithLifecycle()
    var tab by remember { mutableStateOf("Voice") }
    val tabs = listOf("Voice", "Speaker", "Intent", "Context")

    ViveScreenScaffold(title = "Evidence", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(packetState, onRetry = viewModel::refresh) { packets ->
                val latest = packets.lastOrNull()
                FilterChipRow(options = tabs, selected = tab, onSelect = { tab = it })

                if (latest == null) {
                    Text(
                        text = "No evidence available yet.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    ViveCard { EvidenceGroup(tab, latest) }
                }

                SecondaryButton("Open packet timeline", onOpenPacketTimeline)
            }
        }
    }
}

@Composable
private fun EvidenceGroup(tab: String, packet: Packet) {
    when (tab) {
        "Voice" -> {
            SectionHeader(title = "Anti-spoofing")
            Text(
                text = packet.aasist.score?.let { describeSynthetic(it) }
                    ?: "No anti-spoofing output for this window.",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
            packet.aasist.score?.let {
                ContributionBar("Synthetic indicators", it, level = severityFor(it))
            }
            InfoRow("Model", packet.aasist.modelVersion)
            InfoRow("Inference time", packet.aasist.inferenceMs?.let { "$it ms" })
            InfoRow("Audio quality", packet.quality.name.replace('_', ' '))
        }
        "Speaker" -> {
            SectionHeader(title = "Speaker consistency")
            Text(
                text = packet.ecapa.similarity?.let {
                    "Similarity to the enrolled reference voice."
                } ?: "No reference voice is enrolled, so speaker consistency cannot be assessed.",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
            packet.ecapa.similarity?.let {
                ContributionBar("Speaker consistency", it, level = severityFor(1.0 - it))
            }
            InfoRow("Status", packet.ecapa.status.name.replace('_', ' '))
            InfoRow("Model", packet.ecapa.modelVersion)
        }
        "Intent" -> {
            SectionHeader(title = "Intent and behaviour")
            InfoRow("Intent", packet.intent.label.name.replace('_', ' '))
            InfoRow(
                "Intent confidence",
                packet.intent.confidence?.let { "${(it * 100).toInt()}%" },
            )
            InfoRow(
                "Behaviour",
                packet.behavior.labels.takeIf { it.isNotEmpty() }
                    ?.joinToString(", ") { it.name.replace('_', ' ') },
            )
            InfoRow("Transcript", packet.asr.transcript)
        }
        else -> {
            SectionHeader(title = "Context")
            InfoRow(
                "Caller verified",
                if (packet.context.callerVerified) "Yes" else "No",
            )
            InfoRow(
                "Session authenticated",
                packet.context.sessionAuthenticated?.let { if (it) "Yes" else "No" },
            )
            InfoRow("Source", packet.context.sourceType?.name)
            InfoRow("Requested action", packet.context.requestedAction)
            packet.context.contextRisk?.let {
                ContributionBar("Context risk", it, level = severityFor(it))
            }
        }
    }
}

/** Live transcript (docs/UI_SPEC.md 4.8). */
@Composable
fun LiveTranscriptScreen(
    viewModel: SessionDetailViewModel,
    onBack: () -> Unit,
    onOpenPacket: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val transcriptState by viewModel.transcript.collectAsStateWithLifecycle()
    val sessionState by viewModel.session.collectAsStateWithLifecycle()
    val packetsState by viewModel.packets.collectAsStateWithLifecycle()
    val language = (sessionState as? UiState.Success)?.data?.language?.uppercase()

    // Whether text understanding ran is read from the PACKETS, not from a
    // hard-coded language list. The backend decides what it supports, and
    // deriving the notice from its actual reported status keeps this correct
    // if that ever changes (docs/BLOCKERS.md O11).
    val textUnderstandingUnsupported = (packetsState as? UiState.Success)?.data
        ?.any { it.intent.status == AnalyzerStatus.UNSUPPORTED_LANGUAGE } == true

    ViveScreenScaffold(title = "Live transcript", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            language?.let {
                Text(
                    text = "Detected language: $it",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (textUnderstandingUnsupported) {
                // Transcription and understanding are different capabilities,
                // and VIVE has only the first one here. Saying so plainly is
                // the whole point: silence would let a reader assume the
                // absence of a scam warning meant no scam was found.
                ViveCard {
                    Text(
                        text = "Transcription only",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = "Speech in this language is transcribed, but " +
                            "intent and behaviour analysis is not supported " +
                            "for it. No scam assessment is being made from " +
                            "this transcript.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            StateHost(
                state = transcriptState,
                onRetry = viewModel::refresh,
                emptyTitle = "No speech yet",
                emptyDescription = "Transcribed speech appears here as the call proceeds.",
            ) { lines ->
                Column(verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md)) {
                    lines.forEach { line ->
                        TranscriptBubble(
                            line = line,
                            isLocal = line.speaker == "You",
                            modifier = Modifier.clickable { onOpenPacket(line.packetId) },
                        )
                    }
                }
            }
        }
    }
}



/** Call summary (docs/UI_SPEC.md 4.13) - the post-call report. */
@Composable
fun CallSummaryScreen(
    viewModel: SessionDetailViewModel,
    onBack: () -> Unit,
    onOpenTranscript: () -> Unit,
    onOpenPacketTimeline: () -> Unit,
    onOpenRiskDetails: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val sessionState by viewModel.session.collectAsStateWithLifecycle()
    val packetState by viewModel.packets.collectAsStateWithLifecycle()

    ViveScreenScaffold(title = "Call summary", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(sessionState, onRetry = viewModel::refresh) { session ->
                val packets = (packetState as? UiState.Success)?.data.orEmpty()
                CallSummaryContent(session, packets)

                SecondaryButton("View risk details", onOpenRiskDetails)
                SecondaryButton("View transcript", onOpenTranscript)
                PrimaryButton("View packet timeline", onOpenPacketTimeline)
            }
        }
    }
}

@Composable
private fun CallSummaryContent(session: Session, packets: List<Packet>) {
    val overall = session.overallRisk
    val current = session.currentRisk

    ViveCard {
        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = session.sessionId,
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
            session.startedAt?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            RiskGauge(
                score = overall?.score ?: 0,
                level = overall?.level ?: RiskLevel.LOW,
                size = 150.dp,
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.md),
            )
            ConfidenceIndicator(overall?.confidence)
        }
    }

    MetricRow {
        MetricCard(
            value = "${current?.score ?: 0}",
            label = "Current risk",
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            value = formatDuration(session.durationSec),
            label = "Duration",
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            value = "${session.packetsProcessed}",
            label = "Packets",
            modifier = Modifier.weight(1f),
        )
    }

    ViveCard {
        SectionHeader(title = "Risk progression")
        RiskTimeline(
            scores = packets.map { it.risk.score },
            level = overall?.level ?: RiskLevel.LOW,
        )
    }

    // Escalation timings. A null reading means "not reached" - information,
    // not a missing value, so it is stated rather than blanked.
    ViveCard {
        SectionHeader(title = "Escalation")
        InfoRow("First anomaly", session.timings.firstAnomalySec?.let { "${it}s" } ?: "Not reached")
        InfoRow("First warning", session.timings.firstWarningSec?.let { "${it}s" } ?: "Not reached")
        InfoRow("First high", session.timings.firstHighSec?.let { "${it}s" } ?: "Not reached")
        InfoRow("Critical escalation", session.timings.firstCriticalSec?.let { "${it}s" } ?: "Not reached")
    }

    val reasons = packets.lastOrNull()?.risk?.reasons.orEmpty()
    if (reasons.isNotEmpty()) {
        ViveCard {
            SectionHeader(title = "Evidence summary")
            reasons.forEach {
                Text(
                    text = "• $it",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.padding(vertical = 2.dp),
                )
            }
        }
    }
}

/**
 * Incoming call (docs/UI_SPEC.md 4.6).
 *
 * States the analysis path available. For cellular this screen must say audio
 * is not analysed - the platform does not permit it (docs/ARCHITECTURE.md 7).
 */
@Composable
fun IncomingCallScreen(
    onAccept: () -> Unit,
    onDecline: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ViveScreenScaffold(title = "Incoming call", onBack = onDecline, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.sm),
                ) {
                    Text(
                        text = "+91 98765 43210",
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = "Unknown caller · not in contacts",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            ViveCard {
                SectionHeader(title = "Analysis path")
                Text(
                    text = "This call will be analysed over the authorized in-app audio " +
                        "path. Ordinary cellular calls are screened by number and metadata " +
                        "only — their audio is not accessible to VIVE.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }

            PrimaryButton("Accept and analyse", onAccept)
            SecondaryButton("Decline", onDecline)
        }
    }
}
