"""Shared ASR text normalisation.

One definition, used by every ASR evaluation, because WER is extremely
sensitive to normalisation and two scripts that normalise differently produce
numbers that cannot be compared. Hindi and Tamil results are only meaningfully
comparable because they pass through this exact function.

Applied identically to reference and hypothesis, and reported verbatim in
every evaluation record so a figure can be reproduced.
"""

from __future__ import annotations

import re
import unicodedata

# Stripped from BOTH sides. Includes the Devanagari danda (U+0964) and double
# danda (U+0965): CTC vocabularies for Indic models do not contain them, so
# leaving them in the reference would charge a model for tokens it has no way
# to emit. Whisper can emit punctuation, so stripping it on both sides keeps
# the two architectures on the same footing rather than penalising one.
PUNCT = re.compile(r"[।॥,.!?;:\"'`()\[\]{}<>\-–—_/\|@#$%^&*+=~]")
WS = re.compile(r"\s+")

NORMALISATION_STEPS = [
    "Unicode NFC",
    "lowercase",
    "strip punctuation including Devanagari danda U+0964 and double danda U+0965",
    "collapse whitespace",
]


def normalise(text: str) -> str:
    """Identical treatment for reference and hypothesis."""
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = PUNCT.sub(" ", text)
    return WS.sub(" ", text).strip()
