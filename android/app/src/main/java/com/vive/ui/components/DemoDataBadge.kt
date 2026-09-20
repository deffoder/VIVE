package com.vive.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.vive.ui.theme.RiskMedium
import com.vive.ui.theme.RiskMediumContainer

/**
 * Persistent, non-dismissable indicator shown whenever any adapter is running
 * in mock mode (docs/UI_SPEC.md 6).
 *
 * This exists so a demo can never be mistaken for production inference. It must
 * not be hidden, collapsed or made dismissable.
 */
@Composable
fun DemoDataBadge(modifier: Modifier = Modifier) {
    val text = "Demo data"
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = RiskMedium,
        modifier = modifier
            .background(RiskMediumContainer, MaterialTheme.shapes.small)
            .padding(PaddingValues(horizontal = 8.dp, vertical = 3.dp))
            .semantics { contentDescription = "$text. Values shown are not real model output." },
    )
}
