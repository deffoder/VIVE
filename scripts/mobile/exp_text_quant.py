"""Which int8 recipe keeps the text heads faithful?

MatMul+Gather per-tensor int8 was rejected by export_text.py: intent macro-F1
fell 0.9375 -> 0.7878. This isolates the cause by quantising one op family at a
time, per-tensor and per-channel, and measuring each against the fp32 graph on
the held-out test split. Results: models/evaluation/mobile/text_quant_experiment.json

Usage:
    python scripts/mobile/exp_text_quant.py [--sample 800]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from export_text import ART, HEADS, MAX_LENGTH, OUT, ROOT, load_test  # noqa: E402

VARIANTS = {
    "matmul": dict(op_types_to_quantize=["MatMul"], per_channel=False),
    "matmul_pc": dict(op_types_to_quantize=["MatMul"], per_channel=True),
    "gather": dict(op_types_to_quantize=["Gather"], per_channel=False),
    "gather_pc": dict(op_types_to_quantize=["Gather"], per_channel=True),
    "matmul_pc+gather_pc": dict(op_types_to_quantize=["MatMul", "Gather"], per_channel=True),
}


def main() -> int:
    import numpy as np
    import onnxruntime as ort
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from sklearn.metrics import f1_score
    from transformers import AutoTokenizer

    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=800)
    args = parser.parse_args()
    rows = load_test(args.sample)
    tok = AutoTokenizer.from_pretrained(os.path.join(ART, HEADS["intent"]["dir"]))
    enc = [tok(r["text"], truncation=True, max_length=MAX_LENGTH, return_tensors="np") for r in rows]

    def run(path):
        s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        return np.stack([s.run(None, {"input_ids": e["input_ids"].astype("int64"),
                                      "attention_mask": e["attention_mask"].astype("int64")})[0][0]
                         for e in enc])

    results = {}
    tmp = os.path.join(OUT, "_quant_tmp.onnx")
    for head in ("intent", "behavior"):
        fp32_path = os.path.join(OUT, f"{head}.onnx")    # export_text shipped fp32
        ref = run(fp32_path)
        labels = HEADS[head]
        results[head] = {}
        for name, kw in VARIANTS.items():
            quantize_dynamic(fp32_path, tmp, weight_type=QuantType.QInt8, **kw)
            q = run(tmp)
            size = round(os.path.getsize(tmp) / 1e6, 1)
            if head == "intent":
                id2label = json.load(open(os.path.join(ART, labels["dir"], "config.json"),
                                          encoding="utf-8"))["id2label"]
                index = {v: int(k) for k, v in id2label.items()}
                y = np.array([index[r["label_intent"]] for r in rows])
                m = {"top1_agreement": round(float((ref.argmax(1) == q.argmax(1)).mean()), 4),
                     "macro_f1_fp32": round(float(f1_score(y, ref.argmax(1), average="macro")), 4),
                     "macro_f1_q": round(float(f1_score(y, q.argmax(1), average="macro")), 4)}
            else:
                a, b = ref >= 0, q >= 0          # sigmoid >= 0.5  <=>  logit >= 0
                m = {"per_label_agreement": round(float((a == b).mean()), 4),
                     "exact_set_agreement": round(float((a == b).all(1).mean()), 4)}
            m["size_mb"] = size
            m["max_abs_logit_diff"] = round(float(np.abs(ref - q).max()), 4)
            results[head][name] = m
            print(head, name, m, flush=True)
    os.remove(tmp)
    out = os.path.join(ROOT, "models", "evaluation", "mobile", "text_quant_experiment.json")
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump({"sample": len(rows), "results": results}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
