package com.vive.ondevice

/**
 * BERT WordPiece tokenizer for the multilingual-cased DistilBERT heads.
 *
 * A port of HF `tokenizers`' BertNormalizer (clean_text, handle_chinese_chars,
 * no lowercasing, no accent stripping), BertPreTokenizer and WordPiece, so the
 * phone feeds the heads the same ids the backend does. A tokenizer that
 * differs on even a few characters changes predictions silently, so this is
 * pinned by `text_tokenizer_golden.json`: HF's own ids for real corpus texts
 * in every language plus edge cases, reproduced exactly in a JVM test.
 */
class WordPieceTokenizer(vocabLines: List<String>, private val maxLength: Int = 96) {

    private val vocab: Map<String, Int> =
        vocabLines.withIndex().associate { (i, token) -> token to i }

    private val unk = id("[UNK]")
    private val cls = id("[CLS]")
    private val sep = id("[SEP]")
    val padId = id("[PAD]")

    private fun id(token: String) = vocab[token] ?: error("vocab has no $token")

    /** `[CLS] … [SEP]`, truncated to [maxLength] like `truncation=True`. */
    fun encode(text: String): IntArray {
        val ids = ArrayList<Int>()
        for (word in preTokenize(normalize(text))) {
            wordPiece(word, ids)
            if (ids.size >= maxLength - 2) break
        }
        val body = if (ids.size > maxLength - 2) ids.subList(0, maxLength - 2) else ids
        return IntArray(body.size + 2).also { out ->
            out[0] = cls
            body.forEachIndexed { i, v -> out[i + 1] = v }
            out[out.size - 1] = sep
        }
    }

    private fun normalize(text: String): String {
        val sb = StringBuilder(text.length)
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            i += Character.charCount(cp)
            if (cp == 0 || cp == 0xFFFD || isControl(cp)) continue
            if (isWhitespace(cp)) { sb.append(' '); continue }
            if (isChinese(cp)) sb.append(' ').appendCodePoint(cp).append(' ')
            else sb.appendCodePoint(cp)
        }
        return sb.toString()
    }

    private fun preTokenize(text: String): List<String> {
        val words = ArrayList<String>()
        val current = StringBuilder()
        fun flush() { if (current.isNotEmpty()) { words += current.toString(); current.setLength(0) } }
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            i += Character.charCount(cp)
            when {
                isWhitespace(cp) -> flush()
                isPunctuation(cp) -> { flush(); words += String(Character.toChars(cp)) }
                else -> current.appendCodePoint(cp)
            }
        }
        flush()
        return words
    }

    private fun wordPiece(word: String, out: MutableList<Int>) {
        if (word.codePointCount(0, word.length) > MAX_CHARS_PER_WORD) { out += unk; return }
        val pieces = ArrayList<Int>()
        var start = 0
        while (start < word.length) {
            var end = word.length
            var found = -1
            while (start < end) {
                val sub = (if (start > 0) "##" else "") + word.substring(start, end)
                val hit = vocab[sub]
                if (hit != null) { found = hit; break }
                // Step back one CODE POINT, never into a surrogate pair.
                end = word.offsetByCodePoints(end, -1)
            }
            if (found < 0) { out += unk; return }
            pieces += found
            start = end
        }
        out += pieces
    }

    companion object {
        const val MAX_CHARS_PER_WORD = 100

        // Rust char::is_whitespace is the Unicode White_Space property.
        fun isWhitespace(cp: Int): Boolean = when (cp) {
            0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680,
            in 0x2000..0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000 -> true
            else -> false
        }

        // tokenizers: Cc, Cf, Cn, Co are control, except \t \n \r.
        fun isControl(cp: Int): Boolean {
            if (cp == 0x09 || cp == 0x0A || cp == 0x0D) return false
            if (isWhitespace(cp)) return false
            return when (Character.getType(cp).toByte()) {
                Character.CONTROL, Character.FORMAT, Character.UNASSIGNED, Character.PRIVATE_USE -> true
                else -> false
            }
        }

        fun isPunctuation(cp: Int): Boolean {
            if (cp in 33..47 || cp in 58..64 || cp in 91..96 || cp in 123..126) return true
            return when (Character.getType(cp).toByte()) {
                Character.CONNECTOR_PUNCTUATION, Character.DASH_PUNCTUATION,
                Character.START_PUNCTUATION, Character.END_PUNCTUATION,
                Character.INITIAL_QUOTE_PUNCTUATION, Character.FINAL_QUOTE_PUNCTUATION,
                Character.OTHER_PUNCTUATION -> true
                else -> false
            }
        }

        fun isChinese(cp: Int): Boolean =
            cp in 0x4E00..0x9FFF || cp in 0x3400..0x4DBF || cp in 0x20000..0x2A6DF ||
                cp in 0x2A700..0x2B73F || cp in 0x2B740..0x2B81F || cp in 0x2B820..0x2CEAF ||
                cp in 0xF900..0xFAFF || cp in 0x2F800..0x2FA1F
    }
}
