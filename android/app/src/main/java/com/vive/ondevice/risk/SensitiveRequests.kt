package com.vive.ondevice.risk

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Rule-based detection of a caller REQUESTING a secret or a money movement.
 * Port of `backend/app/risk/sensitive.py`, reading the same
 * `sensitive_requests.json`, pinned to it by golden cases.
 *
 * Not a model: no confidence, reported under its own name, and it never
 * rewrites the intent model's label. It exists because the intent head,
 * trained on SMS, misses spoken requests and has no Tamil (O11, O18).
 */
class SensitiveRequests(config: String) {

    @Serializable
    data class Rule(val secret: List<String>, val request: List<String>)

    @Serializable
    data class Config(val version: String, val rules: Map<String, Rule>, val negation: List<String>)

    data class Detection(val label: String, val secret: String, val request: String)

    val spec: Config = Json { ignoreUnknownKeys = true }.decodeFromString(Config.serializer(), config)

    fun detect(text: String?): Detection? {
        if (text.isNullOrBlank()) return null
        val t = normalise(text)
        if (spec.negation.any { contains(t, it) }) return null
        for (label in PRIORITY) {
            val rule = spec.rules[label] ?: continue
            val secret = rule.secret.firstOrNull { contains(t, it) } ?: continue
            val request = rule.request.firstOrNull { contains(t, it) } ?: continue
            return Detection(label, secret, request)
        }
        return null
    }

    /** Previous + current window; fires only if the current window adds a matched term. */
    fun detectInContext(current: String?, previous: String?): Detection? {
        if (current.isNullOrBlank()) return null
        val found = detect("${previous ?: ""} $current") ?: return null
        val t = normalise(current)
        return if (contains(t, found.secret) || contains(t, found.request)) found else null
    }

    companion object {
        const val ASSET = "sensitive_requests.json"
        val PRIORITY = listOf(
            "OTP_REQUEST", "PASSWORD_REQUEST", "CARD_DETAILS_REQUEST",
            "REMOTE_ACCESS_REQUEST", "MONEY_TRANSFER_REQUEST",
        )

        /**
         * Python: " ".join(text.lower().split()). Split by hand: Android's ICU
         * regex rejects the `(?U)` flag the JVM accepts, which made every
         * speech window throw on the phone while the JVM tests passed.
         */
        fun normalise(text: String): String {
            val sb = StringBuilder(text.length)
            var pendingSpace = false
            for (c in text.lowercase()) {
                if (c.isWhitespace()) { pendingSpace = sb.isNotEmpty(); continue }
                if (pendingSpace) { sb.append(' '); pendingSpace = false }
                sb.append(c)
            }
            return sb.toString()
        }

        private fun isLatin(term: String) = term.all { it.code < 0x250 }

        private fun isWordChar(c: Char) = c in 'a'..'z' || c in '0'..'9'

        /** Latin terms on [a-z0-9] boundaries, Indic-script terms as substrings. */
        fun contains(text: String, term: String): Boolean {
            if (!isLatin(term)) return text.contains(term)
            var from = 0
            while (true) {
                val i = text.indexOf(term, from)
                if (i < 0) return false
                val before = i == 0 || !isWordChar(text[i - 1])
                val after = i + term.length >= text.length || !isWordChar(text[i + term.length])
                if (before && after) return true
                from = i + 1
            }
        }
    }
}
