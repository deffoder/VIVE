package com.vive

import android.app.Application
import com.vive.core.ServiceLocator
import com.vive.core.ViveLog
import com.vive.core.ViveResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

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
        resolveAdapterMode()
    }

    /**
     * Asks the backend once, at start-up, whether it is running real models.
     *
     * The "Demo data" badge is a claim about what is on screen, so it has to
     * be answered by the backend rather than assumed. Before this, the badge
     * defaulted to shown and only cleared once an analysis packet arrived -
     * which meant Home, Sessions and Alerts were all badged as demo data
     * while displaying real backend content, for as long as the user stayed
     * off the live-call screen.
     *
     * Failure is silent and leaves the badge shown. That is the safe
     * direction: if VIVE cannot confirm the models are real, saying so
     * understates the product rather than overstating it.
     */
    private fun resolveAdapterMode() {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            when (val ready = ServiceLocator.models.ready()) {
                is ViveResult.Success -> {
                    ServiceLocator.observeAdapterMode(ready.data.hasMockAdapter)
                    ViveLog.i(TAG, "adapters are " +
                        if (ready.data.hasMockAdapter) "mock" else "real")
                }
                is ViveResult.Failure ->
                    ViveLog.d(TAG) { "adapter mode unresolved; badge stays on" }
            }
        }
    }

    private companion object {
        const val TAG = "ViveApplication"
    }
}
