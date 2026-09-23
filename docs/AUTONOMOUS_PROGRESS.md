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

M2 (on-device ASR) measured on the phone and committed. Kotlin on-device
components for M3 (text), M4 (VAD + ECAPA) and M6 (risk) are written and
unit-tested on the JVM; not yet measured on the phone or wired into the app.

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

## IN_PROGRESS

- Wiring an on-device analysis engine + SQLite session store behind the
  existing SessionRepository/AlertRepository/ModelRepository interfaces, so
  the UI consumes the same events it gets from the backend.

## BLOCKED

(none)

## NEXT_TASK

1. ECAPA threshold: with EER 0 the export picks the minimum genuine score
   (0.4121) - zero margin. Use the midpoint of the separating gap instead and
   record max-impostor / min-genuine. Re-run `export_audio.py`.
2. androidTest for text parity (eval/text_eval.json) and speaker protocol
   (eval/speaker_eval.json) on the phone.
3. OnDeviceEngine + OnDeviceSessionRepository + SessionStore (SQLite);
   ServiceLocator on-device mode as default; language picker on Home.
4. M5 anti-spoof decision (read `scripts/evaluation/exp_antispoof_replacement.py`
   results first).

## TEST_RESULTS

- 2026-09-23 baseline: Android `testDebugUnitTest` pass; backend pytest
  168 passed, 38 skipped.
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

- [ ] Phone-only: no backend, no adb reverse
- [ ] Real microphone capture
- [ ] On-device ASR: Hindi / Tamil / English
- [ ] On-device intent + behaviour, agreement vs Python measured
- [ ] On-device ECAPA enrolment + verification (same / different speaker)
- [ ] Anti-spoof: deployed only if validated; otherwise excluded from risk
- [ ] On-device risk fusion + temporal risk; unavailable evidence lowers confidence
- [ ] Alert raised -> visible Android notification (POST_NOTIFICATIONS)
- [ ] Session persists across app restart
- [ ] Professional UI, no demo data
