package com.vive.ui.screens.more

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vive.data.model.AdapterMode
import com.vive.data.model.ModelInfo
import com.vive.navigation.ViveDestination
import com.vive.ui.components.InfoRow
import com.vive.ui.components.NavigationRow
import com.vive.ui.components.PrimaryButton
import com.vive.ui.components.SecondaryButton
import com.vive.ui.components.SectionHeader
import com.vive.ui.components.StatusBadge
import com.vive.ui.components.ViveCard
import com.vive.ui.components.ViveScreenBody
import com.vive.ui.components.ViveScreenScaffold
import com.vive.ui.screens.ModelsViewModel
import com.vive.ui.screens.StateHost
import com.vive.ui.theme.ViveThemeTokens

/** More menu (docs/UI_SPEC.md 3.1) - everything outside the four tabs. */
@Composable
fun MoreScreen(
    onNavigate: (ViveDestination) -> Unit,
    modifier: Modifier = Modifier,
) {
    ViveScreenScaffold(title = "More", modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                NavigationRow(Icons.Filled.Build, "Reports & insights") {
                    onNavigate(ViveDestination.Reports)
                }
                NavigationRow(Icons.Filled.Info, "Model information") {
                    onNavigate(ViveDestination.ModelInformation)
                }
                NavigationRow(Icons.Filled.Share, "Connected services") {
                    onNavigate(ViveDestination.ConnectedServices)
                }
                NavigationRow(Icons.Filled.Settings, "API integrations") {
                    onNavigate(ViveDestination.ApiIntegrations)
                }
            }
            ViveCard {
                NavigationRow(Icons.Filled.Settings, "Settings") {
                    onNavigate(ViveDestination.Settings)
                }
                NavigationRow(Icons.Filled.Person, "Profile") {
                    onNavigate(ViveDestination.Profile)
                }
                NavigationRow(Icons.Filled.Email, "Help & support") {
                    onNavigate(ViveDestination.Help)
                }
                NavigationRow(Icons.Filled.Info, "About") {
                    onNavigate(ViveDestination.About)
                }
            }
            ViveCard {
                NavigationRow(Icons.Filled.AccountCircle, "Log out") {
                    onNavigate(ViveDestination.Logout)
                }
            }
        }
    }
}

/**
 * Model information (docs/UI_SPEC.md 4.20).
 *
 * The mode badge is the point of this screen: it states per model whether the
 * output is demo or real, so a demo can never be mistaken for inference. No
 * accuracy is shown, because none has been measured (docs/ML_SPEC.md 8.5).
 */
@Composable
fun ModelInformationScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ModelsViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    ViveScreenScaffold(title = "Model information", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            StateHost(state, onRetry = viewModel::refresh) { models ->
                Text(
                    text = "Accuracy is not shown because none has been measured. " +
                        "Figures appear here only once they come from a recorded evaluation run.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Column(verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.md)) {
                    models.forEach { ModelInfoCard(it) }
                }
            }
        }
    }
}

@Composable
private fun ModelInfoCard(model: ModelInfo) {
    ViveCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = model.displayName,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = model.purpose,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            StatusBadge(if (model.mode == AdapterMode.MOCK) "DEMO" else "REAL")
        }
        InfoRow("Identifier", model.id)
        InfoRow("Version", model.version.takeIf { it.isNotBlank() })
        InfoRow("Status", model.status.name.replace('_', ' '))
    }
}

/** Reports & insights (docs/UI_SPEC.md 4.16). */
@Composable
fun ReportsScreen(onBack: () -> Unit, modifier: Modifier = Modifier) {
    ViveScreenScaffold(title = "Reports", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                SectionHeader(title = "Aggregate insights")
                Text(
                    text = "Trends are computed from completed sessions. With only demo " +
                        "sessions available, no meaningful aggregate can be reported yet.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** Settings (docs/UI_SPEC.md 4.17). */
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    onNavigate: (ViveDestination) -> Unit,
    modifier: Modifier = Modifier,
) {
    ViveScreenScaffold(title = "Settings", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                NavigationRow(Icons.Filled.Person, "Account", subtitle = "Manage your account") {
                    onNavigate(ViveDestination.Profile)
                }
                NavigationRow(Icons.Filled.Notifications, "Notifications", subtitle = "Alert preferences") {}
                NavigationRow(Icons.Filled.Share, "Connected services") {
                    onNavigate(ViveDestination.ConnectedServices)
                }
                NavigationRow(Icons.Filled.Lock, "Privacy & security") {}
                NavigationRow(Icons.Filled.Info, "Model information") {
                    onNavigate(ViveDestination.ModelInformation)
                }
            }
            ViveCard {
                SectionHeader(title = "Preferences")
                InfoRow("Language", "English")
                InfoRow("Theme", "Light")
                InfoRow("Version", "0.1.0")
            }
        }
    }
}

/** Connected services (docs/UI_SPEC.md 4.18). */
@Composable
fun ConnectedServicesScreen(onBack: () -> Unit, modifier: Modifier = Modifier) {
    ViveScreenScaffold(title = "Connected services", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            Text(
                text = "Nothing is connected. Channels appear as connected only when a " +
                    "real integration has been configured.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ViveCard {
                SectionHeader(title = "Alert channels")
                InfoRow("Email", "Not configured")
                InfoRow("SMS", "Not configured")
                InfoRow("Push notifications", "Not configured")
            }
        }
    }
}

/** API integrations (docs/UI_SPEC.md 4.19). */
@Composable
fun ApiIntegrationsScreen(onBack: () -> Unit, modifier: Modifier = Modifier) {
    ViveScreenScaffold(title = "API integrations", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            Text(
                text = "No integration is shown as connected unless it actually is.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ViveCard {
                SectionHeader(title = "Endpoints")
                InfoRow("Backend", "Not connected")
                InfoRow("Webhook", "Not configured")
                InfoRow("Banking APIs", "Not configured")
            }
            ViveCard {
                SectionHeader(title = "Security")
                Text(
                    text = "Secrets are never displayed after entry. Webhook payloads carry " +
                        "risk metadata only — never transcripts or audio.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

/** Profile (docs/UI_SPEC.md 4.21). */
@Composable
fun ProfileScreen(onBack: () -> Unit, modifier: Modifier = Modifier) {
    ViveScreenScaffold(title = "Profile", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                SectionHeader(title = "Account")
                InfoRow("Name", "Demo user")
                InfoRow("Signed in", "No")
            }
        }
    }
}

/** Help & support (docs/UI_SPEC.md 4.22). */
@Composable
fun HelpScreen(onBack: () -> Unit, modifier: Modifier = Modifier) {
    ViveScreenScaffold(title = "Help & support", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                NavigationRow(Icons.Filled.Info, "How VIVE reads risk") {}
                NavigationRow(Icons.Filled.Info, "What the risk levels mean") {}
                NavigationRow(Icons.Filled.Email, "Contact support") {}
            }
            ViveCard {
                SectionHeader(title = "Understanding risk")
                Text(
                    text = "Risk score reflects the strength of the combined evidence. " +
                        "Confidence describes how much that assessment can be trusted. " +
                        "They are different measures and are always shown separately.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

/** About (docs/UI_SPEC.md 4.23). */
@Composable
fun AboutScreen(onBack: () -> Unit, modifier: Modifier = Modifier) {
    ViveScreenScaffold(title = "About", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        text = "VIVE",
                        style = MaterialTheme.typography.headlineSmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Text(
                        text = "Voice Integrity Verification Engine",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "Version 0.1.0",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = ViveThemeTokens.spacing.sm),
                    )
                }
            }
            ViveCard {
                SectionHeader(title = "What VIVE does")
                Text(
                    text = "VIVE is decision support. It surfaces evidence and calibrated " +
                        "risk for authorized voice communication. It does not transfer money, " +
                        "retrieve credentials or make banking decisions.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            ViveCard {
                SectionHeader(title = "Platform limitation")
                Text(
                    text = "Ordinary cellular call audio is not accessible to a third-party " +
                        "Android app. Cellular calls are screened by number and metadata only. " +
                        "Full analysis requires the authorized in-app audio path.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

/** Logout confirmation (docs/UI_SPEC.md 4.24). Confirmation is required. */
@Composable
fun LogoutScreen(
    onBack: () -> Unit,
    onConfirm: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ViveScreenScaffold(title = "Log out", onBack = onBack, modifier = modifier) { padding ->
        ViveScreenBody(padding) {
            ViveCard {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(ViveThemeTokens.spacing.sm),
                ) {
                    Text(
                        text = "Log out of VIVE?",
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = "Cached session data on this device will be cleared.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            PrimaryButton("Log out", onConfirm)
            SecondaryButton("Cancel", onBack)
        }
    }
}
