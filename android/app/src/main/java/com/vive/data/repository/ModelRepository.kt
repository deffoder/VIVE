package com.vive.data.repository

import com.vive.core.ViveResult
import com.vive.data.model.ModelInfo
import com.vive.data.model.ReadyState

interface ModelRepository {
    suspend fun listModels(): ViveResult<List<ModelInfo>>

    /** Drives the persistent Demo data badge (docs/UI_SPEC.md 6). */
    suspend fun ready(): ViveResult<ReadyState>
}
