"""Identifier generation.

Session ids are VS-<counter> and packet ids are P<zero-padded seq>, matching
docs/API_SPEC.md 1 and the ids the Android client already parses.

The counter is process-local and monotonic. That is sufficient for the current
single-node scope (docs/BLOCKERS.md D6 defers multi-node); a distributed
deployment would need a shared allocator, which is recorded there.
"""

from __future__ import annotations

import itertools
import threading

_lock = threading.Lock()
_session_counter = itertools.count(1)


def next_session_id() -> str:
    with _lock:
        return f"VS-{next(_session_counter):03d}"


def packet_id(seq: int) -> str:
    return f"P{seq:03d}"


def reset_for_tests() -> None:
    """Test seam so id assertions are deterministic."""
    global _session_counter
    with _lock:
        _session_counter = itertools.count(1)
