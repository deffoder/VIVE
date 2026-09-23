"""Golden vectors for the on-device risk engine, produced by the backend code.

The phone runs a Kotlin port of backend/app/risk/{fusion,temporal,policy}.py.
A port that drifts - one constant, one comparison, one rounding rule - scores
the same call differently on the phone than on the server, and nothing would
notice. This script runs the REAL backend functions over seeded random inputs
that cover every quality, status, intent and behaviour, and writes the inputs
with the backend's outputs. The Kotlin JVM test (RiskParityTest) must
reproduce every one.

Usage (backend venv):
    python scripts/mobile/make_risk_golden.py
"""

from __future__ import annotations

import io
import json
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.adapters.interfaces import (AntiSpoofResult, AsrResult,  # noqa: E402
                                     BehaviorResult, IntentResult,
                                     SpeakerResult, VadResult)
from app.risk import policy  # noqa: E402
from app.risk.fusion import FusionInput, fuse  # noqa: E402
from app.risk.sensitive import detect_in_context  # noqa: E402
from app.risk.temporal import TemporalState  # noqa: E402
from app.schemas.models import (AdapterMode, AnalyzerStatus,  # noqa: E402
                                AudioQuality, Behavior, Intent,
                                PolicyEvaluateRequest, RiskLevel)

OUT = os.path.join(ROOT, "android", "app", "src", "test", "resources", "risk_golden.json")
M = AdapterMode.REAL
V = "v"


def pick_status(rng, common=0.7):
    return (AnalyzerStatus.AVAILABLE if rng.random() < common
            else rng.choice(list(AnalyzerStatus)))


def fusion_case(rng):
    q = rng.choice(list(AudioQuality))
    synthetic = None if rng.random() < 0.35 else round(rng.random(), 4)
    sp_status = rng.choice([AnalyzerStatus.AVAILABLE, AnalyzerStatus.NO_REFERENCE,
                            AnalyzerStatus.INSUFFICIENT_AUDIO, AnalyzerStatus.LOAD_ERROR])
    sim = round(rng.uniform(-0.2, 1.0), 4) if sp_status == AnalyzerStatus.AVAILABLE else None
    asr_status = pick_status(rng)
    asr_conf = None if rng.random() < 0.2 else round(rng.random(), 4)
    it_status = pick_status(rng)
    intent = rng.choice(list(Intent))
    bh_status = pick_status(rng)
    behaviors = rng.sample(list(Behavior), rng.randint(0, 3))
    cv, sa = rng.random() < 0.3, rng.random() < 0.5
    rule = None if rng.random() < 0.6 else rng.choice(list(Intent))
    out = fuse(FusionInput(
        vad=VadResult(status=AnalyzerStatus.AVAILABLE, model_version=V, mode=M, quality=q),
        antispoof=AntiSpoofResult(status=AnalyzerStatus.AVAILABLE if synthetic is not None
                                  else AnalyzerStatus.UNAVAILABLE,
                                  model_version=V, mode=M, score=synthetic),
        speaker=SpeakerResult(status=sp_status, model_version=V, mode=M, similarity=sim),
        asr=AsrResult(status=asr_status, model_version=V, mode=M, confidence=asr_conf),
        intent=IntentResult(status=it_status, model_version=V, mode=M, label=intent),
        behavior=BehaviorResult(status=bh_status, model_version=V, mode=M, labels=behaviors),
        caller_verified=cv, session_authenticated=sa, sensitive_request=rule))
    return {
        "in": {"quality": q.value, "synthetic": synthetic, "speaker_status": sp_status.value,
               "speaker_similarity": sim, "asr_status": asr_status.value,
               "asr_confidence": asr_conf, "intent_status": it_status.value,
               "intent": intent.value, "behavior_status": bh_status.value,
               "behaviors": [b.value for b in behaviors], "caller_verified": cv,
               "session_authenticated": sa,
               "sensitive_request": rule.value if rule else None},
        "out": {"score": out.risk.score, "level": out.risk.level.value,
                "confidence": out.risk.confidence, "contributions": out.risk.contributions,
                "reasons": out.risk.reasons, "ood": out.ood_state.value,
                "uncertainty": out.uncertainty, "context_risk": out.context_risk},
    }


def temporal_case(rng):
    shape = rng.choice(["random", "spike", "periodic", "burst"])
    n = rng.randint(3, 30)
    if shape == "random":
        scores = [rng.randint(0, 100) for _ in range(n)]
    elif shape == "spike":
        scores = [rng.randint(0, 30) for _ in range(n)]
        scores[rng.randrange(n)] = rng.randint(80, 100)
    elif shape == "periodic":
        scores = [rng.randint(70, 95) if i % 3 == 0 else rng.randint(5, 30) for i in range(n)]
    else:
        k = rng.randrange(n)
        scores = [rng.randint(70, 100) if k <= i < k + 4 else rng.randint(0, 25) for i in range(n)]
    state = TemporalState()
    steps = []
    for i, s in enumerate(scores):
        conf = round(rng.random(), 4)
        cur, ov = state.update(s, conf, i + 2)
        t = state.timings
        steps.append({"score": s, "confidence": conf, "at": i + 2,
                      "current_level": cur.level.value, "overall_score": ov.score,
                      "overall_level": ov.level.value,
                      "timings": [t.first_anomaly_sec, t.first_warning_sec,
                                  t.first_high_sec, t.first_critical_sec]})
    return {"shape": shape, "steps": steps}


def policy_case(rng):
    score = rng.randint(0, 100)
    level = None if rng.random() < 0.3 else rng.choice(list(RiskLevel))
    conf = round(rng.random(), 4)
    intent = None if rng.random() < 0.2 else rng.choice(list(Intent))
    cv = rng.random() < 0.4
    r = policy.evaluate(PolicyEvaluateRequest(risk_score=score, risk_level=level,
                                              confidence=conf, intent=intent,
                                              caller_verified=cv))
    return {"in": {"score": score, "level": level.value if level else None,
                   "confidence": conf, "intent": intent.value if intent else None,
                   "caller_verified": cv},
            "out": {"action": r.recommended_action.value, "alert": r.should_alert,
                    "reasons": r.reasons}}


SENSITIVE_TEXTS = [
    "please tell me the OTP right now", "your OTP is 482913. Do not share it",
    "अभी आपके फोन पर एक ओटीपी आया होगा", "कृप्या वह ओटीपी तुरंत बताइए",
    "உங்கள் OTP எண்ணை உடனே சொல்லுங்கள்", "install anydesk and give me the code",
    "stop the car", "send money now", "what is your atm pin tell me",
    "मुझे अपना पासवर्ड बताइए", "CVV number bata do", "never share your pin",
    "OTP", "tell", "", "the otp", "hello how are you",
    "नमस्ते कैसे हैं आप", "transfer karo abhi", "कार्ड नंबर दीजिए",
    "अपना पासपर्ड", "अपना पासपर्ट बताए", "please tell me your pasword",
    "give me min now", "why spend money tell", "passwords tell",
]


def sensitive_cases(rng):
    cases = []
    for _ in range(600):
        prev = rng.choice(SENSITIVE_TEXTS + [None])
        cur = rng.choice(SENSITIVE_TEXTS + [None])
        d = detect_in_context(cur, prev)
        cases.append({"previous": prev, "current": cur, "label": d.label if d else None})
    return cases


def main() -> int:
    rng = random.Random(20260923)
    data = {
            "sensitive": sensitive_cases(rng),"fusion": [fusion_case(rng) for _ in range(1500)],
            "temporal": [temporal_case(rng) for _ in range(300)],
            "policy": [policy_case(rng) for _ in range(800)]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {os.path.relpath(OUT, ROOT)}: "
          + ", ".join(f"{k} {len(v)}" for k, v in data.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
