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
            val secret = rule.secret.firstOrNull { secretIn(t, it) } ?: continue
            val request = rule.request.firstOrNull { contains(t, it) } ?: continue
            return Detection(label, secret, request)
        }
        return null
    }

    /**
     * Previous + current window, firing only when the previous window did not
     * already fire alone: windows overlap by 1 s, so one sentence sits in two
     * of them and was raising two alerts for one request (sensitive.py).
     */
    fun detectInContext(current: String?, previous: String?): Detection? {
        if (current.isNullOrBlank()) return null
        val found = detect("${previous ?: ""} $current") ?: return null
        return if (detect(previous) == null) found else null
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

        /** Single-word secret terms this long or longer also match at edit distance 1 (sensitive.py). */
        const val FUZZY_MIN_LEN = 6

        fun secretIn(text: String, term: String) = contains(text, term) || fuzzyContains(text, term)

        /** Edit distance between a and b is at most 1. */
        fun lev1(a0: String, b0: String): Boolean {
            if (a0 == b0) return true
            var a = a0; var b = b0
            if (kotlin.math.abs(a.length - b.length) > 1) return false
            if (a.length > b.length) { val t = a; a = b; b = t }
            var i = 0
            while (i < a.length && a[i] == b[i]) i++
            return if (a.length == b.length) a.substring(minOf(i + 1, a.length)) == b.substring(minOf(i + 1, b.length))
            else a.substring(i) == b.substring(i + 1)
        }

        private fun latinWords(text: String): List<String> {
            val out = mutableListOf<String>()
            val cur = StringBuilder()
            for (c in text) {
                if (isWordChar(c)) cur.append(c) else if (cur.isNotEmpty()) { out += cur.toString(); cur.setLength(0) }
            }
            if (cur.isNotEmpty()) out += cur.toString()
            return out
        }

        fun fuzzyContains(text: String, term: String): Boolean {
            if (term.length < FUZZY_MIN_LEN || ' ' in term) return false
            if (isLatin(term)) return latinWords(text).any { lev1(it, term) }
            for (size in listOf(term.length - 1, term.length, term.length + 1)) {
                for (i in 0..text.length - size) if (lev1(text.substring(i, i + size), term)) return true
            }
            return false
        }

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
