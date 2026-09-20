# VIVE — Voice Integrity Verification Engine

## PROJECT ROLE

You are the principal software engineer and UI/UX engineer for VIVE.

VIVE is a real-time voice integrity verification and social-engineering risk analysis platform.

The system analyzes authorized live or near-live voice communication using:

- Voice anti-spoofing
- Speaker consistency
- Multilingual speech recognition
- Intent classification
- Social-engineering behavior analysis
- Contextual risk
- Uncertainty / OOD detection
- Temporal risk analysis
- Explainable risk fusion

The product must feel like a professional enterprise security product, NOT a generic AI demo.

---

# PRIMARY UI DESIGN REFERENCE

The PRIMARY visual reference is:

design/02_vive_ui_reference.png

Additional references:

design/01_vive_ui_reference.png
design/03_vive_ui_reference.png
design/04_vive_ui_reference.png

Study the reference images before implementing UI.

The implementation should preserve the visual language of the reference:

- Clean white surfaces
- Professional blue primary color
- Soft blue secondary surfaces
- Rounded cards
- Clear typography
- Spacious layouts
- Minimal visual clutter
- Enterprise security aesthetic
- Strong information hierarchy
- Subtle shadows
- Clean icons
- Clear status indicators
- Professional charts
- Consistent spacing

Do NOT blindly copy individual screenshots.

Extract the underlying design system and apply it consistently across the application.

---

# DESIGN PRINCIPLES

The application should feel:

- Professional
- Trustworthy
- Secure
- Modern
- Minimal
- Fast
- Clear
- Enterprise-grade

Avoid:

- Excessive gradients
- 3D AI graphics
- Futuristic neon interfaces
- Excessive glassmorphism
- Huge decorative illustrations
- Fake voice wave animations
- Unnecessary cards
- Excessive statistics
- Technical model numbers on primary screens
- Cluttered dashboards
- Decorative elements that do not communicate information

Every UI element must have a purpose.

---

# PRIMARY NAVIGATION

Use:

Home
Sessions
Alerts
More

Do not introduce unnecessary navigation items.

---

# MAIN USER FLOWS

The application must support:

1. Splash
2. Onboarding
3. Permissions
4. Login / account setup
5. Home dashboard
6. Incoming call
7. Active call analysis
8. Live transcript
9. Risk details
10. Evidence details
11. Packet timeline
12. Packet detail
13. Call summary
14. Call history
15. Alerts
16. Reports / insights
17. Settings
18. Connected services
19. API integrations
20. Model information
21. Profile
22. Help / support
23. About
24. Logout

---

# ACTIVE CALL SCREEN

The active call screen is one of the most important screens.

It must clearly show:

- Current risk score
- Risk level
- Confidence
- Call duration
- Packets processed
- Current language
- Synthetic voice indicators
- Speaker consistency
- Intent risk
- Behavior risk
- Context risk
- Risk timeline
- Access to live transcript
- Access to packet timeline
- Access to detailed evidence

Do not overwhelm the user.

The most important information must be visible first.

---

# RISK DESIGN

Risk levels:

LOW
MEDIUM
HIGH
CRITICAL

Use visual differentiation while maintaining accessibility.

Risk score and confidence are different concepts.

Never present confidence as fraud probability.

Never claim that synthetic voice automatically means fraud.

Never claim that human voice automatically means safe.

Use language such as:

"High voice-integrity risk"

rather than:

"87% AI voice"

unless the underlying metric specifically represents that quantity.

---

# PACKET MODEL

The system processes audio using overlapping/sliding windows.

Example:

P001 — 00:00–00:02
P002 — 00:01–00:03
P003 — 00:02–00:04

Every packet should be independently inspectable.

Packet information can include:

- packet ID
- timestamp
- duration
- language
- audio quality
- AASIST score
- ECAPA similarity
- ASR transcript
- intent
- behavior
- context
- risk score
- risk level
- confidence

---

# PACKET DETAIL SCREEN

When a packet is selected, show:

Packet ID
Timestamp
Window
Duration
Language
Audio quality
Transcript
Intent
Behavior
Synthetic voice evidence
Speaker consistency
Context
Packet risk
Confidence

Also provide an explainable contribution visualization.

Example:

Synthetic indicators — 87%
Intent risk — 94%
Context risk — 82%
Speaker consistency — 43%
Packet risk — 91%

These values must come from backend data.

Never hard-code production-looking model results.

---

# OVERALL CALL ANALYSIS

Show:

- Overall risk
- Current risk
- Confidence
- Duration
- Packet count
- First anomaly
- First warning
- Critical escalation
- Risk progression
- Evidence summary

The user must be able to move from:

Call
→ Risk
→ Evidence
→ Packet
→ Detailed evidence

---

# LIVE TRANSCRIPT

Support multilingual speech.

Initial priority:

Hindi
Tamil
English

Design for future Indic-language expansion.

The UI should show:

- Live transcript
- Language
- ASR confidence
- Relevant intent
- Relevant behavioral indicators

Avoid excessive technical information.

---

# INTENT TAXONOMY

Support:

NORMAL_CONVERSATION
OTP_REQUEST
PASSWORD_REQUEST
CARD_DETAILS_REQUEST
BANKING_CREDENTIAL_REQUEST
MONEY_TRANSFER_REQUEST
ACCOUNT_CHANGE_REQUEST
REMOTE_ACCESS_REQUEST
URGENT_ACTION
THREAT_OR_INTIMIDATION
CONFIDENTIAL_INFORMATION
UNKNOWN

---

# BEHAVIOR TAXONOMY

Support:

AUTHORITY_IMPERSONATION
URGENCY
THREAT
FEAR
SECRECY
PRESSURE
REWARD_PROMISE
NORMAL

---

# MODEL STACK

The architecture should support:

Silero VAD
AASIST
ECAPA-TDNN
IndicConformer
Multilingual intent classifier
Behavior classifier
Context engine
OOD / uncertainty layer
Risk fusion engine

Model inference should remain behind backend/service interfaces.

UI must NOT directly call model inference.

---

# DATA FLOW

Audio
→ secure ingestion
→ session manager
→ streaming buffer
→ VAD / DSP
→ AASIST
→ ECAPA
→ Indic ASR
→ intent
→ behavior
→ context
→ uncertainty
→ risk fusion
→ temporal risk
→ policy engine
→ API/WebSocket
→ mobile UI

---

# BACKEND/UI CONTRACT

The UI must consume structured backend events.

Example packet:

{
  "packet_id": "P007",
  "timestamp": "00:08",
  "duration_sec": 2,
  "language": "ta",
  "quality": "GOOD",
  "aasist": {
    "score": 0.87
  },
  "ecapa": {
    "status": "AVAILABLE",
    "similarity": 0.43
  },
  "asr": {
    "transcript": "OTP sollunga...",
    "confidence": 0.91
  },
  "intent": {
    "label": "OTP_REQUEST",
    "confidence": 0.94
  },
  "behavior": {
    "labels": ["URGENCY"],
    "confidence": 0.89
  },
  "context": {
    "caller_verified": false
  },
  "risk": {
    "score": 91,
    "level": "CRITICAL",
    "confidence": 0.84
  }
}

Do not create fake model logic just to populate UI.

If backend data does not exist yet, create typed interfaces/mock adapters that can later be replaced.

Clearly separate mock/demo data from production data.

---

# RESPONSIVENESS

The UI must work across common Android phone sizes.

Use:

- responsive spacing
- scalable typography
- reusable components
- safe areas
- accessibility-friendly touch targets
- consistent padding
- dark/light compatibility if architecture permits

---

# COMPONENT SYSTEM

Create reusable components for:

RiskCard
RiskIndicator
EvidenceCard
MetricCard
PacketCard
PacketTimeline
RiskTimeline
TranscriptBubble
AlertCard
SessionCard
StatusBadge
ConfidenceIndicator
PrimaryButton
SecondaryButton
BottomNavigation
TopAppBar
SectionHeader
EmptyState
LoadingState
ErrorState
PermissionCard
IntegrationCard
ModelInfoCard
ChartCard

Do not duplicate UI code unnecessarily.

---

# STATE DESIGN

Every important screen should handle:

Loading
Success
Empty
Error
Offline
Unavailable
Insufficient data

The UI must not crash when model output is unavailable.

---

# PRIVACY

Treat voice and transcript data as sensitive.

Do not expose unnecessary raw audio.

Do not add unnecessary storage.

Do not claim access to private cellular audio unless the platform/API actually provides it.

For ordinary cellular calls, respect Android and telecom platform restrictions.

Use authorized VoIP/in-app audio for full live audio analysis where required.

---

# PHONE INTEGRATION

The mobile architecture should support Android CallScreeningService for authorized call screening.

Do NOT implement or claim unrestricted access to both sides of ordinary cellular call audio.

For complete live audio analysis, use an authorized VoIP/in-app/collaboration audio path.

---

# ALERTS

Support:

- In-app alerts
- Android notification
- Secure webhook
- Email integration where configured

Alert severity:

LOW
MEDIUM
HIGH
CRITICAL

Alerts should include:

Risk
Reason
Timestamp
Session
Intent
Recommended action

---

# API ARCHITECTURE

Backend should support:

REST
WebSocket
Optional gRPC

Use clean versioned APIs.

Example:

/api/v1/sessions
/api/v1/sessions/{id}
/api/v1/sessions/{id}/packets
/api/v1/alerts
/api/v1/integrations

---

# DEVELOPMENT RULES

Before modifying code:

1. Inspect the repository.
2. Understand the existing architecture.
3. Reuse existing components where appropriate.
4. Do not rewrite working systems unnecessarily.
5. Do not create duplicate implementations.
6. Do not invent APIs that do not exist.
7. Do not hard-code model results.
8. Do not hard-code production-looking metrics.
9. Keep frontend/backend contracts typed.
10. Keep changes modular.

---

# IMPLEMENTATION STYLE

Prefer:

- reusable components
- clear naming
- typed data models
- modular architecture
- testable services
- clean separation of UI/business/data layers

Avoid unnecessary abstraction.

Avoid overengineering.

Implement the simplest architecture that satisfies the requirements.

---

# VERIFICATION

After implementing a feature:

1. Build the project.
2. Run relevant tests.
3. Check for type errors.
4. Check navigation.
5. Check loading/error/empty states.
6. Check visual consistency.
7. Check that data flows correctly.
8. Fix discovered issues before moving forward.

Never declare a feature complete merely because the code compiles.

---

# DESIGN QUALITY GATE

Before declaring the UI complete, verify:

- Does it resemble the reference design?
- Is spacing consistent?
- Are cards consistent?
- Is typography consistent?
- Is blue used as the primary accent?
- Is information hierarchy clear?
- Is unnecessary content removed?
- Are risk states understandable?
- Can the user reach packet evidence quickly?
- Does the UI look like a real security product rather than a hackathon mockup?

---

# PERFORMANCE

Prioritize:

- fast screen rendering
- efficient WebSocket updates
- incremental packet updates
- avoiding unnecessary recompositions/renders
- lightweight charts
- efficient list rendering
- minimal network payloads

Do not rebuild entire screens for every packet.

---

# IMPORTANT

Do not stop after creating a basic prototype.

Implement the requested feature completely within the current scope.

If something is impossible because of a platform/API limitation:

1. identify the limitation
2. implement the closest valid architecture
3. clearly isolate the limitation
4. continue with the rest of the implementation

Do not fake functionality.

Do not fabricate model accuracy.

Do not fabricate backend results.

Do not fabricate integrations.

# AUTONOMOUS ERROR RECOVERY

Do not stop the implementation for ordinary errors.

When an error occurs:

1. Read the complete error.
2. Identify the root cause.
3. Inspect the relevant source/configuration.
4. Apply the smallest correct fix.
5. Run the failed command again.
6. If it fails, inspect the NEW error rather than repeating the same fix.
7. Try up to 3 technically different fixes when reasonable.
8. If still blocked, isolate the failing component and continue with independent work.
9. Record the blocker in docs/BLOCKERS.md.
10. Continue all work that does not depend on the blocker.

Never ask the user to copy/paste an error that is already visible in the terminal.

Never ask the user to provide screenshots of ordinary build errors if the terminal output is accessible.

Never repeatedly retry the same command without changing the underlying cause.

Never rewrite the entire project because of a localized error.

Never modify unrelated working components to solve a localized problem.

When a dependency is unavailable:

- identify it
- determine whether an alternative exists
- use the simplest compatible alternative
- document the decision

When cloud credentials/GPU access are unavailable:

- prepare the complete cloud training package
- create reproducible commands/notebooks
- continue all non-training work
- record the exact external action required

When a model download is too large or slow:

- do not repeatedly retry
- create the model adapter
- verify the interface using a lightweight fixture
- continue other work

Maintain:

docs/BLOCKERS.md

with:

- blocker
- cause
- attempted fixes
- current status
- required external action

Do not fabricate a successful result.

# RELATIONSHIP TO OTHER SECTIONS

These rules govern how an error is handled. They do not lower any quality standard.

VERIFICATION step 8 ("fix discovered issues before moving forward") governs every issue that can be fixed. The escalate-and-continue path above applies only after three technically different fixes have failed.

A platform/API limitation follows IMPORTANT: identify it, implement the closest valid architecture, isolate it, continue. Record it in docs/BLOCKERS.md as a permanent limitation rather than as an open blocker.

Continuing past a blocker never permits fabricating functionality, model accuracy, backend results or integrations. An unfinished component is reported as unfinished.
