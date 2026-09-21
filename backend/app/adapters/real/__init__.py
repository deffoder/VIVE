"""Real, checkpoint-backed adapters.

Separate package from `app.adapters.mock` so the mock bundle stays importable
with no ML dependencies at all. Every module here imports its heavy runtime
(onnxruntime, torch, numpy) **lazily inside `load()`**, never at module import,
so:

  * the backend starts and all existing tests run without the ML extras,
  * a missing dependency surfaces as `LOAD_ERROR` on one adapter rather than
    breaking application start-up,
  * and a real adapter that cannot load **stays in REAL mode** reporting the
    failure. It never silently degrades to mock output (docs/ML_SPEC.md 4).

Install the extras with: ``pip install -e "backend[ml]"``
"""

from __future__ import annotations

__all__ = ["asr_conformer"]
