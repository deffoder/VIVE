package com.vive

import android.app.Application
import com.vive.core.ViveLog

/**
 * Application entry point.
 *
 * Deliberately thin. Dependency wiring lives in ServiceLocator rather than a DI
 * framework - Hilt would be an unnecessary dependency at this stage
 * (CLAUDE.md: avoid overengineering, simplest architecture that works).
 */
class ViveApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        ViveLog.i(TAG, "VIVE ${BuildConfig.VERSION_NAME} starting")
    }

    private companion object {
        const val TAG = "ViveApplication"
    }
}
