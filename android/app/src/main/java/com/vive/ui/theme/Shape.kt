package com.vive.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp

/** VIVE shapes. Source of truth: docs/UI_SPEC.md 2.3. */
val ViveShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),   // chips, pills
    medium = RoundedCornerShape(14.dp),  // buttons
    large = RoundedCornerShape(20.dp),   // cards
    extraLarge = RoundedCornerShape(28.dp),
)
