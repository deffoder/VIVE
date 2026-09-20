# data/

Datasets for VIVE. Full rules: [`../docs/DATA_SPEC.md`](../docs/DATA_SPEC.md).

## Layout

| Directory | Contents | Tracked in git |
|---|---|---|
| `raw/` | Source corpora exactly as downloaded | **No** |
| `processed/` | Resampled / segmented, ready for training | **No** |
| `manifests/` | JSONL indexes — the source of truth | **Yes** |

Audio never enters git. The dataset is reproducible from `manifests/` plus the
conversion scripts in `../scripts/setup/`, without shipping corpora.

## Working audio format

**16 kHz · mono · `pcm_s16le`** — matching the analysis contract in
[`../docs/ML_SPEC.md`](../docs/ML_SPEC.md) §5. Conversion from `raw/` to
`processed/` is scripted, never manual.

## Before adding a dataset

1. Check the license and record it in the manifest. No license, no use.
2. Record `provenance` (the source URL or agreement).
3. Assign `split` in the manifest, never at load time.
4. Run the speaker- and generator-leakage checks (`DATA_SPEC.md` §5). A failed
   check blocks the training run.
5. Redact PII — account numbers, OTP digits, names.

## Current state

Empty. No dataset has been downloaded: real ML is the final phase and the
architecture phase explicitly excludes large downloads and training
(`../docs/IMPLEMENTATION_PLAN.md`, Phase 8).

License verification for the candidate sources is tracked as **O5** in
[`../docs/BLOCKERS.md`](../docs/BLOCKERS.md).

## Real call audio

Never committed here. Never used for training without recorded consent. See
[`../docs/SECURITY_SPEC.md`](../docs/SECURITY_SPEC.md) §4.
