# VIVE — Training Instructions

How to reproduce the VIVE ML pipeline: data, manifests, splits, training and
verification.

> **Nothing here may be quoted as a VIVE accuracy figure.** Every metric this
> pipeline produces is measured on a held-out split of one SMS corpus. That is
> not a call-transcript benchmark and not an end-to-end fraud-detection result.

---

## 1. Environment

The training stack is **deliberately separate** from the backend, so training
dependencies never become runtime dependencies.

> **Correction (Phase 8A).** An earlier version of this line claimed
> `ARCHITECTURE.md` decision 8 forbids a backend torch dependency. It does not
> — decision 8 is about **Android** never running the ML pipeline, and
> decision 5 explicitly puts the backend on "the same runtime as the ML stack".
> The backend therefore *may* host real models, and from Phase 8A it does, via
> the optional `backend[ml]` extra with lazy imports so the base install and
> its tests stay dependency-free.

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

Currently: Silero VAD, AASIST, ECAPA-TDNN and AI4Bharat `indicwav2vec-hindi`
all load and run.

The ASR repository ships only `pytorch_model.bin`, which transformers refuses
to load on torch < 2.6 (CVE-2025-32434). Do not disable that check. Audit and
convert once instead:

```bash
python scripts/training/safe_load_bin.py --bin <snapshot>/pytorch_model.bin --out models/artifacts/_pretrained/indicwav2vec-hindi/model.safetensors
```

It walks the pickle opcode stream without executing it and refuses any file
referencing a symbol outside a tensor-rebuild allowlist. Then measure WER:

```bash
python scripts/training/eval_asr_hindi.py --model-dir models/artifacts/_pretrained/indicwav2vec-hindi --limit 0
```

### Tamil and the multilingual path

Survey the candidates before downloading anything. Licence, gating and
reachability come from repository metadata and a real download probe, never
from a model card's prose:

```bash
python scripts/training/survey_tamil_asr.py
```

Recorded in `models/evaluation/tamil_asr_survey.json`. Two results matter:
`ai4bharat/indicwav2vec_v1_tamil` publishes **no weight files**, and
`facebook/mms-1b-all` is **CC-BY-NC-4.0**, which forbids commercial use.

Whisper is the multilingual path — one architecture for both priority
languages, MIT, ungated, safetensors:

```bash
python scripts/training/eval_asr_whisper.py --lang ta --model-dir models/artifacts/_pretrained/whisper-large-v3-turbo --limit 0
```

`--lang hi` runs the same model on Hindi, which is how Whisper and
indicwav2vec are compared rather than ranked by assumption.

### Why the normaliser is shared

`models/training/asr_text.py` holds the one normalisation used by every ASR
evaluation. WER is extremely sensitive to normalisation, so two scripts that
normalise differently produce numbers that cannot be compared. Do not inline a
variant. The Hindi figure was re-measured after this was factored out and came
back bit-identical, which is the standard any change here must meet.

The Whisper evaluation also reports a **script ratio**: the share of letters in
the expected script. Whisper can transcribe into the wrong language, which
inflates WER in a way that looks like poor accuracy. A low script ratio means
*wrong language*, not *bad model*, and the two need different fixes.

---

## 4.1 Audits

Run these before trusting any documented number.

```bash
python scripts/training/audit_label_coverage.py
```

Measures per-label support per split and, more importantly, whether intent and
behaviour actually carry independent evidence. They do not in this corpus:
`intent != NORMAL_CONVERSATION` reproduces `is_scam` for 100% of records and no
benign record carries a behaviour flag (`BLOCKERS.md` O10). Risk fusion assumes
independence, so this bounds what the fused score and its confidence mean.
Writes `models/evaluation/label_coverage_audit.json`.

```bash
python scripts/training/check_docs_consistency.py
```

Compares the figures in the specs against the JSON artifacts, checks that every
cited blocker id exists, and fails if a resolved blocker is still described as
blocking. Exit code 1 on any inconsistency, so it can gate a commit. It caught
a stale "accept the terms" instruction that had already been resolved.

```bash
python scripts/training/survey_tamil_asr.py
```

Licence, gating and real file reachability for ASR candidates.

## 4.2 Stamping the label mapping (required before real inference)

The Phase 7 runs saved generic `LABEL_0..LABEL_11`, so a checkpoint did not
carry its own label mapping. Stamp it before serving the model:

```bash
python scripts/training/stamp_label_mapping.py
```

It takes the order from `vive_labels.py`, **cross-checks it against the order
recorded in the training report**, and refuses to write if they disagree -
a disagreement means the true order is unknown, and guessing is the exact
failure this prevents. `--check` verifies without writing.

The backend adapter validates the stamped mapping again at load time and
returns `LOAD_ERROR` on any mismatch, so an unstamped or reordered checkpoint
cannot serve predictions.

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
