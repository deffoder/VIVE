# VIVE — Autonomous Progress (source of truth across contexts)

Worktree: `.claude/worktrees/vive-final-recovery-135c03`, branch
`claude/vive-final-recovery-135c03`. Model artifacts are git-ignored and live in
the main checkout; the worktree reaches them through directory junctions under
`models/artifacts/` (recreate with `New-Item -ItemType Junction` if missing).

Toolchain: `JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"`,
Python venv `../../../backend/.venv/Scripts/python.exe` (3.11, torch 2.14 cpu,
onnxruntime 1.30, transformers 5.17). Device: OnePlus CPH2661, arm64-v8a,
Android 16 (SDK 36), 7.5 GB RAM, ~1.5 GB available.

## CURRENT_STATUS

Phone-only VIVE is built, installed and accepted on the target phone (see
FINAL_ACCEPTANCE_CHECKLIST). No backend, no adb reverse, no laptop in the
analysis path; the laptop only plays the scripted caller's voice. Remaining
gaps are model-quality limits, listed under BLOCKED with evidence.

Live test setup: phone ~10-20 cm from the laptop speaker (laptop volume
100%); `python scripts/mobile/drive_call.py <hi|en|ta> [--script call|direct]`.

## COMPLETED

- M1 Recovery: previous work was already committed in `1dba35e`; the untracked
  `scripts/mobile/export_asr.py` was brought in (`6149fb6`).
- M2 On-device ASR (`com.vive.ondevice.OnDeviceAsr`, `CtcDecoder`):
  - Model: one wav2vec2-base CTC per language, ONNX, int8 MatMul, 122 MB each.
    hi `Harveenchadha/vakyansh-wav2vec2-hindi-him-4200` (MIT),
    ta `Harveenchadha/vakyansh-wav2vec2-tamil-tam-250` (MIT),
    en `facebook/wav2vec2-base-960h` (Apache-2.0). NOT IndicConformer.
  - Bug found and fixed: the vakyansh checkpoints were converted from fairseq,
    whose CTC blank is `<s>` (id 0), while their HF config declares `<pad>`
    (id 1). The previous run decoded with the declared id (WER 8.05 hi,
    10.2 ta) and rejected int8 on noise. The export now MEASURES the blank
    (dominant argmax, must be a special token) and records its provenance.
  - Port proven: fp32 graph on the phone vs desktop fp32 = 20/20 identical
    transcripts, max confidence diff 2.5e-6
    (`models/evaluation/mobile/asr_port_check_fp32.json`). int8 outputs differ
    slightly between ARM and x86 kernels, so WER is measured ON the phone.
- M3 prep: text heads exported; Gather-only int8 (265 MB each) agrees with
  fp32 torch on 99.95% intent / 99.99% behaviour-label decisions over 2,000
  held-out texts. MatMul int8 was measured to damage the heads (intent
  macro-F1 0.9747 -> 0.9146 per-tensor, 0.128 per-channel), so it is not used
  (`text_quant_experiment.json`). Kotlin WordPiece tokenizer reproduces HF ids
  on 199/199 golden cases.
- M4 prep: ECAPA exported as ONE graph (STFT as DFT conv1d + SpeechBrain
  Filterbank + ECAPA_TDNN): cosine vs SpeechBrain encode_batch = 1.000000.
  Silero ONNX vs JIT max |p| diff 2e-6. Protocol (enrol >= 3 s vs 2 s window,
  LibriSpeech 20 speakers, 40 genuine / 760 impostor): EER 0.0.
- M6 prep: Kotlin port of fusion/temporal/policy matches the backend on 1,500
  fusion, 300 temporal (step by step) and 800 policy golden cases generated
  by the backend code itself (`scripts/mobile/make_risk_golden.py`).

- M5 anti-spoof: J2 model exported (2 s: ASVspoof EER 0.0105, probe 0.15)
  and FAILED the pre-registered handset criterion (en EER 0.7168, 62% of
  genuine windows flagged). validated=false; excluded from risk; weights not
  shipped. `models/evaluation/mobile/antispoof_handset_eval.json`.
- Semantic gap: the SMS-trained heads miss spoken scams even from reference
  text (`text_heads_spoken_check.md`). Added a rule-based sensitive-request
  channel (`models/configs/sensitive_requests.json`, shared by backend and
  phone; edit-distance-1 on single-word secrets >= 6 chars). Independent
  negatives: 0/1200 FLEURS (hi/ta/en); benign-SMS FPs are mostly mislabelled
  scams. Recall on SMS positives ~5% (phishing links, not spoken requests).
- M6 fusion/temporal/policy on the phone, parity-tested; policy acts on the
  rule's finding when the model's label is not sensitive; overlapping windows
  no longer fire the rule twice.
- M7 alerts: live Hindi "अपना पासवर्ड बताइए" through the phone mic ->
  R74 HIGH -> AL-004 SECONDARY_VERIFICATION -> notification visible in the
  shade (channel vive_risk_high, lock-screen PRIVATE).
- M8 persistence: sessions survive force-stop + relaunch (Sessions screen).

## IN_PROGRESS

- Wiring an on-device analysis engine + SQLite session store behind the
  existing SessionRepository/AlertRepository/ModelRepository interfaces, so
  the UI consumes the same events it gets from the backend.

## BLOCKED

(none). Known limits, not blockers: English phone ASR (LibriSpeech wav2vec2)
fails on Indian-accented speech through a loudspeaker; "OTP" is not rendered
by the Hindi/English phone ASR through the air, so the OTP scripts do not
alert - the password/PIN scripts do.

## NEXT_TASK

1. English ASR for Indian-accented speech: the LibriSpeech wav2vec2 fails
   through the handset. Candidate to measure on the phone: whisper-base int8
   English (Phase H: 185 MB, en WER 0.10 desktop) - check ARM latency per
   2 s window before adopting.
2. Spoken-scam training data for the intent/behaviour heads (O18); the
   rules are a stop-gap with measured precision, not a replacement.
3. Tamil request detection: needs Tamil text data (O11) and a better Tamil
   ASR (phone WER 0.42 clean).
4. Update docs/BLOCKERS.md O17 (resolved for the pipeline, with these limits).

## TEST_RESULTS

- 2026-09-23 baseline: Android `testDebugUnitTest` pass; backend pytest
  168 passed, 38 skipped.
- 2026-09-24 final: Android unit tests 138/138; backend pytest 173 passed,
  38 skipped. Parity goldens: fusion 1500, temporal 300, policy 800,
  sensitive-rule 600 cases; WordPiece 199 cases.
- 2026-09-23 after M2: Android unit tests 128/128 (incl. CtcDecoderTest 5,
  RiskParityTest 3 over 2,600 golden cases, WordPieceTokenizerTest 199 cases).

## DEVICE_RESULTS

OnePlus CPH2661, Android 16, ORT 1.30.0 CPU, 4 threads
(`models/evaluation/mobile/asr_device_eval.json`, 20 FLEURS test utts/lang):

| lang | WER on phone | WER desktop (same clips) | load | 2 s window median / max |
|---|---:|---:|---:|---:|
| hi | 0.1518 | 0.1689 | 483 ms | 142 / 154 ms |
| ta | 0.4240 | 0.4269 | 258 ms | 154 / 269 ms |
| en | 0.2227 | 0.2273 | 364 ms | 156 / 174 ms |

For comparison the server IndicConformer measured hi 0.116, ta 0.283: the
phone model is less accurate, and Tamil especially. Peak RSS in the eval
process ~850 MB is dominated by transcribing 10-20 s utterances in one pass;
the app only ever runs 2 s windows.

Provisioning: `python scripts/mobile/provision_device.py [--only asr text audio] [--eval]`
pushes into `/sdcard/Android/data/com.vive/files/models` - the APP must create
that directory (Android 11+ denies the app access to a dir adb created).

## FINAL_ACCEPTANCE_CHECKLIST

Target: OnePlus CPH2661, Android 16, clean debug APK 51 MB (arm64-v8a only),
models provisioned in app storage. adb reverse empty; no process on :8000.

- [x] Phone-only: no backend, no adb reverse (checked before each run)
- [x] Real microphone capture (app's MIC path; laptop speaker as the caller)
- [x] On-device ASR: Hindi good through the air; Tamil and English run but
      transcribe poorly through the handset (ASR ~150-290 ms per 2 s window)
- [x] On-device intent + behaviour: 120/120 identical to desktop graphs; but
      the SMS-trained heads miss spoken scams (O18)
- [x] Sensitive-request rules on device: live Hindi password request ->
      R74 HIGH alert in 3 of 4 runs (S-0012, S-0013, S-0014 yes; S-0016 no -
      ASR heard "बात सवर्ण"). OTP/English/Tamil scripts did not alert: the
      key word never reached the transcript.
- [x] ECAPA enrolment + verification: device embeddings identical to
      desktop; 40/40 genuine accepted, 760/760 impostors rejected (LibriSpeech)
- [x] Anti-spoof: measured on handset audio, FAILED (EER 0.72) -> excluded
      from risk, reported as such
- [x] Risk fusion + temporal + policy on device, parity with backend; missing
      evidence lowers confidence (anti-spoof absent: -0.15 on every packet)
- [x] Alert -> visible Android notification (vive_risk_high, lock-screen
      private), POST_NOTIFICATIONS requested in-app
- [x] Sessions persist across force-stop + relaunch
- [x] UI: no demo data on the on-device path; summary leads with peak risk
      and findings; alerts say what the caller did and what to do
- Memory: app PSS ~127 MB idle, ~1.0 GB with all models loaded during a call
