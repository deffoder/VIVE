package com.vive.core

import android.util.Log
import com.vive.BuildConfig

/**
 * VIVE logging.
 *
 * Privacy rule (docs/SECURITY_SPEC.md 5): logs may carry request/session/packet
 * identifiers, status and latency. They must NEVER carry transcript text, audio
 * bytes, tokens or API keys. [redact] exists so callers have an obvious correct
 * option when they are tempted to log user content.
 *
 * Debug logs are compiled against BuildConfig.DEBUG so release builds stay quiet.
 */
object ViveLog {

    private const val MAX_TAG = 23

    fun d(tag: String, message: () -> String) {
        if (BuildConfig.DEBUG) Log.d(tag.safe(), message())
    }

    fun i(tag: String, message: String) = Log.i(tag.safe(), message)

    fun w(tag: String, message: String, throwable: Throwable? = null) =
        Log.w(tag.safe(), message, throwable)

    fun e(tag: String, message: String, throwable: Throwable? = null) =
        Log.e(tag.safe(), message, throwable)

    /**
     * Replaces sensitive content with a length-only marker.
     * Use for anything derived from audio or transcripts.
     */
    fun redact(value: String?): String =
        if (value.isNullOrEmpty()) "<empty>" else "<redacted:${value.length}>"

    private fun String.safe(): String = if (length <= MAX_TAG) this else substring(0, MAX_TAG)
}
