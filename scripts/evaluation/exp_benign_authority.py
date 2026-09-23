"""Phase L: what do the text heads do on a legitimate call?

O10 records that the training corpus contains **0 benign records carrying any
behaviour flag** out of 85,602, and draws the obvious consequence: the
behaviour head has never seen legitimate urgency or authority - a real
delivery notice, a genuine bank fraud alert - so it cannot have learned that
urgency alone is not fraud.

That consequence has always been stated as an expectation. "False positives on
legitimate urgent calls are expected" is a prediction, and an unmeasured
prediction is not a finding. It has never been tested, because the corpus that
would test it is exactly the corpus that is missing.

DATA_SPEC 8.2 named a candidate and deferred it: `BothBosu/multi-agent-scam-
conversation`, Apache-2.0 and ungated, "its label scheme was not mapped in this
phase". Mapping it is this experiment.

Why this corpus answers the question
------------------------------------
It holds 800 scam and 800 **benign** telephone conversations. The benign half
is not small talk - it is legitimate business calls: a delivery firm confirming
an address, a clinic confirming an appointment, an insurer following up a
claim, a wrong number. Those callers state authority, ask for personal
confirmation and press for a decision, because that is what real service calls
do. They are the population VIVE's behaviour head has never seen, and the
population a deployed VIVE would meet constantly.

One thing this corpus does NOT provide, and it matters: the scenario types are
disjoint. The scam half is `ssn`, `reward`, `refund` and `support`; the benign
half is `delivery`, `appointment`, `insurance` and `wrong`. Nothing appears on
both sides, so the two populations differ in SUBJECT as well as in legitimacy
and no matched contrast is possible. Any separation measured between them is
therefore an upper bound that a topic classifier could reach without
understanding legitimacy at all.

That confound does not touch the number O10 actually needs. A legitimate
delivery call that produces a behaviour flag is a false alarm whatever the scam
half contains, and the benign rate stands on its own.

What this measures, and what it does not
----------------------------------------
This measures the **false-positive rate on legitimate calls**, which O10 needs
and does not have. It does not retrain anything and does not resolve O10: the
corpus is English-only and LLM-generated, so it is a diagnostic population, not
a training set that could be dropped into a corpus of human SMS without
introducing a new provenance problem.

Usage:
    python scripts/evaluation/exp_benign_authority.py [--turns 400]
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, add_backend_to_path  # noqa: E402

CORPUS = "BothBosu/multi-agent-scam-conversation"
CORPUS_FILE = "agent_conversation_all.csv"
EXPECTED_LICENSE = "apache-2.0"

# The dialogues are two-party transcripts with inline speaker tags. VIVE
# analyses the CALLER, so only those turns are scored: the recipient's replies
# ("I'm not giving you my social security number") are a different speaker and
# would be measured against the wrong expectation.
CALLER_TAG = "Suspect:"
TURN_SPLIT = re.compile(r"(?=(?:Innocent:|Suspect:))")

MIN_TURN_CHARS = 40
"""Turns shorter than this are greetings and carry no classifiable content."""

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_SENTENCE_WORDS = 4

# The SENTENCE is the primary unit here, not the turn, for two reasons.
#
# VIVE scores 2-second packets. A 2-second packet holds roughly five to eight
# words, so a whole conversational turn - median 71 words in this corpus - is
# not an input the product ever forms. Measuring turns would characterise a
# system nobody is shipping.
#
# It would also measure the wrong thing even as an approximation: the heads
# truncate at MAX_LENGTH = 96 tokens, which a 71-word turn reaches, so the
# classifier would see the caller's polite opening and never the ask that
# follows it. Turn-level figures are still recorded below, precisely because
# the difference between the two units is itself a finding.

BENIGN_INTENT = "NORMAL_CONVERSATION"
BENIGN_BEHAVIOUR = "NORMAL"

# Both taxonomies carry a small non-zero floor for their benign label
# (NORMAL_CONVERSATION and NORMAL are 0.05 in fusion.py), so "produced a risk
# contribution above zero" is true of almost every turn and measures nothing.
# An ALARM is a label that is not the benign one.


def caller_turns(dialogue: str) -> list[str]:
    out = []
    for piece in TURN_SPLIT.split(dialogue or ""):
        piece = piece.strip()
        if not piece.startswith(CALLER_TAG):
            continue
        text = piece[len(CALLER_TAG):].strip()
        if len(text) >= MIN_TURN_CHARS:
            out.append(text)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=400,
                        help="caller turns to score per class")
    args = parser.parse_args()

    import pandas as pd
    from huggingface_hub import HfApi, hf_hub_download

    add_backend_to_path()
    from app.adapters.real.text_classifiers import (
        RealBehaviorAdapter,
        RealIntentAdapter,
    )
    from app.risk.fusion import BEHAVIOR_RISK, INTENT_RISK
    from app.schemas.models import AnalyzerStatus, Behavior, Intent

    exp = Experiment(
        "10L_benign_authority",
        question=("O10 predicts that the behaviour head will fire on "
                  "legitimate urgency because it has never seen any. On real "
                  "benign service calls, how often does it, and would a "
                  "genuine delivery call be flagged?"),
        hypothesis=("The heads will fire substantially on benign calls. The "
                    "training corpus contains no benign example carrying a "
                    "behaviour flag, so the decision boundary was never asked "
                    "to separate legitimate pressure from illegitimate "
                    "pressure - only scam text from benign text."),
        method=("Score caller turns from the benign and scam halves of an "
                "Apache-2.0 conversational corpus with the shipped heads, and "
                "break the result down by scenario. A matched contrast was "
                "intended and is not possible: the corpus's scenario types "
                "are disjoint across the two halves."))

    api = HfApi()
    info = api.dataset_info(CORPUS)
    declared = (info.card_data or {}).get("license")
    # Read the licence from repository metadata before use, never assume it
    # from the plan that named the corpus (docs/DATA_SPEC.md 3).
    if declared != EXPECTED_LICENSE:
        raise SystemExit(
            f"{CORPUS} declares license={declared!r}, expected "
            f"{EXPECTED_LICENSE!r} - refusing to use it UNVERIFIED")

    frame = pd.read_csv(hf_hub_download(CORPUS, CORPUS_FILE, repo_type="dataset"))
    print(f"=== {CORPUS} ({declared}, gated={info.gated}) ===")
    print(f"  {len(frame)} conversations, "
          f"{int((frame.labels == 0).sum())} benign / "
          f"{int((frame.labels == 1).sum())} scam")

    def balance(entries: list[tuple[str, str]], want: int) -> list[tuple[str, str]]:
        """Round-robin across scenario types.

        The CSV is grouped by type, so a head-slice would draw a single
        scenario and report it as the whole population. Round-robin keeps the
        sample deterministic without a shuffle and weights every scenario
        equally.
        """
        by_type: dict[str, list[tuple[str, str]]] = {}
        for scenario, text in entries:
            by_type.setdefault(scenario, []).append((scenario, text))
        out: list[tuple[str, str]] = []
        index = 0
        while len(out) < want and any(index < len(v) for v in by_type.values()):
            for scenario in sorted(by_type):
                if index < len(by_type[scenario]) and len(out) < want:
                    out.append(by_type[scenario][index])
            index += 1
        return out

    raw: dict[str, dict[str, list[tuple[str, str]]]] = {
        "sentence": {"benign": [], "scam": []},
        "turn": {"benign": [], "scam": []},
    }
    for _, row in frame.iterrows():
        key = "benign" if int(row["labels"]) == 0 else "scam"
        scenario = str(row["type"])
        for turn in caller_turns(str(row["dialogue"])):
            raw["turn"][key].append((scenario, turn))
            for piece in SENTENCE_SPLIT.split(turn):
                piece = piece.strip()
                if len(piece.split()) >= MIN_SENTENCE_WORDS:
                    raw["sentence"][key].append((scenario, piece))

    units = {unit: {key: balance(entries, args.turns)
                    for key, entries in sides.items()}
             for unit, sides in raw.items()}
    pools = units["sentence"]

    exp.dataset(name=CORPUS, source="HuggingFace", license=declared,
                split="all", samples=sum(len(v) for v in pools.values()),
                unit="caller sentences (primary) and whole turns", 
                gated=bool(info.gated),
                conversations=len(frame),
                note=("LLM-generated English telephone dialogue. The benign "
                      "half is legitimate service calls, which is the "
                      "population O10 says is missing."))
    exp.config(turns_per_class=args.turns, min_turn_chars=MIN_TURN_CHARS,
               caller_tag=CALLER_TAG, language="en",
               scenario_types_overlap=False,
               alarm_definition="a label other than the taxonomy's benign one")

    intent = RealIntentAdapter(os.path.join(ROOT, "models", "artifacts",
                                            "intent-classifier"))
    behaviour = RealBehaviorAdapter(os.path.join(ROOT, "models", "artifacts",
                                                 "behavior-classifier"))
    for adapter in (intent, behaviour):
        if adapter.load() is not AnalyzerStatus.AVAILABLE:
            raise SystemExit(f"{adapter.adapter_key}: "
                             f"{adapter.describe().detail}")
    exp.model(name="intent-classifier", revision=intent.version,
              license="in-repo")
    exp.model(name="behavior-classifier", revision=behaviour.version,
              license="in-repo")

    def score(turns: list[tuple[str, str]]) -> list[dict]:
        rows = []
        for scenario, text in turns:
            # language="en" - the gate is satisfied, not bypassed. These are
            # exactly the inputs the head claims to support.
            i_result = intent.analyze(text, "en")
            b_result = behaviour.analyze(text, "en")
            labels = [b.value for b in (b_result.labels or [])]
            rows.append({
                "type": scenario,
                "intent": i_result.label.value,
                "intent_confidence": i_result.confidence,
                "behaviours": labels,
                # The risk CONTRIBUTIONS fusion actually consumes, not the
                # labels. A label that maps to 0.0 risk is not a false alarm
                # in any sense the product cares about.
                "intent_risk": INTENT_RISK[Intent(i_result.label.value)],
                "behaviour_risk": max(
                    [BEHAVIOR_RISK[Behavior(v)] for v in labels] or [0.0]),
                "behaviour_alarm": any(v != BENIGN_BEHAVIOUR for v in labels),
            })
        return rows

    def summarise(rows: list[dict]) -> dict:
        if not rows:
            return {"turns": 0}
        fires = sum(1 for r in rows if r["behaviour_alarm"])
        non_normal = sum(1 for r in rows if r["intent"] != BENIGN_INTENT
                         and r["intent"] != "UNKNOWN")
        silent = sum(1 for r in rows if not r["behaviours"])
        return {
            "turns": len(rows),
            "behaviour_fire_rate": round(fires / len(rows), 4),
            "non_normal_intent_rate": round(non_normal / len(rows), 4),
            "no_behaviour_label_at_all_rate": round(silent / len(rows), 4),
            "median_intent_risk": round(
                statistics.median(r["intent_risk"] for r in rows), 4),
            "median_behaviour_risk": round(
                statistics.median(r["behaviour_risk"] for r in rows), 4),
            "top_intents": dict(collections.Counter(
                r["intent"] for r in rows).most_common(5)),
            "top_behaviours": dict(collections.Counter(
                b for r in rows for b in r["behaviours"]).most_common(5)),
        }

    scored = {key: score(turns) for key, turns in pools.items()}
    overall = {key: summarise(rows) for key, rows in scored.items()}
    exp.result("sentences_all_scenarios", overall)

    # Whole turns, for comparison only. The heads truncate at 96 tokens and a
    # median turn exceeds that, so this is a measurement of the opening of
    # each turn - which is exactly why it is reported separately rather than
    # averaged in.
    turn_level = {key: summarise(score(turns))
                  for key, turns in units["turn"].items()}
    exp.result("whole_turns_for_comparison", turn_level)

    print("\n--- caller SENTENCES (the unit VIVE actually scores) ---")
    for key in ("benign", "scam"):
        row = overall[key]
        print(f"  {key:<8} n={row['turns']:<5} "
              f"behaviour fires {row['behaviour_fire_rate']:.4f}   "
              f"non-normal intent {row['non_normal_intent_rate']:.4f}")
    for key in ("benign", "scam"):
        print(f"  {key} behaviours: {overall[key]['top_behaviours']}")

    print("--- whole turns, for comparison (truncated at 96 tokens) ---")
    for key in ("benign", "scam"):
        row = turn_level[key]
        print(f"  {key:<8} n={row['turns']:<5} "
              f"behaviour fires {row['behaviour_fire_rate']:.4f}   "
              f"non-normal intent {row['non_normal_intent_rate']:.4f}")

    # -- per scenario -----------------------------------------------------
    # Not a matched comparison - the corpus does not support one. This shows
    # whether the benign false-alarm rate is spread across situations or driven
    # by one of them, which changes what a fix would have to address.
    per_scenario: dict[str, dict] = {}
    for key, rows in scored.items():
        for scenario in sorted({r["type"] for r in rows}):
            per_scenario[f"{key}:{scenario}"] = summarise(
                [r for r in rows if r["type"] == scenario])
    exp.result("per_scenario", per_scenario)

    print("\n--- per scenario (types are disjoint; NOT a matched contrast) ---")
    for name, row in per_scenario.items():
        if not row.get("turns"):
            continue
        print(f"  {name:<22}n={row['turns']:<5}"
              f"behaviour {row['behaviour_fire_rate']:.4f}  "
              f"intent {row['non_normal_intent_rate']:.4f}")

    benign, scam = overall["benign"], overall["scam"]
    separation = {
        "benign_behaviour_fire_rate": benign["behaviour_fire_rate"],
        "scam_behaviour_fire_rate": scam["behaviour_fire_rate"],
        "benign_non_normal_intent_rate": benign["non_normal_intent_rate"],
        "scam_non_normal_intent_rate": scam["non_normal_intent_rate"],
        "behaviour_separation": round(
            scam["behaviour_fire_rate"] - benign["behaviour_fire_rate"], 4),
        "intent_separation": round(
            scam["non_normal_intent_rate"] - benign["non_normal_intent_rate"], 4),
    }
    # O10's prediction, stated as a testable threshold rather than a feeling:
    # a head that fires on more than one benign caller turn in five is
    # generating false alarms at a rate a user would notice within one call.
    separation["o10_prediction_holds"] = benign["behaviour_fire_rate"] > 0.20
    # The intent head is the one fusion weights most heavily (INTENT_RISK runs
    # to 0.94 against BEHAVIOR_RISK's 0.85), so a head that fires more often
    # on legitimate calls than on scam calls is not merely uninformative -
    # over this population it points the wrong way.
    separation["intent_head_is_inverted_on_this_population"] = (
        benign["non_normal_intent_rate"] > scam["non_normal_intent_rate"])
    separation["intent_head_scam_recall_on_speech"] = scam[
        "non_normal_intent_rate"]
    separation["heads_separate_legitimacy"] = (
        separation["behaviour_separation"] > 0.30)
    exp.result("separation", separation)

    exp.limitation(
        "The corpus is LLM-generated English dialogue, not recorded calls. "
        "Generated benign calls may be more uniformly polite than real ones, "
        "which would make the false-alarm rate here an UNDER-estimate; they "
        "may also carry generator tics that the heads key on. Neither "
        "direction can be ruled out without human-recorded calls (O15).")
    exp.limitation(
        "The scam and benign halves use DISJOINT scenario types (scam: ssn, "
        "reward, refund, support; benign: delivery, appointment, insurance, "
        "wrong number). The two populations differ in subject as well as in "
        "legitimacy, so the separation between them is an upper bound that "
        "topic alone could produce. The benign false-alarm rate - the figure "
        "O10 needs - does not depend on this.")
    exp.limitation(
        "English only. It says nothing about Hindi or Hinglish false alarms, "
        "and nothing at all about Tamil, which is gated (O11).")
    exp.limitation(
        "Turns are scored independently, as VIVE scores packets. The corpus "
        "label is per CONVERSATION, so a benign conversation's every turn is "
        "counted benign. An individual turn inside a benign call is not "
        "separately annotated, and no human verified these assignments.")
    exp.limitation(
        "This is a DIAGNOSTIC population, not a training set. Adding "
        "LLM-generated English dialogue to a corpus of human SMS would trade "
        "O10 for a provenance problem, and DATA_SPEC 8.3's human-only "
        "test-split rule would still forbid it in any test split.")
    exp.limitation(
        "The heads truncate input at MAX_LENGTH = 96 tokens. The median "
        "caller turn in this corpus is 71 words and exceeds that, so the "
        "turn-level rows describe the OPENING of each turn rather than the "
        "whole of it. The sentence-level rows are unaffected and are the "
        "primary measurement, because a sentence is also much closer to the "
        "2-second packet VIVE actually classifies.")
    exp.limitation(
        "Only the text heads are measured. The fused risk score also depends "
        "on context, anti-spoofing and speaker channels, and the temporal "
        "layer requires recurrence before escalating (Phase K), so a "
        "per-turn false alarm does not map one-to-one onto a user-visible "
        "alert.")

    holds = separation["o10_prediction_holds"]
    exp.finish(
        interpretation=(
            f"On legitimate service calls the behaviour head fires on "
            f"{benign['behaviour_fire_rate']} of caller turns, against "
            f"{scam['behaviour_fire_rate']} on scam calls, and a "
            f"a non-normal intent appears on "
            f"{benign['non_normal_intent_rate']} of benign turns against "
            f"{scam['non_normal_intent_rate']} of scam turns. O10's "
            f"prediction that "
            f"legitimate urgency would be misread "
            f"{'HOLDS' if holds else 'does NOT hold at the rate it implies'}: "
            f"the gap between the two populations is "
            f"{separation['behaviour_separation']} for behaviour and "
            f"{separation['intent_separation']} for intent - and that gap is "
            f"an upper bound, because the two halves differ in scenario as "
            f"well as in legitimacy."),
        conclusion=(
            "O10 now has the measurement it was missing, and the corpus it "
            "named as a required external action turns out to be obtainable "
            "and licence-clear, so the blocker's remaining cost is "
            "annotation and retraining rather than acquisition. It stays "
            "OPEN: nothing here has been added to training, the corpus is "
            "English-only and synthetic, and a diagnostic population cannot "
            "become a test split under DATA_SPEC 8.3's human-only rule. What "
            "changes is that the false-alarm rate on legitimate calls is now "
            "a number instead of an expectation, and it can be checked again "
            "after any future retraining."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
