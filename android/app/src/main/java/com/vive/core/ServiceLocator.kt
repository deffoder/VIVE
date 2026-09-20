package com.vive.core

import com.vive.data.demo.DemoAlertRepository
import com.vive.data.demo.DemoModelRepository
import com.vive.data.demo.DemoSessionRepository
import com.vive.data.repository.AlertRepository
import com.vive.data.repository.ModelRepository
import com.vive.data.repository.SessionRepository

/**
 * Minimal dependency provider.
 *
 * A DI framework would be an unnecessary dependency at this stage
 * (CLAUDE.md: simplest architecture that satisfies the requirements). This is
 * the single place that decides which repository implementation the app uses,
 * so swapping demo for live is a one-line change here.
 *
 * Currently wired to the demo implementations; [isDemo] drives the
 * non-dismissable "Demo data" badge in the UI (docs/UI_SPEC.md 6).
 */
object ServiceLocator {

    var sessions: SessionRepository = DemoSessionRepository()
        internal set

    var alerts: AlertRepository = DemoAlertRepository()
        internal set

    var models: ModelRepository = DemoModelRepository()
        internal set

    /** True while any repository is demo-backed. */
    var isDemo: Boolean = true
        internal set

    /** Test seam: swap implementations, then call [reset]. */
    fun override(
        sessions: SessionRepository = this.sessions,
        alerts: AlertRepository = this.alerts,
        models: ModelRepository = this.models,
        isDemo: Boolean = this.isDemo,
    ) {
        this.sessions = sessions
        this.alerts = alerts
        this.models = models
        this.isDemo = isDemo
    }

    fun reset() {
        sessions = DemoSessionRepository()
        alerts = DemoAlertRepository()
        models = DemoModelRepository()
        isDemo = true
    }
}
