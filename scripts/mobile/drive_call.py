"""Drives one live on-device call on the phone, for acceptance runs.

The phone does all analysis. This script only does what a person would: taps
the app's own buttons (found by their text, via uiautomator), and plays a
scripted caller through the laptop loudspeaker so the phone's microphone
hears a voice. It then reads the phone's own SQLite store to report what the
phone concluded. No backend, no adb reverse.

Usage:
    python scripts/mobile/drive_call.py hi [--no-end] [--screenshot out.png]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CALLS = os.path.join(ROOT, "models", "artifacts", "mobile", "calls")
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")
LANG_CHIP = {"hi": "Hindi", "ta": "Tamil", "en": "English"}


def adb(*args, binary=False):
    out = subprocess.run(["adb", *args], capture_output=True, env=ENV, check=False)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def nodes():
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    xml = adb("shell", "cat", "/sdcard/ui.xml")
    found = []
    for m in re.finditer(r'(?:text|content-desc)="([^"]+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        x1, y1, x2, y2 = map(int, m.groups()[1:])
        found.append((m.group(1), (x1 + x2) // 2, (y1 + y2) // 2))
    return found


def tap(text, timeout=10.0, exact=True):
    end = time.time() + timeout
    while time.time() < end:
        for t, x, y in nodes():
            if (t == text) if exact else (text.lower() in t.lower()):
                adb("shell", "input", "tap", str(x), str(y))
                return True
        time.sleep(0.5)
    return False


def play(path):
    import winsound
    winsound.PlaySound(path, winsound.SND_FILENAME)


def store():
    tmp = tempfile.mkdtemp()
    for suffix in ("", "-wal"):
        data = adb("exec-out", "run-as", "com.vive", "cat", f"databases/vive_sessions.db{suffix}", binary=True)
        if data:
            with open(os.path.join(tmp, f"vive.db{suffix}"), "wb") as fh:
                fh.write(data)
    return sqlite3.connect(os.path.join(tmp, "vive.db"))


def report(session_id=None):
    c = store()
    sid = session_id or c.execute(
        "select id from sessions order by started_at desc, id desc limit 1").fetchone()[0]
    s = json.loads(c.execute("select body from sessions where id=?", (sid,)).fetchone()[0])
    packets = [json.loads(b) for (b,) in c.execute(
        "select body from packets where session_id=? order by seq", (sid,))]
    alerts = [json.loads(b) for (b,) in c.execute(
        "select body from alerts where session_id=?", (sid,))]
    return s, packets, alerts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lang", choices=list(LANG_CHIP))
    ap.add_argument("--script", default="call", choices=["call", "direct"])
    ap.add_argument("--no-end", action="store_true")
    ap.add_argument("--screenshot")
    args = ap.parse_args()

    assert not adb("reverse", "--list").strip(), "adb reverse is set; acceptance must run without it"
    adb("shell", "am", "force-stop", "com.vive")
    adb("shell", "am", "start", "-n", "com.vive/.MainActivity")
    time.sleep(3)
    assert tap(LANG_CHIP[args.lang]), "language chip not found"
    assert tap("Start live analysis"), "start button not found"
    assert tap("Start microphone analysis"), "microphone button not found"
    # First use: the system asks for the microphone.
    tap("While using the app", timeout=2) or tap("Allow", timeout=1)
    time.sleep(4)   # models warm up when the session is created
    play(os.path.join(CALLS, f"{args.lang}_{args.script}.wav"))
    time.sleep(4)
    if args.screenshot:
        with open(args.screenshot, "wb") as fh:
            fh.write(adb("exec-out", "screencap", "-p", binary=True))
    if not args.no_end:
        for _ in range(6):   # "End call" sits below the fold
            if tap("End call", timeout=1):
                break
            adb("shell", "input", "swipe", "600", "2000", "600", "700", "300")
        time.sleep(3)

    s, packets, alerts = report()
    print(f"{s['session_id']} {s['status']} lang={s['language']} packets={len(packets)} "
          f"overall={s.get('overall_risk')} timings={s['timings']}")
    for p in packets:
        c = p["risk"]["contributions"]
        print(f"  {p['packet_id']} {p['window']['start_sec']:5.1f}s {p['quality'][:4]} "
              f"R{p['risk']['score']:3d} {p['risk']['level'][:4]} c{p['risk']['confidence']:.2f} "
              f"| {(p['asr']['transcript'] or p['asr']['status'])[:38]:38s} "
              f"| {p['intent']['label'][:12]} {'RULE' if 'sensitive_request' in c else ''} "
              f"| asr {p['asr']['inference_ms']} ms")
    for a in alerts:
        print(f"  ALERT {a['alert_id']} {a['level']} {a['packet_id']} {a['recommended_action']} | {a['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
