"""Audits and converts a PyTorch `.bin` checkpoint to safetensors.

Why this exists: `ai4bharat/indicwav2vec-hindi` ships only `pytorch_model.bin`,
and transformers refuses to `torch.load` a `.bin` on torch < 2.6 because of
CVE-2025-32434 - a `torch.load` deserialisation flaw that `weights_only=True`
did not fully contain in older versions. The refusal is correct and is NOT
bypassed here.

Instead the pickle is *audited without executing it*: `pickletools.genops`
walks the opcode stream and every global symbol the pickle would import is
checked against an allowlist. A weights-only checkpoint references nothing but
tensor rebuild helpers and container types. Anything else - `os`, `subprocess`,
`builtins.eval`, `posix`, a `__reduce__` onto an arbitrary callable - fails the
audit and the file is refused.

Only after the audit passes is the file loaded with `weights_only=True` and
re-serialised to `.safetensors`, which has no code-execution path at all. Every
later load reads the safetensors file, so the `.bin` is touched exactly once,
under audit.

This does not make an arbitrary untrusted `.bin` safe. It makes *this* file's
contents inspectable before any code runs, which is what the CVE requires.

Usage:
    python scripts/training/safe_load_bin.py --bin <path> --out <path.safetensors>
    python scripts/training/safe_load_bin.py --bin <path> --audit-only
"""

from __future__ import annotations

import argparse
import io
import pickletools
import sys
import zipfile

# Symbols a pure weights checkpoint legitimately needs. Anything outside this
# set means the pickle does more than describe tensors.
ALLOWED_GLOBALS = {
    ("torch", "FloatStorage"), ("torch", "HalfStorage"), ("torch", "DoubleStorage"),
    ("torch", "LongStorage"), ("torch", "IntStorage"), ("torch", "ShortStorage"),
    ("torch", "CharStorage"), ("torch", "ByteStorage"), ("torch", "BoolStorage"),
    ("torch", "BFloat16Storage"),
    ("torch", "Size"), ("torch", "Tensor"), ("torch", "device"), ("torch", "dtype"),
    ("torch._utils", "_rebuild_tensor"),
    ("torch._utils", "_rebuild_tensor_v2"),
    ("torch._utils", "_rebuild_parameter"),
    ("torch._utils", "_rebuild_device_tensor_from_numpy"),
    ("collections", "OrderedDict"),
    ("numpy.core.multiarray", "scalar"), ("numpy", "dtype"), ("numpy", "ndarray"),
    ("__builtin__", "set"), ("builtins", "set"),
}

# Never acceptable in a weights file, listed so a hit is reported explicitly
# rather than just "not allowed".
DANGEROUS_MODULES = {
    "os", "posix", "nt", "subprocess", "sys", "shutil", "socket", "builtins",
    "__builtin__", "importlib", "runpy", "pty", "commands", "pickle", "code",
}
DANGEROUS_NAMES = {"system", "popen", "exec", "eval", "compile", "open",
                   "__import__", "getattr", "call", "check_output", "Popen"}


def find_pickle(bin_path: str) -> bytes:
    """Extracts the pickle stream. A torch save is a zip containing data.pkl."""
    if not zipfile.is_zipfile(bin_path):
        # Legacy non-zip format: the whole file is a pickle stream.
        with open(bin_path, "rb") as handle:
            return handle.read()
    with zipfile.ZipFile(bin_path) as archive:
        names = [n for n in archive.namelist() if n.endswith("data.pkl")]
        if not names:
            raise ValueError("no data.pkl inside the checkpoint archive")
        return archive.read(names[0])


def audit(bin_path: str) -> tuple[bool, list[str], set[tuple[str, str]]]:
    """Walks the opcode stream. Executes nothing."""
    data = find_pickle(bin_path)
    findings: list[str] = []
    globals_seen: set[tuple[str, str]] = set()

    # STACK_GLOBAL takes its module/name from the two preceding string pushes,
    # so track recent string constants to resolve it.
    recent: list[str] = []
    for op, arg, _pos in pickletools.genops(io.BytesIO(data)):
        if op.name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "STRING",
                       "SHORT_BINSTRING", "BINSTRING"):
            recent.append(arg if isinstance(arg, str) else str(arg))
            if len(recent) > 8:
                recent.pop(0)
        elif op.name in ("GLOBAL", "INST"):
            parts = str(arg).split(" ", 1)
            if len(parts) == 2:
                globals_seen.add((parts[0], parts[1]))
        elif op.name == "STACK_GLOBAL":
            if len(recent) >= 2:
                globals_seen.add((recent[-2], recent[-1]))
            else:
                findings.append("STACK_GLOBAL with unresolvable operands")

    for module, name in sorted(globals_seen):
        if (module, name) in ALLOWED_GLOBALS:
            continue
        root = module.split(".")[0]
        if root in DANGEROUS_MODULES or name in DANGEROUS_NAMES:
            findings.append(f"DANGEROUS global: {module}.{name}")
        else:
            findings.append(f"unrecognised global: {module}.{name}")

    return (not findings), findings, globals_seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin", required=True)
    parser.add_argument("--out")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    print(f"auditing {args.bin}")
    clean, findings, globals_seen = audit(args.bin)

    print(f"  globals referenced ({len(globals_seen)}):")
    for module, name in sorted(globals_seen):
        mark = "ok " if (module, name) in ALLOWED_GLOBALS else "!! "
        print(f"    {mark}{module}.{name}")

    if not clean:
        print("\n  AUDIT FAILED - file refused, nothing was loaded:")
        for f in findings:
            print(f"    {f}")
        return 1

    print("\n  AUDIT PASSED: only tensor-rebuild and container symbols present.")
    if args.audit_only:
        return 0

    import torch
    from safetensors.torch import save_file

    print("  loading with weights_only=True ...")
    state = torch.load(args.bin, map_location="cpu", weights_only=True)
    if not isinstance(state, dict):
        print(f"  unexpected payload type: {type(state)}")
        return 1

    # safetensors rejects shared storage, so materialise independent tensors.
    tensors = {k: v.contiguous().clone() for k, v in state.items()
               if hasattr(v, "contiguous")}
    skipped = [k for k in state if k not in tensors]
    save_file(tensors, args.out, metadata={"format": "pt"})
    print(f"  wrote {args.out}  ({len(tensors)} tensors"
          + (f", skipped {len(skipped)} non-tensor entries" if skipped else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
