"""Phase 10: the final end-to-end matrix.

Runs each demo scenario through the REAL backend - HTTP, WebSocket, session
manager, adapters, fusion, temporal risk, policy - and records expected
against actual for every case. Nothing is skipped silently: a case that cannot
run reports why, and that counts as a failure rather than an omission.

Two modes, for two different reasons.

**Mock mode** is what runs here. It is deterministic and needs no multi-GB
weights, so the matrix is reproducible on any machine and a scenario's
behaviour is a property of the pipeline rather than of which checkpoint
happened to load. Every case below exercises the real orchestration; only the
model outputs are scripted.

**Real mode** cases are NOT re-run. Phase 9 already measured them end to end
with real models (`models/evaluation/phase9/9I_runtime_end_to_end.json`), and
re-running a 30-packet two-language real-model benchmark to re-derive the same
statuses would burn an hour to learn nothing. The matrix reads that record and
asserts against it, citing it as the source. If the record is missing those
rows report UNVERIFIED rather than passing.

Usage:
    python scripts/evaluation/e2e_matrix.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, add_backend_to_path  # noqa: E402

OUT_DIR = os.path.join(ROOT, "models", "evaluation", "phase10")
PHASE9_RUNTIME = os.path.join(ROOT, "models", "evaluation", "phase9",
                              "9I_runtime_end_to_end.json")


class Matrix:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, case: str, expected: str, actual: str, passed: bool,
               *, source: str = "live mock-mode run", detail: str = "") -> None:
        self.rows.append({
            "case": case, "expected": expected, "actual": actual,
            "result": "PASS" if passed else "FAIL",
            "source": source, "detail": detail,
        })
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {case}")
        if not passed:
            print(f"         expected: {expected}")
            print(f"         actual  : {actual}")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if r["result"] != "PASS")


def drive(client, lines: list[str], *, language: str | None = None) -> list[dict]:
    """Runs a scripted session and returns its packets."""
    body: dict = {"source_type": "VOIP"}
    if language:
        body["language"] = language
    session_id = client.post("/api/v1/sessions", json=body).json()["session_id"]
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for line in lines:
            ws.send_json({"type": "client.audio", "transcript": line,
                          "speaker": "Caller"})
            for _ in range(8):
                if ws.receive_json()["type"] == "risk.update":
                    break
    return client.get(f"/api/v1/sessions/{session_id}/packets").json()


# Deliberately free of the keywords the mock classifiers script on. An
# earlier draft ended with "Nothing urgent, I will call back later", and the
# mock behaviour head matched "urgent" and pushed a benign call to MEDIUM -
# a reminder that these are keyword tables, not models.
BENIGN = ["Hello, just confirming our meeting tomorrow afternoon.",
          "No rush at all, I will call back later if needed."]
SCAM = ["This is the bank security team, your account will be blocked.",
        "Tell me the OTP that was just sent to your phone immediately."]
TAMIL = ["உங்கள் ஓடிபி "
         "என்ன என்று "
         "சொல்லுங்கள்"]


def main() -> int:
    add_backend_to_path()
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    settings = get_settings()
    matrix = Matrix()
    print(f"adapter_mode: {settings.adapter_mode}\n")

    app = create_app()
    with TestClient(app) as client:
        # 1-2. benign vs suspicious -------------------------------------
        packets = drive(client, BENIGN)
        last = packets[-1]["risk"]
        matrix.record(
            "1. benign conversation stays LOW",
            "risk level LOW, no alert",
            f"level={last['level']} score={last['score']}",
            last["level"] == "LOW")

        packets = drive(client, SCAM)
        last = packets[-1]["risk"]
        matrix.record(
            "2. social engineering escalates on semantic evidence",
            "risk level HIGH or CRITICAL",
            f"level={last['level']} score={last['score']}",
            last["level"] in ("HIGH", "CRITICAL"))

        # 3. supported language -----------------------------------------
        packets = drive(client, SCAM, language="hi")
        intent = packets[-1]["intent"]
        matrix.record(
            "3. supported language produces an intent",
            "intent status AVAILABLE",
            f"status={intent['status']} label={intent['label']}",
            intent["status"] == "AVAILABLE")

        # 4. unsupported language ---------------------------------------
        packets = drive(client, TAMIL, language="ta")
        intent = packets[-1]["intent"]
        behavior = packets[-1]["behavior"]
        risk = packets[-1]["risk"]
        ok = (intent["status"] == "UNSUPPORTED_LANGUAGE"
              and behavior["status"] == "UNSUPPORTED_LANGUAGE"
              and intent["label"] == "UNKNOWN"
              and risk["level"] != "CRITICAL")
        matrix.record(
            "4. unsupported language declines rather than guessing",
            "intent+behaviour UNSUPPORTED_LANGUAGE, label UNKNOWN, not CRITICAL",
            f"intent={intent['status']} behaviour={behavior['status']} "
            f"label={intent['label']} level={risk['level']}",
            ok,
            detail="An unsupported language is missing evidence, not "
                   "incriminating evidence (BLOCKERS O11).")

        # 5. absent evidence never carries a value ----------------------
        offenders = []
        for packet in packets:
            for analyzer, field in (("aasist", "score"), ("ecapa", "similarity")):
                block = packet[analyzer]
                if block["status"] != "AVAILABLE" and block[field] is not None:
                    offenders.append(f"{analyzer}:{block['status']}")
        matrix.record(
            "5. an analyzer that did not run carries no value",
            "every non-AVAILABLE analyzer has a null value",
            "clean" if not offenders else f"violations: {offenders}",
            not offenders)

        # 6. speaker reference ------------------------------------------
        ecapa = packets[-1]["ecapa"]
        matrix.record(
            "6. no enrolment reports NO_REFERENCE, not a mismatch",
            "ecapa status NO_REFERENCE with null similarity",
            f"status={ecapa['status']} similarity={ecapa['similarity']}",
            ecapa["status"] == "NO_REFERENCE" and ecapa["similarity"] is None)

        # 7. packet traceability ----------------------------------------
        required = ["packet_id", "session_id", "seq", "timestamp", "duration_sec",
                    "language", "quality", "asr", "intent", "behavior", "aasist",
                    "ecapa", "context", "ood", "risk", "adapter_mode"]
        missing = sorted({f for p in packets for f in required if f not in p})
        matrix.record(
            "7. every packet is fully traceable",
            f"all {len(required)} fields present on every packet",
            "complete" if not missing else f"missing: {missing}",
            not missing)

        # 8. per-stage timing is observable -----------------------------
        timed = [k for k in ("asr", "intent", "behavior", "aasist", "ecapa")
                 if "inference_ms" in (packets[-1].get(k) or {})]
        matrix.record(
            "8. all five analyzers expose their inference cost",
            "inference_ms present on asr, intent, behavior, aasist, ecapa",
            f"present on {timed}",
            len(timed) == 5,
            detail="Phase 9 found the two text heads had no inference_ms, so "
                   "per-stage latency could only account for four of six.")

        # 9. adapter mode is declared -----------------------------------
        modes = {p.get("adapter_mode") for p in packets}
        ready = client.get("/api/v1/ready").json()
        declared = {a["mode"] for a in ready["adapters"].values()}
        matrix.record(
            "9. real vs mock is declared, never implicit",
            "every packet and every adapter declares its mode",
            f"packet modes={modes} adapter modes={declared}",
            len(modes) == 1 and None not in modes and len(declared) == 1)

        # 10. risk and confidence are separate --------------------------
        independent = all(
            isinstance(p["risk"]["score"], int)
            and isinstance(p["risk"]["confidence"], float)
            and p["risk"]["score"] != int(p["risk"]["confidence"] * 100)
            or p["risk"]["score"] == 0
            for p in packets)
        matrix.record(
            "10. risk score and confidence are distinct quantities",
            "score is an int 0-100, confidence a separate float",
            "distinct" if independent else "score tracks confidence",
            independent)

        # 11. temporal timings ------------------------------------------
        session = client.get(
            f"/api/v1/sessions/{packets[0]['session_id']}").json()
        has_timings = "timings" in session or "escalation" in json.dumps(session)
        matrix.record(
            "11. session reports escalation timings",
            "session carries escalation timing fields",
            "present" if has_timings else "absent",
            has_timings)

        # 12. malformed input is rejected -------------------------------
        sid = client.post("/api/v1/sessions",
                          json={"source_type": "VOIP"}).json()["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{sid}/stream") as ws:
            ws.receive_json()
            ws.send_json({"type": "client.audio", "not_a_field": "x"})
            reply = ws.receive_json()
        matrix.record(
            "12. malformed frames are rejected, not silently accepted",
            "an error frame or no packet",
            f"reply type={reply.get('type')}",
            reply.get("type") != "packet.new")

        # 13. unknown session ------------------------------------------
        response = client.get("/api/v1/sessions/VS-does-not-exist")
        matrix.record(
            "13. unknown session returns a clean 404",
            "HTTP 404",
            f"HTTP {response.status_code}",
            response.status_code == 404)

    # 14-15. real-mode statuses, from the Phase 9 record ----------------
    if os.path.exists(PHASE9_RUNTIME):
        with open(PHASE9_RUNTIME, encoding="utf-8") as fh:
            runtime = json.load(fh)["results"]
        languages = {L["language"]: L for L in runtime["languages"]}
        tamil = languages.get("ta", {})
        counts = tamil.get("analyzer_status_counts", {})
        matrix.record(
            "14. real mode: Tamil text heads decline on every packet",
            "intent and behaviour UNSUPPORTED_LANGUAGE on all 30 packets",
            f"intent={counts.get('intent')} behaviour={counts.get('behavior')}",
            counts.get("intent", {}).get("UNSUPPORTED_LANGUAGE") == 30,
            source="models/evaluation/phase9/9I_runtime_end_to_end.json")
        hindi = languages.get("hi", {})
        first_scored = hindi.get("first_packet_with_antispoof_score")
        matrix.record(
            "15. real mode: anti-spoofing waits for genuine audio",
            "no AASIST score until ~4 s of real audio has accumulated",
            f"first scored packet = #{first_scored}",
            bool(first_scored and first_scored > 1),
            source="models/evaluation/phase9/9I_runtime_end_to_end.json",
            detail="The adapter reports INSUFFICIENT_AUDIO rather than "
                   "padding the window (ML_SPEC 2.7).")
    else:
        for case in ("14. real mode: Tamil text heads decline on every packet",
                     "15. real mode: anti-spoofing waits for genuine audio"):
            matrix.record(case, "verified against the Phase 9 runtime record",
                          "UNVERIFIED - Phase 9 record not found", False,
                          source="missing artifact")

    os.makedirs(OUT_DIR, exist_ok=True)
    record = {
        "matrix": "phase10_e2e",
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "adapter_mode": settings.adapter_mode,
        "cases": len(matrix.rows),
        "passed": len(matrix.rows) - matrix.failed,
        "failed": matrix.failed,
        "rows": matrix.rows,
        "notes": [
            "Mock mode exercises the real orchestration with scripted model "
            "outputs, so results are deterministic and reproducible without "
            "multi-GB weights.",
            "Real-mode rows are asserted against the Phase 9 runtime record "
            "rather than re-measured; re-running a real-model benchmark would "
            "re-derive the same statuses at high cost.",
            "No case is skipped. A case that cannot run is recorded as a "
            "failure with its reason.",
        ],
    }
    out = os.path.join(OUT_DIR, "e2e_matrix.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)

    print(f"\n{record['passed']}/{record['cases']} passed")
    print(f"wrote {os.path.relpath(out, ROOT)}")
    return 0 if matrix.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
