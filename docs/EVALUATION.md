# VIVE — Phase 9 Evaluation Report

Measured on 2026-09-22. Every figure here comes from a record under
`models/evaluation/phase9/`, each of which carries its own environment, seed,
dataset licences and limitations. Nothing in this document is estimated,
extrapolated or carried over from an earlier phase without being marked as
such.

**Hardware for every timing figure:** AMD 12-thread CPU, 7.5 GB RAM, Windows
11, onnxruntime on `CPUExecutionProvider` only — the installed driver caps at
CUDA 11.2 while `onnxruntime-gpu` needs CUDA 12. No timing here transfers to
other hardware.

Reproduce any row with the script named in its section. All experiments are
deterministic given the recorded seed, except where a dataset is streamed and
the network decides which shards arrive first.

---

## 1. How to read this document

Three kinds of statement, kept apart on purpose.

**MEASURED** — a number produced by a recorded run, with its sample size.

**INTERPRETATION** — what the number appears to mean. Argued, not measured.

**UNVERIFIED** — something VIVE does not know. These are the entries that
bound what the product may claim, and they are the most important part of the
report.

A metric is quoted only with the conditions that produced it. "Hindi WER
0.1141" is meaningless; "Hindi WER 0.1141 on 40 clean FLEURS read-speech
utterances" is a fact.

---

## 2. Headline: what Phase 9 changed

Three findings alter what VIVE may say about itself.

1. **AASIST does not work on this audio.** Against a two-class probe it
   separates synthetic from genuine speech at chance — best EER 0.4333 with a
   90% interval of 0.3500–0.5000, which contains 0.50. The anti-spoofing
   channel must not be presented as evidence. This escalates `BLOCKERS.md` O12
   from "unreliable out of domain" to "no measured discrimination".

2. **The risk score is not a probability.** Expected calibration error 0.3171.
   The rule in `PROJECT_SPEC.md` §2.1 forbidding "91 = 91% chance of fraud" is
   now backed by a reliability table rather than by assertion alone.

3. **The packet budget is met at the median and missed at the tail.** Steady
   state 751–844 ms median against a 1000 ms budget, p95 930–1069 ms, with
   3.7–11.1% of packets overrunning. O13 now has a precise answer instead of a
   range that straddled the boundary.

Phase 9 also found and fixed a live defect in `fusion.py` (§11) that made a
model outage *raise* risk, and penalised Tamil callers specifically.

---

## 3. Experiment index

| ID | Question | Script |
|---|---|---|
| 9A | Are the datasets licence-clean, split-clean and large enough? | `scripts/evaluation/audit_datasets.py` |
| 9B | Can AASIST give evidence before ~4 s? | `scripts/evaluation/exp_aasist_window.py` |
| 9C | How much ASR accuracy survives a call channel? | `scripts/evaluation/exp_asr_robustness.py` |
| 9D | What is ECAPA's verification error rate? | `scripts/evaluation/exp_ecapa_speaker.py` |
| 9E | Intent/behaviour accuracy, leakage cost, head dependence | `scripts/evaluation/exp_text_heads.py` |
| 9F | Channel contribution and score calibration | `scripts/evaluation/exp_fusion_calibration.py` |
| 9G | Temporal escalation, spike resistance, recovery | `scripts/evaluation/exp_temporal_risk.py` |
| 9H | OOD behaviour and failure injection | `scripts/evaluation/exp_ood_failure.py` |
| 9I | End-to-end packet cost | `scripts/evaluation/exp_runtime_e2e.py` |

Integrity of the whole set is checked by
`scripts/evaluation/check_phase9_integrity.py`, which refuses a record with no
stated limitations and fails if a scoped metric appears in the docs without its
scope.

---

## 4. Datasets and provenance (9A)

**MEASURED.** 85,602 scamshield records across train (68,412), val (8,546) and
test (8,644). All 85,602 carry `MIT/VERIFIED`. Zero records lack a verified
licence. Zero exact text collisions between train and test.

**MEASURED.** 622 of 8,644 test records (7.20%) share a digits-masked key with
a training record — near-duplicate leakage that exact hashing did not test for.
Concentrated in `Synthetic_Tier_C` (320) and `Smishing_Dataset` (250).

**MEASURED.** 134 of 178 `split_group` lineages appear in more than one split.
The large ones are whole source corpora, which cannot be held out entirely and
still leave test data from them; 129 straddling groups hold ≤200 records and
account for 359 test records.

**MEASURED.** Zero Tamil codepoints (U+0B80–U+0BFF) in the entire corpus. Zero
records tagged Tamil.

**MEASURED.** `intent != NORMAL_CONVERSATION` reproduces `is_scam` for
85,602/85,602 records (100.0000%). Zero benign records carry a non-NORMAL
behaviour.

**Corpora used for audio evaluation**, licences verified against repository
metadata before download:

| Source | Licence | Role |
|---|---|---|
| `google/fleurs` hi_in/ta_in | CC-BY-4.0 | ASR benchmark, bonafide half of the probe |
| `openslr/librispeech_asr` clean/test | CC-BY-4.0 | speaker verification (real `speaker_id`) |
| `microsoft/speecht5_tts` + `speecht5_hifigan` | MIT | synthetic half of the probe |
| `Matthijs/cmu-arctic-xvectors` | MIT | speaker embeddings for synthesis |
| ASVspoof2019 LA | registration required | **UNAVAILABLE** |
| VoxCeleb1 | request form required | **UNAVAILABLE** |

`facebook/mms-tts-{hin,tam}` was rejected: CC-BY-NC-4.0 forbids commercial use,
the same rule that rejected `facebook/mms-1b-all` in Phase 7.
`ai4bharat/indic-parler-tts` is Apache-2.0 but `gated: auto`, so it needs the
account holder to accept terms; **it was not downloaded**.

**UNVERIFIED.** Licence status reflects repository metadata at build time. It
is not a legal review.

---

## 5. Anti-spoofing: AASIST does not discriminate (9B)

This was the experiment Phase 9 most needed, and its result is the most
consequential.

### The probe

No anti-spoofing corpus was obtainable (O5), so a two-class probe was built
from openly-licensed parts: 60 synthetic clips from SpeechT5 + HiFiGAN (MIT,
16 kHz native, no resampling) across 4 distinct CMU Arctic speakers, against 60
bonafide FLEURS clips.

**Validity control, MEASURED.** Silero VAD — an independent model with no stake
in the outcome — detects speech in 20/20 synthetic clips at GOOD quality,
median RMS 0.0523 against 0.0428 for bonafide. The synthetic half is genuine
speech, so a near-chance result is a fact about AASIST, not about broken audio.

### Is a shorter window even valid?

**MEASURED.** AASIST accepts variable-length input natively. Its classifier
reads max- and average-pooled features plus a master node, so `nn.Linear` sees
a fixed width regardless of input length. Shorter windows required **no**
padding, tiling, resampling or adapter change. Architecturally valid is not the
same as trained-for: the checkpoint was trained at 64,600 samples.

### Result

**MEASURED**, 60 spoof + 60 bonafide at each length, all prefixes of the same
clips:

| Window | Spoof median | Bonafide median | EER | 90% interval | AUC | Latency |
|---|---:|---:|---:|---|---:|---:|
| 1.0000 s | 0.9982 | 0.9975 | 0.4500 | 0.3667–0.5500 | 0.4875 | 95 ms |
| 2.0000 s | 0.9845 | 0.9643 | 0.4500 | 0.3833–0.5500 | 0.5039 | 183 ms |
| 3.0000 s | 0.9032 | 0.6934 | 0.4167 | 0.3583–0.5000 | 0.5317 | 279 ms |
| 4.0000 s | 0.8118 | 0.4193 | 0.4333 | 0.3500–0.5000 | 0.5592 | 375 ms |
| **4.0375 s (native)** | 0.8225 | 0.4248 | **0.4333** | **0.3500–0.5000** | **0.5600** | 384 ms |

Agreement with each clip's own full-window score, label-free:

| Window | Median abs. delta | Verdict flips at 0.5 |
|---|---:|---:|
| 1.0 s | 0.3565 | 45.0% |
| 2.0 s | 0.2103 | 38.3% |
| 3.0 s | 0.0827 | 19.2% |
| 4.0 s | 0.0017 | 1.7% |

**INTERPRETATION.** AASIST does not separate these classes at any window
length. Every bootstrap interval reaches or crosses 0.50. The question "can we
get anti-spoofing evidence earlier?" is moot: there is no measured performance
at the native length to deliver earlier.

Two checks stop this being an artefact of the setup:

- **The confound cuts the reassuring way.** The probe's classes differ in
  language and channel (English vocoder output vs Hindi/Tamil recorded
  speech), which should make separation *easier* than real spoofing. A
  near-chance result under a favourable confound is conservative, not
  optimistic.
- **The class-index convention cannot rescue it.** Reversing it gives AUC
  0.4400 — also chance.

**UNVERIFIED.** One synthesis family, one language, 120 clips. This does not
establish that AASIST fails in general, and it is not an ASVspoof-comparable
EER. It establishes that VIVE has no evidence AASIST works on audio like this,
which is the operative fact for the product.

**Fusion weights were NOT changed on this basis.** Re-weighting a channel from
a single-family probe would be fitting to the probe. That needs a real corpus
(O5).

---

## 6. ASR under call conditions (9C)

**MEASURED**, 40 FLEURS utterances per language per condition, decoded through
the real `IndicConformerAsrAdapter`, all outputs at 16 kHz, shared Phase 7
normaliser:

| Condition | Hindi WER | Hindi CER | Tamil WER | Tamil CER |
|---|---:|---:|---:|---:|
| clean | 0.1141 | 0.0421 | 0.2936 | 0.1080 |
| snr20 | 0.1217 | 0.0457 | 0.2832 | 0.0972 |
| snr10 | 0.1597 | 0.0636 | 0.3219 | 0.1063 |
| snr5 | 0.1683 | 0.0773 | 0.3994 | 0.1506 |
| telephony_band (300–3400 Hz) | 0.1340 | 0.0492 | 0.2876 | 0.0972 |
| g711_ulaw | 0.1198 | 0.0432 | 0.2876 | 0.0987 |
| narrowband_8k | 0.1179 | 0.0427 | 0.2876 | 0.0989 |
| reverb | 0.1369 | 0.0503 | 0.3070 | 0.1041 |
| quiet −20 dB | 0.1131 | 0.0427 | 0.3025 | 0.1158 |
| clipped | 0.1141 | 0.0423 | 0.2832 | 0.1002 |
| **window_2s** | **0.8959** | 0.8735 | **0.9147** | 0.8866 |

**INTERPRETATION.** The hypothesis held: channel effects cost little. Telephony
band-limiting costs Hindi 0.1141 → 0.1340; μ-law and narrowband are nearly
free. Additive noise is the harsher axis, and Tamil degrades faster than Hindi
under it (0.2936 → 0.3994 at SNR 5).

**The 2 s window is the dominant degradation, and its number needs care.** The
row scores a 2 s decode against the *full* utterance reference, because no
per-window ground truth exists. It is therefore dominated by deletions and is
**not** an accuracy figure comparable to the other rows. What it establishes is
structural: VIVE's analysis window sees a fragment of a sentence, and the
intent head reads that fragment rather than a complete utterance.

**UNVERIFIED.** Every degradation is simulated. A real call adds packet loss,
jitter concealment, echo cancellation, automatic gain control and an unknown
handset. **No telephone-call WER exists for VIVE and none may be quoted.** The
clean FLEURS figure remains an upper bound and keeps its "clean read speech"
label wherever it appears.

---

## 7. Speaker verification (9D)

**MEASURED**, 25 LibriSpeech test-clean speakers, 75 genuine and 300 impostor
pairs per condition, through the real `EcapaSpeakerAdapter`. Genuine pairs use
two *different* utterances from the same speaker — splitting one recording
would measure recording similarity, not speaker similarity.

| Condition | EER | EER threshold | AUC | Genuine median | Impostor median | FRR @0.5 | FAR @0.5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| clean_full | 0.0000 | 0.554 | 1.0000 | 0.813 | 0.074 | 0.0000 | 0.0000 |
| vive_window_2s | 0.0150 | 0.292 | 0.9980 | 0.555 | 0.058 | **0.2933** | 0.0000 |
| telephony_band | 0.0033 | 0.533 | 0.9995 | 0.787 | 0.257 | 0.0000 | 0.0133 |
| g711_ulaw | 0.0000 | 0.566 | 1.0000 | 0.813 | 0.091 | 0.0000 | 0.0000 |

**MEASURED.** The `NO_REFERENCE` contract holds: with no enrolled voice, and
with an empty reference, the adapter returns `NO_REFERENCE` and `similarity =
None`.

**INTERPRETATION.** ECAPA discriminates speakers well on clean speech and
survives the channel simulations almost unchanged. The operationally important
row is `vive_window_2s`: the *ranking* barely degrades (AUC 0.9980) but the
*operating point* moves sharply — the genuine median drops 0.813 → 0.555 and
the EER threshold 0.554 → 0.292. **A fixed threshold of 0.5 would falsely
reject 29.33% of genuine 2 s windows.** Any threshold VIVE adopts must come
from a measurement like this, not be chosen by eye.

**UNVERIFIED.** LibriSpeech is clean English audiobook read speech — the *easy*
case. These are not comparable to published VoxCeleb ECAPA numbers, and
VoxCeleb itself remains unavailable (O5). Speaker *verification* is not speaker
*identification*: nothing here supports recognising who a caller is.

**In production this channel contributes nothing**, because there is no
enrolment source (O3) and the adapter correctly reports `NO_REFERENCE` on every
packet — confirmed 30/30 in the end-to-end run (§10).

---

## 8. Intent and behaviour (9E)

**MEASURED**, 8,644 held-out records through the real adapters. Tokenisation
was verified byte-identical between the evaluation environment (transformers
4.57.6) and the backend runtime (5.17.0), so these numbers describe the
shipped pipeline.

| Split | Records | Intent macro-F1 | Behaviour macro-F1 |
|---|---:|---:|---:|
| full test | 8,644 | 0.9219 | 0.9460 |
| de-leaked | 8,022 | 0.9213 | 0.9403 |

Intent macro-F1 is over **7 of 12** classes present in the test split.
Behaviour macro-F1 counts all 8, absent ones as zero.

**MEASURED — hypothesis refuted.** Removing all 622 near-duplicate records
moved intent macro-F1 by **−0.0006** and behaviour by **−0.0057**. The leakage
found in 9A is real but costs essentially nothing. The concern it raised is
withdrawn, and it is recorded rather than deleted.

### Per-class, de-leaked

Intent:

| Label | Support | P | R | F1 |
|---|---:|---:|---:|---:|
| NORMAL_CONVERSATION | 5,057 | 0.9868 | 0.9873 | 0.9871 |
| UNKNOWN | 2,529 | 0.9714 | 0.9676 | 0.9695 |
| BANKING_CREDENTIAL_REQUEST | 136 | 0.9712 | 0.9926 | 0.9818 |
| MONEY_TRANSFER_REQUEST | 146 | 0.9524 | 0.9589 | 0.9556 |
| URGENT_ACTION | 90 | 0.9451 | 0.9556 | 0.9503 |
| THREAT_OR_INTIMIDATION | 56 | 0.9818 | 0.9643 | 0.9730 |
| **OTP_REQUEST** | **8** | — | — | **UNMEASURABLE** |
| PASSWORD_REQUEST, CARD_DETAILS_REQUEST, ACCOUNT_CHANGE_REQUEST, REMOTE_ACCESS_REQUEST, CONFIDENTIAL_INFORMATION | 0 | — | — | **NO TEST DATA** |

Behaviour:

| Label | Support | P | R | F1 |
|---|---:|---:|---:|---:|
| NORMAL | 6,278 | 0.9918 | 0.9769 | 0.9843 |
| REWARD_PROMISE | 906 | 0.9637 | 0.9658 | 0.9647 |
| URGENCY | 580 | 0.9564 | 0.9828 | 0.9694 |
| PRESSURE | 451 | 0.8787 | 0.8514 | 0.8649 |
| FEAR | 258 | 0.9540 | 0.9651 | 0.9595 |
| AUTHORITY_IMPERSONATION | 294 | 0.9038 | 0.8946 | 0.8991 |
| THREAT, SECRECY | 0 | — | — | **NO TEST DATA** |

`OTP_REQUEST` has 8 test records, below the 30-record floor. **Its F1 must
never be quoted as a capability** — this is VIVE's highest-value intent and it
is unmeasurable.

### Are the two heads independent evidence?

`fusion.py` combines them with a noisy-OR, which assumes conditional
independence. **MEASURED** on the model outputs fusion actually consumes:

| Quantity | Value |
|---|---:|
| Pearson (intent risk vs behaviour risk) | 0.5281 |
| Spearman | 0.6247 |
| Mutual information | 0.1202 bits |
| Normalised mutual information | 0.3287 |
| Predicted non-NORMAL intent matches `is_scam` | 98.3688% |
| Behaviour flag matches `is_scam` | 84.4285% |
| Behaviour flag rate on benign records | 0.0100 |
| Behaviour flag rate on scam records | 0.5921 |

**INTERPRETATION.** Moderately dependent, not redundant — NMI 0.3287 means
they share about a third of the smaller entropy. The behaviour head is highly
specific (fires on 1% of benign text) but abstains often (59% on scam text).

**UNVERIFIED.** This is SMS text, not call transcripts, and records are scored
from ground-truth text rather than ASR output. Real end-to-end accuracy is
additionally bounded by ASR (P4) and by the 2 s fragment problem (§6). Intent
labels remain 100% collinear with `is_scam` (O10), so intent macro-F1 partly
measures the easier scam/not-scam boundary and **is not intent-discrimination
accuracy**. **Tamil is not evaluated at all** and stays `UNSUPPORTED_LANGUAGE`.

---

## 9. Fusion and calibration (9F)

Driven by real head outputs over held-out text with the audio channels at their
true production values for a text-only record: no anti-spoof score, speaker
`NO_REFERENCE`. That is also what fusion receives during the first ~4 s of
every real call. Thresholds selected on **validation** (8,546), reported on the
de-leaked **test** split (8,022).

### Ablation

| Configuration | AUC | Scam median | Benign median | P@65 | R@65 | Val-selected threshold |
|---|---:|---:|---:|---:|---:|---:|
| full_text_pipeline | 0.9825 | 36 | 18 | 0.9972 | 0.1184 | 20 |
| intent_only | 0.9829 | 19 | 16 | 0.9972 | 0.1184 | 5 |
| behavior_only | 0.7740 | 36 | 21 | 0.0000 | 0.0000 | 25 |
| context_only | 0.5000 | 19 | 19 | 0.0000 | 0.0000 | 5 |
| full, caller verified | 0.9825 | 28 | 9 | 0.9972 | 0.1184 | 10 |

**INTERPRETATION — and a distinction that matters.** Intent carries essentially
all the *ranking* power; adding behaviour leaves AUC unchanged (0.9829 →
0.9825). But AUC is rank-based and blind to scale, and VIVE's policy uses
*absolute* thresholds. In the score domain behaviour contributes substantially:
it lifts the scam median from 19 to 36 while leaving benign at 16–18. So
behaviour earns its place in the fused score even though it adds no
discriminative information — a conclusion neither metric reaches alone.

**MEASURED — the alert threshold is badly placed.** At the policy alert
threshold of 65, recall is **0.1184**: 88% of scam text never raises an alert,
at precision 0.9972. The validation-selected threshold of 20 gives precision
0.9688 and recall 0.9619 on test. This applies to text-only evidence — a packet
carrying a high anti-spoof score scores higher (see the sweep below) — but
text-only is exactly the state of every call for its first ~4 seconds.

### Label-free audio-channel sensitivity

No labelled audio exists, so these channels are measured for *influence*, not
accuracy:

| Anti-spoof score | Benign text | Risky text |
|---:|---:|---:|
| 0.00 | 18 | 79 |
| 0.50 | 37 | 83 |
| 1.00 | **55** | 88 |

Speaker similarity on benign text: 0.00 → 43, 0.50 → 30, 1.00 → 18.

**MEASURED.** `SYNTHETIC_ONLY_CEILING` binds: anti-spoof evidence alone tops
out at 55 on benign text, below HIGH. Given §5, this guard is doing real work —
a maximally-confident false synthetic detection reaches MEDIUM, not HIGH.

### Calibration

| Quantity | Value |
|---|---:|
| Brier score | 0.1798 |
| Brier, always predicting base rate | 0.2330 |
| **Expected calibration error** | **0.3171** |
| Base scam rate in test | 0.3696 |

Reliability:

| Bin | n | Mean predicted | Observed scam rate | Gap |
|---|---:|---:|---:|---:|
| 0.1–0.2 | 5,078 | 0.180 | 0.022 | −0.158 |
| 0.2–0.3 | 1,124 | 0.210 | 0.964 | +0.754 |
| 0.3–0.4 | 798 | 0.370 | 0.957 | +0.588 |
| 0.4–0.5 | 611 | 0.435 | 0.974 | +0.539 |
| 0.5–0.6 | 51 | 0.577 | 0.980 | +0.404 |
| 0.6–0.7 | 14 | 0.661 | 1.000 | +0.339 |
| 0.7–0.8 | 151 | 0.772 | 0.993 | +0.221 |
| 0.8–0.9 | 195 | 0.807 | 1.000 | +0.193 |

**INTERPRETATION.** `risk.score / 100` is **not** a usable probability. The
score separates the classes well — it is nearly bimodal — but its numeric value
bears no relation to a likelihood: records scoring 0.2–0.3 are scams 96.4% of
the time. `PROJECT_SPEC.md` §2.1's prohibition is now an empirical finding.

**UNVERIFIED.** `is_scam` marks scam *text*, not confirmed fraud by a caller.
Every precision, recall and calibration figure is against that proxy. Fusion
weights remain expert-set and unfitted (O6).

---

## 10. Runtime (9I)

**MEASURED**, 30 packets per language through the real backend over HTTP and
WebSocket, genuinely overlapping 2 s windows at a 1 s stride, bucketed on
whether the anti-spoof buffer had filled:

| | Hindi | Tamil |
|---|---:|---:|
| Steady-state median | 844.0 ms | 778.5 ms |
| Steady-state p95 | 1005.6 ms | 999.9 ms |
| Within 1.0 s budget | 88.9% | 96.3% |
| Before buffer filled (median) | 606.5 ms | 524.6 ms |
| First packet | 5,353 ms | 6,076 ms |
| First packet with an AASIST score | #4 | #4 |

Across three runs: median **751–844 ms**, p95 **930–1069 ms**.

Per-stage medians on the same packets (all six analyzers now instrumented —
see §11):

| Stage | Hindi median | Hindi p95 | Tamil median |
|---|---:|---:|---:|
| aasist | 366.0 ms | 421.0 ms | 373.5 ms |
| asr | 265.0 ms | 306.0 ms | 266.0 ms |
| ecapa | 74.0 ms | 101.0 ms | 78.5 ms |
| intent | 65.5 ms | 86.0 ms | 0.0 ms (unsupported) |
| behavior | 41.5 ms | 61.0 ms | 0.0 ms (unsupported) |
| **sum of stage medians** | **812.0 ms** | | 718.0 ms |

Startup: bundle load 16.4 s; RSS 0.535 GB → 3.282 GB after load.

**INTERPRETATION.** The stage sum accounts for 812 of the 844 ms packet, so
the remaining ~32 ms is fusion, temporal risk, policy and transport — there is
no unexplained cost. AASIST is the largest contributor at ~45% of the budget,
which is notable given §5: the most expensive stage is the one with no measured
discrimination. Removing it would move the p95 comfortably inside budget. That
is a Phase 10 decision and is **not** made here.

**The median fits the budget; the p95 does not.** 3.7–11.1% of packets
overrun, and overruns accumulate because the cadence is fixed.

**UNVERIFIED.** One machine, one session at a time, via FastAPI's TestClient
rather than a real network. **No throughput or concurrency claim follows.**
"Near-real-time" must not be claimed without naming the hardware and quoting
both median and p95.

---

## 11. Defects found and fixed in Phase 9

### `fusion.py` — an unavailable intent head raised risk

Found by 9H, not by a test. Intent entered the noisy-OR unconditionally, so a
head that had never run still contributed `UNKNOWN`'s 0.10 — **double** a
benign `NORMAL_CONVERSATION`'s 0.05.

Three promises broke at once:

- *"Missing evidence lowers CONFIDENCE, not risk."* A model outage raised the
  score, measured 26 → 28 on otherwise identical evidence.
- *Explainability.* `contributions` correctly omitted intent while the score
  silently included it, so the packet-detail breakdown could not reconstruct
  the number it was explaining.
- *Confidence.* Losing the intent head cost no confidence at all.

It also **penalised Tamil specifically**: every Tamil packet reports
`UNSUPPORTED_LANGUAGE` by design (O11), so an identical call scored higher in
Tamil than in Hindi purely because VIVE cannot read Tamil.

Fixed: intent enters the noisy-OR only when `status is AVAILABLE`, and
`semantic_pressure` reads from the same map. **Verified after the fix:**
`text_heads_failed` 28 → 26 with confidence 0.960 → 0.900; every degraded
configuration now lowers confidence without raising risk. Three regression
tests pin it, including one that reconciles the score against the reported
contributions.

### Packet schema — two analyzers could not be timed

`IntentEvidence` and `BehaviorEvidence` carried no `inference_ms`, so the text
heads measured their own cost and the schema discarded it. Per-stage latency
could account for only four of six analyzers. Added as an optional field
(additive per `API_SPEC.md` §4.1; the Android client sets
`ignoreUnknownKeys`), wired through the backend, the DTO, the domain model and
the mapper, and pinned by a test. ECAPA was additionally being excluded from
the latency table by an `AVAILABLE`-only filter despite doing full work on the
`NO_REFERENCE` path; corrected in the experiment.

---

## 12. Safety behaviour (9G, 9H)

**MEASURED — temporal.** A single anomalous packet scoring 95 in an otherwise
benign call reaches MEDIUM, never HIGH. Two adjacent 95/93 packets also never
reach HIGH. A lone first packet stays LOW. After a sustained burst ends, the
level returns to LOW in 4 packets. On a rising scam the engine warns at 3 s and
reaches HIGH at 4 s in packet time.

**MEASURED — and unanticipated.** Intermittent risk — a score of ~80 every
third packet, which is the shape social engineering actually takes — **never
leaves MEDIUM**, peaking at 82. The damping that suppresses a false spike
suppresses genuine periodic evidence equally. This is a detection gap, not a
tuning preference; `EMA_ALPHA` was not tuned because tuning it needs labelled
call sequences that do not exist.

**MEASURED — OOD.** Across 9 degenerate audio inputs (silence, DC offset, pure
tone, white noise, full-scale square, 10 ms fragment, single sample, empty
buffer, odd byte count) and Tamil/empty/whitespace/unknown-tag text: **zero**
adapters emitted a value while not `AVAILABLE`. An odd-length PCM buffer
produces `INFERENCE_ERROR` rather than a crash.

**MEASURED — failure injection.** With weights missing, all six adapters report
`LOAD_ERROR`, stay in REAL mode (**zero** silent downgrades to mock), and emit
no value. Fused risk under failure, on benign evidence:

| Configuration | Score | Confidence |
|---|---:|---:|
| all models healthy | 30 | 0.970 |
| antispoof failed | 23 | 0.810 |
| speaker failed | 26 | 0.960 |
| text heads failed | 26 | 0.900 |
| everything but VAD failed | 13 | 0.630 |

**No failure raised risk; every failure lowered confidence.** All contract
checks pass.

**UNVERIFIED.** Failure injection exercises the *load* path. A model that loads
and is wrong — the O12/§5 case — is not detectable this way, and is the more
dangerous of the two.

---

## 13. What VIVE may and may not claim

### May be claimed, with the stated scope

- Hindi ASR WER 0.1141 / Tamil 0.2936 on **clean FLEURS read speech**, 40
  utterances each, degrading gracefully under simulated channel conditions.
- Speaker verification EER 0.0000 on **clean LibriSpeech** (25 speakers),
  0.0150 on a 2 s window.
- Intent macro-F1 0.9213 and behaviour macro-F1 0.9403 on **held-out SMS
  text**, over 7 of 12 and 8 of 8 classes respectively, with support counts.
- Steady-state packet median 751–844 ms on **the stated hardware**, p95
  930–1069 ms.
- The system reports explicit states rather than guessing, does not escalate on
  model failure, and does not silently fall back to mock output — all measured.
- Tamil speech is **transcribed**, not understood.

### Must NOT be claimed

- **Any synthetic-voice detection capability.** Measured at chance (§5).
- **Any anti-spoofing EER.** The probe EER is one synthesis family and is not
  ASVspoof-comparable.
- **Telephone-call accuracy of any kind.** No call-channel corpus exists.
- **`risk.score` as a probability of fraud.** ECE 0.3171.
- **`OTP_REQUEST` performance.** 8 test records, below the floor.
- **Tamil intent or behaviour classification.** No data, `UNSUPPORTED_LANGUAGE`.
- **Speaker identification**, or speaker consistency in production — there is
  no enrolment source, so the channel reports `NO_REFERENCE`.
- **Near-real-time operation** without naming the hardware and quoting the p95.
- **Throughput or concurrent-call capacity.** Never measured.
- Performance on the 5 intents and 2 behaviours with **no test data at all**.

---

## 14. Limitations of Phase 9 itself

- **No anti-spoofing or speaker corpus *at the time of Phase 9*.** The probe
  and LibriSpeech were substitutes with narrower scope, not replacements.
  **Superseded for anti-spoofing on 2026-09-23:** the ASVspoof 2019 LA
  evaluation partition was located under ODC-By 1.0 and ungated, and the
  Phase J in-domain measurement (O12,
  `models/evaluation/phase9/10J_aasist_in_domain.json`) rests on it. VoxCeleb
  still needs a request form, so the speaker half of this limitation stands.
- **No labelled call data anywhere.** Fusion, calibration and temporal
  behaviour are all evaluated against SMS text or synthetic sequences. There is
  no corpus of real calls with risk labels, so no end-to-end accuracy figure
  exists for VIVE as a product.
- **Simulated channels.** Every degradation in §6 and §7 is synthetic.
- **Small samples in the audio experiments.** 120 probe clips, 25 speakers, 40
  ASR utterances per condition. Bootstrap intervals are reported where they
  exist and should be quoted with the point estimate.
- **Machine constraint.** 7.5 GB RAM. The backend suite crashed once when
  several model-loading processes ran concurrently; it is run per-file, one
  process at a time, and evaluations were run sequentially for the same reason.
  This is a measurement-process limitation, not a product defect, and it is why
  no concurrency figure exists.
- **One hardware configuration, CPU only.**

---

## 15. Reproducing

Backend tests must be run per-file on a machine with limited RAM:

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_pipeline.py -q
```

Experiments need `models/.venv` (it carries `datasets`, `sklearn`, `psutil`)
and the `VIVE_*_MODEL_DIR` variables. Run them one at a time; two model-loading
processes at once will contend for both CPU and RAM, and a Phase 7 RTF probe
was already invalidated once by exactly that.

```bash
models/.venv/Scripts/python scripts/evaluation/exp_aasist_window.py
```

Re-running an experiment archives the previous record under
`models/evaluation/phase9/superseded/` rather than overwriting it.
