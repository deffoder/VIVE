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
import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import com.vive.audio.CaptureState
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
            LiveCaptureCard(viewModel)
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

/**
 * Microphone capture control.
 *
 * Holds the runtime permission flow, because `RECORD_AUDIO` is a dangerous
 * permission: declaring it in the manifest grants nothing on API 23+, and
 * capture must not be attempted until the user has actually said yes.
 *
 * What it reports is capture state and windows SENT - not analysis. Whether
 * those windows produced anything is the backend's answer, rendered by the
 * rest of the screen.
 */
@Composable
private fun LiveCaptureCard(viewModel: SessionDetailViewModel) {
    val context = LocalContext.current
    val captureState by viewModel.captureState.collectAsStateWithLifecycle()
    val windowsSent by viewModel.windowsSent.collectAsStateWithLifecycle()

    var permissionDenied by remember { mutableStateOf(false) }
    val granted = ContextCompat.checkSelfPermission(
        context, Manifest.permission.RECORD_AUDIO,
    ) == PackageManager.PERMISSION_GRANTED

    val requestPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { allowed ->
        permissionDenied = !allowed
        if (allowed) viewModel.startCapture(context)
    }

    val capturing = captureState is CaptureState.Capturing ||
        captureState is CaptureState.Starting

    ViveCard {
        SectionHeader(title = "Live microphone analysis")
        Text(
            text = when (val state = captureState) {
                is CaptureState.Idle -> "Not capturing."
                is CaptureState.Starting -> "Starting microphone..."
                is CaptureState.Capturing ->
                    "Capturing. $windowsSent analysis windows sent to the backend."
                is CaptureState.Stopping -> "Stopping..."
                is CaptureState.Completed ->
                    "Capture ended. $windowsSent windows were sent."
                is CaptureState.Failed -> state.reason
            },
            style = MaterialTheme.typography.bodyMedium,
            color = if (captureState is CaptureState.Failed) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        if (permissionDenied) {
            Text(
                text = "Microphone access is required to analyse live audio. " +
                    "Nothing is captured without it.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
            )
        }
        Text(
            text = "Analyses this device's microphone during an authorized " +
                "in-app session. Two-way cellular call audio is not accessible " +
                "to third-party Android apps.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
        )
        // Speaker enrolment. Without a reference voice the speaker channel
        // reports NO_REFERENCE on every packet - correct, but inert. Enrolling
        // is what makes that comparison possible at all (docs/BLOCKERS.md O3).
        val enrolment by viewModel.enrolment.collectAsStateWithLifecycle()
        enrolment?.let { status ->
            Text(
                text = status,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
            )
        }
        if (!capturing) {
            SecondaryButton(
                text = "Enrol reference voice (4s)",
                onClick = {
                    if (granted) {
                        viewModel.enrolSpeaker(context)
                    } else {
                        requestPermission.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
            )
        }
        if (capturing) {
            SecondaryButton(
                text = "Stop microphone",
                onClick = viewModel::stopCapture,
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.md),
            )
        } else {
            PrimaryButton(
                text = "Start microphone analysis",
                onClick = {
                    permissionDenied = false
                    if (granted) {
                        viewModel.startCapture(context)
                    } else {
                        requestPermission.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                modifier = Modifier.padding(top = ViveThemeTokens.spacing.md),
            )
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

    // Anti-spoofing. Phase 9 measured this model at chance on the only
    // two-class probe VIVE has (EER 0.4333, 90% interval 0.3500-0.5000, which
    // contains 0.50 - docs/EVALUATION.md 5). So the row reports that the model
    // RAN, never what it "found": a graded scale would imply the number
    // discriminates, and no severity is attached because a colour is a claim.
    EvidenceRow(
        icon = Icons.Filled.GraphicEq,
        title = "Anti-spoofing signal",
        subtitle = if (packet.aasist.status.producedAValue) {
            "Inconclusive - this model is not validated on call audio"
        } else {
            packet.aasist.status.absenceExplanation()
        },
        severity = null,
        severityText = if (packet.aasist.status.producedAValue) "Inconclusive"
        else packet.aasist.status.absenceLabel(),
        onClick = onOpenRiskDetails,
    )
    EvidenceRow(
        icon = Icons.Filled.Person,
        title = "Speaker consistency",
        subtitle = if (packet.ecapa.status.producedAValue) {
            "Similarity to the enrolled reference voice"
        } else {
            packet.ecapa.status.absenceExplanation()
        },
        severity = packet.ecapa.similarity
            ?.takeIf { packet.ecapa.status.producedAValue }
            ?.let { severityFor(1.0 - it) },
        severityText = if (packet.ecapa.status.producedAValue) null
        else packet.ecapa.status.absenceLabel(),
        onClick = onOpenRiskDetails,
    )
    // Intent and behaviour: an analyzer that declined to run must never render
    // as one that ran and found nothing. Tamil reports UNSUPPORTED_LANGUAGE on
    // every packet by design (docs/BLOCKERS.md O11).
    EvidenceRow(
        icon = Icons.Filled.Lock,
        title = "Intent",
        subtitle = if (packet.intent.status.producedAValue) {
            packet.intent.label.name.replace('_', ' ').lowercase()
                .replaceFirstChar { it.uppercase() }
        } else {
            packet.intent.status.absenceExplanation()
        },
        severity = if (packet.intent.status.producedAValue) {
            intentSeverity(packet.intent.label)
        } else {
            null
        },
        severityText = if (packet.intent.status.producedAValue) null
        else packet.intent.status.absenceLabel(),
        onClick = onOpenRiskDetails,
    )
    EvidenceRow(
        icon = Icons.Filled.Group,
        title = "Behaviour",
        subtitle = if (!packet.behavior.status.producedAValue) {
            packet.behavior.status.absenceExplanation()
        } else {
            packet.behavior.labels.takeIf { it.isNotEmpty() }
                ?.joinToString(", ") { it.name.replace('_', ' ').lowercase() }
                ?.replaceFirstChar { it.uppercase() }
                ?: "No persuasion behaviour detected"
        },
        severity = if (packet.behavior.status.producedAValue) {
            behaviorSeverity(packet.behavior.labels)
        } else {
            null
        },
        severityText = if (packet.behavior.status.producedAValue) null
        else packet.behavior.status.absenceLabel(),
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
 * How a raw anti-spoof score may be described, which is: barely at all.
 *
 * This used to return a graded scale - "Strong" / "Elevated" / "Some" / "Few"
 * synthetic-voice indicators. CLAUDE.md already forbade "87% AI voice", and
 * the wording obeyed that, but the GRADE was still a claim: it told the user
 * the number tracked reality closely enough to be binned.
 *
 * Phase 9 measured that it does not. Against the only two-class probe VIVE
 * has, AASIST separates synthetic from genuine speech at chance - EER 0.4333
 * with a 90% interval of 0.3500-0.5000, which contains 0.50, at every window
 * length tested (docs/EVALUATION.md 5, docs/BLOCKERS.md O12). A scale built on
 * a signal measured at chance reads as evidence and is not.
 *
 * The score is still shown in the packet detail view, as a raw model output
 * with its limitation stated, because hiding it would be its own kind of
 * dishonesty. It is simply never graded or coloured.
 */
internal fun describeSynthetic(score: Double): String =
    "Raw model output %.2f - not validated for this audio".format(score)

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

