"""Temporal risk.

EMA smoothing plus hysteresis so the displayed level does not oscillate, a
minimum-evidence gate before the first non-LOW level, and escalation timings
(docs/ML_SPEC.md 7).

Overall risk is the smoothed series; current risk is the latest packet. Both
are reported because they answer different questions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.risk.fusion import _level_for
from app.schemas.models import EscalationTimings, RiskLevel, RiskSummary

EMA_ALPHA = 0.4
MIN_PACKETS_BEFORE_ESCALATION = 2
"""Minimum-evidence gate: one window is not enough to leave LOW."""

HYSTERESIS = 5
"""Points a score must fall below a threshold before the level de-escalates."""

# --- persistence, added to fix O14 ---------------------------------------
#
# An EMA answers "how elevated is this call right now", and damps a single
# anomalous packet - the property this most needed, since Phase 9 measured a
# lone 95 reaching only MEDIUM and O12 makes such packets likely.
#
# The same damping suppressed genuine PERIODIC evidence. A sequence scoring
# ~80 every third packet - the shape social engineering actually takes, since
# the incriminating sentence is one window in several - peaked at 82 and never
# left MEDIUM, so it never raised an alert.
#
# Both behaviours are wanted, and one number cannot provide both: the
# difference between a spike and an intermittent pattern is not magnitude, it
# is RECURRENCE. So recurrence is counted separately from the average.

PERSISTENCE_WINDOW = 12
"""Recent packets the persistence counter looks back over.

Bounded on purpose: memory per session stays constant however long the call.
"""

PERSISTENCE_SCORE = 65
"""A packet at or above this counts as elevated evidence."""

PERSISTENCE_COUNT = 3
"""Elevated packets within the window needed to escalate on recurrence alone.

Three is the smallest count that one spike cannot reach, and that two adjacent
packets of the same event cannot reach either - both of which Phase 9 measured
as the false-positive shapes worth resisting.
"""

PERSISTENCE_RECENCY = 4
"""At least one elevated packet must fall within this many recent packets.

Without it, recurrence keeps firing on evidence that has already passed: a
burst of four high packets stayed inside the 12-window memory long after the
call went quiet, so the level never came back down. Phase 9 measured recovery
to LOW within 4 packets of a burst ending, and that property is worth keeping.

Requiring recency separates the two cases cleanly. Intermittent evidence -
every third packet - always has an elevated window within the last four. A
burst that genuinely ended does not.
"""


@dataclass
class TemporalState:
    ema: float = 0.0
    packets: int = 0
    level: RiskLevel = RiskLevel.LOW
    timings: EscalationTimings = field(default_factory=EscalationTimings)
    peak_score: int = 0
    recent: deque[int] = field(
        default_factory=lambda: deque(maxlen=PERSISTENCE_WINDOW))
    """Recent packet scores. Bounded by PERSISTENCE_WINDOW."""

    escalation_reason: str = ""
    """Why the level is what it is, so the UI can say why risk changed."""

    @property
    def elevated_recently(self) -> int:
        return sum(1 for s in self.recent if s >= PERSISTENCE_SCORE)

    @property
    def recurrence_is_live(self) -> bool:
        """Recurring evidence that has not already passed.

        Both halves matter. The count says the evidence repeats rather than
        being one anomaly; the recency says it is still happening, so a burst
        that ended stops holding the level up.
        """
        tail = list(self.recent)[-PERSISTENCE_RECENCY:]
        return (self.elevated_recently >= PERSISTENCE_COUNT
                and any(s >= PERSISTENCE_SCORE for s in tail))

    def update(self, score: int, confidence: float, at_sec: int) -> tuple[RiskSummary, RiskSummary]:
        """Feed one packet in; returns (current_risk, overall_risk)."""
        self.packets += 1
        self.ema = float(score) if self.packets == 1 else (
            EMA_ALPHA * score + (1 - EMA_ALPHA) * self.ema
        )
        self.peak_score = max(self.peak_score, score)

        self.recent.append(score)

        smoothed = int(round(self.ema))
        candidate = _level_for(smoothed)
        reason = "smoothed score"

        # Recurrence, independent of the average. Repeated elevated packets
        # are evidence even when the quiet gaps between them pull the mean
        # down far enough to hide them.
        elevated = self.elevated_recently
        live = self.recurrence_is_live
        if live and _rank(candidate) < _rank(RiskLevel.HIGH):
            candidate = RiskLevel.HIGH
            reason = f"{elevated} elevated windows in the last {len(self.recent)}"

        if self.packets < MIN_PACKETS_BEFORE_ESCALATION:
            # Not enough evidence yet to claim anything but LOW.
            candidate = RiskLevel.LOW
            reason = "insufficient evidence"
        elif _rank(candidate) < _rank(self.level):
            # De-escalate only once clearly below the threshold (hysteresis),
            # and never while recurring evidence is still arriving.
            if smoothed > _lower_bound(self.level) - HYSTERESIS or live:
                candidate = self.level
                reason = "held by hysteresis"

        self.level = candidate
        self.escalation_reason = reason
        self._record_timings(score, at_sec)

        current = RiskSummary(score=score, level=_level_for(score), confidence=confidence)
        overall = RiskSummary(score=smoothed, level=self.level, confidence=confidence)
        return current, overall

    def _record_timings(self, score: int, at_sec: int) -> None:
        t = self.timings
        if t.first_anomaly_sec is None and score >= 20:
            t.first_anomaly_sec = at_sec
        if t.first_warning_sec is None and score >= 35:
            t.first_warning_sec = at_sec
        if t.first_high_sec is None and score >= 65:
            t.first_high_sec = at_sec
        if t.first_critical_sec is None and score >= 85:
            t.first_critical_sec = at_sec


def _rank(level: RiskLevel) -> int:
    return [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL].index(level)


def _lower_bound(level: RiskLevel) -> int:
    return {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 35, RiskLevel.HIGH: 65, RiskLevel.CRITICAL: 85}[level]
