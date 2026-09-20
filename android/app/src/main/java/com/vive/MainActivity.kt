package com.vive

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.vive.ui.ViveApp
import com.vive.ui.theme.ViveTheme

/**
 * Single activity host. All navigation is Compose-internal
 * (docs/ARCHITECTURE.md 6).
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            ViveTheme {
                ViveApp()
            }
        }
    }
}
