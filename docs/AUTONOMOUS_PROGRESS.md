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

Milestone 1 (recovery) complete. Starting Milestone 2 (on-device ASR).

## COMPLETED

- M1 Recovery: the previous session's in-flight work (wav2vec2 anti-spoof,
  Home entry point, hermetic tests, ASR routing, AlertNotifier) was already
  committed in `1dba35e`. The only uncommitted file was
  `scripts/mobile/export_asr.py` (untracked in the main checkout), now brought
  into the worktree. Previous run of it left `asr-hi.onnx`, `asr-ta.onnx`
  (fp32-sized, i.e. int8 rejected) and `asr-en.onnx` + `asr-en.fp32.onnx` but
  no manifest - the run did not finish.

## IN_PROGRESS

- M2 On-device ASR.

## BLOCKED

(none yet)

## NEXT_TASK

Re-run `scripts/mobile/export_asr.py` to produce `asr_manifest.json` with WER
for hi/ta/en; then build the Android ONNX Runtime ASR path and measure on the
device.

## TEST_RESULTS

- 2026-09-23 baseline: Android `testDebugUnitTest` pass; backend pytest
  168 passed, 38 skipped.

## DEVICE_RESULTS

(none yet in this context)

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
