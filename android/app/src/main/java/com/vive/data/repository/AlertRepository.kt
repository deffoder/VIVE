package com.vive.data.repository

import com.vive.core.ViveResult
import com.vive.data.model.Alert

interface AlertRepository {
    suspend fun listAlerts(sessionId: String? = null): ViveResult<List<Alert>>
    suspend fun acknowledge(alertId: String): ViveResult<Alert>
}
