package com.vive.ondevice

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Test

/**
 * The phone must feed the text heads exactly the ids HF's tokenizer does.
 * `text_tokenizer_golden.json` is written by `scripts/mobile/export_text.py`
 * from the real tokenizer over held-out corpus texts in every language plus
 * edge cases (ZWJ/ZWNJ, emoji, CJK, control chars, 150-char words, >96 tokens).
 */
class WordPieceTokenizerTest {

    private fun resource(name: String) = javaClass.classLoader!!.getResource(name)!!.readText()

    @Test
    fun `reproduces HF tokenizer ids on every golden case`() {
        val golden = Json.parseToJsonElement(resource("text_tokenizer_golden.json")).jsonObject
        val tok = WordPieceTokenizer(resource("text-vocab.txt").lines().dropLastWhile { it.isEmpty() },
            golden["max_length"]!!.jsonPrimitive.int)
        golden["cases"]!!.jsonArray.forEachIndexed { i, c ->
            val text = c.jsonObject["text"]!!.jsonPrimitive.content
            val want = c.jsonObject["ids"]!!.jsonArray.map { it.jsonPrimitive.int }.toIntArray()
            assertArrayEquals("case $i: ${text.take(60)}", want, tok.encode(text))
        }
    }
}
