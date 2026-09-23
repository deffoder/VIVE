"""Acceptance test for the live microphone path, on a physical device.

Drives the real app on a real phone against the real backend and collects
evidence for each step. It asserts on EVIDENCE, never on the absence of an
error: a step passes only when something observable proves it happened - a
session id in the backend, a packet count that grew, a window the backend
recorded receiving. A step that cannot be checked reports UNVERIFIED and the
run fails.

What it cannot do, and says so rather than pretending
-----------------------------------------------------
* **Unlock the phone.** If the screen is locked behind a PIN or fingerprint
  the run stops and asks for it to be unlocked. Unlocking is not something a
  test should work around.
* **Grant RECORD_AUDIO on some OEM builds.** `pm grant` is refused by several
  vendor ROMs (measured on a OnePlus CPH2661: `SecurityException: neither
  user 2000 nor current process has GRANT_RUNTIME_PERMISSIONS`). Where that
  happens the script taps the app's own permission dialog instead, which is
  the flow a user actually sees.
* **Speak.** Real speech has to come from a person or a speaker near the
  phone. The script reports how many windows were captured and sent; whether
  those windows contained speech is visible in the transcript it prints.

Usage:
    python scripts/verify_android_live.py
    python scripts/verify_android_live.py --seconds 20
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PACKAGE = "com.vive"
ACTIVITY = f"{PACKAGE}/.MainActivity"
BACKEND = "http://127.0.0.1:8000"
APK = os.path.join(ROOT, "android", "app", "build", "outputs", "apk",
                   "debug", "app-debug.apk")


def adb_path() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    candidate = os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe")
    return candidate if os.path.isfile(candidate) else "adb"


ADB = adb_path()


def adb(*args: str, timeout: int = 120) -> str:
    result = subprocess.run([ADB, *args], capture_output=True, text=True,
                            timeout=timeout)
    return (result.stdout or "") + (result.stderr or "")


def shell(*args: str, timeout: int = 120) -> str:
    return adb("shell", *args, timeout=timeout)


class Report:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def step(self, name: str, passed: bool, evidence: str) -> bool:
        self.steps.append({"step": name, "result": "PASS" if passed else "FAIL",
                           "evidence": evidence})
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {evidence}")
        return passed

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if s["result"] != "PASS")


def get_json(path: str):
    try:
        with urllib.request.urlopen(BACKEND + path, timeout=15) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def ui_dump() -> str:
    shell("uiautomator", "dump", "/sdcard/vive_ui.xml")
    return shell("cat", "/sdcard/vive_ui.xml")


def find_node(xml: str, text: str) -> tuple[int, int] | None:
    """Centre of the first node whose text contains `text`."""
    for match in re.finditer(
            r'text="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        if text.lower() in match.group(1).lower():
            x1, y1, x2, y2 = (int(match.group(i)) for i in range(2, 6))
            return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def tap_text(text: str, attempts: int = 3) -> bool:
    for _ in range(attempts):
        found = find_node(ui_dump(), text)
        if found:
            shell("input", "tap", str(found[0]), str(found[1]))
            time.sleep(2)
            return True
        time.sleep(2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=15,
                        help="how long to capture for")
    parser.add_argument("--play-wav", default="",
                        help="WAV played on THIS machine's speakers during "
                             "capture, so the phone hears it acoustically. "
                             "Without it the room is usually silent, and the "
                             "run then proves transport but not transcription.")
    args = parser.parse_args()
    report = Report()

    print("=== device ===")
    devices = adb("devices")
    online = [line.split()[0] for line in devices.splitlines()[1:]
              if line.strip().endswith("device")]
    if not report.step("a physical device is attached", bool(online),
                       devices.strip().replace("\n", " | ")):
        return 1
    serial = online[0]

    model = shell("getprop", "ro.product.model").strip()
    release = shell("getprop", "ro.build.version.release").strip()
    print(f"  {serial}  {model}  Android {release}\n")

    print("=== backend ===")
    version = get_json("/api/v1/version")
    report.step("backend is reachable", version is not None, str(version))
    if version is None:
        print("\n  Start it first:")
        print("    uvicorn app.main:app --host 0.0.0.0 --port 8000")
        return 1
    real = version.get("adapter_mode") == "real"
    report.step("backend is in REAL mode", real,
                f"adapter_mode={version.get('adapter_mode')}")

    ready = get_json("/api/v1/ready") or {}
    adapters = ready.get("adapters", {})
    loaded = {k: v.get("status") for k, v in adapters.items()}
    all_real = all(v.get("mode") == "real" for v in adapters.values())
    report.step("every adapter reports real mode", all_real and bool(adapters),
                json.dumps(loaded))

    print("\n=== screen ===")
    locked = "mDreamingLockscreen=true" in adb("shell", "dumpsys", "window")
    shell("input", "keyevent", "KEYCODE_WAKEUP")
    time.sleep(1)
    if locked:
        shell("input", "swipe", "540", "1800", "540", "700", "200")
        time.sleep(2)
        locked = "mDreamingLockscreen=true" in adb("shell", "dumpsys", "window")
    if not report.step("screen is unlocked", not locked,
                       "locked - unlock the phone and re-run" if locked
                       else "unlocked"):
        print("\n  The device is locked behind a PIN or fingerprint. A test "
              "must not work around that; unlock it and run this again.")
        return 1

    print("\n=== install ===")
    if not os.path.isfile(APK):
        report.step("APK exists", False, f"not found: {APK}")
        return 1
    install = adb("install", "-r", APK, timeout=600)
    report.step("APK installed", "Success" in install, install.strip()[-120:])
    adb("reverse", "tcp:8000", "tcp:8000")

    print("\n=== launch ===")
    adb("logcat", "-c")
    shell("am", "force-stop", PACKAGE)
    shell("am", "start", "-n", ACTIVITY)
    time.sleep(6)
    focused = shell("dumpsys", "activity", "activities")
    report.step("app is in the foreground", PACKAGE in focused,
                f"{PACKAGE} present in resumed activities"
                if PACKAGE in focused else "app not resumed")

    # Alert notification channels. The app declared POST_NOTIFICATIONS from
    # the start and used nothing, so an alert raised while the user was in
    # another app produced no notification at all. The channels are created at
    # start-up, which means their presence on the device is proof the delivery
    # path was wired rather than merely written - and their absence is proof
    # it was not, which no unit test can establish.
    channels = shell("dumpsys", "notification", "--noredact")
    have = [name for name in ("vive_risk_high", "vive_risk_info")
            if name in channels]
    report.step("alert notification channels exist on the device",
                len(have) == 2,
                f"found {have or 'none'}; both are created at application "
                "start-up, so a missing one means delivery is not wired")

    # Identify the new session by SET DIFFERENCE, not by list position.
    # Taking sessions_after[-1] picked an unrelated old session, and every
    # downstream check then validated stale packets from a previous run -
    # reporting transcripts and risk scores as evidence of microphone capture
    # when they came from a FLEURS test hours earlier. A verification script
    # that can pass on the wrong data is worse than no script.
    ids_before = {s["session_id"] for s in (get_json("/api/v1/sessions") or [])}

    print("\n=== live analysis ===")
    # Navigate to the live entry point. The app may open on onboarding, so
    # try the known forward paths before giving up.
    for label in ("Continue", "Get started", "Sign in", "Next"):
        if find_node(ui_dump(), label):
            tap_text(label)

    started = tap_text("Start live analysis")
    report.step("live analysis entry point is reachable", started,
                "tapped 'Start live analysis'" if started
                else "control not found on screen")

    ids_after = {s["session_id"] for s in (get_json("/api/v1/sessions") or [])}
    new_ids = sorted(ids_after - ids_before)
    session_id = new_ids[0] if len(new_ids) == 1 else None
    report.step(
        "a REAL backend session was created by the app", session_id is not None,
        f"new session id(s): {new_ids or 'none'}"
        + ("" if len(new_ids) <= 1 else "  (ambiguous - more than one appeared)"))
    if session_id is None:
        print("  Without an unambiguous new session there is nothing to "
              "attribute captured audio to. Stopping rather than reporting "
              "another session's packets as evidence.")
        return 1

    # Microphone permission, then capture. The control can sit below the fold
    # on a short screen, so scroll before giving up - an ignored tap failure
    # previously let the run continue and report "no capture" as if the code
    # were broken, when nothing had ever been pressed.
    # Clear the buffer immediately before capture starts. This ROM logs
    # heavily enough that the capture line rotates out within seconds
    # otherwise, and the check then reports a failure on working code.
    adb("logcat", "-c")
    started = False
    for attempt in range(3):
        if tap_text("Start microphone analysis", attempts=1):
            started = True
            break
        shell("input", "swipe", "540", "1500", "540", "900", "250")
        time.sleep(2)
    if not started:
        report.step("microphone control was reachable", False,
                    f"'Start microphone analysis' not found after "
                    f"{attempt + 1} attempts including scrolling")

    for allow in ("While using the app", "Allow", "ALLOW"):
        if find_node(ui_dump(), allow):
            tap_text(allow)
            break
    time.sleep(2)
    granted = "granted=true" in shell(
        "dumpsys", "package", PACKAGE, timeout=60).split("RECORD_AUDIO")[-1][:200]
    report.step("RECORD_AUDIO granted at runtime", granted,
                "granted" if granted else "still denied - approve the dialog")

    # Confirm from the UI that capture is actually running before timing
    # anything. Playing audio at a screen that never started recording proves
    # nothing and looks exactly like a broken capture path.
    time.sleep(2)
    capturing = "Capturing" in ui_dump()
    report.step("capture is running", capturing,
                "the capture card reads 'Capturing'" if capturing
                else "capture did not start - the control was not pressed")

    # Sample the capture log NOW, not at the end. This ROM is chatty enough
    # that a 30 s wait rotates the start line out of the ring buffer, and
    # reading it late reported "no capture log line found" while AudioRecord
    # was demonstrably running.
    pid_now = shell("pidof", PACKAGE).strip().split(" ")[0]
    start_logs = adb("logcat", "-d", f"--pid={pid_now}", timeout=120) if pid_now else ""
    started_line = "capturing 16 kHz mono" in start_logs
    source = ""
    for line in start_logs.splitlines():
        if "capturing 16 kHz mono" in line:
            source = line.split("MicrophoneAudioSource:")[-1].strip()
            break
    report.step("AudioRecord captured on-device", started_line,
                source or "no capture log line found")

    if args.play_wav and os.path.isfile(args.play_wav):
        # Played through THIS machine's speakers. The sound travels through
        # the air into the phone's microphone, so the capture path is
        # exercised for real - nothing is injected into the device, and the
        # run is repeatable without a person in the room.
        print(f"  playing {os.path.basename(args.play_wav)} for "
              f"{args.seconds}s - the phone should hear it")
        try:
            import winsound
            winsound.PlaySound(args.play_wav,
                               winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as exc:  # noqa: BLE001
            print(f"  could not play audio ({type(exc).__name__}); "
                  f"speak into the phone instead")
    else:
        print(f"  capturing for {args.seconds}s - SPEAK INTO THE PHONE NOW")
    time.sleep(args.seconds)

    print("=== evidence ===")
    packets = get_json(f"/api/v1/sessions/{session_id}/packets") or []
    report.step("the backend produced analysis packets from device audio",
                len(packets) > 0,
                f"{len(packets)} packets for {session_id} (this run's session)")

    if packets:
        last = packets[-1]
        report.step("packets carry real adapter output",
                    last.get("adapter_mode") == "real",
                    f"adapter_mode={last.get('adapter_mode')} "
                    f"asr={last.get('asr', {}).get('status')} "
                    f"aasist={last.get('aasist', {}).get('status')}")
        transcripts = [p.get("asr", {}).get("transcript") for p in packets
                       if p.get("asr", {}).get("transcript")]
        report.step("ASR transcribed the captured audio", bool(transcripts),
                    f"{len(transcripts)} non-empty transcripts; "
                    f"last={transcripts[-1][:60] if transcripts else 'none'}")
        risks = [p["risk"]["score"] for p in packets if "risk" in p]
        report.step("risk was computed per packet", bool(risks),
                    f"scores={risks[-8:]}")

    # Filter by PID, not by tag. `logcat -s TAG:*` did not match these tags and
    # reported a capture failure while AudioRecord was demonstrably running -
    # the platform's own log showed `start() return status 0`. A check that can
    # report failure on working code is worse than no check.
    pid = shell("pidof", PACKAGE).strip().split(" ")[0] if shell(
        "pidof", PACKAGE).strip() else ""
    logs = adb("logcat", "-d", f"--pid={pid}", timeout=120) if pid else ""

    windows = logs.count("skipping silent window")
    report.step("the packetizer produced analysis windows", windows > 0
                or any(p.get("quality") for p in packets),
                f"{windows} windows reached the silence gate; "
                f"{len(packets)} were analysed by the backend")

    speech = [p for p in packets if p.get("quality") == "GOOD"]
    report.step("at least one window contained speech", bool(speech),
                f"{len(speech)} of {len(packets)} packets had quality GOOD"
                + ("" if speech else
                   " - the room was silent, so nothing was said to analyse"))

    print("\n=== summary ===")
    for step in report.steps:
        print(f"  {step['result']}  {step['step']}")
    print(f"\n{len(report.steps) - report.failed}/{len(report.steps)} steps passed")

    out_dir = os.path.join(ROOT, "models", "evaluation", "phase10")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "android_live_acceptance.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({
            "device": {"serial": serial, "model": model, "android": release},
            "backend": version,
            "session_id": session_id,
            "packets": len(packets),
            "steps": report.steps,
            "passed": len(report.steps) - report.failed,
            "failed": report.failed,
        }, fh, indent=2, ensure_ascii=False)
    print(f"wrote {os.path.relpath(out, ROOT)}")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
