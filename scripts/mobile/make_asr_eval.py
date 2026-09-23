"""Builds the on-device ASR evaluation set and its desktop reference outputs.

For each language in asr_manifest.json this writes N FLEURS test utterances as
16 kHz mono 16-bit WAV, plus `eval.json` holding for every clip:

  * the FLEURS reference transcript (for WER),
  * the transcript and decoder confidence that ONNX Runtime on THIS machine
    produces from the SAME shipped graph with the SAME greedy decoder.

The phone decodes the same WAVs (androidTest `AsrDeviceEvalTest`) and
`score_device_asr.py` compares the two. Agreement with the desktop output is
the check that the Android port - int16 read, normalisation, tensor layout,
CTC decode - is faithful; WER against the reference is the accuracy claim.

The WAV is what the phone reads, so the desktop reference is computed from
the int16-quantised WAV too, not from the float source: otherwise the two
sides would differ by quantisation before either did anything.

Usage:
    python scripts/mobile/make_asr_eval.py [--clips 20]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from export_asr import (MODELS, OUT, SAMPLE_RATE, ctc_greedy,  # noqa: E402
                        fleurs, normalise_wave, read_json)


def logsumexp_conf(logits, blank):
    import numpy as np
    ids = logits.argmax(axis=-1)
    kept = ids != blank
    if not kept.any():
        return None
    m = logits.max(axis=-1, keepdims=True)
    lse = (m[:, 0] + np.log(np.exp(logits - m).sum(axis=-1)))
    return float(np.exp((logits.max(axis=-1) - lse)[kept].mean()))


def main() -> int:
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf

    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=int, default=20)
    parser.add_argument("--manifest", default="asr_manifest.json",
                        help="e.g. a manifest naming the fp32 graph, to check the port without int8")
    parser.add_argument("--out", default="eval.json")
    args = parser.parse_args()

    manifest = read_json(os.path.join(OUT, args.manifest))
    root = os.path.join(OUT, "eval")
    out = {"clips": []}
    for lang, spec in manifest["models"].items():
        session = ort.InferenceSession(os.path.join(OUT, spec["file"]),
                                       providers=["CPUExecutionProvider"])
        os.makedirs(os.path.join(root, lang), exist_ok=True)
        for i, (wave, reference) in enumerate(fleurs(MODELS[lang]["fleurs"], args.clips)):
            name = f"{lang}/{i:02d}.wav"
            pcm = np.clip(np.round(wave * 32768.0), -32768, 32767).astype("<i2")
            sf.write(os.path.join(root, name), pcm, SAMPLE_RATE, subtype="PCM_16")
            x = pcm.astype("float32") / 32768.0
            x = normalise_wave(x) if spec["do_normalize"] else x
            logits = session.run(None, {"input_values": x[None, :]})[0][0]
            out["clips"].append({
                "lang": lang, "wav": name, "reference": reference,
                "desktop_hyp": ctc_greedy(logits, spec["vocab"], spec["blank_id"],
                                          spec["delimiter"]),
                "desktop_conf": logsumexp_conf(logits, spec["blank_id"]),
                "seconds": round(len(pcm) / SAMPLE_RATE, 2),
            })
        print(f"{lang}: {args.clips} clips")
    with io.open(os.path.join(root, args.out), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
