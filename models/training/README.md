# VIVE — Training Instructions

How to reproduce the VIVE ML pipeline: data, manifests, splits, training and
verification.

> **Nothing here may be quoted as a VIVE accuracy figure.** Every metric this
> pipeline produces is measured on a held-out split of one SMS corpus. That is
> not a call-transcript benchmark and not an end-to-end fraud-detection result.

---

## 1. Environment

The ML stack is **deliberately separate** from the backend. The application must
not gain a torch dependency (`docs/ARCHITECTURE.md` decision 8).

```bash
cd models && python -m venv .venv && . .venv/Scripts/activate
```

```bash
pip install torch==2.5.1+cu118 torchaudio==2.5.1+cu118 --index-url https://download.pytorch.org/whl/cu118
```

```bash
pip install "transformers>=4.44,<5" "scikit-learn>=1.5" "accelerate>=0.33" speechbrain onnxruntime
```

**Why cu118:** the development machine runs driver 461.72, which caps at CUDA
11.2. The cu118 wheels work through minor-version compatibility; cu12x wheels
do not. On a newer driver, use a matching build.

Verify:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

---

## 2. Data

```bash
python scripts/training/build_manifests.py
```

Downloads nothing on its own — it reads `data/raw/scamshield/*.jsonl` and writes
`data/manifests/`. Fetch the raw corpus first from
<https://huggingface.co/datasets/sidzzz07/scamshield-dataset> (MIT).

The manifests are the **source of truth for splits**. Never re-split downstream:
splits are content-addressed by a hash of the normalised text, so a duplicated
message always lands in the same split. Re-splitting destroys that guarantee.

```bash
python scripts/training/build_eval_splits.py
```

Writes `data/manifests/eval/` plus `eval_splits.json`. Splits that **cannot** be
populated are recorded with `available: false` and a reason — they are never
filled with substitutes.

---

## 3. Training

Local, on a 4 GB GPU:

```bash
python models/training/train_text_classifier.py --task intent --epochs 2 --batch-size 16
```

```bash
python models/training/train_text_classifier.py --task behavior --epochs 2 --batch-size 16
```

Artifacts land in `models/artifacts/<task>-classifier/`; a reproducibility
record with the measured metrics lands in
`models/evaluation/<task>_training_report.json`.

### Memory constraints on 4 GB

Three settings exist solely because of the 4 GB budget, and each was driven by
an actual OOM rather than a guess:

| Setting | Why |
|---|---|
| Embeddings frozen by default | The 119k multilingual vocabulary holds ~2/3 of the parameters. Their gradients and optimizer states alone overflow 4 GB. Pass `--train-embeddings` on a larger card. |
| `AdamW(foreach=False)` | The multi-tensor path allocates temporaries that were the specific allocation that overflowed. |
| Dynamic padding, `--max-length 96` | Median length is 30 tokens; the corpus p99 is 95. Fixed 128-padding spent roughly 4x the compute on padding. |

`--grad-checkpointing` is available for larger backbones.

### Larger backbones

MuRIL is the better Indic backbone but ships a `.bin` checkpoint, which
transformers refuses to `torch.load` on torch < 2.6 (CVE-2025-32434). XLM-R
ships safetensors but its optimizer states exhaust 4 GB — verified by OOM.

Use the Colab notebook for either:

```text
models/notebooks/train_text_classifiers_colab.ipynb
```

It is restartable (checkpoints every epoch) and does not assume a GPU is
allocated.

---

## 4. Pretrained stack

```bash
python scripts/training/check_pretrained.py
```

Smoke tests only — load and run, shapes checked, **no accuracy measured**.
Writes `models/evaluation/pretrained_checks.json`.

Currently: Silero VAD, AASIST and ECAPA-TDNN load and run. AI4Bharat Indic ASR
returns 403 — the repositories are gated and need their terms accepted once on
the HuggingFace model page (`docs/BLOCKERS.md` O7).

---

## 5. Reproducibility

Every training run records: base model, label set, seed (`20260921`),
hyperparameters, dataset sizes, python/torch versions, device name, platform,
start and end timestamps, wall-clock duration, peak VRAM, and the measured test
metrics — in `models/evaluation/<task>_training_report.json`.

Checkpoints are **git-ignored** (`models/artifacts/**`). The manifests, scripts
and reports are tracked, so a run is reproducible from a commit without the
repository carrying model weights.

---

## 6. What this pipeline does not do

- It does not train AASIST, ECAPA or ASR. Those are pretrained checkpoints, and
  wiring them into the backend is the next phase.
- It does not measure EER, WER or any audio metric. No audio corpus was
  acquired.
- It does not cover Tamil. The corpus has none (`BLOCKERS.md` O8).
- It cannot predict five of the twelve intents, or two of the eight behaviours,
  because those labels have no source in the data. See `docs/DATA_SPEC.md` 8.1.
