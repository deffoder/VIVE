package com.vive.ui.screens.onboarding

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.vive.ui.components.IconChip
import com.vive.ui.components.PrimaryButton
import com.vive.ui.components.SecondaryButton
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.ViveCard
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.theme.ViveThemeTokens

/**
 * Splash (docs/UI_SPEC.md 4.1).
 *
 * Static mark and wordmark. No animated waveform - CLAUDE.md forbids fake
 * voice-wave animation, and there is no audio to visualise here anyway.
 */
@Composable
fun SplashScreen(onContinue: () -> Unit, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.sm),
        ) {
            Text(
                text = "VIVE",
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                text = "Voice Integrity. A Safer Tomorrow.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            PrimaryButton(
                text = "Get started",
                onClick = onContinue,
                modifier = Modifier
                    .padding(top = ViveThemeTokens.spacing.xl)
                    .fillMaxWidth(0.7f),
            )
        }
    }
}

private data class OnboardingPage(val title: String, val body: String)

/** Onboarding (docs/UI_SPEC.md 4.2) - three pages, skippable. */
@Composable
fun OnboardingScreen(
    onFinish: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val pages = listOf(
        OnboardingPage(
            "Protect yourself from voice scams",
            "VIVE analyses authorized calls in real time and surfaces the evidence behind " +
                "its assessment.",
        ),
        OnboardingPage(
            "Evidence, not verdicts",
            "Synthetic speech is not proof of fraud, and a genuine human voice is not proof " +
                "of safety. VIVE shows you what it found and how confident it is.",
        ),
        OnboardingPage(
            "Inspect every window",
            "Audio is analysed in short overlapping windows. Any one of them can be opened " +
                "to see exactly which signals contributed.",
        ),
    )
    var index by remember { mutableIntStateOf(0) }
    val page = pages[index]

    ViveScreenScaffold(title = "Welcome", showDemoBadge = false, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
                ) {
                    Text(
                        text = page.title,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                        textAlign = TextAlign.Center,
                    )
                    Text(
                        text = page.body,
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                    PageDots(count = pages.size, selected = index)
                }
            }

            PrimaryButton(
                text = if (index == pages.lastIndex) "Continue" else "Next",
                onClick = { if (index == pages.lastIndex) onFinish() else index++ },
            )
            TextButton(
                onClick = onFinish,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Skip") }
        }
    }
}

@Composable
private fun PageDots(count: Int, selected: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        repeat(count) { i ->
            Box(
                modifier = Modifier
                    .size(if (i == selected) 9.dp else 7.dp)
                    .background(
                        if (i == selected) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.outline,
                        CircleShape,
                    ),
            )
        }
    }
}

/**
 * Permissions (docs/UI_SPEC.md 4.3).
 *
 * Each permission states WHY it is needed. The telephony boundary is stated
 * here, because this is where a user would otherwise assume VIVE can hear
 * ordinary cellular calls.
 */
@Composable
fun PermissionsScreen(
    onContinue: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ViveScreenScaffold(title = "Permissions", showDemoBadge = false, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            Text(
                text = "VIVE asks for each permission at the point it is used, and explains why.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ViveCard {
                PermissionRow(
                    Icons.Filled.Mic,
                    "Microphone",
                    "Analyse audio on the authorized in-app call path.",
                )
                PermissionRow(
                    Icons.Filled.Call,
                    "Phone",
                    "Detect call state and screen incoming numbers.",
                )
                PermissionRow(
                    Icons.Filled.Notifications,
                    "Notifications",
                    "Deliver risk alerts. Alert text never contains transcript content.",
                )
                PermissionRow(
                    Icons.Filled.Storage,
                    "Storage (optional)",
                    "Retain call evidence only if you turn retention on.",
                )
            }
            ViveCard {
                SectionHeader(title = "What VIVE cannot do")
                Text(
                    text = "Android does not allow a third-party app to capture ordinary " +
                        "cellular call audio. Those calls are screened by number and metadata " +
                        "only. Full analysis requires the authorized in-app audio path.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            PrimaryButton("Continue", onContinue)
        }
    }
}

@Composable
private fun PermissionRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    reason: String,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = ViveThemeTokens.spacing.sm),
        horizontalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md),
    ) {
        IconChip(icon = icon, contentDescription = null)
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = reason,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** Login / account setup (docs/UI_SPEC.md 4.4). */
@Composable
fun LoginScreen(
    onSignedIn: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ViveScreenScaffold(title = "Sign in", showDemoBadge = false, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                SectionHeader(title = "Welcome back")
                Text(
                    text = "Authentication is not wired up in this build. Continuing opens " +
                        "the app against demo data.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            PrimaryButton("Continue", onSignedIn)
        }
    }
}
