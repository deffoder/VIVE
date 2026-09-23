"""Rule-based detection of a caller REQUESTING a secret or a money movement.

Why a rule set exists next to the intent model
----------------------------------------------
The intent head was trained on SMS and does not transfer to speech
(docs/BLOCKERS.md O18). Measured on scripted spoken calls, it labelled "an OTP
has come to your phone, tell it now" NORMAL_CONVERSATION from the exact
reference text (models/evaluation/mobile/text_heads_spoken_check.md), and it
has no Tamil at all (O11). Without another signal a spoken OTP request moves
risk nowhere.

What this is, and is not
------------------------
A deterministic lexicon (models/configs/sensitive_requests.json): a rule fires
when a secret term and a request cue occur in the same transcript context and
no negation cue ("do not share your OTP") is present. It is NOT a model, has
no confidence, and is reported under its own name - it never rewrites the
intent model's label. Its precision and recall were measured on data it was
not written from (scripts/evaluation/exp_sensitive_rules.py); those numbers,
not the design, are the claim.

The Kotlin port (com.vive.ondevice.risk.SensitiveRequests) reads the same
JSON and is pinned to this file by golden cases.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache

CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "models", "configs",
                      "sensitive_requests.json")

# Evaluation order when several rules fire: the most specific secret first.
PRIORITY = ("OTP_REQUEST", "PASSWORD_REQUEST", "CARD_DETAILS_REQUEST",
            "REMOTE_ACCESS_REQUEST", "MONEY_TRANSFER_REQUEST")


@dataclass(frozen=True)
class Detection:
    label: str
    secret: str
    request: str


def _is_latin(term: str) -> bool:
    return all(ord(c) < 0x250 for c in term)


def _contains(text: str, term: str) -> bool:
    if _is_latin(term):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
    return term in text


FUZZY_MIN_LEN = 6
"""Single-word secret terms at least this long also match at edit distance 1.

Phone ASR renders secret words with one-character slips ("पासपर्ड" for
पासवर्ड, measured through the handset). A single edit is the generic ASR
tolerance; it applies to SECRET terms only - request and negation cues stay
exact - and its cost in false positives is measured by
exp_sensitive_rules.py on the same independent negatives as the exact rules.

Measured, which is why the bounds are what they are: at 4 characters "mpin"
matched "min" and multi-word "send money" matched "spend money" in benign
SMS. Six characters and single words only removed both.
"""


def _lev1(a: str, b: str) -> bool:
    """True when the edit distance between a and b is at most 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    if la == lb:
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:]


def _fuzzy_contains(text: str, term: str) -> bool:
    if len(term) < FUZZY_MIN_LEN or " " in term:
        return False
    if _is_latin(term):
        return any(_lev1(w, term) for w in re.findall(r"[a-z0-9]+", text))
    for size in (len(term) - 1, len(term), len(term) + 1):
        for i in range(0, len(text) - size + 1):
            if _lev1(text[i:i + size], term):
                return True
    return False


def _secret_in(text: str, term: str) -> bool:
    return _contains(text, term) or _fuzzy_contains(text, term)


@lru_cache(maxsize=1)
def load(path: str = CONFIG) -> dict:
    with open(os.path.abspath(path), encoding="utf-8") as fh:
        return json.load(fh)


def detect(text: str | None, config: dict | None = None) -> Detection | None:
    """Returns the highest-priority rule that fires on `text`, or None."""
    if not text or not text.strip():
        return None
    cfg = config or load()
    t = " ".join(text.lower().split())
    if any(_contains(t, n) for n in cfg["negation"]):
        return None
    for label in PRIORITY:
        rule = cfg["rules"].get(label)
        if not rule:
            continue
        secret = next((s for s in rule["secret"] if _secret_in(t, s)), None)
        if secret is None:
            continue
        request = next((r for r in rule["request"] if _contains(t, r)), None)
        if request is not None:
            return Detection(label, secret, request)
    return None


def detect_in_context(current: str | None, previous: str | None,
                      config: dict | None = None) -> Detection | None:
    """Detection over the previous and current window's transcripts.

    A request often straddles two 2 s windows ("...an OTP has come" | "tell
    it now"), so the pair is read together. It fires only when the previous
    window did NOT already fire on its own: windows overlap by 1 s, so one
    spoken sentence appears in two of them, and counting it twice raised two
    alerts for one request on the phone - and would fake the recurrence that
    temporal risk treats as escalation.
    """
    if not current or not current.strip():
        return None
    found = detect(f"{previous or ''} {current}", config)
    if found is None or detect(previous, config) is not None:
        return None
    return found
