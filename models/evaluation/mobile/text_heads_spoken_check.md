# Text heads on spoken scam sentences (2026-09-24)

Fictional scripted calls (`scripts/mobile/make_call_audio.py`, edge-tts), each
sentence classified whole by the shipped ONNX heads, from the REFERENCE text
and from desktop ASR of the clean audio.

| lang | kind | reference text | ASR text |
|---|---|---|---|
| hi | benign x2 | NORMAL x2 | NORMAL x2 |
| hi | "bank ... account will be closed today" | NORMAL 1.00 | NORMAL 1.00 |
| hi | "an OTP has come to your phone, tell it now" | NORMAL 0.95 | NORMAL 0.94 |
| hi | "hurry or your money is gone, tell no one" | NORMAL 1.00 | NORMAL 1.00 |
| en | benign x2 | NORMAL x2 | NORMAL x2 |
| en | "calling from your bank's security department ..." | NORMAL 0.94, FEAR | NORMAL 0.96 |
| en | "tell me the OTP right now" | OTP_REQUEST 0.95 | NORMAL 0.83 |
| en | "do it quickly ... do not tell anyone" | NORMAL 0.53 | NORMAL 0.94 |

On the phone, through the microphone, every Hindi window of the same call was
NORMAL_CONVERSATION. The heads are faithful on the phone (120/120 agreement
with desktop); what fails is transfer from the SMS training corpus to spoken
social engineering (docs/BLOCKERS.md O18). Whole-sentence context does not fix
it, because the reference-text column already has whole sentences.
