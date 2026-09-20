package com.vive.telephony

import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.os.Build

/**
 * Call-screening role management — PATH A setup flow.
 *
 * From Android 10 (API 29) a call-screening service only runs if the user has
 * granted the app `ROLE_CALL_SCREENING`, which the user must confirm in a
 * system dialog. It cannot be granted programmatically.
 *
 * Below API 29 the role API does not exist; the service may be bound directly,
 * but availability varies by OEM, so the UI must not promise screening works.
 */
object CallScreeningRole {

    /** True when this device exposes the role API at all. */
    val isSupported: Boolean
        get() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q

    /** True when VIVE currently holds the call-screening role. */
    fun isHeld(context: Context): Boolean {
        if (!isSupported) return false
        val manager = context.getSystemService(RoleManager::class.java) ?: return false
        return manager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING) &&
            manager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)
    }

    /**
     * Intent that opens the system role-request dialog.
     *
     * Returns null when the role is unavailable, so a caller can show an honest
     * "not supported on this device" state instead of a button that does nothing.
     */
    fun requestIntent(context: Context): Intent? {
        if (!isSupported) return null
        val manager = context.getSystemService(RoleManager::class.java) ?: return null
        if (!manager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) return null
        return manager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING)
    }

    /** What the setup screen should tell the user, given the current state. */
    fun status(context: Context): RoleStatus = when {
        !isSupported -> RoleStatus.Unsupported
        isHeld(context) -> RoleStatus.Held
        requestIntent(context) == null -> RoleStatus.Unavailable
        else -> RoleStatus.NotHeld
    }
}

sealed interface RoleStatus {
    /** Screening is active for cellular calls - metadata only, still no audio. */
    data object Held : RoleStatus

    /** The role exists and can be requested. */
    data object NotHeld : RoleStatus

    /** This Android version has no role API. */
    data object Unsupported : RoleStatus

    /** The role API exists but this device does not offer the role. */
    data object Unavailable : RoleStatus
}
