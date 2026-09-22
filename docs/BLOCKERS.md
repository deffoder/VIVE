# VIVE — Blockers, Deferrals & Open Decisions

Live document. Nothing is silently dropped: if it is not done, it is recorded
here with a reason.

Status: `OPEN` · `RESOLVED` · `DEFERRED` · `PERMANENT` (platform limitation)

Per `CLAUDE.md` (Autonomous Error Recovery), every open blocker records:
**blocker · cause · attempted fixes · current status · required external action.**
Work that does not depend on a blocker continues regardless.

---

## Resolved

### R1 — Git repository rooted at the home directory · `RESOLVED`
The only repo in scope was rooted at `C:\Users\cvumj` with 0 commits and no
`.gitignore`; a commit would have swept in ~297,000 files including
`.claude.json`, `.bash_history`, `AppData` and `NTUSER.DAT`. A repo was
initialised at `VIVE/` instead. `git rev-parse --show-toplevel` now resolves to
the VIVE directory.

### R2 — Frontend stack undecided · `RESOLVED`
Native Android, Kotlin + Jetpack Compose. No React Native, no separate web
frontend. `frontend/` removed.

### R3 — Conflicting API base path · `RESOLVED`
`CLAUDE.md` specifies `/api/v1`; the external SIH documents use `/v1`.
`CLAUDE.md` wins. All specs use `/api/v1`.

### R4 — Conflicting packet schema · `RESOLVED`
`CLAUDE.md`'s packet object is canonical (`aasist.score`, `ecapa.similarity`,
`language` as a string, `timestamp` as `mm:ss`). The external API document's
`analysis_update` shape (`voice.synthetic_likelihood`,
`speaker.consistency`) is **not** used. Extensions are additive only —
`API_SPEC.md` §4.1.

### R6 — Third packet-schema variant in COMPLETE_PROJECT_DOCUMENTATION · `RESOLVED`
That document (§11–12, §29) defines a third shape: flat `aasist_score` /
`ecapa_similarity`, `start_time`/`end_time` instead of `timestamp`,
`audio_quality` as a float rather than an enum, `packet_risk` as `0.91` rather
than `risk.score` `91`, and SCREAMING_SNAKE WebSocket events (`PACKET_RESULT`).
`CLAUDE.md` remains canonical, so none of these are adopted — same ruling as R4.
Two genuinely new concepts from it **were** adopted, because `CLAUDE.md`'s Model
Stack requires an OOD/uncertainty layer that the specs had under-covered:
`ood.state` and `ood.uncertainty` are now in `API_SPEC.md` §4.1.

### R5 — Streamlit dashboard in external docs · `RESOLVED`
Not built. The mobile app is the product; a second UI would duplicate effort and
diverge from the design references.

---

### R7 — Indic ASR model access · `RESOLVED`

- **Was:** `ai4bharat/indicwav2vec-hindi` returned `403 Client Error` on file
  download, so no real Indic ASR model could be loaded.
- **Cause:** the repository is `gated: auto`. The token authenticated and
  repository *metadata* was readable, but a gated repo blocks **file**
  downloads until the account holder accepts the terms on the model page.
- **Resolution (2026-09-21):** the account holder had already accepted the
  terms. Re-verified directly rather than assumed: `config.json` and
  `vocab.json` download, and the full 1.26 GB snapshot including
  `pytorch_model.bin` (1,262,181,719 bytes) retrieves under the existing
  token. No credential was changed and no token value was printed.
- **Follow-on issue, also resolved:** the repository ships **only**
  `pytorch_model.bin` — no safetensors — and transformers refuses to
  `torch.load` a `.bin` on torch < 2.6 (CVE-2025-32434). That check was **not**
  disabled. `scripts/training/safe_load_bin.py` audits the pickle opcode
  stream *without executing it* (`pickletools.genops`) and allowlists the
  global symbols it may import. This file references only
  `collections.OrderedDict`, `torch.FloatStorage` and
  `torch._utils._rebuild_tensor_v2`. Only after the audit passed was it loaded
  with `weights_only=True` and converted to 424 safetensors tensors, which
  every later load reads instead. The `.bin` is touched once, under audit.
- **Verified:** `Wav2Vec2ForCTC` loads (315.5M params, vocab 68, 16 kHz) and a
  forward pass returns well-formed logits. WER measured on `google/fleurs`
  (CC-BY-4.0) `hi_in` test — see `docs/PHASE7_REPORT.md` §3.

---

## Open

### O1 — `C:\Users\cvumj\.git` still exists · `OPEN`

- **Blocker:** a git repository remains rooted at the user's home directory.
- **Cause:** an accidental `git init` in `C:\Users\cvumj` predating this project.
- **Attempted fixes:** initialised a separate repo at `VIVE/`, which takes
  precedence for everything under it; verified the home repo has 0 commits and
  0 tracked files, so nothing was ever committed from it.
- **Current status:** VIVE is fully isolated and unaffected. Any `git` command
  run from the home directory or a sibling folder such as `SIH26104-ALL\MD`
  still resolves to the home repo and reports ~297,000 untracked files.
- **Required external action:** user decision to delete
  `C:\Users\cvumj\.git`, or to leave it. Out of scope by explicit instruction
  that no files outside VIVE be deleted.

### O2 — `docs/` content derived from unversioned external sources · `OPEN`

- **Blocker:** the specs depend on documents outside this repository.
- **Cause:** written from `CLAUDE.md`, the four design references, and the
  SIH26104 documents in `../MD/`, which are not version-controlled with VIVE.
- **Attempted fixes:** all decisions extracted from those sources are recorded
  in-repo (R3–R5 below), so `docs/` stands alone for day-to-day work.
- **Current status:** consistent now; will drift if the external documents change.
- **Required external action:** user decision — vendor the relevant sources into
  `docs/reference/`, or declare `docs/` authoritative from here on.

### O3 — Speaker enrolment source undefined · `OPEN`

- **Blocker:** `ecapa-tdnn` cannot produce a similarity without a reference
  embedding.
- **Cause:** the origin of that reference in a real deployment is undecided —
  prior verified call, explicit enrolment, or a bank-held voiceprint.
- **Attempted fixes:** none applicable; this is a product/legal decision, not a
  technical fault. The `NO_REFERENCE` status path is specified and testable
  (scenario S5).
- **Current status:** system runs correctly in `NO_REFERENCE`; fusion re-weights
  around the missing signal. Confirmed end to end in Phase 9: `NO_REFERENCE`
  on 30/30 packets in both languages, `similarity` null throughout.
- **Phase 9 measurement (2026-09-22).** The model itself was evaluated for the
  first time, on LibriSpeech test-clean (CC-BY-4.0, real `speaker_id`), 25
  speakers, 75 genuine and 300 impostor pairs
  (`models/evaluation/phase9/9D_ecapa_speaker.json`): EER **0.0000** on clean
  full utterances, **0.0150** on VIVE's 2 s window, 0.0033 band-limited,
  0.0000 through G.711. The channel is inert for a product reason, not a model
  one.
- **What that changes for enrolment:** the 2 s window barely moves the
  *ranking* (AUC 0.9980) but moves the *operating point* sharply - the genuine
  median falls 0.813 -> 0.555 and the EER threshold 0.554 -> 0.292. **A fixed
  threshold of 0.5 would falsely reject 29.33% of genuine 2 s windows.** Any
  threshold adopted alongside an enrolment source must come from a measurement
  like this, not be chosen by eye.
- **Scope:** LibriSpeech is clean English audiobook read speech - the easy
  case. Not comparable to published VoxCeleb ECAPA numbers, and VoxCeleb
  itself is still unavailable (O5).
- **Required external action:** decision on enrolment source, with its consent
  and retention obligations (`SECURITY_SPEC.md` §4).

### O4 — Backend persistence engine not chosen · `OPEN`

- **Blocker:** `ARCHITECTURE.md` §5 names a `store/` layer with no backing engine.
- **Cause:** deferred deliberately; the choice does not affect the API contract.
- **Attempted fixes:** `store/` is defined as an interface so the engine can be
  swapped without touching routes or fusion.
- **Current status:** an in-memory store is now implemented behind an
  `EventStore` interface, so the engine choice is a constructor change. Still
  sufficient; not blocking. Data is lost on restart by design for now.
- **Required external action:** choose an engine before Phase 10, so retention
  (`SECURITY_SPEC.md` §4) can actually be enforced.

### O5 — Audio corpora for anti-spoofing and speaker evaluation not acquired · `OPEN`

> Restated 2026-09-21. The original wording — *no candidate dataset has a
> verified license* — is no longer true and would misrepresent the state of the
> project. Every dataset and model actually in use now has its license verified
> against repository metadata: scamshield (MIT), FLEURS (CC-BY-4.0),
> whisper-large-v3-turbo (MIT), indicwav2vec-hindi (Apache-2.0), ECAPA-TDNN
> (Apache-2.0), mDistilBERT (Apache-2.0). What remains is narrower.

- **Blocker:** no anti-spoofing or speaker-verification corpus has been
  acquired, so AASIST and ECAPA-TDNN cannot be independently evaluated.
- **Cause:** ASVspoof requires a registration/agreement and VoxCeleb a request
  form; neither can be completed programmatically. `facebook/mms-1b-all` was
  also rejected during the Tamil survey for a different licensing reason —
  CC-BY-NC-4.0 forbids commercial use.
- **Attempted fixes:** the manifest schema requires `license` and `provenance`
  on every record, so an unlicensed clip cannot enter a split unnoticed;
  `scripts/training/survey_tamil_asr.py` reads license and gating from
  repository metadata and probes real file access rather than trusting a model
  card.
- **Current status (updated 2026-09-22, Phase 9):** both models have now been
  measured against *substitutes*, which narrows this blocker without closing
  it.
  - **Speaker:** LibriSpeech test-clean (CC-BY-4.0, ungated, carries a real
    `speaker_id`) supports a genuine verification EER - see O3. Clean English
    read speech, so the easy case, and not VoxCeleb.
  - **Anti-spoofing:** a two-class probe was built from openly-licensed parts
    (SpeechT5 + HiFiGAN + CMU Arctic x-vectors, all MIT) against FLEURS
    bonafide, because ASVspoof cannot be obtained programmatically. It is ONE
    synthesis family in one language and is **not** a substitute for ASVspoof.
    Its result is in O12 and it is not an ASVspoof-comparable EER.
  - `facebook/mms-tts-{hin,tam}` was rejected for the probe: CC-BY-NC-4.0
    forbids commercial use, the same rule that rejected `facebook/mms-1b-all`
    in Phase 7. `ai4bharat/indic-parler-tts` is Apache-2.0 but `gated: auto`,
    so it needs the account holder to accept terms and **was not downloaded**.
  - The `generator_disjoint` and `speaker_disjoint` evaluation splits stay
    blocked.
- **Required external action:** complete the ASVspoof and VoxCeleb access
  requests, or accept that anti-spoofing and speaker performance are
  unquantified against their proper benchmarks and say so wherever they are
  presented.

### O6 — Fusion weights unvalidated · `OPEN`

- **Blocker:** risk-fusion calibration is provisional.
- **Cause:** initial weights are expert-set; no real model outputs exist yet to
  calibrate against.
- **Attempted fixes:** weights externalised and versioned as `risk-fusion`, so
  recalibration is a config change. The combination rule was additionally
  changed from a weighted average to noisy-OR after the average was found to
  let low anti-spoof evidence suppress high semantic evidence.
- **Phase 9 measurement (2026-09-22,
  `models/evaluation/phase9/9F_fusion_ablation_calibration.json`).** Real head
  outputs over 8,022 de-leaked held-out records, thresholds chosen on
  validation and reported on test:
  - **The score is not a probability.** Expected calibration error **0.3171**;
    Brier 0.1798 against a base-rate baseline of 0.2330. Records scoring
    0.2-0.3 are scams 96.4% of the time. `PROJECT_SPEC.md` 2.1's prohibition
    on reading `risk.score` as a fraud probability is now an empirical
    finding, not only a rule.
  - **Channel contribution.** Intent carries essentially all the *ranking*
    power (AUC 0.9829 alone vs 0.9825 for the full text pipeline), but AUC is
    rank-based and the policy uses absolute thresholds. In the score domain
    behaviour matters: it lifts the scam median 19 -> 36 while leaving benign
    at 16-18. Behaviour earns its place without adding discriminative
    information - a conclusion neither metric reaches alone.
  - **`SYNTHETIC_ONLY_CEILING` binds**, measured: anti-spoof evidence alone
    tops out at 55 on benign text, below HIGH. Given O12 that guard is doing
    real work.
- **Current status:** weights remain expert-set and unfitted, but no longer
  unexamined. Calibration is measured and negative; the honest reading is that
  the score is a well-separating *ordinal* signal, not a probability.
- **Required external action:** recalibrate against labelled *call* data,
  which does not exist (O15). Never present provisional weights as measured
  accuracy, and never present the score as a likelihood.

### O8 — No Tamil training or evaluation data · `OPEN`

- **Blocker:** VIVE names Hindi, Tamil and English as priority languages, but
  no Tamil data is available for the text classifiers.
- **Cause:** the scamshield corpus covers English (76,246), Hindi (6,352) and
  Hinglish (3,004) only. No openly-licensed Tamil scam/social-engineering text
  corpus has been identified.
- **Attempted fixes:** searched HuggingFace for scam, phishing and fraud text
  datasets; every ungated candidate is English-dominant.
- **Current status (narrowed 2026-09-21):** Tamil **ASR** is now solved -
  IndicConformer-600M measures Tamil WER 0.2833 / CER 0.1107 on FLEURS `ta_in`
  with a 1.0000 Tamil-script ratio (`PHASE7_REPORT.md` §7). What remains is
  the **text** half: the intent and behaviour classifiers are trained on a
  corpus with no Tamil, so Tamil intent/behaviour classification is still
  **not supported** and the Tamil text evaluation split cannot be populated.
  Transcribing Tamil is not the same as understanding it.
- **Required external action:** source or commission a Tamil corpus, or accept
  that Tamil intent/behaviour classification is out of scope for now.

### O9 — Seven taxonomy labels have no training data · `OPEN`

- **Blocker:** the trained classifiers cannot predict 5 of the 12 intents or
  2 of the 8 behaviours, and `OTP_REQUEST` is trained on 103 samples (~0.1%).
- **Cause:** the scamshield corpus is SMS spam/scam text. It has no source for
  `PASSWORD_REQUEST`, `CARD_DETAILS_REQUEST`, `ACCOUNT_CHANGE_REQUEST`,
  `REMOTE_ACCESS_REQUEST`, `CONFIDENTIAL_INFORMATION`, `THREAT` or `SECRECY` —
  those belong to interactive voice social engineering, which SMS does not
  contain. OTP requests appear in SMS mainly as *delivered* codes rather than
  as a caller soliciting one.
- **Attempted fixes:** (1) reviewed every public intent label in the corpus and
  mapped what genuinely corresponded, refusing to force genre labels such as
  "Lottery / Prize" onto an intent; (2) searched for supplementary ungated
  corpora — `BothBosu/multi-agent-scam-conversation` (Apache-2.0) is
  conversational and a better register match but its label scheme was not
  mapped in this phase.
- **Current status:** measured and documented rather than hidden. The absent
  labels render as "no data, cannot be predicted" in every generated metrics
  table, and the macro-F1 denominator is stated wherever the figure appears.
  `OTP_REQUEST` scores 0.632 on 8 test records — weak, and statistically
  fragile at that support.
- **Required external action:** acquire or commission a call-transcript corpus
  covering the missing labels, or scope the product to the labels that have
  data. Until then these labels must not be described as supported.
- **Audit (2026-09-21):** `scripts/training/audit_label_coverage.py` measured
  per-label support per split. `OTP_REQUEST` has **8 test records**, below the
  30-record floor, so it is **unmeasurable** rather than merely weak — its
  0.632 F1 must not be quoted as a capability. A concrete remediation plan,
  with a verified candidate corpus, is in `DATA_SPEC.md` §8.2.
- **Phase 9 confirmation (2026-09-22).** Re-measured through the real adapters
  on the de-leaked split: 5 of 12 intents and 2 of 8 behaviours still have
  **zero** test records and render as "NO TEST DATA - cannot be scored";
  `OTP_REQUEST` renders as "UNMEASURABLE" at its 8 records. Intent macro-F1
  0.9213 is over **7 of 12** classes, and the denominator is stated wherever
  the figure appears (`EVALUATION.md` 8).

### O13 — Packet latency sits at the real-time budget, not inside it · `OPEN`

- **Blocker:** VIVE analyses a 2.0 s window every 1.0 s, so a packet must cost
  under 1.0 s end to end. Measured on real FLEURS audio through the full
  backend, the median packet sits **at** that boundary rather than below it.
- **Measured (Phase 8D, 6 packets per language, first packet excluded):**

  | Run | Hindi median | Tamil median |
  |---|---:|---:|
  | sequential | 938 ms | 1039 ms |
  | sequential (repeat) | **1062 ms** | **830 ms** |
  | thread-pool across analyzers | 1197 ms | 1036 ms |

  Range across runs: **830-1197 ms**. Some runs fit, some do not.
- **Per-stage cost on a representative packet:** AASIST ~364-395 ms,
  ASR ~254-273 ms, ECAPA ~68-87 ms, plus VAD, the two text heads, fusion,
  temporal risk, policy and WebSocket transport.
- **Attempted fix, measured and reverted:** running the four window analyzers
  on a thread pool made it **worse** - Hindi 938 -> 1197 ms, with per-stage
  cost rising across the board (ASR 273 -> 584 ms, AASIST 395 -> 741 ms,
  ECAPA 81 -> 732 ms). torch and onnxruntime each already use every core, so
  concurrent analyzers oversubscribe the CPU and contend rather than overlap.
  The change was reverted and the measurement recorded in the code.
- **Phase 9 restatement (2026-09-22):** the Phase 8D range straddled the
  budget because six packets cannot resolve it. Measured properly - 30 packets
  per language, genuinely overlapping windows, startup and anti-spoof warm-up
  separated out
  (`models/evaluation/phase9/9I_runtime_end_to_end.json`):

  | | Hindi | Tamil |
  |---|---:|---:|
  | steady-state median | 844.0 ms | 778.5 ms |
  | steady-state p95 | 1005.6 ms | 999.9 ms |
  | packets inside the 1.0 s budget | 88.9% | 96.3% |
  | first packet | 5,353 ms | 6,076 ms |

  Across three runs: median **751-844 ms**, p95 **930-1069 ms**.

  **The median fits; the p95 does not.** 3.7-11.1% of packets overrun, and
  overruns accumulate because the cadence is fixed.
- **Per-stage medians, now complete.** Phase 9 found the packet schema carried
  no `inference_ms` for the intent and behaviour heads, so earlier per-stage
  tables silently omitted two of six analyzers; ECAPA was additionally dropped
  by an AVAILABLE-only filter despite doing full work on the `NO_REFERENCE`
  path. With both fixed: aasist 366.0 ms, asr 265.0 ms, ecapa 74.0 ms, intent
  65.5 ms, behaviour 41.5 ms - summing to 812 ms of an 844 ms packet, so the
  remaining ~32 ms is fusion, temporal risk, policy and transport. There is no
  unexplained cost.
- **Current status:** the pipeline runs end to end and produces correct
  packets, but **near-real-time operation must not be claimed without naming
  the hardware and quoting the p95 alongside the median**. Startup is a
  separate cost: 16.4 s to load the bundle, then a first packet of ~5-6 s.
- **Required external action:** either a GPU execution path (`onnxruntime-gpu`
  needs CUDA 12 while the development driver caps at 11.2), a faster
  anti-spoofing model, a decision to run some analyzers on a slower secondary
  cadence than ASR, or **dropping the anti-spoof channel**, which at ~45% of
  the budget would move the p95 comfortably inside it. O12 now shows that
  channel has no measured discrimination, so the cost is currently bought with
  no evidence. Choosing between these is Phase 10 work and needs target
  hardware.

### O12 — AASIST shows no measured discrimination · `OPEN`

> **Escalated 2026-09-22 (Phase 9).** The original wording — *unreliable out of
> domain* — understated it. A 120-clip two-class measurement now shows the
> checkpoint separating synthetic from genuine speech **at chance**. The
> heading and the required action both changed; the earlier spot-check
> evidence is retained below because it is what prompted the measurement.

- **Phase 9 measurement (`models/evaluation/phase9/9B_aasist_early_window.json`):**
  60 synthetic clips (SpeechT5 + HiFiGAN, MIT) against 60 bonafide FLEURS
  clips, scored at five window lengths, no padding or resampling anywhere.

  | Window | EER | 90% interval | ROC AUC |
  |---|---:|---|---:|
  | 1.0 s | 0.4500 | 0.3667-0.5500 | 0.4875 |
  | 2.0 s | 0.4500 | 0.3833-0.5500 | 0.5039 |
  | 3.0 s | 0.4167 | 0.3583-0.5000 | 0.5317 |
  | 4.0 s | 0.4333 | 0.3500-0.5000 | 0.5592 |
  | 4.0375 s (native) | **0.4333** | **0.3500-0.5000** | **0.5600** |

  Every interval reaches or crosses 0.50. **No window length discriminates.**
- **Two checks that stop this being an artefact:** (1) a Silero VAD control
  confirms the synthetic half is speech - detected in 20/20 clips at GOOD
  quality - so this is a result about AASIST, not about broken audio; (2)
  reversing the class-index convention gives AUC 0.4400, also chance, so the
  finding does not depend on the mapping.
- **The probe's confound cuts the reassuring way.** Its classes differ in
  language and channel (English vocoder output vs Hindi/Tamil recorded
  speech), which should make separation EASIER than real spoofing. A
  near-chance result under a favourable confound is conservative.
- **Scope, and it is narrow.** One synthesis family, one language, 120 clips.
  This does **not** establish that AASIST fails in general and is **not** an
  ASVspoof-comparable EER. It establishes that VIVE has no evidence the model
  works on audio like this, which is the operative fact for the product.
- **Not acted on in fusion.** Re-weighting the anti-spoof channel from a
  single-family probe would be fitting to the probe. The existing
  `SYNTHETIC_ONLY_CEILING` guard was measured to bind (anti-spoof evidence
  alone tops out at 55 on benign text), which bounds the damage. Changing the
  weight needs a real corpus (O5) and is a Phase 10 decision.
- **Cost of keeping it:** AASIST is the single largest latency contributor at
  ~366-374 ms, roughly 45% of the packet budget (O13). The most expensive
  stage is the one with no measured discrimination.

- **Original blocker (retained):** the pretrained AASIST checkpoint produces
  scores on out-of-domain audio that do not track reality, so its output must
  not be treated as trustworthy synthetic-voice evidence.
- **Observed (Phase 8C spot check, 2026-09-22):** decoding four
  `google/fleurs` clips of **genuine human speech** plus a silence control
  through the integrated adapter:

  | Input | P(spoof) |
  |---|---:|
  | genuine human clip 1 | **0.8377** |
  | genuine human clip 2 | **0.9994** |
  | genuine human clip 3 | 0.0034 |
  | digital silence | 0.0115 (i.e. scored as *bonafide*) |

  Two of three genuine clips were flagged as likely synthetic, and digital
  silence was scored as bonafide speech, which is meaningless.
- **This is a spot check of 4 samples, not a measurement.** It is not an EER,
  not a false-positive rate, and must never be quoted as one. It is recorded
  because it is evidence of a real problem, not because it quantifies it.
- **Cause:** AASIST was trained on ASVspoof2019 LA. FLEURS is a different
  recording domain (different microphones, codecs, noise floor). Anti-spoofing
  models are known to generalise poorly across domains, which is exactly what
  `BLOCKERS.md` P2 warns about. No VIVE-side evaluation corpus was acquired
  (O5), so this was never going to be caught by a metric.
- **Windowing investigated separately (2026-09-22):** the adapter used to pad
  a 2 s window up to the model's 64,600-sample input, so half of every input
  was invented filler; a controlled experiment measured the score moving by a
  median of 0.43 with padding strategy alone. **Fixed** — the adapter now
  buffers real audio and reports `INSUFFICIENT_AUDIO` until it holds a full
  genuine window (`ML_SPEC.md` §2.7). **This does not explain O12:** the
  genuine-speech spot check above used native 64,600-sample windows with no
  padding, so the out-of-domain behaviour is unaffected by the fix.
- **Attempted fixes:** verified the class-index convention against upstream
  (`main.py` scores `batch_out[:, 1]`, which `evaluation.py` documents as the
  bonafide/positive class), so the adapter's mapping is correct and the
  behaviour is the model's, not a wiring error. Checked the checkpoint loads
  with 0 missing and 0 unexpected keys.
- **Current status:** integrated and reporting real inference, now with a
  measurement showing that inference carries no usable signal on this kind of
  audio. **No synthetic-voice detection capability may be claimed, and the
  anti-spoof score must not be presented to a user as evidence.**
- **Required external action:** acquire a real anti-spoofing corpus (O5) and
  measure EER in-domain and out-of-domain. Then one of: calibrate, replace the
  model, or drop the channel. Dropping it would also resolve most of O13,
  since it is ~45% of the packet budget. That decision is Phase 10 and needs
  the corpus first.

### O11 — No Tamil text for intent or behaviour · `OPEN`

- **Blocker:** Tamil intent and behaviour classification cannot be trained.
  Tamil **ASR** is solved (WER 0.2833); the **text** half has no data at all.
- **Measured (2026-09-21):** 0 Tamil records and **0 Tamil codepoints**
  (U+0B80-U+0BFF) across all 85,602 corpus records. A romanised-Tamil scan
  returned 37 candidate hits, **all false positives** ("b*unga*low",
  "chah*unga*"). Tamil is absent by script, not by labelling, so no
  relabelling can recover it.
- **Cause:** the scamshield corpus is English/Hindi/Hinglish SMS. Separately,
  a survey of 19 Tamil text corpora
  (`models/evaluation/tamil_text_survey.json`) found **no Tamil scam or
  social-engineering labelled corpus under any licence**. Five are
  licence-clear but carry the wrong labels; one is CC-BY-NC-4.0
  (non-commercial, rejected); one is `openrail` (needs a human licence read);
  eleven declare **no licence at all** and are UNVERIFIED.
- **Attempted fixes:** keyword search across 11 Tamil/Tanglish/Dravidian terms
  plus direct lookup of named corpora; licence and gating read from repository
  metadata before any download.
- **Current status:** Tamil intent/behaviour is **not supported and must not
  be described as supported**. No Tamil intent or behaviour metric exists and
  none may be quoted or estimated. The `language_tamil` text evaluation split
  stays blocked.
- **Enforced in code (Phase 8B):** the intent and behaviour adapters return
  `UNSUPPORTED_LANGUAGE` for Tamil rather than a prediction, the mock adapters
  do the same so demos cannot overstate the product, and demo scenario S11
  asserts the behaviour end to end.
- **That enforcement was incomplete, and Phase 10 found it.** The protection
  held only for *romanised* Tamil, which is what S11 was written in. Three
  layers had to be fixed before it held for Tamil script:
  1. the mock language guess matched only romanised keywords and had no
     script check, so real Tamil text was reported as `en`;
  2. `session_manager` passed the ASR's *detected* language to the text heads
     unconditionally, letting that guess override a session explicitly
     declared `ta`;
  3. the Android `AnalyzerStatus` enum had no `UNSUPPORTED_LANGUAGE` member,
     and its mapper resolved unknown values to `AVAILABLE`, so even a correct
     backend status arrived in the app as a successful analysis.

  Each alone was enough to defeat O11. Together they meant a Tamil call could
  display `NORMAL_CONVERSATION` at status AVAILABLE. All three are fixed and
  pinned by tests, including one that drives a session in Tamil script and one
  that pins Kotlin/backend enum parity.
- **Current status is unchanged by that fix.** Tamil intent and behaviour
  remain **unsupported**; what changed is that the unsupported state is now
  reported correctly everywhere instead of only for one spelling of Tamil.
- **Required external action:** commission human-authored Tamil scam text
  against the VIVE taxonomy. `DATA_SPEC.md` §8.3 sets out the plan, including
  the ~300 human records per label needed to make a single label reportable,
  the human-only test-split rule that prevents synthetic and translation
  leakage, and the Tanglish coverage requirement.

### O10 — Intent and behaviour labels are collinear with `is_scam` · `OPEN`

- **Blocker:** the two heads that risk fusion treats as independent evidence
  are, in the training data, both proxies for one underlying flag.
- **Measured:** `intent != NORMAL_CONVERSATION` reproduces `is_scam` for
  **85,602 / 85,602 records (100.0000%)**. A non-`NORMAL` behaviour reproduces
  it for 85.98%. **0** of 85,602 benign records carry any behaviour flag.
- **Cause:** the corpus is built around a binary scam/not-scam split, and both
  label sets were derived from that same partition rather than annotated
  independently.
- **Consequences, both real:**
  1. `app/risk/fusion.py` uses a noisy-OR, which assumes conditional
     independence. Two signals that are really one, combined as if
     independent, inflate both the fused score and its confidence.
  2. The behaviour head has never seen legitimate urgency or authority — a
     real delivery notice, a genuine bank fraud alert. It cannot have learned
     that urgency alone is not fraud, so false positives on legitimate urgent
     calls are expected. This contradicts `PROJECT_SPEC.md` §2, which requires
     risk to follow evidence rather than a proxy.
- **Attempted fixes:** none applicable within Phase 7 — this is a property of
  the corpus, not of the training code. Re-weighting or thresholding would
  hide it rather than fix it.
- **Phase 9 measurement on the MODEL OUTPUTS (2026-09-22).** The Phase 7
  figure was about *labels*; fusion never sees a label. Measured on the risk
  contributions fusion actually consumes
  (`models/evaluation/phase9/9E_text_heads.json`): Pearson **0.5281**,
  Spearman 0.6247, mutual information 0.1202 bits, **normalised mutual
  information 0.3287**. Predicted non-NORMAL intent matches `is_scam` for
  98.3688% of records; the behaviour head fires on **1.00%** of benign records
  and 59.21% of scam records.
- **Reading:** the heads are **moderately dependent, not redundant** - they
  share about a third of the smaller entropy. Materially better than the 100%
  label collinearity implied, so the noisy-OR is not simply double-counting
  one signal, but the independence it assumes is still not satisfied.
- **Current status:** measured and documented. The intent macro-F1 of 0.9219
  partly reflects the easier scam/not-scam boundary and **must not be
  presented as intent-discrimination accuracy**. Fusion weights remain
  provisional (O6).
- **Required external action:** add benign records that carry
  social-engineering behaviours, so behaviour and scam can vary independently.
  `DATA_SPEC.md` §8.2 identifies a verified Apache-2.0 conversational corpus
  for this. Re-calibrate fusion afterwards.

### O14 — Intermittent risk never escalates · `OPEN`

- **Blocker:** the temporal layer damps periodic evidence as hard as it damps
  a spurious spike, so a scam that is risky only intermittently never raises
  an alert.
- **Measured (Phase 9, `models/evaluation/phase9/9G_temporal_risk.json`):** a
  synthetic sequence scoring ~80 every third packet - the shape social
  engineering actually takes, since the incriminating sentence is one window
  in several - peaks at 82 per packet and **never leaves MEDIUM**. It never
  reaches HIGH, so `policy.py` never raises an alert.
- **Cause:** `EMA_ALPHA = 0.4` plus hysteresis. This is the same mechanism
  that produces the layer's best property - a single 95-scoring packet reaches
  only MEDIUM, and two adjacent 95/93 packets also never reach HIGH, which is
  exactly the false positive O12 makes likely. The damping cannot tell the two
  cases apart.
- **Attempted fixes:** none. `EMA_ALPHA` was deliberately **not** tuned:
  trading spike resistance for intermittent sensitivity needs labelled call
  sequences to choose the operating point, and none exist (O15). Tuning it
  against synthetic sequences would be fitting to sequences this author wrote.
- **Current status:** measured and documented. A detection gap, not a tuning
  preference. Time-to-warning figures (`first_warning_sec` and friends) are
  historical markers recording when a raw score first crossed a threshold and
  must be presented as "first reached", never as the current level.
- **Phase 10 review:** deliberately **not** acted on. Changing `EMA_ALPHA`
  would improve a demo sequence and invalidate the Phase 9 measurement in the
  same edit, with no labelled data to say which direction is correct. Stays
  OPEN with the consequence stated: a scam whose incriminating evidence
  appears only intermittently may never raise an alert.
- **Required external action:** labelled call sequences, then re-tune the
  smoothing against a measured operating point.

### O15 — No labelled call data, so no end-to-end accuracy exists · `OPEN`

- **Blocker:** every accuracy figure VIVE has is measured on a proxy. There is
  no corpus of real calls with risk labels, so **VIVE has no measured
  end-to-end accuracy as a product** and cannot state a false-positive rate
  for a call.
- **What is measured on a proxy instead:**
  - intent and behaviour on **SMS text** (`is_scam`), scored from
    ground-truth text rather than ASR output;
  - ASR on **clean read speech** plus simulated channel degradation;
  - speaker verification on **clean audiobook speech**;
  - anti-spoofing on a **single-synthesis-family probe**;
  - temporal behaviour on **synthetic score sequences**.
- **Why it matters beyond the missing number.** The policy alert threshold was
  measured to be badly placed for the evidence it actually receives: at the
  alert threshold of 65, recall against `is_scam` is **0.1184** at precision
  0.9972 - 88% of scam text raises no alert - while the validation-selected
  threshold of 20 gives precision 0.9688 and recall 0.9619 on test
  (`models/evaluation/phase9/9F_fusion_ablation_calibration.json`). That
  measurement is on text-only evidence, which is also the state of every call
  for its first ~4 seconds. **The threshold was not changed**, because moving
  a production alert threshold to fit an SMS proxy would be exactly the error
  this blocker describes.
- **Cause:** collecting real call audio with fraud outcomes needs consent, a
  lawful basis and an operator or bank partner (`SECURITY_SPEC.md` §4,
  deferral D1).
- **Attempted fixes:** none possible in-repo. Phase 9 instead measured every
  component against the best legally-available substitute and recorded the
  substitution each time.
- **Current status:** all published metrics carry their corpus and conditions.
  No call-level accuracy, false-positive rate or alert-threshold claim may be
  made.
- **Phase 10 review:** the alert threshold was **not** moved. Tuning it to the
  SMS proxy would convert a measured limitation into an apparent capability,
  which is the specific failure this blocker exists to prevent. The threshold
  stays where policy put it, and the measured recall against the proxy is
  published next to it (`EVALUATION.md` §9) so the gap is visible rather than
  hidden.
- **Required external action:** a consented, lawfully-obtained corpus of
  labelled calls. Until it exists, thresholds and fusion weights stay
  provisional (O6) and are presented as such.

### O16 — End-to-end language coverage is Hindi only · `OPEN`

- **Blocker:** the ASR and the text heads support almost disjoint language
  sets, so the only language VIVE can both transcribe AND understand is Hindi.
- **Measured (2026-09-23)** by enumerating the loaded model's vocabulary
  masks and the adapters' declared languages:

  | Stage | Languages |
  |---|---|
  | ASR (`indic-conformer-600m`) | 22 Indic: `as bn brx doi gu hi kn kok ks mai ml mni mr ne or pa sa sat sd ta te ur` |
  | Intent / behaviour | `en`, `hi`, `hi-en` |
  | **Both** | **`hi` only** |

- **What that means per language:**
  - **Hindi** - transcribed and understood. The full pipeline works.
  - **Tamil** - transcribed, not understood (O11). Known and documented.
  - **English** - **understood, but cannot be transcribed.** IndicConformer
    is IN-22 and has no English mask, so an English session produces no
    transcript at all, and the text heads then have nothing to read.

- **Why it went unnoticed:** every ASR evaluation used FLEURS `hi_in` and
  `ta_in`, and every text evaluation used a corpus that is 89% English *text*.
  Each half was measured against the languages it was good at, and no
  measurement crossed the two. `PROJECT_SPEC.md` §6 names Hindi, Tamil and
  English as priority languages; the Phase 7 ASR selection then compared
  candidates on "both priority languages", meaning Hindi and Tamil, and
  English quietly left the comparison without ever being ruled out in
  writing.
- **Consequence, and it is a demo-facing one:** someone speaking **English**
  into the phone gets no transcript, no intent, no behaviour, and a risk score
  that stays at its floor. Before this was diagnosed the ASR reported the
  condition as `INFERENCE_ERROR`, so it looked like a crash rather than an
  unsupported language - fixed, and it now reports `UNSUPPORTED_LANGUAGE`.
- **Attempted fixes:** none yet; this is a model-coverage gap, not a defect.
  Options, none of them free:
  1. **Add an English ASR.** `whisper-large-v3-turbo` is already acquired
     (MIT) and covers English, but Phase 7 measured it as worse on Hindi and
     Tamil and **5.5x over the per-window budget** (`ML_SPEC.md` §2.1), so it
     would have to run as a second, language-routed model rather than a
     replacement - and there is no language-ID model to route with
     (`PHASE8_PREREQUISITES.md` §6).
  2. **Train Indic-language text heads** so the text side matches the ASR's
     22 languages. Blocked by the same data problem as O11.
  3. **Scope the product to Hindi** and say so everywhere.
- **Current status:** measured and documented. **VIVE must not be described as
  supporting English end to end.** The honest claim is Hindi end to end, Tamil
  transcription only.
- **Required external action:** a product decision between the three options
  above. Option 1 additionally needs a language-ID model.

---

## Deferred

| ID | Item | Reason |
|---|---|---|
| D1 | Full telecom / operator integration | Out of scope; requires operator agreements |
| D2 | Advanced OOD / unknown-generator research | Research effort beyond current scope |
| D3 | Large-scale fine-tuning | No GPU budget; Colab/Kaggle only |
| D4 | Full SDK suite (Python / Android / JS) | Backend contract first |
| D5 | Production gRPC | REST + WebSocket is sufficient |
| D6 | Distributed inference, multi-region | Single-node scope |
| D7 | Advanced observability | Basic structured logging only |
| D8 | Dark theme | Tokens defined so it can be added later without component changes |

---

## Permanent limitations

These are platform or scientific realities, not backlog items. They must be
stated in the UI and in any demonstration (`DEMO_SPEC.md` §6).

### P1 — Cellular call audio is inaccessible
Android does not permit third-party capture of two-way cellular call audio.
`CallScreeningService` provides number and metadata only. Full analysis requires
the authorized VoIP/in-app path (`ARCHITECTURE.md` §7). The product must never
claim otherwise.

### P2 — Detection of unknown generators is not guaranteed
Anti-spoofing generalises imperfectly to generators unseen in training. No
universal or future-proof detection claim may be made.

### P3 — Synthetic speech is not fraud; human speech is not safety
Both directions are false. The system reports evidence and calibrated risk, never
a verdict (`PROJECT_SPEC.md` §2.1).

### P4 — ASR quality varies
Accent, code-switching, channel quality and background noise all degrade
transcription, which propagates to intent and behaviour. Low ASR confidence must
lower overall confidence rather than be ignored.
