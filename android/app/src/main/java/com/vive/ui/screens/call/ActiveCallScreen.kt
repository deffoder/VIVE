package com.vive.ui.screens.call

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vive.core.UiState
import com.vive.data.model.Behavior
import com.vive.data.model.Intent
import com.vive.data.model.Packet
import com.vive.data.model.RiskLevel
import com.vive.data.model.Session
import com.vive.ui.components.ConfidenceIndicator
import com.vive.ui.components.EvidenceRow
import com.vive.ui.components.MetricCard
import com.vive.ui.components.MetricRow
import com.vive.ui.components.PrimaryButton
import com.vive.ui.components.RiskGauge
import com.vive.ui.components.RiskTimeline
import com.vive.ui.components.SecondaryButton
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.ViveCard
import com.vive.ui.screens.SessionDetailViewModel
import com.vive.ui.screens.StateHost
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.theme.ViveThemeTokens

/**
 * Active call analysis - the most important screen (docs/UI_SPEC.md 4.7).
 *
 * Order is deliberate and matches the spec: gauge, confidence, key metrics,
 * "why is this risky", risk progression, then entry points to the deeper views.
 * The score and confidence are adjacent but visually distinct, never merged.
 */
@Composable
fun ActiveCallScreen(
    sessionId: String,
    viewModel: SessionDetailViewModel,
    onBack: () -> Unit,
    onOpenTranscript: () -> Unit,
    onOpenRiskDetails: () -> Unit,
    onOpenPacketTimeline: () -> Unit,
    onEndCall: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val sessionState by viewModel.session.collectAsStateWithLifecycle()
    val packetState by viewModel.packets.collectAsStateWithLifecycle()

    ViveScreenScaffold(title = "Call analysis", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(sessionState, onRetry = viewModel::refresh) { session ->
                val packets = (packetState as? UiState.Success)?.data.orEmpty()
                ActiveCallContent(
                    session = session,
                    packets = packets,
                    onOpenTranscript = onOpenTranscript,
                    onOpenRiskDetails = onOpenRiskDetails,
                    onOpenPacketTimeline = onOpenPacketTimeline,
                    onEndCall = onEndCall,
                )
            }
        }
    }
}

@Composable
private fun ActiveCallContent(
    session: Session,
    packets: List<Packet>,
    onOpenTranscript: () -> Unit,
    onOpenRiskDetails: () -> Unit,
    onOpenPacketTimeline: () -> Unit,
    onEndCall: () -> Unit,
) {
    val risk = session.currentRisk
    val latest = packets.lastOrNull()

    // 1-2. Gauge + confidence, as one visual unit but two distinct readings.
    ViveCard {
        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.sm),
        ) {
            Text(
                text = "Voice analysis in progress",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            RiskGauge(
                score = risk?.score ?: 0,
                level = risk?.level ?: RiskLevel.LOW,
            )
            ConfidenceIndicator(risk?.confidence)
            Text(
                text = "Risk score and confidence are separate measures.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    // 3. Duration, packets, language.
    MetricRow {
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
        MetricCard(
            value = session.language?.uppercase() ?: "—",
            label = "Language",
            modifier = Modifier.weight(1f),
        )
    }

    // 4. Why is this call risky - the five evidence signals.
    ViveCard {
        SectionHeader(title = "Why is this call risky?")
        EvidenceSignals(latest, onOpenRiskDetails)
    }

    // 5. Risk progression.
    ViveCard {
        SectionHeader(title = "Risk progression")
        Text(
            text = "Score per analysis window",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        RiskTimeline(
            scores = packets.map { it.risk.score },
            level = risk?.level ?: RiskLevel.LOW,
            modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
        )
    }

    // 6. Entry points to the deeper views.
    Column(verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md)) {
        SecondaryButton("View live transcript", onOpenTranscript)
        SecondaryButton("View packet timeline", onOpenPacketTimeline)
        PrimaryButton("End call", onEndCall)
    }
}

/**
 * The five signals from docs/UI_SPEC.md 4.7.
 *
 * Every row states what was observed in words. A signal with no model output
 * reads "Unavailable" and carries no severity - never 0%, never a guess.
 */
@Composable
private fun EvidenceSignals(packet: Packet?, onOpenRiskDetails: () -> Unit) {
    if (packet == null) {
        Text(
            text = "Waiting for the first analysis window.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }

    EvidenceRow(
        icon = Icons.Filled.GraphicEq,
        title = "Synthetic voice indicators",
        subtitle = packet.aasist.score?.let { describeSynthetic(it) } ?: "No analysis available",
        severity = packet.aasist.score?.let { severityFor(it) },
        severityText = if (packet.aasist.score == null) "Unavailable" else null,
        onClick = onOpenRiskDetails,
    )
    EvidenceRow(
        icon = Icons.Filled.Person,
        title = "Speaker consistency",
        subtitle = packet.ecapa.similarity?.let { "Similarity to the reference voice" }
            ?: "No enrolled reference voice",
        severity = packet.ecapa.similarity?.let { severityFor(1.0 - it) },
        severityText = if (packet.ecapa.similarity == null) "No reference" else null,
        onClick = onOpenRiskDetails,
    )
    EvidenceRow(
        icon = Icons.Filled.Lock,
        title = "Intent risk",
        subtitle = packet.intent.label.name.replace('_', ' ').lowercase()
            .replaceFirstChar { it.uppercase() },
        severity = intentSeverity(packet.intent.label),
        severityText = if (packet.intent.confidence == null) "Unavailable" else null,
        onClick = onOpenRiskDetails,
    )
    EvidenceRow(
        icon = Icons.Filled.Group,
        title = "Behaviour risk",
        subtitle = packet.behavior.labels.takeIf { it.isNotEmpty() }
            ?.joinToString(", ") { it.name.replace('_', ' ').lowercase() }
            ?.replaceFirstChar { it.uppercase() }
            ?: "No persuasion behaviour detected",
        severity = behaviorSeverity(packet.behavior.labels),
        severityText = if (packet.behavior.confidence == null) "Unavailable" else null,
        onClick = onOpenRiskDetails,
    )
    EvidenceRow(
        icon = Icons.Filled.Warning,
        title = "Context risk",
        subtitle = if (packet.context.callerVerified) "Caller independently verified"
        else "Caller not independently verified",
        severity = packet.context.contextRisk?.let { severityFor(it) },
        severityText = if (packet.context.contextRisk == null) "Unavailable" else null,
        onClick = onOpenRiskDetails,
    )
}

/**
 * Evidence-shaped phrasing. CLAUDE.md forbids "87% AI voice" because the
 * AASIST score is spoof likelihood, not a probability that the call is fraud.
 */
internal fun describeSynthetic(score: Double): String = when {
    score >= 0.75 -> "Strong synthetic-voice indicators"
    score >= 0.5 -> "Elevated synthetic-voice indicators"
    score >= 0.25 -> "Some synthetic-voice indicators"
    else -> "Few synthetic-voice indicators"
}

/**
 * Intent severity comes from WHAT was asked for, not from how confident the
 * classifier was. A confidently-identified normal conversation is low risk;
 * reading confidence as risk would label it "High", which is exactly the kind
 * of misleading presentation CLAUDE.md forbids.
 */
internal fun intentSeverity(label: Intent): RiskLevel = when (label) {
    Intent.NORMAL_CONVERSATION -> RiskLevel.LOW
    Intent.UNKNOWN -> RiskLevel.LOW
    Intent.URGENT_ACTION,
    Intent.CONFIDENTIAL_INFORMATION,
    Intent.ACCOUNT_CHANGE_REQUEST -> RiskLevel.MEDIUM
    Intent.OTP_REQUEST,
    Intent.PASSWORD_REQUEST,
    Intent.CARD_DETAILS_REQUEST,
    Intent.BANKING_CREDENTIAL_REQUEST,
    Intent.MONEY_TRANSFER_REQUEST,
    Intent.REMOTE_ACCESS_REQUEST,
    Intent.THREAT_OR_INTIMIDATION -> RiskLevel.HIGH
}

/** Behaviour severity likewise comes from WHICH behaviours were observed. */
internal fun behaviorSeverity(labels: List<Behavior>): RiskLevel = when {
    labels.isEmpty() || labels == listOf(Behavior.NORMAL) -> RiskLevel.LOW
    labels.any {
        it == Behavior.THREAT || it == Behavior.AUTHORITY_IMPERSONATION || it == Behavior.FEAR
    } -> RiskLevel.HIGH
    else -> RiskLevel.MEDIUM
}

/** Maps a 0..1 evidence strength onto the risk scale for pill colouring. */
internal fun severityFor(value: Double): RiskLevel = when {
    value >= 0.85 -> RiskLevel.CRITICAL
    value >= 0.65 -> RiskLevel.HIGH
    value >= 0.4 -> RiskLevel.MEDIUM
    else -> RiskLevel.LOW
}

internal fun formatDuration(seconds: Int): String =
    "%02d:%02d".format(seconds / 60, seconds % 60)

