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
- **Required external action:** choose an engine before Phase 6, so retention
  (`SECURITY_SPEC.md` §4) can actually be enforced.

### O5 — Dataset licenses unverified · `OPEN`

- **Blocker:** no candidate dataset in `DATA_SPEC.md` §4 has a verified license.
- **Cause:** the architecture phase explicitly excludes downloads and training,
  so no corpus has been fetched or inspected.
- **Attempted fixes:** manifest schema requires `license` and `provenance` on
  every record, so an unlicensed clip cannot enter a split unnoticed.
- **Current status:** not blocking Phases 1–7.
- **Required external action:** license review per dataset before Phase 8.

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
- **Required external action:** recalibrate against real outputs in Phase 8;
  never present provisional weights as measured accuracy.

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
