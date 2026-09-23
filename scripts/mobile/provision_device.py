"""Installs the on-device models onto a connected phone.

This is installation, like `adb install` for the APK: it runs once, and
afterwards the app analyses audio with no computer attached. Files go to the
app's own external files directory, which only the app (and adb) can read:

    /sdcard/Android/data/com.vive/files/models/

Pushes every `*_manifest.json` in models/artifacts/mobile and every file those
manifests name, then checks each file's size on the device against the
manifest - a truncated push must fail here rather than as a load error on
the phone. `--eval` also pushes the evaluation clips.

Usage:
    python scripts/mobile/provision_device.py [--eval] [--serial SERIAL]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "models", "artifacts", "mobile")
DEST = "/sdcard/Android/data/com.vive/files/models"


def adb(serial: str | None, *args: str, capture: bool = False) -> str:
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    out = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    return out.stdout


def files_named_by(manifest: dict) -> list[tuple[str, int | None, str | None]]:
    """(relative file, expected bytes, sha256) for every file a manifest names."""
    out = []
    # Top-level entries with a file (e.g. the text manifest's tokenizer).
    for value in manifest.values():
        if isinstance(value, dict) and "file" in value:
            out.append((value["file"], value.get("bytes"), value.get("sha256")))
    for spec in manifest.get("models", {}).values():
        if spec.get("validated") is False:
            continue   # the phone never runs an unvalidated model; don't ship it
        out.append((spec["file"], spec.get("bytes"), spec.get("sha256")))
    return out


def remote_sha256(serial: str | None, path: str) -> str | None:
    try:
        return adb(serial, "shell", "sha256sum", path).split()[0]
    except (subprocess.CalledProcessError, IndexError):
        return None


def remote_size(serial: str | None, path: str) -> int | None:
    try:
        return int(adb(serial, "shell", "stat", "-c", "%s", path, capture=True).strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def push(serial: str | None, rel: str, expected: int | None,
         sha: str | None = None, always: bool = False) -> None:
    """Pushes unless the device already holds the identical file.

    Identity is the manifest's sha256 when it has one. Size alone is not
    enough: a re-exported manifest changed a threshold from 0.4121 to 0.4096
    at the same byte length and the device kept the stale one. Files without
    a hash (manifests, fixtures) are pushed whenever `always` is set.
    """
    local = os.path.join(SRC, rel)
    size = os.path.getsize(local)
    if expected is not None and size != expected:
        raise SystemExit(f"{rel}: local file is {size} bytes, manifest says {expected}")
    target = f"{DEST}/{rel}"
    if not always and remote_size(serial, target) == size and (
            sha is None or remote_sha256(serial, target) == sha):
        print(f"  = {rel} ({size / 1e6:.1f} MB, already present)")
        return
    adb(serial, "shell", "mkdir", "-p", os.path.dirname(target).replace("\\", "/"))
    print(f"  > {rel} ({size / 1e6:.1f} MB)")
    for attempt in range(3):   # adb push fails transiently on long runs
        try:
            adb(serial, "push", local, target)
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
    got = remote_size(serial, target)
    if got != size:
        raise SystemExit(f"{rel}: device has {got} bytes after push, expected {size}")


def ensure_app_dir(serial: str | None) -> None:
    """The APP must create its models directory, not adb.

    On Android 11+ a directory adb creates under Android/data/<pkg> is owned
    by `shell` and the app cannot read anything inside it (measured on the
    target: the eval set was present and the app saw nothing). ViveApplication
    creates it on start, so the app is launched once if it is missing.
    """
    import time

    for _ in range(20):
        try:
            owner = adb(serial, "shell", "stat", "-c", "%U", DEST).strip()
        except subprocess.CalledProcessError:
            owner = ""
        if owner.startswith("u0_"):
            return
        if owner:
            raise SystemExit(f"{DEST} is owned by {owner!r}, so the app cannot read it. "
                             "Remove /sdcard/Android/data/com.vive and re-run.")
        adb(serial, "shell", "am", "start", "-n", "com.vive/.MainActivity")
        time.sleep(1)
    raise SystemExit("the app did not create its model directory; is it installed?")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", action="store_true")
    parser.add_argument("--serial")
    parser.add_argument("--only", nargs="+", metavar="PREFIX",
                        help="only manifests whose name starts with one of these (asr, text, audio, antispoof)")
    args = parser.parse_args()

    manifests = sorted(glob.glob(os.path.join(SRC, "*_manifest.json")))
    if args.only:
        manifests = [m for m in manifests if os.path.basename(m).startswith(tuple(args.only))]
    if not manifests:
        raise SystemExit(f"no manifests under {SRC}; run the export scripts first")
    ensure_app_dir(args.serial)
    for path in manifests:
        name = os.path.basename(path)
        print(name)
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        for rel, expected, sha in files_named_by(manifest):
            push(args.serial, rel, expected, sha)
        push(args.serial, name, None, always=True)   # last: it declares the rest present
    if args.eval:
        for local in sorted(glob.glob(os.path.join(SRC, "eval", "**", "*"), recursive=True)):
            if os.path.isfile(local):
                rel = os.path.relpath(local, SRC).replace("\\", "/")
                push(args.serial, rel, None, always=rel.endswith(".json"))
    print("provisioned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
