# VIVE — UI Specification

> Primary visual reference: `design/02_vive_ui_reference.png`.
> Supporting: `design/01`, `design/03`, `design/04`.
> Extract the design system; do not copy individual screenshots literally.

Stack: **Kotlin + Jetpack Compose, Material 3**. No React Native, no web frontend.
Data contract: `API_SPEC.md`. Taxonomies: `PROJECT_SPEC.md` §7.

---

## 1. Design intent

Professional · trustworthy · secure · modern · minimal · fast · clear.

All four references converge on an enterprise security aesthetic: clean white
cards on a very light blue-grey page, one confident blue accent, generous
spacing, strong hierarchy, and colour used to carry meaning rather than decorate.

**Forbidden:** heavy gradients, 3D AI imagery, neon/futuristic styling,
glassmorphism, decorative illustrations, fake waveform animations, redundant
cards, vanity statistics, raw model numbers on primary screens.

Every element must communicate information.

---

## 2. Design tokens

### 2.1 Colour

| Token | Value | Use |
|---|---|---|
| `primary` | `#1B6FE8` | Wordmark, primary buttons, active nav, gauge arc |
| `primaryContainer` | `#EAF2FE` | Icon chips, selected tabs, soft panels |
| `surface` | `#FFFFFF` | Cards |
| `background` | `#F5F8FD` | Page |
| `onSurface` | `#0F1B33` | Primary text |
| `onSurfaceVariant` | `#5A6B85` | Secondary text |
| `outline` | `#E2E9F3` | Dividers, card borders |

Risk palette — the only other saturated colours in the product:

| Level | Base | Container |
|---|---|---|
| `LOW` | `#16A34A` | `#E8F6EE` |
| `MEDIUM` | `#F59E0B` | `#FEF3E2` |
| `HIGH` | `#EF4444` | `#FEECEC` |
| `CRITICAL` | `#DC2626` | `#FDE4E4` |

Colour never carries risk alone — a text label always accompanies it.

### 2.2 Type

One sans family, three weights. Display 32/40 semibold (gauge numeral 44/48) ·
Title 20/28 semibold · Body 15/22 regular · Label 13/18 medium ·
Caption 12/16 regular.

### 2.3 Spacing and shape

4dp scale: 4 · 8 · 12 · 16 · 24 · 32. Screen gutter 16dp. Card padding 16dp.
Card radius 20dp, chip/pill 12dp, button 14dp. Minimum touch target 48dp.
Elevation is a 1dp `outline` border plus a very soft shadow — never heavy.

---

## 3. Navigation

Bottom navigation, exactly four destinations (`CLAUDE.md`):

```
Home · Sessions · Alerts · More
```

### 3.1 Graph

```
Splash → Onboarding → Permissions → Login ─┐
                                           ▼
                        ┌──────────── Home (tab) ────────────┐
                        │                                     │
              Incoming Call                            Recent session
                        │                                     │
                 Active Call ──┬── Live Transcript            │
                               ├── Risk Details ── Evidence Details
                               ├── Packet Timeline ── Packet Detail
                               └── Call Summary ─────────────┘

Sessions (tab) → Call History → Call Summary → Packet Timeline → Packet Detail
Alerts (tab)   → Alert Detail → Session / Packet Detail
More (tab)     → Reports · Settings · Connected Services · API Integrations
                 · Model Information · Profile · Help · About · Logout
```

### 3.2 Required evidence path

```
Call → Risk → Evidence → Packet → Detailed evidence
```

Packet evidence must be reachable from an active call in **at most two taps**.
Back always returns along the entry path; the four tabs keep independent
back stacks.

---

## 4. Screen specifications

Every screen below states: purpose · reached from · components · interactions ·
states · backend data. States are drawn from §8. "Backend data" names the
`API_SPEC.md` source; a screen with no backend source is local-only.

### 4.1 Splash
- **Purpose** — brand moment while the app resolves auth and backend readiness.
- **Reached from** — app launch.
- **Components** — wordmark, tagline, shield mark.
- **Interactions** — none; auto-advances.
- **States** — Loading · Error (backend unreachable → retry).
- **Backend** — `GET /health`, `GET /ready`.
- **Note** — no animated waveform. References show a static mark.

### 4.2 Onboarding
- **Purpose** — explain what VIVE does before requesting permissions.
- **Reached from** — Splash, first run only.
- **Components** — 3 pages, illustration, title, body, page dots, Skip, Next.
- **Interactions** — swipe or Next; Skip jumps to Permissions.
- **States** — Success only.
- **Backend** — none.

### 4.3 Permissions
- **Purpose** — request microphone, phone, notifications, storage with reasons.
- **Reached from** — Onboarding.
- **Components** — `PermissionCard` per permission (icon, name, reason, toggle
  or status), Continue, privacy line.
- **Interactions** — per-permission request; Continue enabled once required ones
  are granted; denial is non-blocking and degrades features visibly.
- **States** — Success · Error (permanently denied → deep-link to settings).
- **Backend** — none.
- **Note** — storage is optional; its card must say so. The telephony boundary
  (§6) is stated here.

### 4.4 Login / account setup
- **Purpose** — authenticate.
- **Reached from** — Permissions, or Logout.
- **Components** — email/phone field, password field, Sign In, federated
  buttons, forgot-password, sign-up link.
- **Interactions** — validation on blur; submit; error surfaced inline.
- **States** — Loading · Success · Error · Offline.
- **Backend** — auth endpoint; token stored per `SECURITY_SPEC.md` §2.

### 4.5 Home dashboard
- **Purpose** — protected status at a glance plus entry to recent sessions.
- **Reached from** — post-login; Home tab.
- **Components** — `TopAppBar`, protected-state banner, `MetricCard` row
  (calls analysed / alerts / active threats), `SectionHeader` + `SessionCard`
  list, `BottomNavigation`.
- **Interactions** — tap session → Call Summary; View All → Call History;
  settings icon → Settings.
- **States** — Loading · Success · Empty (no sessions yet) · Error · Offline.
- **Backend** — `GET /api/v1/sessions?limit=n`, `GET /api/v1/alerts?limit=n`.
- **Note** — when a session is live, the banner becomes a resume affordance into
  Active Call. Counters are real aggregates, never decorative.

### 4.6 Incoming call
- **Purpose** — show an inbound call and the analysis path available for it.
- **Reached from** — `CallScreeningService` or an in-app call event.
- **Components** — number, caller status, Accept/Decline, analysis-path notice.
- **Interactions** — Accept → Active Call (VoIP/in-app) or screening-only view
  (cellular); Decline dismisses.
- **States** — Success · Unavailable (screening metadata only).
- **Backend** — `POST /api/v1/sessions` on accept.
- **Note** — for cellular this screen must state that audio is not analysed.
  See §6.

### 4.7 Active call analysis
The most important screen. Visible without scrolling, in order:

1. **`RiskGauge`** — circular arc, score numeral, risk level inside.
2. **`ConfidenceIndicator`** — directly below, separate text (`Confidence 89%`).
3. **`MetricCard` row** — duration · packets processed · current language.
4. **"Why is this call risky?"** — `EvidenceCard` rows with severity pills.
5. **`RiskTimeline`** — sparkline of score over packets.
6. Entries to transcript, packet timeline, detailed evidence.
7. Call controls (mute / speaker / end).

- **Reached from** — Incoming Call, or resume from Home.
- **Interactions** — tap evidence row → Risk Details; tap timeline → Packet
  Timeline; transcript button → Live Transcript; End → Call Summary.
- **States** — all seven. Insufficient data when audio quality is `POOR`/
  `NO_SPEECH`; Unavailable per-signal when an analyzer reports a status.
- **Backend** — `WS /api/v1/sessions/{id}/stream` frames `session.state`,
  `packet.new`, `risk.update`, `alert.raised`; REST backfill on reconnect.
- **Rules** — the five evidence rows are synthetic-voice indicators, speaker
  consistency, intent risk, behaviour risk, context risk. Phrasing is
  evidence-shaped: *"High voice-integrity risk"*, never *"87% AI voice"*.
  Score and confidence are never merged. Appends are incremental — no full
  rebuild per packet (`ARCHITECTURE.md` §8).

### 4.8 Live transcript
- **Purpose** — running transcript with language and risk markers.
- **Reached from** — Active Call; Call Summary (historical).
- **Components** — language selector (auto-detected, overridable),
  `TranscriptBubble` per utterance, listening indicator, pause/stop.
- **Interactions** — auto-scroll with scroll-lock on manual scroll; tap a bubble
  → the packet that produced it.
- **States** — Loading · Success · Empty (no speech yet) · Error · Offline ·
  Insufficient data.
- **Backend** — WS `transcript.append`; `GET /api/v1/sessions/{id}/transcript`.
- **Rules** — show speaker, call-relative timestamp, ASR confidence, and inline
  intent/behaviour markers only on lines that carry them. Indic script renders
  as-is; no transliteration. `FLAG_SECURE` applies (`SECURITY_SPEC.md` §6).

### 4.9 Risk details
- **Purpose** — decompose current risk into its contributing signals.
- **Reached from** — Active Call, Call Summary.
- **Components** — `RiskCard`, per-signal labelled progress bars, risk-level
  scale, advisory text.
- **Interactions** — tap a signal → Evidence Details for that signal.
- **States** — Loading · Success · Error · Unavailable · Insufficient data.
- **Backend** — `GET /api/v1/sessions/{id}/risk`; live via `risk.update`.

### 4.10 Evidence details
- **Purpose** — the evidence behind one signal group.
- **Reached from** — Risk Details.
- **Components** — tab row (Voice · Speaker · Intent · Context), model panel
  with score and plain-language reading, audio-feature rows, analysis window.
- **Interactions** — tabs switch group; audio evidence plays only if retained.
- **States** — Success · Unavailable · Insufficient data.
- **Backend** — packet evidence from `GET …/packets`.
- **Rules** — model version and inference time belong here, not on Active Call
  (`CLAUDE.md`: no technical model numbers on primary screens).

### 4.11 Packet timeline
- **Purpose** — every analysis window in sequence.
- **Reached from** — Active Call, Call Summary.
- **Components** — `PacketTimeline` — vertical rail, coloured dot, `P0N`,
  window `00:06 – 00:08`, `RiskPill`.
- **Interactions** — tap row → Packet Detail; paginates on scroll.
- **States** — Loading · Success · Empty · Error · Offline.
- **Backend** — `GET /api/v1/sessions/{id}/packets?since_seq=`; live `packet.new`.
- **Rules** — rows keyed by `packet_id`, appended incrementally. Windows
  overlap; the UI must not imply they partition the call.

### 4.12 Packet detail
- **Purpose** — full forensic record for one window.
- **Reached from** — Packet Timeline, transcript bubble, alert.
- **Components** — header (`packet_id`, `RiskPill`, window), risk + confidence
  pair, audio player if retained, transcript, field rows, **contribution bars**.
- **Interactions** — play evidence; navigate to adjacent packets.
- **States** — Loading · Success · Error · Unavailable · Insufficient data.
- **Backend** — `GET /api/v1/sessions/{id}/packets/{packet_id}`.
- **Required fields** — packet ID · timestamp · window · duration · language ·
  audio quality · transcript · intent · behaviour · synthetic-voice evidence ·
  speaker consistency · context · packet risk · confidence.
- **Contribution visualization** — horizontal bars from `risk.contributions`
  (`API_SPEC.md` §4.1):

  ```
  Synthetic indicators   87%
  Intent risk            94%
  Context risk           82%
  Speaker consistency    43%
  Packet risk            91%
  ```

  These are **evidence strengths, not a decomposition of the score**, and the
  screen must not imply they sum to it. All values come from backend data —
  never hard-coded, never invented when a field is absent.

### 4.13 Call summary
- **Purpose** — post-call report.
- **Reached from** — End Call; Call History.
- **Components** — header, overall + current risk, confidence, `MetricCard`s
  (duration, packets, language, intent, behaviour, caller status), escalation
  timings, evidence summary, View Full Details, Report Call.
- **Interactions** — into Packet Timeline / Transcript / Risk Details.
- **States** — Loading · Success · Error · Insufficient data.
- **Backend** — `GET /api/v1/sessions/{id}/report`; WS `session.ended`.
- **Rules** — shows first anomaly, first warning, critical escalation and risk
  progression (`CLAUDE.md`, Overall Call Analysis).

### 4.14 Call history
- **Purpose** — past sessions.
- **Reached from** — Sessions tab; Home "View All".
- **Components** — search, filter chips (All/Low/Medium/High/Critical), day
  `SectionHeader`s, `SessionCard` rows.
- **Interactions** — tap → Call Summary; filter; search by number; paginate.
- **States** — Loading · Success · Empty · Error · Offline.
- **Backend** — `GET /api/v1/sessions` with filters and paging.

### 4.15 Alerts
- **Purpose** — policy-raised alerts across sessions.
- **Reached from** — Alerts tab; notification.
- **Components** — filter chips (All/Critical/High/Medium), `AlertCard` rows
  (severity icon, title, number, reason, relative time).
- **Interactions** — tap → alert detail → originating session/packet;
  acknowledge.
- **States** — Loading · Success · Empty · Error · Offline.
- **Backend** — `GET /api/v1/alerts`, `POST /api/v1/alerts/{id}/ack`;
  live `alert.raised`.
- **Rules** — each alert shows risk, reason, timestamp, session, intent and
  recommended action. Unacknowledged alerts are visually distinct.

### 4.16 Reports / insights
- **Purpose** — aggregate trends.
- **Reached from** — More.
- **Components** — period tabs (Weekly/Monthly/All), `MetricCard` row,
  `ChartCard` bar chart, top-risk-types list.
- **Interactions** — switch period.
- **States** — Loading · Success · Empty · Error · Insufficient data.
- **Backend** — aggregate over `GET /api/v1/sessions` / `alerts`.
- **Rules** — only real aggregates. No projected or illustrative figures.

### 4.17 Settings
- **Purpose** — preferences hub.
- **Reached from** — More; Home gear icon.
- **Components** — grouped rows with leading icon, title, subtitle, chevron.
- **Interactions** — navigate to sub-screens; toggles apply immediately.
- **States** — Success · Error on persist failure.
- **Backend** — local preferences; server-side ones via integrations.

### 4.18 Connected services
- **Purpose** — alert delivery channels.
- **Reached from** — Settings / More.
- **Components** — `IntegrationCard` per channel with connection status,
  Add Channel.
- **Interactions** — connect/disconnect (confirmation required).
- **States** — Loading · Success · Empty · Error.
- **Backend** — `GET /api/v1/integrations`, `PUT …/{id}`.

### 4.19 API integrations
- **Purpose** — programmatic integration config.
- **Reached from** — More.
- **Components** — `IntegrationCard` rows (banking APIs, SMS, email, webhook)
  with Configured / Not Configured status.
- **Interactions** — configure; webhook endpoint + secret entry.
- **States** — Loading · Success · Empty · Error.
- **Backend** — `GET /api/v1/integrations`, `PUT …/{id}`.
- **Rules** — secrets are never displayed after entry. No integration is shown
  as connected unless it actually is (`CLAUDE.md`: do not fabricate).

### 4.20 Model information
- **Purpose** — what is running, at what version, in which mode.
- **Reached from** — More.
- **Components** — `ModelInfoCard` per model (name, purpose, version, status,
  **mode badge**), last-updated.
- **Interactions** — tap → detail with measured inference time.
- **States** — Loading · Success · Error · Unavailable.
- **Backend** — `GET /api/v1/models`, `GET /ready`.
- **Rules** — **must show `mock` vs `real` per model.** Never display accuracy
  that was not measured (`ML_SPEC.md` §8).

### 4.21 Profile
- **Purpose** — account identity and preferences.
- **Components** — avatar, name, email, personal info rows, preference rows.
- **Interactions** — edit profile; change language/theme.
- **States** — Loading · Success · Error · Offline.
- **Backend** — auth/profile endpoint.

### 4.22 Help / support
- **Purpose** — self-service help.
- **Components** — search, FAQ, user guide, report an issue, contact, feedback.
- **States** — Loading · Success · Empty (no search results) · Error.

### 4.23 About
- **Purpose** — version, legal, acknowledgements.
- **Components** — wordmark, version, description, legal rows.
- **Rules** — the description must not overstate capability; the platform
  limitation (§6) is linked here.

### 4.24 Logout
- **Purpose** — end the session safely.
- **Components** — icon, confirmation question, Logout (destructive), Cancel.
- **Interactions** — confirmation required; clears tokens and cached session data.
- **States** — Success · Error.

---

## 5. Cross-screen interactions

| Interaction | Behaviour |
|---|---|
| Live packet arrives | Append only, keyed by `packet_id`; no full rebuild |
| Risk level changes | Gauge animates over ≤300ms; level label updates with it |
| Alert raised | In-app banner + notification; tap deep-links to Packet Detail |
| WebSocket drops | Offline state; backoff reconnect; `since_seq` backfill |
| Analyzer unavailable | That row shows "Unavailable" — never `0%` or a guess |
| Poor audio | Insufficient-data state; risk must not rise |
| Back from drill-down | Returns along the entry path |
| Session ends | Active Call → Call Summary automatically |

---

## 6. Honesty in the UI

When any adapter reports `mode: "mock"` (`API_SPEC.md` §2), the app shows a
persistent, non-dismissable **Demo data** indicator on Active Call and Packet
Detail, and Model Information lists the mode per model.

The telephony boundary (`ARCHITECTURE.md` §7) is stated on Permissions,
Incoming Call and About: cellular calls are screened by metadata only; full
analysis requires the authorized VoIP/in-app path. The UI must never imply
otherwise.

---

## 7. Components

`RiskCard` · `RiskIndicator` · `EvidenceCard` · `MetricCard` · `PacketCard` ·
`PacketTimeline` · `RiskTimeline` · `TranscriptBubble` · `AlertCard` ·
`SessionCard` · `StatusBadge` · `ConfidenceIndicator` · `PrimaryButton` ·
`SecondaryButton` · `BottomNavigation` · `TopAppBar` · `SectionHeader` ·
`EmptyState` · `LoadingState` · `ErrorState` · `PermissionCard` ·
`IntegrationCard` · `ModelInfoCard` · `ChartCard`

Supporting primitives: `RiskGauge` (the circular score), `RiskPill`,
`EvidenceRow`, `ContributionBar`.

Build order: `RiskGauge`, `EvidenceRow`, `RiskPill`, `MetricCard` first — they
account for most of the pixels across the inventory. No duplicated UI code.

---

## 8. States

Every screen handles: **Loading · Success · Empty · Error · Offline ·
Unavailable · Insufficient data.**

Modelled as a sealed `UiState` per ViewModel. Rules:

- Missing model output renders "Unavailable" — never `0`, `—` or a guess.
- Poor audio renders "Insufficient data" — never an inflated risk.
- Offline is distinct from Error: offline is recoverable and shows cached data.
- The UI must not crash when any analyzer block is absent from a packet.

---

## 9. Responsiveness and accessibility

Common Android phone widths (360–430dp); scalable typography honouring the
system font scale; safe-area insets; 48dp touch targets; content descriptions on
every icon-only control; risk conveyed by label and icon as well as colour;
contrast at WCAG AA against the surface behind it.

Dark theme is deferred (`BLOCKERS.md` D8) but tokens are defined so it can be
added without touching component code.
