# VIVE — Implementation Plan

> Ordering principle: the product must work end-to-end on mock adapters before
> any real model is integrated, so that UI, transport and fusion defects are
> never confused with model defects. Real ML is the **last** major phase.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` complete

## Phase 0 — Repository and architecture `[x]`

- [x] Git rooted at `VIVE/`, home-directory repo not used
- [x] `.gitignore` covering secrets, builds, checkpoints, corpora
- [x] Final directory structure; `frontend/` removed
- [x] Documentation set written and mutually consistent

**Exit:** structure matches `ARCHITECTURE.md`; no contradictory paths, schemas or
model names across the specs.

## Phase 1 — Android foundation + typed contract `[~]`

Delivered as the Android application foundation, with the Kotlin half of the
typed contract. The backend half moves to Phase 2.

Android foundation — **complete**:

- [x] Gradle/AGP/Kotlin configuration, version catalog, wrapper
- [x] Package structure per `ARCHITECTURE.md` §6
- [x] Navigation architecture — 4 tabs + full drill-down, all 24 routes
- [x] Theme, colour system, typography, spacing, shapes (`UI_SPEC.md` §2)
- [x] Component foundation incl. all seven state components
- [x] Screen/state architecture (`UiState` sealed interface)
- [x] Repository/service interfaces + REST/WebSocket/event interfaces
- [x] Logging with transcript redaction, typed error handling
- [x] Test structure; 16 unit tests passing
- [x] Kotlin mirrors of every taxonomy and the canonical packet
- [x] Contract test pinning the `CLAUDE.md` example packet

Deferred to Phase 2 (backend side of the same contract):

- [ ] Pydantic schemas in `backend/app/schemas/`
- [ ] OpenAPI generated and checked against `API_SPEC.md`

**Exit (Android side, met):** app builds, launches, navigates; the canonical
packet models with no field renamed or dropped; a missing analyzer yields
`null`, never `0`.

## Phase 2 — Backend skeleton, no models `[ ]`

- [ ] FastAPI app, config, health/ready/version
- [ ] Session manager and state machine
- [ ] Bounded ring buffer; sliding-window packetizer (2.0 s / 1.0 s / 16 kHz)
- [ ] Analyzer orchestrator calling interfaces that all return `UNAVAILABLE`
- [ ] REST routes per `API_SPEC.md` §3 and §5
- [ ] WebSocket manager and frame envelopes (§6)
- [ ] Error contract (§7)

**Exit:** a `REPLAY` session produces packets end-to-end with zero models loaded.

## Phase 3 — Design system in Compose `[ ]`

- [ ] Theme tokens from `UI_SPEC.md` §2
- [ ] `RiskGauge`, `EvidenceRow`, `RiskPill`, `MetricCard` first
- [ ] Remaining components from `UI_SPEC.md` §7
- [ ] Every component's Loading / Empty / Error / Unavailable variants
- [ ] Component preview screen for visual review against `design/02`

**Exit:** components render all states; no duplicated UI code.

## Phase 4 — Navigation and screens `[ ]`

- [ ] Nav graph, four-tab bottom nav, drill-down path
- [ ] Screens in dependency order: Home → Active Call → Risk Details → Packet
      Timeline → Packet Detail → Transcript → Summary → Sessions → Alerts →
      More cluster
- [ ] Each screen bound to a `UiState` sealed type
- [ ] Packet evidence reachable in ≤2 taps from an active call

**Exit:** all 24 flows navigable; every screen handles all seven states.

## Phase 5 — Live wiring `[ ]`

- [ ] Retrofit client; OkHttp WebSocket client
- [ ] Incremental packet append keyed by `packet_id`; no full rebuilds
- [ ] Reconnect with backoff; `since_seq` backfill
- [ ] Offline and error states wired
- [ ] Mock adapters driven by `DEMO_SPEC.md` scenarios
- [ ] Demo-data indicator surfaced (`UI_SPEC.md` §6)

**Exit:** **the product is fully demonstrable on mock data.** Scenarios S1–S10
run end-to-end. This is the milestone that must be reached before any ML work.

## Phase 6 — Fusion, temporal, policy `[ ]`

- [ ] Transparent weighted fusion, weights in `models/configs/fusion.yaml`
- [ ] Separate confidence computation
- [ ] EMA smoothing, hysteresis, minimum-evidence gate, cooldown
- [ ] Escalation timings
- [ ] Policy → recommended action → alert
- [ ] Webhook delivery: signing, idempotency, retry

**Exit:** S2 escalates on semantic evidence alone; S4 lowers confidence without
raising risk.

## Phase 7 — Android telephony `[ ]`

- [ ] `CallScreeningService` for cellular screening/metadata
- [ ] Authorized VoIP/in-app capture at 16 kHz
- [ ] Permission flow with per-permission rationale
- [ ] Telephony boundary stated in the UI

**Exit:** both paths work; no claim of cellular audio capture anywhere.

## Phase 8 — Real ML `[ ]`

Last major phase. Strictly sequential (`ML_SPEC.md` §9). Training on Kaggle or
Google Colab; no local GPU assumed.

- [ ] Dataset manifests, licenses, leakage checks (`DATA_SPEC.md` §5)
- [ ] `silero-vad` → `aasist` → `ecapa-tdnn` → `indicconformer`
      → `intent-classifier` → `behavior-classifier`
- [ ] Per model: real sample, recorded inference time and version, UI verified
- [ ] Fusion recalibrated against real outputs
- [ ] Evaluation report

**Exit:** adapters report `mode: "real"`; every metric traces to a measured run.

## Phase 9 — Verification and hardening `[ ]`

- [ ] `tests/backend/` — pipeline, fusion, temporal, policy
- [ ] `tests/android/` — component states, navigation, drill-down
- [ ] `tests/integration/` — REST + WebSocket contract
- [ ] `tests/e2e/` — scenarios S1–S10
- [ ] Latency measured and recorded, not claimed
- [ ] Security review against `SECURITY_SPEC.md` §8
- [ ] Design quality gate against `CLAUDE.md`

**Exit:** the definition of done in `PROJECT_SPEC.md` is met by demonstration,
not by compilation.

## Notes on sequencing

Phases 3 and 4 may run alongside Phase 2 once Phase 1 is frozen — the contract is
what decouples them. Phase 8 must not begin before Phase 5's exit criterion is
met. Nothing in Phases 0–7 requires a GPU or a large model download.
