"""Shared reproducibility harness for every Phase 9 experiment.

Phase 9 exists to produce numbers that someone else can reproduce and that
nobody can mistake for something they are not. Two rules follow from that, and
this module enforces both mechanically rather than by convention.

**Every result carries its environment.** A latency figure without the machine
that produced it, or a WER without the model revision, is not a measurement -
it is an anecdote. `Experiment.finish()` refuses to write a record that has no
`limitations`, because a Phase 9 result with no stated limits is exactly the
kind of number that later gets quoted as a capability.

**Superseded results are kept.** `write()` never overwrites a previous record
in place; it moves the old file aside under `superseded/` with its own run
timestamp. Deleting an inconvenient measurement and deleting a fabricated one
leave the same trace.

Seeds are set for `random`, `numpy` and `torch` where present. The audio models
are deterministic in eval mode, so seeding matters mainly for which clips an
experiment draws.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PHASE9_DIR = os.path.join(ROOT, "models", "evaluation", "phase9")
DEFAULT_SEED = 20260922


def seed_everything(seed: int = DEFAULT_SEED) -> int:
    import random

    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch
        torch.manual_seed(seed)
    except ImportError:
        pass
    return seed


def _package_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("torch", "onnxruntime", "transformers", "datasets", "numpy",
                 "scipy", "sklearn", "soundfile", "speechbrain"):
        try:
            mod = __import__(name)
            out[name] = str(getattr(mod, "__version__", "unknown"))
        except Exception:  # noqa: BLE001
            out[name] = "not installed"
    return out


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def environment() -> dict[str, Any]:
    """Everything needed to judge whether a number transfers to other hardware."""
    info: dict[str, Any] = {
        "git_commit": _git_commit(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "cpu_count_logical": os.cpu_count(),
        "packages": _package_versions(),
    }
    try:
        import psutil
        info["ram_total_gb"] = round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:  # noqa: BLE001
        info["ram_total_gb"] = None
    try:
        import torch
        info["torch_cuda_available"] = bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        info["torch_cuda_available"] = None
    try:
        import onnxruntime as ort
        info["onnxruntime_providers"] = list(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        info["onnxruntime_providers"] = None
    return info


class Experiment:
    """One reproducible experiment and its record.

    `question` and `hypothesis` are required. An experiment that cannot state
    what it was asking cannot state what its numbers mean, and a hypothesis
    written down beforehand is what makes a refutation reportable instead of
    quietly discarded.
    """

    def __init__(self, experiment_id: str, *, question: str, hypothesis: str,
                 method: str, seed: int = DEFAULT_SEED) -> None:
        self.id = experiment_id
        self.seed = seed_everything(seed)
        self._began = time.perf_counter()
        self.record: dict[str, Any] = {
            "experiment_id": experiment_id,
            "phase": 9,
            "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "question": question,
            "hypothesis": hypothesis,
            "method": method,
            "seed": self.seed,
            "environment": environment(),
            "datasets": [],
            "models": [],
            "results": {},
            "interpretation": None,
            "limitations": [],
            "conclusion": None,
        }

    # -- provenance --------------------------------------------------------
    def dataset(self, *, name: str, source: str, license: str, split: str,
                samples: int, **extra: Any) -> "Experiment":
        """Records a dataset. `license` is mandatory: an unlicensed corpus must
        be visible as such rather than silently used (docs/DATA_SPEC.md 3)."""
        self.record["datasets"].append(
            {"name": name, "source": source, "license": license,
             "split": split, "samples": samples, **extra})
        return self

    def model(self, *, name: str, revision: str, license: str,
              **extra: Any) -> "Experiment":
        self.record["models"].append(
            {"name": name, "revision": revision, "license": license, **extra})
        return self

    def config(self, **kwargs: Any) -> "Experiment":
        self.record.setdefault("configuration", {}).update(kwargs)
        return self

    # -- results -----------------------------------------------------------
    def result(self, key: str, value: Any) -> "Experiment":
        self.record["results"][key] = value
        return self

    def limitation(self, text: str) -> "Experiment":
        self.record["limitations"].append(text)
        return self

    def finish(self, *, interpretation: str, conclusion: str) -> dict[str, Any]:
        if not self.record["limitations"]:
            raise ValueError(
                f"{self.id}: refusing to write a result with no stated "
                "limitations - every Phase 9 number has a scope")
        if not self.record["results"]:
            raise ValueError(f"{self.id}: no results recorded")
        self.record["interpretation"] = interpretation
        self.record["conclusion"] = conclusion
        self.record["runtime_sec"] = round(time.perf_counter() - self._began, 1)
        return self.write()

    def write(self) -> dict[str, Any]:
        os.makedirs(PHASE9_DIR, exist_ok=True)
        path = os.path.join(PHASE9_DIR, f"{self.id}.json")
        if os.path.exists(path):
            # Supersede, never silently replace (Phase 9 principle).
            with open(path, encoding="utf-8") as fh:
                try:
                    stamp = json.load(fh).get("run_at_utc", "unknown")
                except json.JSONDecodeError:
                    stamp = "unparsable"
            safe = stamp.replace(":", "").replace("-", "")
            archive = os.path.join(PHASE9_DIR, "superseded")
            os.makedirs(archive, exist_ok=True)
            shutil.move(path, os.path.join(archive, f"{self.id}.{safe}.json"))
            print(f"  (previous run archived as superseded/{self.id}.{safe}.json)")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.record, fh, indent=2, ensure_ascii=False)
        print("\nwrote " + os.path.relpath(path, ROOT))
        return self.record


def add_backend_to_path() -> None:
    backend = os.path.join(ROOT, "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def model_dir(*parts: str) -> str:
    return os.path.join(ROOT, "models", "artifacts", *parts)


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile. Returns None below 20 samples.

    A p95 from six packets is not a p95; refusing to compute it is cheaper than
    explaining later why the number meant nothing.
    """
    if len(values) < 20:
        return None
    ordered = sorted(values)
    rank = max(1, int(round(pct / 100.0 * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]
