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

### S3 — Synthetic scam
Elevated anti-spoof evidence plus `OTP_REQUEST` plus `URGENCY` plus unverified
caller. **Expect:** escalation through `MEDIUM` → `HIGH` → `CRITICAL` with
`SECONDARY_VERIFICATION` recommended, and an alert raised by policy — not by a
hard-coded trigger.

> **Changed in Phase 8B.** S3 was written in romanised Tamil, which meant the
> scenario demonstrated Tamil scam detection VIVE cannot perform: the intent
> and behaviour heads were trained on a corpus with zero Tamil records
> (`BLOCKERS.md` O11). It now runs in **Hindi**, preserving what the scenario
> actually tests — synthetic-voice escalation — while S11 covers Tamil
> honestly.

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
`UNAVAILABLE` for that analyzer, the UI shows Unavailable, and the session still
produces a risk assessment.

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
