package com.vive.alerts

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.vive.data.model.Alert
import com.vive.data.model.RiskLevel

/**
 * Delivers a raised alert as an Android notification.
 *
 * `POST_NOTIFICATIONS` was declared in the manifest from the start, and until
 * now nothing used it: `alert.raised` arrived over the WebSocket and the
 * session view mapped it to `Unit`. An alert that fires while the user is
 * looking at another app produced nothing at all, which is precisely the case
 * an alert exists for.
 *
 * What is NOT in a notification, and why
 * --------------------------------------
 * No transcript text. Notifications surface on a lock screen, over a
 * screen share and in a notification history the app does not control, and
 * `SECURITY_SPEC.md` 4 treats transcript content as sensitive. `reason` is
 * safe by construction - the policy engine builds it from levels, intents and
 * confidence, never from what anyone said - but the notification is also
 * marked `VISIBILITY_PRIVATE` so the system hides its body on a locked screen
 * regardless.
 *
 * Wording
 * -------
 * "voice-integrity risk", never "fraud" and never "AI voice". Synthetic speech
 * is not fraud and human speech is not safety (`BLOCKERS.md` P3), and a
 * notification is the surface most likely to be read as a verdict because it
 * arrives with no context around it.
 */
object AlertNotifier {

    /**
     * Two channels, so the user can silence advisories without silencing
     * warnings. One channel with a per-notification importance would not work:
     * Android takes importance from the CHANNEL on O and above, and ignores
     * what the notification asks for.
     */
    const val CHANNEL_HIGH = "vive_risk_high"
    const val CHANNEL_INFO = "vive_risk_info"

    /** LOW alerts are recorded in the app and never interrupt. */
    private val INTERRUPTS = setOf(RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

    fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_HIGH,
                "Call risk warnings",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = "High and critical voice-integrity risk during a call."
                setShowBadge(true)
            },
        )
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_INFO,
                "Call risk advisories",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = "Medium voice-integrity risk. Informational."
                setShowBadge(false)
            },
        )
    }

    /**
     * Posts [alert], or does nothing if it should not interrupt or the user
     * has not granted notifications.
     *
     * Returns whether a notification was actually posted, so a caller can
     * report delivery honestly rather than assuming it.
     */
    fun notify(context: Context, alert: Alert): Boolean {
        if (alert.level !in INTERRUPTS) return false
        if (!canPost(context)) return false

        val action = alert.recommendedAction?.let { humanise(it.name) }
        val intent = alert.intent?.let { humanise(it.name) }
        val body = buildString {
            append(alert.reason)
            if (intent != null) append("\nDetected intent: ").append(intent)
            if (action != null) append("\nSuggested: ").append(action)
        }

        val notification = NotificationCompat.Builder(context, channelFor(alert.level))
            .setSmallIcon(android.R.drawable.stat_sys_warning)
            .setContentTitle("${humanise(alert.level.name)} voice-integrity risk")
            .setContentText(alert.reason)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setPriority(
                if (alert.level == RiskLevel.CRITICAL) NotificationCompat.PRIORITY_HIGH
                else NotificationCompat.PRIORITY_DEFAULT,
            )
            // The body can name an intent, so keep it off a locked screen.
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .build()

        return try {
            // Keyed by alertId so the same alert re-delivered over a
            // reconnected socket updates one notification instead of stacking
            // duplicates for a single event.
            NotificationManagerCompat.from(context)
                .notify(alert.alertId, NOTIFICATION_ID, notification)
            true
        } catch (_: SecurityException) {
            // Permission revoked between the check and the post.
            false
        }
    }

    fun canPost(context: Context): Boolean {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return false
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    internal fun channelFor(level: RiskLevel): String =
        if (level == RiskLevel.MEDIUM) CHANNEL_INFO else CHANNEL_HIGH

    /** `OTP_REQUEST` to `Otp request`, so a taxonomy constant is not shown raw. */
    internal fun humanise(value: String): String =
        value.replace('_', ' ').lowercase().replaceFirstChar { it.uppercase() }

    private const val NOTIFICATION_ID = 4101
}
