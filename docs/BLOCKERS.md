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
  around the missing signal. Not blocking any phase before 8.
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
- **Current status:** AASIST and ECAPA are used as **pretrained checkpoints
  with no measured EER or verification metric**, and none may be quoted. The
  `generator_disjoint` and `speaker_disjoint` evaluation splits stay blocked.
- **Required external action:** complete the ASVspoof and VoxCeleb access
  requests, or accept that anti-spoofing and speaker performance are
  unquantified and say so wherever they are presented.

### O6 — Fusion weights unvalidated · `OPEN`

- **Blocker:** risk-fusion calibration is provisional.
- **Cause:** initial weights are expert-set; no real model outputs exist yet to
  calibrate against.
- **Attempted fixes:** weights externalised and versioned as `risk-fusion`, so
  recalibration is a config change. The combination rule was additionally
  changed from a weighted average to noisy-OR after the average was found to
  let low anti-spoof evidence suppress high semantic evidence.
- **Current status:** acceptable for mock-driven demos provided the provisional
  status is stated (`DEMO_SPEC.md` §6).
- **Required external action:** recalibrate against real outputs in Phase 9;
  never present provisional weights as measured accuracy.

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
  asserts the behaviour end to end. The gap is now impossible to present
  accidentally as a capability.
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
- **Current status:** measured and documented. The intent macro-F1 of 0.9219
  partly reflects the easier scam/not-scam boundary and **must not be
  presented as intent-discrimination accuracy**. Fusion weights remain
  provisional (O6).
- **Required external action:** add benign records that carry
  social-engineering behaviours, so behaviour and scam can vary independently.
  `DATA_SPEC.md` §8.2 identifies a verified Apache-2.0 conversational corpus
  for this. Re-calibrate fusion afterwards.

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
