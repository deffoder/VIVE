"""Exports the intent and behaviour heads to ONNX for the phone, and proves them.

The two Phase 7 heads are fine-tuned multilingual DistilBERT, 541 MB each in
fp32 - over 1 GB for the pair, most of the phone's free memory. Two thirds of
each checkpoint is the 119,547 x 768 embedding table.

Only the embedding table (Gather) is quantised. exp_text_quant.py measured
each op family separately on the held-out split: Gather int8 agrees with fp32
on 100% of intent and behaviour decisions, while MatMul int8 - the usual
recipe - moved intent macro-F1 from 0.9747 to 0.9146 per-tensor and to 0.128
per-channel. The embedding table is also where the bytes are, so Gather-only
takes each head from 541 MB to 265 MB at no measured cost.

Nothing about the int8 graph is assumed. On the held-out scamshield TEST
split (never seen in training) this measures, against the fp32 torch model
the backend runs:

  * intent: top-1 label agreement, and macro-F1 of each against gold;
  * behaviour: per-label agreement at the 0.5 threshold, exact-set agreement,
    and micro-F1 of each against gold.

The int8 graph ships only if intent agreement >= AGREEMENT_FLOOR; otherwise
the fp32 graph ships and the manifest says so.

It also writes the fixtures the Android side is tested against:

  * text_tokenizer_golden.json - HF tokenizer ids for a sample of real texts
    plus edge cases; the Kotlin WordPiece port must reproduce them exactly
    (JVM unit test, android/app/src/test/resources).
  * eval/text_eval.json - texts with the int8 graph's desktop outputs; the
    phone runs the same texts (androidTest) and must agree.

Usage:
    python scripts/mobile/export_text.py [--sample 2000]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import shutil
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ART = os.path.join(ROOT, "models", "artifacts")
OUT = os.path.join(ART, "mobile")
MAIN_CHECKOUT_DATA = os.environ.get("VIVE_DATA_DIR") or os.path.join(ROOT, "data")
TEST_SPLIT = os.path.join(MAIN_CHECKOUT_DATA, "manifests", "scamshield.test.jsonl")
GOLDEN_OUT = os.path.join(ROOT, "android", "app", "src", "test", "resources",
                          "text_tokenizer_golden.json")
REPORT = os.path.join(ROOT, "models", "evaluation", "mobile", "text_export_eval.json")

MAX_LENGTH = 96            # the training / backend truncation point
BEHAVIOR_THRESHOLD = 0.5
AGREEMENT_FLOOR = 0.98     # int8 intent top-1 agreement required to ship int8
SEED = 20260923

HEADS = {
    "intent": {"dir": "intent-classifier", "kind": "softmax",
               "version": "intent-classifier-distilbert-v1"},
    "behavior": {"dir": "behavior-classifier", "kind": "sigmoid",
                 "version": "behavior-classifier-distilbert-v1"},
}

EDGE_CASES = [
    "", "   ", "OTP", "otp bataiye jaldi", "आपका OTP क्या है? जल्दी बताइए।",
    "Your A/C XX1234 is blocked!!! Call +91-98765-43210 now.",
    "मैं बैंक से बोल रहा हूँ, आपका खाता बंद हो जाएगा",
    "நீங்கள் OTP சொல்லுங்கள்", "naïve café résumé", "ZWJ क्‍ष and ZWNJ क्‌ष",
    "tab\tnew\nline\rreturn", "emoji 😀 test 🙏🏽", "中文字符 mixed with English",
    "a" * 150, "supercalifragilisticexpialidocious", "don't won't isn't",
    "₹5,000 transfer karo abhi", "“quoted” — dash… ellipsis", "x\u0000y�z",
]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_test(sample: int) -> list[dict]:
    with io.open(TEST_SPLIT, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    rng = random.Random(SEED)
    rng.shuffle(rows)
    return rows[:sample]


def export(head: str, meta: dict) -> tuple[str, str]:
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSequenceClassification

    src = os.path.join(ART, meta["dir"])
    model = AutoModelForSequenceClassification.from_pretrained(src).eval()
    fp32 = os.path.join(OUT, f"{head}.fp32.onnx")
    int8 = os.path.join(OUT, f"{head}.onnx")
    ids = torch.ones(1, 16, dtype=torch.long)
    torch.onnx.export(
        model, (ids, torch.ones_like(ids)), fp32,
        input_names=["input_ids", "attention_mask"], output_names=["logits"],
        dynamic_axes={"input_ids": {1: "tokens"}, "attention_mask": {1: "tokens"}},
        opset_version=17, do_constant_folding=True, dynamo=False)
    quantize_dynamic(fp32, int8, weight_type=QuantType.QInt8,
                     op_types_to_quantize=["Gather"])
    return fp32, int8


def evaluate(head: str, meta: dict, int8_path: str, rows: list[dict]) -> dict:
    import numpy as np
    import onnxruntime as ort
    import torch
    from sklearn.metrics import f1_score
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    src = os.path.join(ART, meta["dir"])
    tok = AutoTokenizer.from_pretrained(src)
    model = AutoModelForSequenceClassification.from_pretrained(src).eval()
    labels = [model.config.id2label[i] for i in range(model.config.num_labels)]
    sess = ort.InferenceSession(int8_path, providers=["CPUExecutionProvider"])

    ref, q, gold, ms = [], [], [], []
    for row in rows:
        enc = tok(row["text"], truncation=True, max_length=MAX_LENGTH, return_tensors="np")
        with torch.no_grad():
            ref.append(model(input_ids=torch.from_numpy(enc["input_ids"]),
                             attention_mask=torch.from_numpy(enc["attention_mask"])
                             ).logits[0].numpy())
        began = time.perf_counter()
        q.append(sess.run(None, {"input_ids": enc["input_ids"].astype("int64"),
                                 "attention_mask": enc["attention_mask"].astype("int64")})[0][0])
        ms.append((time.perf_counter() - began) * 1000)
        gold.append(row)
    ref, q = np.stack(ref), np.stack(q)

    if meta["kind"] == "softmax":
        index = {l: i for i, l in enumerate(labels)}
        y = np.array([index[r["label_intent"]] for r in gold])
        a, b = ref.argmax(1), q.argmax(1)
        return {
            "labels": labels,
            "top1_agreement": round(float((a == b).mean()), 4),
            "macro_f1_fp32_torch": round(float(f1_score(y, a, average="macro")), 4),
            "macro_f1_int8_onnx": round(float(f1_score(y, b, average="macro")), 4),
            "desktop_ms_median": round(float(np.median(ms)), 2),
        }
    index = {l: i for i, l in enumerate(labels)}
    y = np.zeros((len(gold), len(labels)), dtype=int)
    for i, r in enumerate(gold):
        for l in r["label_behaviors"]:
            y[i, index[l]] = 1
    sig = lambda z: 1 / (1 + np.exp(-z))  # noqa: E731
    a = (sig(ref) >= BEHAVIOR_THRESHOLD).astype(int)
    b = (sig(q) >= BEHAVIOR_THRESHOLD).astype(int)
    return {
        "labels": labels,
        "per_label_agreement": round(float((a == b).mean()), 4),
        "exact_set_agreement": round(float((a == b).all(1).mean()), 4),
        "micro_f1_fp32_torch": round(float(f1_score(y, a, average="micro", zero_division=0)), 4),
        "micro_f1_int8_onnx": round(float(f1_score(y, b, average="micro", zero_division=0)), 4),
        "desktop_ms_median": round(float(np.median(ms)), 2),
    }


def device_fixtures(rows: list[dict], manifest: dict, count: int = 120) -> None:
    """Texts plus the shipped graphs' desktop outputs, for the phone to match."""
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(os.path.join(ART, HEADS["intent"]["dir"]))
    sessions = {h: ort.InferenceSession(os.path.join(OUT, s["file"]),
                                        providers=["CPUExecutionProvider"])
                for h, s in manifest["models"].items()}
    out = []
    for row in rows[:count]:
        enc = tok(row["text"], truncation=True, max_length=MAX_LENGTH, return_tensors="np")
        item = {"text": row["text"], "lang": row.get("language")}
        for head, sess in sessions.items():
            item[head] = [round(float(v), 5) for v in sess.run(None, {
                "input_ids": enc["input_ids"].astype("int64"),
                "attention_mask": enc["attention_mask"].astype("int64")})[0][0]]
        out.append(item)
    os.makedirs(os.path.join(OUT, "eval"), exist_ok=True)
    with io.open(os.path.join(OUT, "eval", "text_eval.json"), "w", encoding="utf-8") as fh:
        json.dump({"items": out}, fh, ensure_ascii=False)


def tokenizer_golden(rows: list[dict]) -> None:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(os.path.join(ART, HEADS["intent"]["dir"]))
    by_lang: dict[str, list[str]] = {}
    for r in rows:
        by_lang.setdefault(r.get("language") or "?", []).append(r["text"])
    texts = list(EDGE_CASES)
    for lang, items in sorted(by_lang.items()):
        texts += items[:60]
    cases = [{"text": t, "ids": tok(t, truncation=True, max_length=MAX_LENGTH)["input_ids"]}
             for t in texts]
    os.makedirs(os.path.dirname(GOLDEN_OUT), exist_ok=True)
    with io.open(GOLDEN_OUT, "w", encoding="utf-8") as fh:
        json.dump({"max_length": MAX_LENGTH, "cases": cases}, fh, ensure_ascii=False)
    print(f"tokenizer golden: {len(cases)} cases")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=2000)
    args = parser.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rows = load_test(args.sample)

    vocabs = {sha256(os.path.join(ART, m["dir"], "vocab.txt")) for m in HEADS.values()}
    if len(vocabs) != 1:
        raise SystemExit("the heads use different vocabularies; one tokenizer cannot serve both")
    shutil.copyfile(os.path.join(ART, HEADS["intent"]["dir"], "vocab.txt"),
                    os.path.join(OUT, "text-vocab.txt"))

    manifest = {"tokenizer": {"file": "text-vocab.txt",
                              "bytes": os.path.getsize(os.path.join(OUT, "text-vocab.txt")),
                              "do_lower_case": False, "max_length": MAX_LENGTH},
                "languages": ["en", "hi", "hi-en"], "models": {}}
    report = {"split": "scamshield test (held out)", "sample": len(rows), "heads": {}}
    for head, meta in HEADS.items():
        print(f"=== {head}")
        fp32, int8 = export(head, meta)
        metrics = evaluate(head, meta, int8, rows)
        agreement = metrics.get("top1_agreement", metrics.get("per_label_agreement"))
        ship_int8 = agreement >= AGREEMENT_FLOOR
        if not ship_int8:
            os.replace(fp32, int8)
        else:
            os.remove(fp32)
        metrics["shipped"] = "int8 embeddings (Gather), fp32 MatMul" if ship_int8 else "fp32"
        print(json.dumps(metrics, indent=1))
        report["heads"][head] = metrics
        manifest["models"][head] = {
            "file": os.path.basename(int8), "bytes": os.path.getsize(int8),
            "sha256": sha256(int8), "precision": "int8-embeddings" if ship_int8 else "fp32",
            "kind": meta["kind"], "labels": metrics["labels"],
            "threshold": BEHAVIOR_THRESHOLD if meta["kind"] == "sigmoid" else None,
            "version": meta["version"] + ("-int8" if ship_int8 else ""),
        }
    with io.open(os.path.join(OUT, "text_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with io.open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    tokenizer_golden(rows)
    device_fixtures(rows, manifest)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
