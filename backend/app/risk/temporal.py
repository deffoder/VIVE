"""Temporal risk.

EMA smoothing plus hysteresis so the displayed level does not oscillate, a
minimum-evidence gate before the first non-LOW level, and escalation timings
(docs/ML_SPEC.md 7).

Overall risk is the smoothed series; current risk is the latest packet. Both
are reported because they answer different questions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.risk.fusion import _level_for
from app.schemas.models import EscalationTimings, RiskLevel, RiskSummary

EMA_ALPHA = 0.4
MIN_PACKETS_BEFORE_ESCALATION = 2
"""Minimum-evidence gate: one window is not enough to leave LOW."""

HYSTERESIS = 5
"""Points a score must fall below a threshold before the level de-escalates."""


@dataclass
class TemporalState:
    ema: float = 0.0
    packets: int = 0
    level: RiskLevel = RiskLevel.LOW
    timings: EscalationTimings = field(default_factory=EscalationTimings)
    peak_score: int = 0

    def update(self, score: int, confidence: float, at_sec: int) -> tuple[RiskSummary, RiskSummary]:
        """Feed one packet in; returns (current_risk, overall_risk)."""
        self.packets += 1
        self.ema = float(score) if self.packets == 1 else (
            EMA_ALPHA * score + (1 - EMA_ALPHA) * self.ema
        )
        self.peak_score = max(self.peak_score, score)

        smoothed = int(round(self.ema))
        candidate = _level_for(smoothed)

        if self.packets < MIN_PACKETS_BEFORE_ESCALATION:
            # Not enough evidence yet to claim anything but LOW.
            candidate = RiskLevel.LOW
        elif _rank(candidate) < _rank(self.level):
            # De-escalate only once clearly below the threshold (hysteresis).
            if smoothed > _lower_bound(self.level) - HYSTERESIS:
                candidate = self.level

        self.level = candidate
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
