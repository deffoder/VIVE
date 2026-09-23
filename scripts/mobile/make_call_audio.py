"""Synthesises scripted test calls for device acceptance.

There is no labelled call audio (docs/BLOCKERS.md O15), and acceptance needs a
caller speaking Hindi, Tamil and English into the phone's microphone. These
scripts are fictional, written for this test, and spoken by Microsoft Edge
neural TTS (edge-tts). The laptop plays them through its loudspeaker while
the phone listens - the laptop is only the "caller's mouth"; it runs none of
VIVE's analysis.

This is SYNTHETIC speech. It is fit for exercising the pipeline - ASR, text
heads, risk, alerts - and must never be used as evidence about anti-spoofing
on genuine speech (it is the opposite class).

Each call opens with benign small talk and then escalates, so risk should
start low and rise; the timing of that rise is part of what acceptance checks.

Output (git-ignored): models/artifacts/mobile/calls/<lang>_call.wav, 16 kHz mono
plus calls.json with each segment's text and offset.

Usage:
    python scripts/mobile/make_call_audio.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "models", "artifacts", "mobile", "calls")
SR = 16_000
GAP = 1.2

CALLS = {
    "hi": ("hi-IN-MadhurNeural", [
        ("benign", "नमस्ते, कैसे हैं आप? मैं आपसे कल शाम की मीटिंग के बारे में बात करना चाहता था।"),
        ("benign", "हम लोग सात बजे मिल सकते हैं, अगर आपको ठीक लगे।"),
        ("scam", "सुनिए, मैं आपके बैंक से बोल रहा हूँ। आपका खाता आज बंद होने वाला है।"),
        ("scam", "अभी आपके फ़ोन पर एक OTP आया होगा, कृपया वह OTP तुरंत बताइए।"),
        ("scam", "जल्दी कीजिए, वरना आपका पैसा चला जाएगा। किसी को यह बात मत बताइए।"),
    ]),
    "en": ("en-IN-PrabhatNeural", [
        ("benign", "Hi, how are you doing? I wanted to check about dinner tomorrow evening."),
        ("benign", "We could meet around seven if that works for you."),
        ("scam", "Listen, I am calling from your bank's security department. Your account will be blocked today."),
        ("scam", "You just received a one time password on your phone. Please tell me the OTP right now."),
        ("scam", "Do it quickly or you will lose your money. Do not tell anyone about this call."),
    ]),
    "ta": ("ta-IN-ValluvarNeural", [
        ("benign", "வணக்கம், எப்படி இருக்கீங்க? நாளைக்கு மாலை சந்திப்பு பற்றி பேசலாம்."),
        ("scam", "நான் உங்கள் வங்கியிலிருந்து பேசுகிறேன். உங்கள் கணக்கு இன்று முடக்கப்படும்."),
        ("scam", "உங்கள் மொபைலுக்கு வந்த OTP எண்ணை உடனே சொல்லுங்கள்."),
    ]),
}

# A short direct request per language, built from common words ("password",
# "ATM PIN") rather than "OTP", which neither the Hindi nor the English phone
# ASR renders reliably through a loudspeaker (measured: "ओटी भी", "ME GOOD ME").
# Only the caller's words differ; no rule or model was changed for them.
DIRECT = {
    "hi": ("hi-IN-MadhurNeural", [
        ("scam", "मैं आपके बैंक से बोल रहा हूँ।"),
        ("scam", "अपना पासवर्ड बताइए।"),
        ("scam", "अपना एटीएम पिन अभी बताइए।"),
    ]),
    "en": ("en-IN-PrabhatNeural", [
        ("scam", "This is your bank calling."),
        ("scam", "Tell me your password."),
        ("scam", "Tell me your ATM pin now."),
    ]),
    "ta": ("ta-IN-ValluvarNeural", [
        ("scam", "நான் உங்கள் வங்கியிலிருந்து பேசுகிறேன்."),
        ("scam", "உங்கள் கடவுச்சொல் சொல்லுங்கள்."),
    ]),
}


async def speak(voice: str, text: str) -> np.ndarray:
    import edge_tts
    import soundfile as sf

    audio = b""
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    # edge-tts returns MP3 (24 kHz); libsndfile decodes it, then polyphase
    # resampling to VIVE's 16 kHz.
    from math import gcd

    from scipy.signal import resample_poly
    wave, rate = sf.read(io.BytesIO(audio), dtype="float32")
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    g = gcd(SR, rate)
    wave = resample_poly(wave, SR // g, rate // g)
    return wave.astype("float32")


async def main_async() -> int:
    import soundfile as sf

    os.makedirs(OUT, exist_ok=True)
    meta = {"note": "Synthetic TTS speech (edge-tts). Fictional scripts written for this test.",
            "calls": {}}
    jobs = [(f"{lang}_call", v) for lang, v in CALLS.items()] +            [(f"{lang}_direct", v) for lang, v in DIRECT.items()]
    for name, (voice, lines) in jobs:
        parts, segments, t = [], [], 0.0
        for kind, text in lines:
            wave = await speak(voice, text)
            wave = 0.7 * wave / max(1e-6, float(np.abs(wave).max()))
            segments.append({"kind": kind, "text": text, "start_sec": round(t, 2),
                             "end_sec": round(t + len(wave) / SR, 2)})
            parts += [wave, np.zeros(int(GAP * SR), dtype="float32")]
            t += len(wave) / SR + GAP
        full = np.concatenate([np.zeros(int(1.0 * SR), dtype="float32")] + parts)
        for s in segments:
            s["start_sec"] += 1.0
            s["end_sec"] += 1.0
        sf.write(os.path.join(OUT, f"{name}.wav"), full, SR, subtype="PCM_16")
        meta["calls"][name] = {"voice": voice, "seconds": round(len(full) / SR, 1), "segments": segments}
        print(name, meta["calls"][name]["seconds"], "s")
    with io.open(os.path.join(OUT, "calls.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
