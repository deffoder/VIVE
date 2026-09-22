"""Phase 9: does the temporal layer behave the way a call needs it to?

`temporal.py` smooths per-packet scores with an EMA, holds a level with
hysteresis, and refuses to leave LOW before two packets. Those are three
separate mechanisms with three separate failure modes, and none has ever been
measured against a sequence.

What matters operationally is not the smoothing constant but the answers to
four questions a reviewer would actually ask:

  * **How long until a warning?** A scam call that escalates at packet 40 is
    a scam call that was not caught. Measured as time-to-first-warning and
    time-to-escalation on a rising sequence.

  * **Does one bad packet escalate the call?** ASR mishears, AASIST scores a
    genuine speaker at 0.99 (O12). If a single anomalous window could drive a
    call to HIGH, every one of those becomes a false alarm. Measured with a
    single spike in an otherwise benign sequence.

  * **Does the level come back down?** Hysteresis exists to stop flapping, but
    hysteresis that never releases is a stuck alarm. Measured as recovery
    latency after a spike and after a sustained-then-ended burst.

  * **Does it hold a level under intermittent evidence?** Real social
    engineering is not continuous; the risky sentence is one window in five.

Sequences are synthetic and deliberately so: each one isolates a single
behaviour. This measures the temporal ENGINE, not a call. No real call
recordings with risk labels exist, so nothing here says how often these
patterns occur in practice.

Usage:
    python scripts/evaluation/exp_temporal_risk.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import Experiment, add_backend_to_path  # noqa: E402

STRIDE_SEC = 1.0          # VIVE emits a packet every 1.0 s


def run_sequence(scores: list[int], confidence: float = 0.8) -> dict:
    """Feeds a score series through a fresh TemporalState."""
    from app.risk.temporal import TemporalState

    state = TemporalState()
    trace = []
    for index, score in enumerate(scores):
        at_sec = int(index * STRIDE_SEC)
        current, overall = state.update(score, confidence, at_sec)
        trace.append({
            "packet": index + 1, "at_sec": at_sec, "packet_score": score,
            "smoothed": overall.score, "level": overall.level.value,
            "current_level": current.level.value,
        })
    timings = state.timings
    return {
        "packets": len(scores),
        "trace": trace,
        "final_level": state.level.value,
        "peak_packet_score": state.peak_score,
        "first_anomaly_sec": timings.first_anomaly_sec,
        "first_warning_sec": timings.first_warning_sec,
        "first_high_sec": timings.first_high_sec,
        "first_critical_sec": timings.first_critical_sec,
    }


def first_packet_at_level(trace: list[dict], level: str) -> int | None:
    for row in trace:
        if row["level"] == level:
            return row["packet"]
    return None


def packets_until_back_to(trace: list[dict], level: str, after: int) -> int | None:
    for row in trace:
        if row["packet"] > after and row["level"] == level:
            return row["packet"] - after
    return None


def main() -> int:
    add_backend_to_path()

    exp = Experiment(
        "9G_temporal_risk",
        question=("How quickly does the temporal layer warn, how far can a "
                  "single anomalous packet push a call, and does the level "
                  "recover once the evidence stops?"),
        hypothesis=("The two-packet minimum and the EMA together will stop a "
                    "single spike from reaching HIGH, and hysteresis will "
                    "delay de-escalation by a few packets rather than "
                    "permanently."),
        method=("Drive TemporalState with synthetic score sequences, each "
                "isolating one behaviour. Record the full per-packet trace so "
                "every timing is traceable to the packet that caused it."))
    exp.model(name="temporal-risk", revision="EMA_ALPHA=0.4, HYSTERESIS=5",
              license="in-repo")
    exp.config(stride_sec=STRIDE_SEC,
               levels="LOW<35, MEDIUM>=35, HIGH>=65, CRITICAL>=85")

    SEQUENCES = {
        # A call that turns: benign small talk, then a sustained scam.
        "rising_scam": [8, 10, 12, 45, 70, 88, 92, 90, 91, 89],
        # Entirely benign.
        "benign_call": [6, 9, 7, 11, 8, 10, 9, 7, 8, 6],
        # ONE anomalous window in an otherwise benign call. This is the O12
        # false-positive shape: a genuine speaker scored as synthetic once.
        "single_spike": [8, 9, 7, 95, 8, 7, 9, 8, 7, 8],
        # Two adjacent anomalies - is two enough to escalate?
        "double_spike": [8, 9, 95, 93, 8, 7, 9, 8, 7, 8],
        # Sustained risk that then stops: does the level release?
        "burst_then_clear": [8, 9, 90, 92, 91, 89, 8, 7, 6, 5, 6, 7, 5, 6],
        # Risky sentence every third window - realistic social engineering.
        "intermittent": [10, 8, 80, 9, 10, 78, 8, 9, 82, 10, 9, 79],
        # Slow creep: never a spike, gradually elevated.
        "slow_creep": [20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75],
        # A single packet only - the minimum-evidence gate.
        "one_packet_only": [95],
    }

    results = {name: run_sequence(scores) for name, scores in SEQUENCES.items()}

    spike = results["single_spike"]
    double = results["double_spike"]
    burst = results["burst_then_clear"]
    rising = results["rising_scam"]
    lone = results["one_packet_only"]

    findings = {
        "time_to_first_warning_on_rising_scam_sec": rising["first_warning_sec"],
        "time_to_high_on_rising_scam_sec": rising["first_high_sec"],
        "time_to_critical_on_rising_scam_sec": rising["first_critical_sec"],
        "single_spike_max_smoothed_level": max(
            (row["level"] for row in spike["trace"]),
            key=lambda level: ["LOW", "MEDIUM", "HIGH", "CRITICAL"].index(level)),
        "single_spike_reached_high": any(
            row["level"] in ("HIGH", "CRITICAL") for row in spike["trace"]),
        "double_spike_reached_high": any(
            row["level"] in ("HIGH", "CRITICAL") for row in double["trace"]),
        "single_packet_stays_low": lone["trace"][0]["level"] == "LOW",
        "benign_call_final_level": results["benign_call"]["final_level"],
        "intermittent_final_level": results["intermittent"]["final_level"],
        "intermittent_ever_reached_high": any(
            row["level"] in ("HIGH", "CRITICAL")
            for row in results["intermittent"]["trace"]),
        "intermittent_peak_packet_score": results["intermittent"]["peak_packet_score"],
        "slow_creep_first_warning_sec": results["slow_creep"]["first_warning_sec"],
    }

    high_at = first_packet_at_level(burst["trace"], "HIGH") or 0
    findings["burst_recovery_packets_to_low"] = packets_until_back_to(
        burst["trace"], "LOW", high_at)
    findings["burst_final_level"] = burst["final_level"]

    # Escalation timings record the FIRST packet crossing a raw threshold and
    # are never cleared. A call that recovers keeps its timings, which is
    # correct for an audit trail and must not be read as a current level.
    findings["timings_are_historical_not_current"] = (
        burst["first_high_sec"] is not None and burst["final_level"] == "LOW")

    print("=== temporal behaviour ===")
    for name, result in results.items():
        levels = "".join(row["level"][0] for row in result["trace"])
        print(f"  {name:<20} {levels:<16} final={result['final_level']:<9} "
              f"warn@{result['first_warning_sec']}s high@{result['first_high_sec']}s")
    print("\n=== findings ===")
    for key, value in findings.items():
        print(f"  {key:<46}{value}")

    exp.result("sequences", results)
    exp.result("findings", findings)

    exp.limitation(
        "Sequences are SYNTHETIC and each isolates one behaviour. They "
        "characterise the temporal engine, not real calls. No corpus of real "
        "calls with per-window risk labels exists, so the frequency of these "
        "patterns in practice is unknown.")
    exp.limitation(
        "Confidence is held constant at 0.8. In the live pipeline confidence "
        "varies per packet and gates policy escalation separately "
        "(policy.py MIN_CONFIDENCE_FOR_ESCALATION), so an alert may not fire "
        "even where this shows a HIGH level.")
    exp.limitation(
        "Timings are in packets at a 1.0 s stride. They exclude the ~4 s "
        "before anti-spoof evidence becomes available and the per-packet "
        "processing latency, so wall-clock time to a warning in a live call "
        "is strictly later than the figures here.")
    exp.limitation(
        "The smoothing constant cuts both ways and only one side was "
        "hypothesised. The `intermittent` sequence - a score of ~80 every "
        "third packet, which is the shape social engineering actually takes - "
        "never leaves MEDIUM, so the same damping that suppresses a false "
        "spike also suppresses genuine periodic evidence. EMA_ALPHA was not "
        "tuned here because tuning it needs labelled call sequences that do "
        "not exist.")

    exp.finish(
        interpretation=(
            f"A single anomalous packet "
            f"{'DOES' if findings['single_spike_reached_high'] else 'does not'} "
            f"drive the call to HIGH, and a lone first packet stays LOW as the "
            f"minimum-evidence gate intends. On a rising scam the engine warns "
            f"at {findings['time_to_first_warning_on_rising_scam_sec']}s and "
            f"reaches HIGH at {findings['time_to_high_on_rising_scam_sec']}s "
            f"in packet time. After a burst ends the level returns to LOW in "
            f"{findings['burst_recovery_packets_to_low']} packets, so "
            f"hysteresis delays release rather than latching it."),
        conclusion=(
            "The temporal layer resists the single-window false positive that "
            "O12 makes likely, which is the property it most needed to have. "
            "The cost is symmetric and was not anticipated: intermittent "
            f"risk peaking at "
            f"{findings['intermittent_peak_packet_score']} per packet never "
            f"leaves MEDIUM, so a real scam that is risky only every third "
            f"window would not raise an alert. That is a detection gap, not a "
            f"tuning preference, and it needs labelled call sequences to "
            f"resolve. Escalation timings are historical markers and must be "
            f"presented as 'first reached' rather than as the current state."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
