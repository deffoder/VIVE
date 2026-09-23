"""Phase F: what does the Tamil language gate actually prevent?

O11 records that VIVE has no Tamil text for intent or behaviour, and Phase 8B
made the adapters decline Tamil with `UNSUPPORTED_LANGUAGE` rather than guess.
Phase 10 then found three separate ways that gate could be bypassed and fixed
all three.

So the gate is correct and it is now enforced. What has never been established
is how much it matters. "The model was not trained on Tamil" is an argument
about provenance; it is not a measurement. A reviewer is entitled to ask what
would actually happen if the gate were removed, and until now the answer would
have been a shrug.

Two things are separable here and worth separating:

  * **Can the encoder represent Tamil at all?** `distilbert-base-multilingual-
    cased` was pretrained on 104 languages, Tamil among them. If its tokenizer
    shredded Tamil into unknown tokens, the gate would be permanent and
    architectural. If it handles Tamil comparably to Hindi, then the gate
    exists purely because the fine-tuning corpus had no Tamil - which is a
    DATA problem, and data can be commissioned.

  * **What does the fine-tuned head do when handed Tamil anyway?** This is the
    operational question. A head that fell back to NORMAL_CONVERSATION on
    unfamiliar input would be failing safe, and the gate would be tidy but not
    load-bearing. A head that fires OTP_REQUEST at high confidence on Tamil
    news reading is an active hazard, and the gate is the only thing between
    that and a user.

Method
------
FLEURS Tamil transcriptions are real human Tamil under CC-BY-4.0 and are
already used elsewhere in VIVE's evaluation, so no text is invented and none is
machine-translated. FLEURS is read news: under the VIVE taxonomy essentially
every sentence is NORMAL_CONVERSATION with behaviour NORMAL. That gives a
usable negative set without anyone labelling anything - a non-NORMAL prediction
on a news sentence is a false positive whatever the exact sentence says.

Hindi and English FLEURS run through identically as CONTROLS. Both are
supported languages, so their false-positive rate is the head's ordinary
out-of-domain error on news text. The Tamil number means something only beside
them: what matters is the DIFFERENCE, not the absolute rate.

What this is not
----------------
This does not measure Tamil intent accuracy and cannot. There is no labelled
Tamil scam text (O11), so only the negative class can be evaluated. Nothing
here licenses a Tamil accuracy claim, and nothing here justifies opening the
gate.

Usage:
    python scripts/evaluation/exp_tamil_gate.py [--sentences 200]
"""

from __future__ import annotations

import argparse
import collections
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, add_backend_to_path  # noqa: E402

FLEURS = {"ta": "ta_in", "hi": "hi_in", "en": "en_us"}
SUPPORTED = {"hi", "en"}

# FLEURS is read news. In the VIVE taxonomy that is NORMAL_CONVERSATION with
# behaviour NORMAL - the only labels a news sentence can honestly carry.
BENIGN_INTENT = "NORMAL_CONVERSATION"
BENIGN_BEHAVIOUR = "NORMAL"

# Intents that would raise risk if they fired. UNKNOWN is excluded: it is the
# head declining to commit, which is a different thing from a false alarm.
def is_false_alarm(label: str) -> bool:
    return label not in (BENIGN_INTENT, "UNKNOWN")


def sentences(config: str, count: int) -> list[str]:
    """FLEURS transcriptions only - no audio is decoded."""
    from datasets import Audio, load_dataset

    ds = load_dataset("google/fleurs", config, split="test", streaming=True)
    # This experiment reads TEXT only. The loader decodes the audio column
    # eagerly while formatting each batch, which needs a codec backend and
    # buys nothing here, so the column is switched to raw bytes and ignored.
    # remove_columns() does not help: it is applied after formatting.
    ds = ds.cast_column("audio", Audio(decode=False))
    out: list[str] = []
    seen: set[str] = set()
    for row in ds:
        text = (row.get("transcription") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= count:
            break
    return out


def tokeniser_coverage(tokenizer, texts: list[str]) -> dict:
    """Does the shared vocabulary actually cover this script?

    Two numbers matter. `unknown_token_rate` says whether characters survive
    at all. `tokens_per_character` says how finely the script is shredded: a
    language represented by near-character subwords carries far less meaning
    per token than one with whole-word units, even when nothing is unknown.
    """
    unk_id = getattr(tokenizer, "unk_token_id", None)
    total_tokens = unknown = characters = 0
    for text in texts:
        ids = tokenizer(text, truncation=True, max_length=256)["input_ids"]
        total_tokens += len(ids)
        characters += len(text)
        if unk_id is not None:
            unknown += sum(1 for i in ids if i == unk_id)
    return {
        "sentences": len(texts),
        "tokens": total_tokens,
        "unknown_token_rate": round(unknown / max(total_tokens, 1), 5),
        "tokens_per_character": round(total_tokens / max(characters, 1), 4),
    }


def intent_entropy(adapter, text: str) -> float:
    """Normalised entropy of the intent head's full distribution.

    The reported confidence is only the winning probability, which cannot
    distinguish "confidently NORMAL" from "narrowly NORMAL over eleven
    near-equal alternatives". On a script the head never trained on, the
    second is what abstention would look like - and it would be safe by
    accident rather than by design. Normalising by log(labels) puts all
    languages on one scale: 0 is a one-hot decision, 1 is no information.
    """
    import math

    import torch

    probs = torch.softmax(adapter._logits(text), dim=-1)
    total = -sum(float(p) * math.log(max(float(p), 1e-12)) for p in probs)
    return round(total / math.log(len(probs)), 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=int, default=200)
    args = parser.parse_args()

    add_backend_to_path()
    from app.adapters.real.text_classifiers import (
        SUPPORTED_LANGUAGES,
        RealBehaviorAdapter,
        RealIntentAdapter,
    )
    from app.schemas.models import AnalyzerStatus

    exp = Experiment(
        "10F_tamil_gate_hazard",
        question=("The Tamil gate is correct and enforced. What does it "
                  "prevent? Specifically: can the encoder represent Tamil at "
                  "all, and what do the fine-tuned heads predict when Tamil "
                  "reaches them anyway?"),
        hypothesis=("The tokenizer will cover Tamil comparably to Hindi, "
                    "because the pretraining set included it - so the gate is "
                    "a data limitation, not an architectural one. The heads "
                    "will NOT fail safe: a classifier that has never seen a "
                    "script has no mechanism for recognising it as "
                    "unfamiliar, so predictions on Tamil should look "
                    "arbitrary rather than conservative."),
        method=("Run real FLEURS transcriptions through the tokenizer and "
                "then through both heads with the language gate bypassed. "
                "Hindi and English run identically as supported-language "
                "controls, so the Tamil figure is read as a difference."))
    exp.config(sentences_per_language=args.sentences,
               gate_bypass="analyze(text, language=None)",
               supported_languages=sorted(SUPPORTED_LANGUAGES),
               benign_intent=BENIGN_INTENT, benign_behaviour=BENIGN_BEHAVIOUR)

    intent = RealIntentAdapter(os.path.join(ROOT, "models", "artifacts",
                                            "intent-classifier"))
    behaviour = RealBehaviorAdapter(os.path.join(ROOT, "models", "artifacts",
                                                 "behavior-classifier"))
    for adapter in (intent, behaviour):
        if adapter.load() is not AnalyzerStatus.AVAILABLE:
            raise SystemExit(f"{adapter.adapter_key}: "
                             f"{adapter.describe().detail}")
    exp.model(name="intent-classifier", revision=intent.version,
              license="in-repo (fine-tuned from distilbert-base-multilingual-"
                      "cased, Apache-2.0)")
    exp.model(name="behavior-classifier", revision=behaviour.version,
              license="in-repo (fine-tuned from distilbert-base-multilingual-"
                      "cased, Apache-2.0)")

    # -- the gate itself still holds --------------------------------------
    # Measured first, so everything below is visibly a BYPASS of a gate that
    # works rather than a description of production behaviour.
    probe = "OTP number sollunga"
    gate = {
        "intent_status_for_ta": intent.analyze(probe, "ta").status.value,
        "behaviour_status_for_ta": behaviour.analyze(probe, "ta").status.value,
        "intent_status_for_hi": intent.analyze("OTP batao", "hi").status.value,
    }
    gate["gate_declines_tamil"] = (
        gate["intent_status_for_ta"] == AnalyzerStatus.UNSUPPORTED_LANGUAGE.value
        and gate["behaviour_status_for_ta"]
        == AnalyzerStatus.UNSUPPORTED_LANGUAGE.value)
    exp.result("gate_still_enforced", gate)
    print(f"=== gate enforced: {gate['gate_declines_tamil']} ===")
    if not gate["gate_declines_tamil"]:
        raise SystemExit("the Tamil gate is not enforced - fix that first")

    coverage: dict[str, dict] = {}
    heads: dict[str, dict] = {}

    for lang, config in FLEURS.items():
        texts = sentences(config, args.sentences)
        if not texts:
            heads[lang] = {"error": "no sentences"}
            continue
        exp.dataset(name=f"google/fleurs {config}", source="HuggingFace",
                    license="CC-BY-4.0", split="test", samples=len(texts),
                    language=lang, modality="transcription text only")

        coverage[lang] = tokeniser_coverage(intent._tokenizer, texts)
        print(f"\n=== {lang} ({len(texts)} sentences) ===")
        print(f"  unknown tokens {coverage[lang]['unknown_token_rate']:.5f}   "
              f"tokens/char {coverage[lang]['tokens_per_character']:.4f}")

        intents = collections.Counter()
        entropies: list[float] = []
        confidences: list[float] = []
        alarm_confidences: list[float] = []
        behaviours = collections.Counter()
        non_normal_behaviour = 0
        examples: list[dict] = []

        for text in texts:
            # language=None bypasses the gate without touching it. The gate is
            # a guard on a declared language, not a property of the weights.
            i_result = intent.analyze(text, None)
            b_result = behaviour.analyze(text, None)
            entropies.append(intent_entropy(intent, text))
            label = i_result.label.value
            intents[label] += 1
            if i_result.confidence is not None:
                confidences.append(i_result.confidence)
                if is_false_alarm(label):
                    alarm_confidences.append(i_result.confidence)
            fired = [b.value for b in (b_result.labels or [])]
            for name in fired or [BENIGN_BEHAVIOUR]:
                behaviours[name] += 1
            if any(name != BENIGN_BEHAVIOUR for name in fired):
                non_normal_behaviour += 1
            if is_false_alarm(label) and len(examples) < 5:
                examples.append({
                    "text": text[:90], "intent": label,
                    "confidence": i_result.confidence, "behaviours": fired})

        alarms = sum(count for label, count in intents.items()
                     if is_false_alarm(label))
        confident_alarms = sum(1 for c in alarm_confidences if c >= 0.70)
        heads[lang] = {
            "supported_language": lang in SUPPORTED,
            "sentences": len(texts),
            "intent_distribution": dict(intents.most_common()),
            "false_alarm_rate": round(alarms / len(texts), 4),
            "confident_false_alarm_rate": round(confident_alarms / len(texts), 4),
            "median_confidence": round(statistics.median(confidences), 4)
            if confidences else None,
            "median_normalised_entropy": round(statistics.median(entropies), 4)
            if entropies else None,
            "median_false_alarm_confidence": round(
                statistics.median(alarm_confidences), 4)
            if alarm_confidences else None,
            "behaviour_distribution": dict(behaviours.most_common()),
            "non_normal_behaviour_rate": round(
                non_normal_behaviour / len(texts), 4),
            "examples": examples,
        }
        print(f"  false alarms {heads[lang]['false_alarm_rate']:.4f}  "
              f"(confident >=0.70: "
              f"{heads[lang]['confident_false_alarm_rate']:.4f})")
        print(f"  top intents  {list(intents.most_common(3))}")

    exp.result("tokenizer_coverage", coverage)
    exp.result("heads_with_gate_bypassed", heads)

    ta = heads.get("ta", {})
    hi = heads.get("hi", {})
    en = heads.get("en", {})
    comparison = {
        "tamil_false_alarm_rate": ta.get("false_alarm_rate"),
        "hindi_false_alarm_rate": hi.get("false_alarm_rate"),
        "english_false_alarm_rate": en.get("false_alarm_rate"),
        "tamil_confident_false_alarm_rate": ta.get("confident_false_alarm_rate"),
        "tamil_unknown_token_rate": coverage.get("ta", {}).get(
            "unknown_token_rate"),
        "hindi_unknown_token_rate": coverage.get("hi", {}).get(
            "unknown_token_rate"),
    }
    # The encoder can represent Tamil if the script survives tokenisation at a
    # rate comparable to a language the head already supports.
    comparison["encoder_represents_tamil"] = (
        comparison["tamil_unknown_token_rate"] is not None
        and comparison["tamil_unknown_token_rate"] <= 0.01)
    comparison["heads_fail_safe_on_tamil"] = (
        ta.get("false_alarm_rate") is not None
        and ta["false_alarm_rate"] <= (hi.get("false_alarm_rate") or 0.0) + 0.02)
    # Failing safe on benign text is only reassuring if the head is actually
    # READING the text. A head returning its prior on everything would look
    # identical here and would carry no guarantee at all, so the shape of the
    # output distribution is recorded beside the error rate.
    comparison["median_entropy"] = {
        lang: heads.get(lang, {}).get("median_normalised_entropy")
        for lang in FLEURS}
    ta_h = comparison["median_entropy"].get("ta")
    hi_h = comparison["median_entropy"].get("hi")
    comparison["tamil_output_resembles_supported_language"] = (
        ta_h is not None and hi_h is not None and abs(ta_h - hi_h) < 0.10)
    exp.result("comparison", comparison)

    print("\n--- false alarms on benign news text, gate bypassed ---")
    for lang in ("en", "hi", "ta"):
        row = heads.get(lang, {})
        if "false_alarm_rate" not in row:
            continue
        mark = "supported" if row["supported_language"] else "GATED"
        print(f"  {lang:<4}{mark:<12}{row['false_alarm_rate']:>8.4f}"
              f"{row['confident_false_alarm_rate']:>10.4f}")

    exp.limitation(
        "Only the NEGATIVE class is measured. There is no labelled Tamil scam "
        "text (O11), so this shows what the heads do on benign Tamil and says "
        "nothing about whether they would catch a Tamil scam. No Tamil "
        "accuracy figure exists and none may be inferred from this.")
    exp.limitation(
        "FLEURS is read news, not conversational speech, in all three "
        "languages. The absolute false-alarm rates therefore describe news "
        "text; the comparison between languages is the meaningful part, "
        "because the domain shift is identical across them.")
    exp.limitation(
        "Treating every FLEURS sentence as NORMAL_CONVERSATION is an "
        "assumption about the corpus, not a human annotation. A news sentence "
        "quoting a threat would be counted as a false alarm when the head was "
        "arguably right. This inflates all three rates equally and so does "
        "not bias the comparison.")
    exp.limitation(
        "Tokenizer coverage measures whether a script survives the shared "
        "vocabulary. It does not measure whether the fine-tuned head learned "
        "anything transferable, which would need labelled Tamil data to "
        "establish.")
    exp.limitation(
        "The gate was bypassed by passing language=None, which is a test-only "
        "path. The production call sites always pass a language, and Phase 10 "
        "pinned that with tests at three layers.")

    ta_rate = ta.get("false_alarm_rate")
    hi_rate = hi.get("false_alarm_rate")
    safe = comparison["heads_fail_safe_on_tamil"]
    similar = comparison["tamil_output_resembles_supported_language"]

    # The hypothesis said the heads would misfire on Tamil. Whether they did
    # decides what this experiment is allowed to conclude, so the write-up is
    # built from the measurement rather than from the expectation.
    if safe:
        finding = (
            f"the hypothesis is REFUTED. Benign Tamil produced a non-normal "
            f"intent on {ta_rate} of sentences against {hi_rate} for Hindi, "
            f"so the heads do not misfire on Tamil news - they behave as they "
            f"do on a language they support")
        verdict = (
            "The gate cannot be justified by a measured false-alarm rate, "
            "because on benign text there is not one. That is a weaker "
            "justification than expected and it is the one the evidence "
            "supports. The gate still stands, on the ground it always rested "
            "on: no labelled Tamil scam text exists (O11), so the POSITIVE "
            "class is unmeasured and unmeasurable here. A head that never "
            "raises an alarm on benign Tamil tells you nothing about whether "
            "it would raise one on a Tamil scam, and shipping a detector "
            "whose detection rate is unknown is not made acceptable by a "
            "clean false-alarm rate. What has changed is the argument: the "
            "gate is a refusal to report an unvalidated capability, not a "
            "guard against an observed hazard, and it must be described that "
            "way rather than dramatised.")
    else:
        finding = (
            f"the hypothesis is SUPPORTED. Benign Tamil produced a non-normal "
            f"intent on {ta_rate} of sentences against {hi_rate} for Hindi, "
            f"and {ta.get('confident_false_alarm_rate')} at confidence 0.70 "
            f"or above, so the head does not signal its own unfamiliarity")
        verdict = (
            "The gate is load-bearing and now measurably so. Removing it "
            "would not degrade Tamil gracefully; it would generate confident "
            "social-engineering alerts on ordinary Tamil speech, which is "
            "this product's worst failure mode - a false accusation with a "
            "high-confidence number attached. O11 stays open and the gate "
            "stays shut.")

    transfer = (
        "The output distribution on Tamil closely resembles Hindi's "
        f"(normalised entropy {ta_h} against {hi_h}), which is consistent "
        "with the multilingual encoder carrying some of the decision across "
        "scripts - but consistent is not evidence, and cross-lingual "
        "transfer cannot be confirmed without labelled Tamil data."
        if similar else
        f"The output distribution on Tamil differs from Hindi's (normalised "
        f"entropy {ta_h} against {hi_h}), so the head is not responding to "
        f"Tamil the way it responds to a language it was trained on.")

    exp.finish(
        interpretation=(
            f"The tokenizer covers Tamil at an unknown-token rate of "
            f"{comparison['tamil_unknown_token_rate']} against "
            f"{comparison['hindi_unknown_token_rate']} for Hindi, so the "
            f"encoder can represent the script: the gate follows from the "
            f"training corpus, not from the architecture. On the operational "
            f"question, {finding} (English {en.get('false_alarm_rate')}). "
            f"{transfer}"),
        conclusion=(
            verdict + " Since the encoder already represents Tamil, the "
            "required external action is unchanged and remains commissioning "
            "labelled Tamil text (DATA_SPEC 8.3) - a test split first, "
            "because without one no Tamil claim can be checked even if "
            "training data arrived tomorrow."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
