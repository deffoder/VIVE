package com.vive.core

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Display formatting shared by screens. Stored values stay ISO-8601 UTC. */
object Formatting {

    private val WHEN = DateTimeFormatter.ofPattern("d MMM yyyy, HH:mm", Locale.ENGLISH)

    /** "2026-09-23T20:03:14Z" -> "24 Sep 2026, 01:33" in the phone's zone. Unparseable input is shown as is. */
    fun whenLocal(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String? =
        iso?.let { runCatching { WHEN.format(Instant.parse(it).atZone(zone)) }.getOrDefault(it) }

    fun languageName(code: String?): String? = when (code) {
        null -> null
        "hi" -> "Hindi"
        "ta" -> "Tamil"
        "en" -> "English"
        else -> code.uppercase()
    }
}
