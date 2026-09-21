"""VIVE label taxonomy and the public-label mapping.

Every mapping decision below is deliberate and documented. Public datasets do
not use the VIVE taxonomy, so labels are translated - never copied blindly
(docs/DATA_SPEC.md 6).

The governing rule: **when a public label does not determine a VIVE intent, it
maps to UNKNOWN rather than to a plausible guess.** UNKNOWN carries low intent
risk in fusion (0.10), so an honest "we cannot tell" never inflates risk. A
wrong confident label would.
"""

from __future__ import annotations

# --------------------------------------------------------------- taxonomies
# Must match docs/PROJECT_SPEC.md 7 and the Kotlin/Pydantic enums exactly.

INTENT_LABELS = [
    "NORMAL_CONVERSATION",
    "OTP_REQUEST",
    "PASSWORD_REQUEST",
    "CARD_DETAILS_REQUEST",
    "BANKING_CREDENTIAL_REQUEST",
    "MONEY_TRANSFER_REQUEST",
    "ACCOUNT_CHANGE_REQUEST",
    "REMOTE_ACCESS_REQUEST",
    "URGENT_ACTION",
    "THREAT_OR_INTIMIDATION",
    "CONFIDENTIAL_INFORMATION",
    "UNKNOWN",
]

BEHAVIOR_LABELS = [
    "AUTHORITY_IMPERSONATION",
    "URGENCY",
    "THREAT",
    "FEAR",
    "SECRECY",
    "PRESSURE",
    "REWARD_PROMISE",
    "NORMAL",
]


# ------------------------------------------------------- intent mapping
# Source: sidzzz07/scamshield-dataset, field `head2_scam_intent` (MIT).

INTENT_MAPPING: dict[str, str] = {
    # Direct, unambiguous.
    "Legitimate / Benign": "NORMAL_CONVERSATION",
    "OTP / Credential Theft": "OTP_REQUEST",
    "UPI Fraud": "MONEY_TRANSFER_REQUEST",
    "Fake KYC": "BANKING_CREDENTIAL_REQUEST",
    # Coercion framed as a consequence: the caller's ask is compliance under
    # threat, which is THREAT_OR_INTIMIDATION in the VIVE taxonomy.
    "Electricity Disconnection": "THREAT_OR_INTIMIDATION",
    "Bank Account Freeze": "THREAT_OR_INTIMIDATION",
    "Traffic e-Challan": "THREAT_OR_INTIMIDATION",
    # A withheld parcel demanding immediate action. The ask is action, not a
    # specific credential, so URGENT_ACTION rather than a credential intent.
    "Courier Scam": "URGENT_ACTION",
    # --- deliberately UNKNOWN ---
    # These public labels name a SCAM GENRE, not what the caller asks for. A
    # lottery message may seek a fee, bank details or nothing at all; the label
    # alone cannot distinguish them. Guessing would train the classifier on the
    # annotator's genre taxonomy rather than on intent.
    "Lottery / Prize": "UNKNOWN",
    "Loan Scam": "UNKNOWN",
    "Telegram Job": "UNKNOWN",
    # Unsolicited commercial messaging is not a VIVE intent at all. Mapping it
    # to NORMAL_CONVERSATION would teach the model that spam is safe
    # conversation; mapping it to a risk intent would inflate risk. UNKNOWN is
    # the honest position.
    "General Spam / Telemarketing": "UNKNOWN",
}

INTENT_MAPPING_NOTES = {
    "Lottery / Prize": "Genre label, not an intent. The reward signal is carried by the REWARD_PROMISE behaviour instead.",
    "Loan Scam": "Genre label. May be advance-fee (money transfer) or data harvesting; not determinable.",
    "Telegram Job": "Genre label. Task-scam recruitment; the eventual ask varies.",
    "General Spam / Telemarketing": "Not a VIVE intent. Neither safe conversation nor a risk request.",
}


# ----------------------------------------------------- behaviour mapping
# Source: same dataset, field `head1_social_engineering` (multi-label flags).

BEHAVIOR_MAPPING: dict[str, str] = {
    "urgency": "URGENCY",
    "fear": "FEAR",
    "authority_impersonation": "AUTHORITY_IMPERSONATION",
    "reward_bait": "REWARD_PROMISE",
    "financial_pressure": "PRESSURE",
}

# VIVE behaviours with NO label source in this dataset. They are NOT trained,
# and the classifier must not be described as covering them.
BEHAVIOR_UNSUPPORTED = ["THREAT", "SECRECY"]

BEHAVIOR_NOTES = {
    "NORMAL": "Derived, not annotated: a record with every flag zero is NORMAL.",
    "THREAT": "No label source. Distinct from FEAR: threat is an explicit consequence, fear is an induced state.",
    "SECRECY": "No label source. 'Do not tell anyone' is a common scam move but is unlabelled here.",
}


def map_intent(public_label: str) -> str:
    """Maps a public intent label onto the VIVE taxonomy."""
    return INTENT_MAPPING.get(public_label.strip(), "UNKNOWN")


def map_behaviors(flags: dict[str, object]) -> list[str]:
    """Maps the multi-label social-engineering flags onto VIVE behaviours.

    Returns ``["NORMAL"]`` when nothing is flagged, matching the taxonomy rule
    that NORMAL is exclusive.
    """
    out = [
        BEHAVIOR_MAPPING[key]
        for key, value in flags.items()
        if key in BEHAVIOR_MAPPING and int(value) != 0
    ]
    return sorted(set(out)) if out else ["NORMAL"]


def normalise_language(raw: str) -> str:
    """Maps the dataset's language names onto ISO-639-1 where possible.

    'Hinglish' is code-switched Hindi-English with no ISO code of its own; it
    is kept as a distinct tag rather than forced into 'hi' or 'en', because
    code-switching is a real evaluation condition (docs/ML_SPEC.md 10).
    """
    return {
        "English": "en",
        "Hindi": "hi",
        "Hinglish": "hi-en",
        "Tamil": "ta",
    }.get(raw.strip(), "und")
