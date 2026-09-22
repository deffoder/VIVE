# VIVE — Demo Specification

> Scenarios drive the mock adapters (`ML_SPEC.md` §4) and the automated
> end-to-end tests in `tests/e2e/`. Fixtures live in `tests/fixtures/`
> (`DATA_SPEC.md` §9).

## 1. Principles

- A demo must be **repeatable**: same fixture in, same packets out.
- Demo data is **labelled as such** in the UI at all times (`UI_SPEC.md` §6).
- Mock output is never described as model accuracy or as a real detection.
- A scenario that depends on an unavailable model still runs — the affected
  analyzer reports its status and the UI shows it.

## 2. Replay mechanism

`POST /api/v1/sessions` with `source_type: "REPLAY"` and a fixture reference
drives a WAV file through the real pipeline — real packetizer, real VAD path,
real fusion, real WebSocket transport — with whichever adapters are configured.

This exercises the whole system without a live call and is the basis of the
end-to-end tests. It is the same code path as a live session; only the audio
source differs.

## 3. Scenarios

Each must be demonstrable and each is an e2e test.

### S1 — Normal conversation
Genuine voice, benign content. Anti-spoof evidence low, intent
`NORMAL_CONVERSATION`, behaviour `NORMAL`. **Expect:** risk stays `LOW`,
confidence healthy, no alert.

### S2 — Human social engineering
Genuine human voice, no synthetic indicators, but an OTP request under time
pressure. Intent `OTP_REQUEST`, behaviour `URGENCY` (often with
`AUTHORITY_IMPERSONATION`). **Expect:** risk escalates on semantic evidence
alone, proving that low anti-spoof evidence does not cap risk
(`ML_SPEC.md` §6). This is the most important scenario in the set.

### S3 — Elevated anti-spoof signal alongside semantic evidence
Elevated anti-spoof evidence plus `OTP_REQUEST` plus `URGENCY` plus unverified
caller. **Expect:** escalation through `MEDIUM` → `HIGH` → `CRITICAL` with
`SECONDARY_VERIFICATION` recommended, and an alert raised by policy — not by a
hard-coded trigger.

**What this scenario does and does not demonstrate.** It demonstrates how
VIVE *combines* an elevated anti-spoof signal with semantic evidence, and
specifically that the signal alone is not treated as proof: the
`SYNTHETIC_ONLY_CEILING` guard caps anti-spoof-only evidence at 55, below
`HIGH` (measured, `EVALUATION.md` §9). CRITICAL is reached because the intent
and behaviour evidence is also present — remove it and the same anti-spoof
score does not escalate.

It does **not** demonstrate synthetic-voice detection, and must not be
presented as doing so. In **mock mode** the elevated score is scripted by the
deterministic mock adapter. In **real mode** the score comes from AASIST,
which Phase 9 measured at chance on the only two-class probe available — EER
0.4333, 90% interval 0.3500–0.5000 (`EVALUATION.md` §5, `BLOCKERS.md` O12).
Say so when running it.

> **Changed in Phase 8B.** S3 was written in romanised Tamil, which meant the
> scenario demonstrated Tamil scam detection VIVE cannot perform: the intent
> and behaviour heads were trained on a corpus with zero Tamil records
> (`BLOCKERS.md` O11). It now runs in **Hindi**, and S11 covers Tamil
> honestly.
>
> **Renamed in Phase 10.** It was called "Synthetic scam" and its stated
> purpose was "synthetic-voice escalation". Phase 9 made that framing a claim
> VIVE cannot support, so the scenario now demonstrates the fusion guard
> rather than a detection capability. The packets it produces are unchanged.

### S4 — Poor audio
Noisy, clipped or near-silent input. Quality `POOR` / `NO_SPEECH`. **Expect:**
confidence falls, insufficient-data state shown, risk does **not** rise. Poor
audio is not evidence of fraud.

### S5 — No speaker reference
No enrolment exists. **Expect:** `ecapa.status = NO_REFERENCE`, the UI shows
speaker consistency as unavailable rather than `0%`, and fusion re-weights
around the missing signal.

### S6 — Hindi
Hindi-language scam content, e.g. an account-verification OTP request.
**Expect:** correct language detection, usable transcript, intent recognised
from Hindi input.

### S7 — Tamil
Tamil-language equivalent. **Expect:** as S6. Script renders correctly in the
transcript UI.

### S8 — Escalation and alert delivery
Drives S3 to `CRITICAL`. **Expect:** in-app alert, Android notification with no
transcript content (`SECURITY_SPEC.md` §4), and a signed webhook delivered with
`event_id` idempotency.

### S11 — Tamil: transcribed, not understood
Tamil speech with scam wording. **Expect:** transcript `AVAILABLE` and the
correct Tamil text, `language: ta`, and intent and behaviour both
`UNSUPPORTED_LANGUAGE` with no labels. Risk must **not** reach `CRITICAL` on
text evidence that was never produced — an unsupported language is missing
evidence, not incriminating evidence.

This scenario exists to keep the Tamil claim honest: Tamil ASR is validated,
Tamil understanding is not (`BLOCKERS.md` O11).

### S9 — Connection loss
WebSocket is dropped mid-session. **Expect:** UI shows Offline, backoff
reconnect, missed packets backfilled via `since_seq`, no gap in the timeline and
no crash.

### S10 — Adapter unavailable
An adapter fails to load. **Expect:** `/ready` reports it, packets carry
`LOAD_ERROR` for that analyzer, the UI shows "Model unavailable", and the
session still produces a risk assessment. Risk must **not** rise because a
model is missing, and confidence must fall — both measured in `EVALUATION.md`
§12.

### S12 — Anti-spoofing warm-up (real mode)
The first seconds of any real-mode call. AASIST needs 64,600 samples (~4.04 s)
of genuine audio and the adapter refuses to pad, tile or fabricate the
difference. **Expect:** `aasist.status = INSUFFICIENT_AUDIO` with `score:
null` on the early packets, the UI reading "Not enough audio yet" rather than
"Unavailable" or `0%`, and a real score appearing from roughly the fourth
packet — measured as packet #4 in both languages (`EVALUATION.md` §10).

This scenario exists because the honest behaviour looks like a bug. A
demonstrator who sees an empty anti-spoof row for four seconds should be able
to say why it is empty, and that waiting is the correct answer: Phase 8
measured that padding a short window let the padding strategy, rather than the
speech, decide the score (`ML_SPEC.md` §2.7).

## 4. Walkthrough

1. Home — protected state, recent sessions.
2. Start S3 replay; incoming-call screen.
3. Active call — gauge rises; confidence shown separately; evidence rows fill.
4. Open live transcript; show detected language.
5. Open packet timeline; show overlapping windows.
6. Tap the escalating packet; show contribution bars and the transcript line.
7. Show the alert and its recommended action.
8. End session; show the call summary with escalation timings.
9. Run S4 — show that poor audio lowers confidence without raising risk.
10. Run S2 — show semantic-only escalation with no synthetic indicators.

Steps 9 and 10 are the substance: they demonstrate that the system reasons over
evidence rather than pattern-matching on a single signal.

## 5. Acceptance

A scenario passes when:

- packets are produced automatically at the configured window and stride;
- every displayed value traces to backend data, with nothing hard-coded;
- risk changes follow from evidence, and `score` and `confidence` move
  independently;
- unavailable analyzers degrade visibly rather than silently;
- alerts are raised by the policy engine;
- the run is repeatable end to end.

## 6. Claims discipline

During any demonstration, state plainly: which adapters are mock and which are
real; that synthetic speech is not proof of fraud and human speech is not proof
of safety; that cellular audio is inaccessible by platform design; and that
detection of unknown future generators is not guaranteed. The forbidden claims
in `PROJECT_SPEC.md` §2.1 apply to spoken commentary as much as to the UI.

**Additional disclosures required after Phase 9** (`docs/EVALUATION.md`):

- **Do not point at the AASIST score as evidence.** It is measured at chance
  against the only two-class probe VIVE has - EER 0.4333, 90% interval
  0.3500-0.5000 (`BLOCKERS.md` O12). If the number is visible on screen, say
  that it is an integrated model output with no measured discrimination.
- **Do not read the risk score as a percentage chance of fraud.** Expected
  calibration error 0.3171. Say "risk score 91 of 100", never "91% likely".
- **Do not quote an accuracy figure without its corpus.** Hindi WER 0.1141 is
  clean read speech, not call audio.
- **Anti-spoof evidence does not appear for the first ~4 seconds** of a call,
  by design: the adapter reports `INSUFFICIENT_AUDIO` until it holds 64,600
  samples of real audio rather than padding. If a demo is short, the channel
  may never report at all - measured, the first scored packet is #4.
- **Speaker consistency will read `NO_REFERENCE` throughout.** There is no
  enrolment source (O3). That is the correct output, not a failure.
- If asked about latency, quote the median **and** the p95 with the hardware:
  751-844 ms median, 930-1069 ms p95 on a 12-thread CPU, CPU-only inference.
